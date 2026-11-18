from __future__ import annotations
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
from typing import Callable, Any
from app.services.docx_template import extract_section_tables, consolidate_template
from app.services.template_agent import run_agui_template_pipeline, AguiEmitter
from app.services.excel_explorer_agent import run_parallel_excel_explorers
from app.services.excel_profile import profile_xlsx, profile_to_markdown, build_master_summary
from app.services.mapper import heuristic_mapping, bedrock_refine_mapping, merge_llm_mapping, calculate_topic_metrics
from app.services.docx_render import render_report

Progress=Callable[[str,str,dict[str,Any]],None]


def run_template_learning(run_id: str, tenant_id: str, run_name: str, docx_paths: list[Path], work_dir: Path,
                          progress: Progress, emitter: AguiEmitter | None = None,
                          template_type: str = "generic",
                          pause_check: Callable[[], None] | None = None) -> dict:
    def _fallback_emit(event_type: str, payload: dict[str, Any]):
        if event_type == "CUSTOM" and payload.get("name") == "agent.activity":
            v = payload.get("value") or {}
            progress(v.get("agent", "agent"), v.get("message", ""), v.get("details") or {})

    return run_agui_template_pipeline(
        run_id=run_id,
        tenant_id=tenant_id,
        run_name=run_name,
        docx_paths=docx_paths,
        work_dir=work_dir,
        emitter=emitter or _fallback_emit,
        template_type=template_type,
        pause_check=pause_check,
    )


def generic_table_preview(table: dict) -> list[dict]:
    values={"topic_total":"{{topic_initial_cases}} / {{total_initial_cases}}",
            "search_criteria":"{{client_search_criteria}}","source_spontaneous":"{{spontaneous_case_count}}",
            "source_other_studies":"{{other_study_case_count}}","evaluation":"{{evaluation_narrative}}",
            "conclusion":"{{conclusion_narrative}}","data_source":"{{data_source_reference}}"}
    rows=[]
    for f in table.get("fields",[]):
        rows.append({"key":f["key"],"label":f["label"],"type":f["type"],"placeholder":values.get(f["key"],f"{{{{{f['key']}}}}}"),
                     "required":f.get("required",False),"source_intent":f.get("source_intent","")})
    return rows


def run_source_exploration(run_id: str, excel_paths: list[Path], work_dir: Path, progress: Progress,
                           emitter: AguiEmitter | None = None,
                           pause_check: Callable[[], None] | None = None) -> list[dict]:
    def _fallback_emit(event_type: str, payload: dict[str, Any]):
        if event_type == "CUSTOM" and payload.get("name") == "agent.activity":
            v = payload.get("value") or {}
            progress(v.get("agent", "source_exploration_agent"), v.get("message", ""), v.get("details") or {})

    active_emitter = emitter or _fallback_emit
    if pause_check:
        pause_check()
    progress("orchestrator", f"Stage 1 — launching {len(excel_paths)} parallel Excel explorer agent(s)", {"files": len(excel_paths)})
    profiles = run_parallel_excel_explorers(excel_paths, work_dir, emitter=active_emitter, pause_check=pause_check)
    if pause_check:
        pause_check()
    master = build_master_summary(profiles)
    (work_dir / "master_summary.md").write_text(master, encoding="utf-8")
    (work_dir / "source_profiles.json").write_text(json.dumps(profiles, indent=2, ensure_ascii=False), encoding="utf-8")
    active_emitter("CUSTOM", {"name": "source.master_ready", "value": {"artifact": "master_summary.md", "files": len(profiles)}})
    progress("source_exploration_agent", "Stage 1 complete — all workbook reports, analysis.py scripts & master_summary.md ready", {"artifact": "master_summary.md"})
    return profiles


def run_mapping_stage(template: dict, profiles: list[dict], input_dir: Path, period_start: str | None,
                      period_end: str | None, progress: Progress,
                      pause_check: Callable[[], None] | None = None) -> dict:
    if pause_check:
        pause_check()
    progress("mapper_agent","Stage 2 — mapping template fields to workbook columns",{})
    heur=heuristic_mapping(profiles)
    progress("mapper_agent","Built deterministic candidate mappings from column names and types",{
        "mapped_roles":[k for k,v in heur["mapping"].items() if v],"unmapped_roles":[k for k,v in heur["mapping"].items() if not v]})
    if pause_check:
        pause_check()
    llm=bedrock_refine_mapping(template,profiles,heur)
    mapping=merge_llm_mapping(heur,llm)
    if llm:
        progress("mapper_agent","Bedrock returned a mapping proposal; deterministic validation matched it to uploaded columns",{})
    else:
        progress("mapper_agent","Using local schema-matching mapper (Bedrock disabled/unavailable)",{})
    metrics=[]
    metric_by_id={}
    for table in template.get("base_tables",template.get("tables",[])):
        if pause_check:
            pause_check()
        if table.get("continuation_of_previous") and table.get("parent_topic_table_id") in metric_by_id:
            parent=metric_by_id[table["parent_topic_table_id"]]
            continuation={**parent,"table_id":table["table_id"],"topic_heading":table.get("topic_heading"),"continuation":True}
            metrics.append(continuation);metric_by_id[table["table_id"]]=continuation
            progress("mapper_agent","Linked continuation table to its parent topic",{"topic":table.get("topic_heading"),"table_id":table["table_id"]})
            continue
        progress("mapper_agent","Gathering relevant table data for topic",{"topic":table.get("topic_heading"),"criteria":table.get("criterion_type")})
        metric=calculate_topic_metrics(table,mapping,input_dir,period_start,period_end,"distinct_case")
        metrics.append(metric);metric_by_id[table["table_id"]]=metric
        progress("mapper_agent","Created topic-level mapping and calculation candidate",{
            "topic":table.get("topic_heading"),"table_id":table["table_id"],"status":metric.get("status"),
            "numerator":metric.get("numerator"),"denominator":metric.get("denominator"),
            "evidence_count":len(metric.get("evidence",[])),"reason":metric.get("reason")})
    progress("mapper_agent","Stage 2 mapping proposals assembled",{"table_metrics":len(metrics)})
    return {"column_mapping":mapping,"mapping_candidates":heur["candidates"],"all_columns":heur["all_columns"],
            "bedrock_used":bool(llm),"bedrock_warnings":(llm or {}).get("warnings",[]) if llm else [],
            "topic_metrics":metrics,"count_mode_candidates":["distinct_case","event_rows"],
            "review_required":True}


def recalculate_topics(template: dict, mapping: dict, input_dir: Path, period_start: str | None,
                       period_end: str | None, count_mode: str) -> list[dict]:
    metrics=[];metric_by_id={}
    for table in template.get("base_tables",template.get("tables",[])):
        if table.get("continuation_of_previous") and table.get("parent_topic_table_id") in metric_by_id:
            parent=metric_by_id[table["parent_topic_table_id"]]
            metric={**parent,"table_id":table["table_id"],"topic_heading":table.get("topic_heading"),"continuation":True}
        else:
            metric=calculate_topic_metrics(table,mapping,input_dir,period_start,period_end,count_mode)
        metrics.append(metric);metric_by_id[table["table_id"]]=metric
    return metrics


def generate_docx(template: dict, run: dict, mapping: dict, period_start: str | None, period_end: str | None,
                  count_mode: str, narratives: dict, output_path: Path) -> dict:
    base_path=Path(run["base_docx_path"])
    metrics=recalculate_topics(template,mapping,Path(run["input_dir"]),period_start,period_end,count_mode)
    render=render_report(base_path,template,metrics,output_path,narratives,run.get("source_filenames",[]))
    return {"metrics":metrics,"render":render}

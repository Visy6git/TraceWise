export type BlueprintStatus = 'draft' | 'needs_review' | 'ready_for_review' | 'approved' | 'superseded';
export type GenerationStatus =
  | 'created' | 'profiling' | 'compatibility_review' | 'ready' | 'running'
  | 'output_review' | 'complete' | 'failed' | 'cancelled';

export interface BlueprintSummary {
  blueprint_id: string;
  tenant_id: string;
  source_learning_run_id: string;
  version: number;
  status: BlueprintStatus;
  version_status: BlueprintStatus;
  manifest_hash: string;
  approved_at?: string | null;
  approved_by?: string | null;
  generation_error?: string | null;
  manifest?: { files?: Array<{ path: string; sha256: string; size_bytes: number }> };
}

export interface SchemaDrift {
  code: string;
  severity: 'info' | 'warning' | 'blocking';
  dataset_id?: string | null;
  logical_field?: string | null;
  expected?: string | null;
  observed?: string | null;
  suggested_action: string;
  auto_mapping_candidate?: string | null;
  reviewer_required: boolean;
}

export interface GenerationSummary {
  generation_id: string;
  run_name: string;
  blueprint_id: string;
  blueprint_version: number;
  status: GenerationStatus;
  reporting_period_start: string;
  reporting_period_end: string;
  as_of_date?: string | null;
  source_manifest_hash: string;
  output_manifest_hash?: string | null;
  compatibility_json?: {
    status: string;
    source_profiles: Array<{ file_name: string; sheet_name?: string | null; row_count: number; columns: string[] }>;
    mappings: Array<Record<string, unknown>>;
    drift: SchemaDrift[];
  } | null;
  artifacts_json?: Array<{
    artifact_id: string; logical_path: string; media_type: string; sha256: string; size_bytes: number; status?: string;
  }>;
  error_summary?: string | null;
  created_at: string;
}

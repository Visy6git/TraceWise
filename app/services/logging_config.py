"""Central logging and per-run agent log files.

Every stage run gets a dedicated log file under the run's storage directory
(``.tracewise-runtime/default/<run_id>/logs/stage_<stage>.log``) capturing the
full agent trace: subagent lifecycle, every Bedrock prompt/response, and
errors with tracebacks. A global ``logs/tracewise.log`` keeps INFO-level
summaries across all runs, and INFO also streams to the console.

Full prompts/responses are logged at DEBUG so they land in the per-run file
without flooding the console or the global summary log.
"""
from __future__ import annotations

import logging

from app.services.storage import default_storage

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_root_configured = False


def _ensure_root_logging() -> None:
    global _root_configured
    if _root_configured:
        return
    logs_dir = default_storage.root_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("tracewise")
    root.setLevel(logging.DEBUG)
    root.propagate = False

    if not any(getattr(h, "_tw_global", False) for h in root.handlers):
        file_handler = logging.FileHandler(logs_dir / "tracewise.log", encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        file_handler._tw_global = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)

        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.INFO)
        stream_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        stream_handler._tw_global = True  # type: ignore[attr-defined]
        root.addHandler(stream_handler)

    _root_configured = True


def get_run_logger(run_id: str, stage: str) -> logging.Logger:
    """Return a logger that writes the full trace to the run's stage log file."""
    _ensure_root_logging()
    logger = logging.getLogger(f"tracewise.run.{run_id}.{stage}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = True  # INFO summaries flow up to the global file + console

    run_logs = default_storage.root_dir / "default" / run_id / "logs"
    run_logs.mkdir(parents=True, exist_ok=True)
    target = str(run_logs / f"stage_{stage}.log")

    if not any(getattr(h, "_tw_target", None) == target for h in logger.handlers):
        handler = logging.FileHandler(target, encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        handler._tw_target = target  # type: ignore[attr-defined]
        logger.addHandler(handler)

    return logger


def log_bedrock_exchange(
    logger: logging.Logger,
    label: str,
    prompt: str,
    response: str | None = None,
    error: BaseException | None = None,
) -> None:
    """Record a Bedrock call. Summary at INFO; full text at DEBUG (per-run file only)."""
    logger.info("BEDROCK %s | prompt_chars=%d", label, len(prompt))
    logger.debug("BEDROCK %s PROMPT >>>\n%s\n<<< END PROMPT", label, prompt)
    if response is not None:
        logger.info("BEDROCK %s | response_chars=%d", label, len(response))
        logger.debug("BEDROCK %s RESPONSE >>>\n%s\n<<< END RESPONSE", label, response)
    if error is not None:
        logger.error("BEDROCK %s | ERROR: %s", label, error, exc_info=error)

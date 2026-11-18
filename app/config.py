from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"

    # Active LLM provider: 'lmstudio' or 'bedrock'
    llm_provider: str = "lmstudio"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 8192

    # Local LM Studio OpenAI-compatible server
    lmstudio_enabled: bool = False
    lmstudio_base_url: str = "http://127.0.0.1:1234/v1"
    lmstudio_model_id: str = "prism-ml/bonsai-27b"
    lmstudio_timeout: float = 300.0
    lmstudio_max_concurrency: int = 1

    # AWS Bedrock settings
    aws_region: str = "us-east-1"
    bedrock_model_id: str = ""
    bedrock_max_tokens: int = 6000
    bedrock_temperature: float = 0.1
    bedrock_enabled: bool = False

    workspace_root: Path = Path("./workspace")
    database_path: Path = Path("./workspace/workbench.sqlite3")
    max_upload_mb: int = 150
    max_docx_files: int = 12
    max_excel_files: int = 30

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
settings.workspace_root.mkdir(parents=True, exist_ok=True)
settings.database_path.parent.mkdir(parents=True, exist_ok=True)

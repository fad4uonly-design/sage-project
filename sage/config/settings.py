"""Typed configuration models for SAGE."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LoggingSettings(BaseModel):
    level: str = "INFO"
    format: Literal["console", "json"] = "console"


class MemorySettings(BaseModel):
    short_term_ttl_minutes: int = 120
    consolidation_interval_minutes: int = 30
    default_recall_limit: int = 10


class KnowledgeSettings(BaseModel):
    watch_enabled: bool = False
    supported_extensions: list[str] = Field(
        default_factory=lambda: [
            ".pdf",
            ".docx",
            ".txt",
            ".md",
            ".csv",
            ".xlsx",
            ".png",
            ".jpg",
            ".jpeg",
        ]
    )


class ModelsSettings(BaseModel):
    default_provider: str = "stub"
    default_model_name: str = "stub-v1"

    temperature: float = 0.7
    max_tokens: int = 2048

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    local_base_url: str = "http://127.0.0.1:11434/v1"
    local_model_name: str = "local-model"
    local_timeout: float = 120.0

    # Embedding source (TurboVec slot): "stub" | "hashing" | "local"
    embedding_provider: str = "stub"
    embedding_model_name: str = "nomic-embed-text"
    embedding_dim: int = 256

    # Serving runtime (RuntimePlugin registry): "auto" picks the first
    # available registered runtime; "none" keeps config-driven behavior.
    serving_runtime: str = "auto"


class PerceptionSettings(BaseModel):
    """Vision + speech endpoints (Phase 4 — off until explicitly configured)."""

    # Vision (SmolVLM slot): "none" | "local"
    vision_provider: str = "none"
    vision_base_url: str = "http://127.0.0.1:11434/v1"
    vision_model_name: str = "smolvlm"
    vision_timeout: float = 120.0

    # Speech (Whisper Tiny slot): "none" | "local"
    speech_provider: str = "none"
    speech_base_url: str = "http://127.0.0.1:8080"
    speech_model_name: str = "whisper"
    speech_timeout: float = 120.0


class AgentsSettings(BaseModel):
    enabled: bool = True
    max_concurrent_tasks: int = 4


class PluginsSettings(BaseModel):
    enabled: bool = True
    directories: list[str] = Field(default_factory=lambda: ["./plugins"])
    auto_load: bool = True


class ToolsSettings(BaseModel):
    allow_shell: bool = False
    allow_network: bool = False


class SchedulerSettings(BaseModel):
    enabled: bool = True
    tick_seconds: int = 60


class ApiSettings(BaseModel):
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8742


class ConversationSettings(BaseModel):
    max_history_turns: int = 50
    default_user_id: str = "default"


class FilesSettings(BaseModel):
    index_on_startup: bool = False
    watch_directories: list[str] = Field(default_factory=list)


class Settings(BaseSettings):
    """
    Root settings object.

    Priority (highest last, wins):
      defaults.yaml → user sage.yaml → environment → CLI overrides
    """

    model_config = SettingsConfigDict(
        env_prefix="SAGE_",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    env: Literal["development", "test", "production"] = "development"
    data_dir: Path = Path("./data")
    db_path: Path = Path("./data/sage.db")

    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    knowledge: KnowledgeSettings = Field(default_factory=KnowledgeSettings)
    models: ModelsSettings = Field(default_factory=ModelsSettings)
    perception: PerceptionSettings = Field(default_factory=PerceptionSettings)
    agents: AgentsSettings = Field(default_factory=AgentsSettings)
    plugins: PluginsSettings = Field(default_factory=PluginsSettings)
    tools: ToolsSettings = Field(default_factory=ToolsSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    conversation: ConversationSettings = Field(default_factory=ConversationSettings)
    files: FilesSettings = Field(default_factory=FilesSettings)

    @field_validator("data_dir", "db_path", mode="before")
    @classmethod
    def _coerce_path(cls, v: Any) -> Path:
        return Path(v).expanduser()

    def ensure_directories(self) -> None:
        """Create runtime directories if missing."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "config").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "memory").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "knowledge").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "logs").mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def resolve_paths(self) -> Settings:
        """Return a copy with data_dir-relative paths resolved."""
        data = self.model_copy(deep=True)
        if not data.db_path.is_absolute():
            pass
        return data



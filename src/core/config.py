"""Module for loading configuration files."""

import logging
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class ProjectConfig(BaseModel):
    """Configuration for the project."""

    model_config = ConfigDict(frozen=True)

    id: str
    location: str


class AgentConfig(BaseModel):
    """Configuration for creating an agent."""

    model_config = ConfigDict(frozen=True)

    model_name: str
    base_url: str | None = None
    location: str | None = None
    max_output_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    thinking_level: Literal["low", "medium", "high"] | None = "low"
    timeout: int | None = Field(default=None, gt=0)
    max_retries: int | None = Field(default=None, ge=0)


class AppConfig(BaseModel):
    """Configuration for the entire application."""

    model_config = ConfigDict(frozen=True)

    project: ProjectConfig
    agents: dict[str, AgentConfig]


def load_config(config_path: str = "configs/config.yaml") -> AppConfig:
    """Load configuration from a YAML file and validate it.

    Resolves *config_path* relative to the current working directory first,
    then falls back to the project root (two levels above this file).

    Args:
        config_path: Path to the YAML configuration file.

    Returns:
        Validated application configuration.

    Raises:
        FileNotFoundError: If the configuration file cannot be found.
    """
    path = Path(config_path)
    if not path.exists():
        root_path = Path(__file__).resolve().parent.parent.parent / config_path
        if root_path.exists():
            path = root_path
        else:
            raise FileNotFoundError(f"Config file not found at {config_path}")

    with path.open(encoding="utf-8") as f:
        raw_config = yaml.safe_load(f)

    logger.info("Loaded configuration from %s", path)
    return AppConfig(**raw_config)

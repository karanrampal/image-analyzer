"""Unit tests for the config module."""

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.config import AgentConfig, AppConfig, ProjectConfig, load_config


class TestProjectConfig:
    """Tests for ProjectConfig validation."""

    def test_valid(self) -> None:
        """Test that a fully specified ProjectConfig is accepted."""
        cfg = ProjectConfig(id="my-project", location="europe-west1")
        assert cfg.id == "my-project"
        assert cfg.location == "europe-west1"

    def test_missing_id_raises(self) -> None:
        """Test that omitting the required id field raises ValidationError."""
        with pytest.raises(ValidationError):
            ProjectConfig(location="europe-west1")  # type: ignore[call-arg]

    def test_missing_location_raises(self) -> None:
        """Test that omitting the required location field raises ValidationError."""
        with pytest.raises(ValidationError):
            ProjectConfig(id="my-project")  # type: ignore[call-arg]

    def test_is_immutable(self) -> None:
        """Test that ProjectConfig fields cannot be mutated after construction."""
        cfg = ProjectConfig(id="my-project", location="europe-west1")
        with pytest.raises(ValidationError):
            cfg.id = "other"


class TestAgentConfig:
    """Tests for AgentConfig validation and field constraints."""

    def test_minimal_valid(self) -> None:
        """Test that only model_name is required; optional fields default correctly."""
        cfg = AgentConfig(model_name="gemini-pro")
        assert cfg.model_name == "gemini-pro"
        assert cfg.base_url is None
        assert cfg.thinking_level == "low"

    def test_full_valid(self) -> None:
        """Test that a fully specified AgentConfig is accepted and values are stored."""
        cfg = AgentConfig(
            model_name="gemini-pro",
            base_url="https://example.com",
            location="global",
            max_output_tokens=1024,
            temperature=0.5,
            thinking_level="high",
            timeout=30,
            max_retries=2,
        )
        assert cfg.max_output_tokens == 1024
        assert cfg.temperature == 0.5
        assert cfg.thinking_level == "high"

    def test_missing_model_name_raises(self) -> None:
        """Test that omitting the required model_name raises ValidationError."""
        with pytest.raises(ValidationError):
            AgentConfig()  # type: ignore[call-arg]

    def test_max_output_tokens_must_be_positive(self) -> None:
        """Test that max_output_tokens=0 is rejected (must be gt=0)."""
        with pytest.raises(ValidationError):
            AgentConfig(model_name="gemini-pro", max_output_tokens=0)

    def test_temperature_below_zero_raises(self) -> None:
        """Test that a temperature below 0.0 raises ValidationError."""
        with pytest.raises(ValidationError):
            AgentConfig(model_name="gemini-pro", temperature=-0.1)

    def test_temperature_above_two_raises(self) -> None:
        """Test that a temperature above 2.0 raises ValidationError."""
        with pytest.raises(ValidationError):
            AgentConfig(model_name="gemini-pro", temperature=2.1)

    def test_temperature_boundary_values_accepted(self) -> None:
        """Test that temperature boundary values 0.0 and 2.0 are both valid."""
        AgentConfig(model_name="gemini-pro", temperature=0.0)
        AgentConfig(model_name="gemini-pro", temperature=2.0)

    def test_invalid_thinking_level_raises(self) -> None:
        """Test that a thinking_level outside the allowed literals raises ValidationError."""
        with pytest.raises(ValidationError):
            AgentConfig(model_name="gemini-pro", thinking_level="extreme")  # type: ignore[arg-type]

    def test_timeout_must_be_positive(self) -> None:
        """Test that timeout=0 is rejected (must be gt=0)."""
        with pytest.raises(ValidationError):
            AgentConfig(model_name="gemini-pro", timeout=0)

    def test_max_retries_zero_allowed(self) -> None:
        """Test that max_retries=0 is valid (ge=0 constraint)."""
        cfg = AgentConfig(model_name="gemini-pro", max_retries=0)
        assert cfg.max_retries == 0

    def test_max_retries_negative_raises(self) -> None:
        """Test that a negative max_retries raises ValidationError."""
        with pytest.raises(ValidationError):
            AgentConfig(model_name="gemini-pro", max_retries=-1)

    def test_is_immutable(self) -> None:
        """Test that AgentConfig fields cannot be mutated after construction."""
        cfg = AgentConfig(model_name="gemini-pro")
        with pytest.raises(ValidationError):
            cfg.model_name = "other"


class TestLoadConfig:
    """Tests for load_config file loading and validation."""

    _VALID_YAML = textwrap.dedent("""\
        project:
          id: "test-project"
          location: "us-central1"
        agents:
          primary:
            model_name: "gemini-pro"
            temperature: 0.7
            max_output_tokens: 512
    """)

    def test_loads_valid_config(self, tmp_path: Path) -> None:
        """Test that a well-formed YAML file produces a fully populated AppConfig."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(self._VALID_YAML)
        cfg = load_config(str(config_file))
        assert isinstance(cfg, AppConfig)
        assert cfg.project.id == "test-project"
        assert cfg.project.location == "us-central1"
        assert "primary" in cfg.agents
        assert cfg.agents["primary"].model_name == "gemini-pro"
        assert cfg.agents["primary"].temperature == 0.7

    def test_multiple_agents_loaded(self, tmp_path: Path) -> None:
        """Test that multiple agents defined in YAML are all parsed into the agents dict."""
        yaml_content = textwrap.dedent("""\
            project:
              id: "proj"
              location: "eu"
            agents:
              fast:
                model_name: "gemini-flash"
              slow:
                model_name: "gemini-pro"
                timeout: 120
        """)
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content)
        cfg = load_config(str(config_file))
        assert len(cfg.agents) == 2
        assert cfg.agents["slow"].timeout == 120

    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        """Test that a missing config file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_config(str(tmp_path / "nonexistent.yaml"))

    def test_invalid_yaml_raises_validation_error(self, tmp_path: Path) -> None:
        """Test that a YAML file missing required top-level keys raises ValidationError."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("project:\n  id: 'only-project'\n")
        with pytest.raises(ValidationError):
            load_config(str(config_file))

    def test_invalid_field_type_raises_validation_error(self, tmp_path: Path) -> None:
        """Test that a YAML file with incorrect data types raises a ValidationError."""
        yaml_content = textwrap.dedent("""\
            project:
              id: "proj"
              location: "global"
            agents:
              primary:
                model_name: "gemini-pro"
                temperature: "very hot"
        """)
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content)
        with pytest.raises(ValidationError):
            load_config(str(config_file))

    def test_app_config_is_immutable(self, tmp_path: Path) -> None:
        """Test that AppConfig fields cannot be mutated after loading."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(self._VALID_YAML)
        cfg = load_config(str(config_file))
        with pytest.raises(ValidationError):
            cfg.project = ProjectConfig(id="x", location="y")

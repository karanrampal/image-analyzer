"""Unit tests for the agents.analyzer module."""

from typing import cast
from unittest.mock import MagicMock, patch

from langchain.agents import AgentState
from langchain.agents.structured_output import ProviderStrategy
from langchain_core.messages import AIMessage, HumanMessage
from langchain_google_genai import HarmBlockThreshold, HarmCategory

from agents.analyzer import (
    _ALLOWED_MSGPACK_MODULES,
    _SAFETY_SETTINGS,
    create_img_analysis_agent,
    create_llm,
    trim_messages,
)
from agents.instructions.system_prompts import ANALYZER_INSTRUCTION
from core.config import AgentConfig


def _make_agent_config(**overrides: object) -> AgentConfig:
    """Return a minimal AgentConfig, with optional field overrides."""
    defaults: dict = {
        "model_name": "gemini-pro",
        "location": "global",
        "temperature": 0.5,
        "max_output_tokens": 1024,
        "thinking_level": "low",
        "timeout": 30,
        "max_retries": 2,
    }
    defaults.update(overrides)
    return AgentConfig(**defaults)


class TestSafetySettings:
    """Tests for the _SAFETY_SETTINGS module constant."""

    def test_contains_all_harm_categories(self) -> None:
        """Test that all four harm categories are present in the safety settings."""
        expected = {
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
            HarmCategory.HARM_CATEGORY_HARASSMENT,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        }
        assert set(_SAFETY_SETTINGS.keys()) == expected

    def test_dangerous_content_blocked_low_and_above(self) -> None:
        """Test that dangerous content uses the most restrictive threshold."""
        assert (
            _SAFETY_SETTINGS[HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT]
            == HarmBlockThreshold.BLOCK_LOW_AND_ABOVE
        )


class TestAllowedMsgpackModules:
    """Tests for the _ALLOWED_MSGPACK_MODULES module constant."""

    def test_fashion_image_annotation_included(self) -> None:
        """Test that FashionImageAnnotation is in the allowed modules list."""
        assert (
            "agents.instructions.data_models",
            "FashionImageAnnotation",
        ) in _ALLOWED_MSGPACK_MODULES

    def test_all_entries_are_two_tuples(self) -> None:
        """Test that every entry in the list is a (module, class) pair."""
        for entry in _ALLOWED_MSGPACK_MODULES:
            assert len(entry) == 2, f"Expected 2-tuple, got: {entry}"


class TestCreateLlm:
    """Tests for the create_llm factory function."""

    @patch("agents.analyzer.ChatGoogleGenerativeAI")
    def test_model_name_forwarded(self, mock_cls: MagicMock) -> None:
        """Test that model_name from AgentConfig is passed to ChatGoogleGenerativeAI."""
        cfg = _make_agent_config(model_name="gemini-flash")
        create_llm("my-project", cfg)
        assert mock_cls.call_args.kwargs["model"] == "gemini-flash"

    @patch("agents.analyzer.ChatGoogleGenerativeAI")
    def test_vertexai_true_when_project_set(self, mock_cls: MagicMock) -> None:
        """Test that vertexai=True is set when a non-empty project is provided."""
        create_llm("my-project", _make_agent_config())
        assert mock_cls.call_args.kwargs["vertexai"] is True

    @patch("agents.analyzer.ChatGoogleGenerativeAI")
    def test_vertexai_false_when_no_project(self, mock_cls: MagicMock) -> None:
        """Test that vertexai=False is set when project is an empty string."""
        create_llm("", _make_agent_config())
        assert mock_cls.call_args.kwargs["vertexai"] is False

    @patch("agents.analyzer.ChatGoogleGenerativeAI")
    def test_thinking_kwargs_present_when_thinking_level_set(self, mock_cls: MagicMock) -> None:
        """Test that thinking_level and include_thoughts are added when thinking_level is set."""
        cfg = _make_agent_config(thinking_level="high")
        create_llm("proj", cfg)
        kwargs = mock_cls.call_args.kwargs
        assert kwargs["thinking_level"] == "high"
        assert kwargs["include_thoughts"] is True

    @patch("agents.analyzer.ChatGoogleGenerativeAI")
    def test_thinking_kwargs_absent_when_thinking_level_none(self, mock_cls: MagicMock) -> None:
        """Test that thinking_level and include_thoughts are omitted when thinking_level is None."""
        cfg = _make_agent_config(thinking_level=None)
        create_llm("proj", cfg)
        kwargs = mock_cls.call_args.kwargs
        assert "thinking_level" not in kwargs
        assert "include_thoughts" not in kwargs

    @patch("agents.analyzer.ChatGoogleGenerativeAI")
    def test_standard_params_forwarded(self, mock_cls: MagicMock) -> None:
        """Test that temperature, max_output_tokens, timeout, max_retries are all forwarded."""
        cfg = _make_agent_config(
            temperature=0.7,
            max_output_tokens=2048,
            timeout=60,
            max_retries=3,
        )
        create_llm("proj", cfg)
        kwargs = mock_cls.call_args.kwargs
        assert kwargs["temperature"] == 0.7
        assert kwargs["max_output_tokens"] == 2048
        assert kwargs["timeout"] == 60
        assert kwargs["max_retries"] == 3

    @patch("agents.analyzer.ChatGoogleGenerativeAI")
    def test_location_forwarded(self, mock_cls: MagicMock) -> None:
        """Test that location from AgentConfig is passed, defaulting to 'global' when None."""
        cfg = _make_agent_config(location="europe-west1")
        create_llm("proj", cfg)
        assert mock_cls.call_args.kwargs["location"] == "europe-west1"

    @patch("agents.analyzer.ChatGoogleGenerativeAI")
    def test_none_location_defaults_to_global(self, mock_cls: MagicMock) -> None:
        """Test that a None location falls back to 'global'."""
        cfg = _make_agent_config(location=None)
        create_llm("proj", cfg)
        assert mock_cls.call_args.kwargs["location"] == "global"

    @patch("agents.analyzer.ChatGoogleGenerativeAI")
    def test_safety_settings_always_applied(self, mock_cls: MagicMock) -> None:
        """Test that the module-level safety settings are always passed to the model."""
        create_llm("proj", _make_agent_config())
        assert mock_cls.call_args.kwargs["safety_settings"] is _SAFETY_SETTINGS


class TestTrimMessages:
    """Tests for the trim_messages middleware logic."""

    # The @before_model decorator wraps the function as an AgentMiddleware object.
    # The original logic is exposed via the .before_model bound method.
    _fn = trim_messages.before_model

    def _make_messages(self, count: int) -> list[HumanMessage | AIMessage]:
        """Return alternating HumanMessage/AIMessage objects with unique string IDs.

        lc_trim_messages requires real BaseMessage instances; MagicMocks are rejected.
        """
        msgs: list[HumanMessage | AIMessage] = []
        for i in range(count):
            if i % 2 == 0:
                msgs.append(HumanMessage(content=f"human-{i}", id=str(i)))
            else:
                msgs.append(AIMessage(content=f"ai-{i}", id=str(i)))
        return msgs

    def test_ten_or_fewer_messages_returns_none(self) -> None:
        """Test that no trimming occurs when there are 10 or fewer messages."""
        state = cast(AgentState, {"messages": self._make_messages(10)})
        result = self._fn(state, MagicMock())
        assert result is None

    def test_zero_messages_returns_none(self) -> None:
        """Test that an empty message list returns None."""
        state = cast(AgentState, {"messages": []})
        result = self._fn(state, MagicMock())
        assert result is None

    def test_eleven_messages_returns_remove_dict(self) -> None:
        """Test that 11 messages triggers trimming and returns a RemoveMessage dict."""
        state = cast(AgentState, {"messages": self._make_messages(11)})
        result = self._fn(state, MagicMock())
        assert result is not None
        assert "messages" in result

    def test_remove_messages_are_a_subset_of_original(self) -> None:
        """Test that only IDs present in the original message list are removed."""
        messages = self._make_messages(12)
        original_ids = {m.id for m in messages}
        state = cast(AgentState, {"messages": messages})
        result = self._fn(state, MagicMock())
        assert result is not None
        for rm in result["messages"]:
            assert rm.id in original_ids

    def test_some_messages_are_kept(self) -> None:
        """Test that not all messages are removed when > 10 messages exist."""
        messages = self._make_messages(12)
        state = cast(AgentState, {"messages": messages})
        result = self._fn(state, MagicMock())
        assert result is not None
        removed_ids = {rm.id for rm in result["messages"]}
        assert len(removed_ids) < len(messages)


class TestCreateImgAnalysisAgent:
    """Tests for the create_img_analysis_agent factory."""

    @patch("agents.analyzer.create_agent")
    @patch("agents.analyzer.create_llm")
    def test_returns_compiled_graph(
        self, _mock_create_llm: MagicMock, mock_create_agent: MagicMock
    ) -> None:
        """Test that the return value of create_agent is returned to the caller."""
        expected_graph = MagicMock()
        mock_create_agent.return_value = expected_graph
        result = create_img_analysis_agent("proj", _make_agent_config())
        assert result is expected_graph

    @patch("agents.analyzer.create_agent")
    @patch("agents.analyzer.create_llm")
    def test_create_llm_called_with_project_and_config(
        self, mock_create_llm: MagicMock, _mock_create_agent: MagicMock
    ) -> None:
        """Test that create_llm receives the project and agent_config arguments."""
        cfg = _make_agent_config()
        create_img_analysis_agent("my-proj", cfg)
        mock_create_llm.assert_called_once_with("my-proj", cfg)

    @patch("agents.analyzer.create_agent")
    @patch("agents.analyzer.create_llm")
    def test_no_checkpointer_by_default(
        self, _mock_create_llm: MagicMock, mock_create_agent: MagicMock
    ) -> None:
        """Test that checkpointer=None and no middleware when checkpointer=False."""
        create_img_analysis_agent("proj", _make_agent_config(), checkpointer=False)
        kwargs = mock_create_agent.call_args.kwargs
        assert kwargs.get("checkpointer") is None
        assert kwargs.get("middleware") == []

    @patch("agents.analyzer.InMemorySaver")
    @patch("agents.analyzer.create_agent")
    @patch("agents.analyzer.create_llm")
    def test_checkpointer_true_attaches_saver(
        self,
        _mock_create_llm: MagicMock,
        mock_create_agent: MagicMock,
        mock_saver_cls: MagicMock,
    ) -> None:
        """Test that checkpointer=True creates an InMemorySaver and passes it to create_agent."""
        mock_saver_instance = MagicMock()
        mock_saver_cls.return_value = mock_saver_instance
        create_img_analysis_agent("proj", _make_agent_config(), checkpointer=True)
        mock_saver_cls.assert_called_once()
        kwargs = mock_create_agent.call_args.kwargs
        assert kwargs["checkpointer"] is mock_saver_instance

    @patch("agents.analyzer.InMemorySaver")
    @patch("agents.analyzer.create_agent")
    @patch("agents.analyzer.create_llm")
    def test_checkpointer_true_adds_trim_middleware(
        self,
        _mock_create_llm: MagicMock,
        mock_create_agent: MagicMock,
        _mock_saver_cls: MagicMock,
    ) -> None:
        """Test that checkpointer=True includes trim_messages in the middleware list."""
        create_img_analysis_agent("proj", _make_agent_config(), checkpointer=True)
        kwargs = mock_create_agent.call_args.kwargs
        assert trim_messages in kwargs.get("middleware", [])

    @patch("agents.analyzer.create_agent")
    @patch("agents.analyzer.create_llm")
    def test_create_agent_called_with_correct_static_args(
        self, _mock_create_llm: MagicMock, mock_create_agent: MagicMock
    ) -> None:
        """Test that system_prompt, response_format, and name are passed to create_agent."""
        create_img_analysis_agent("proj", _make_agent_config())
        kwargs = mock_create_agent.call_args.kwargs
        assert kwargs["system_prompt"] == ANALYZER_INSTRUCTION
        assert isinstance(kwargs["response_format"], ProviderStrategy)
        assert kwargs["name"] == "image_analyzer"

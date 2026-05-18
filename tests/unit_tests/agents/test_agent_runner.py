"""Unit tests for the AgentRunner class."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.state import CompiledStateGraph

from agents.agent_runner import AgentRunner
from data_processing.image_processor import ImageType


@pytest.fixture(name="mock_agent")
def _mock_agent() -> MagicMock:
    """Return a MagicMock standing in for a CompiledStateGraph."""
    agent = MagicMock(spec=CompiledStateGraph)
    agent.checkpointer = None
    return agent


@pytest.fixture(name="runner")
def _runner(mock_agent: MagicMock) -> AgentRunner:
    """Return an AgentRunner backed by a mock agent."""
    return AgentRunner(mock_agent)


def _make_image_type(**overrides: Any) -> ImageType:
    """Return a minimal ImageType with optional field overrides."""
    defaults: dict[str, Any] = {
        "id": "img-001",
        "url": "http://example.com/photo.png",
        "mime_type": "image/png",
        "base64": "ZGF0YQ==",
    }
    defaults.update(overrides)
    return ImageType(**defaults)


class TestHasCheckpointer:
    """Tests for the has_checkpointer property."""

    def test_false_when_checkpointer_is_none(
        self, runner: AgentRunner, mock_agent: MagicMock
    ) -> None:
        """Test that has_checkpointer returns False when the agent has no checkpointer."""
        mock_agent.checkpointer = None
        assert runner.has_checkpointer is False

    def test_true_when_checkpointer_is_set(
        self, runner: AgentRunner, mock_agent: MagicMock
    ) -> None:
        """Test that has_checkpointer returns True when a checkpointer is attached."""
        mock_agent.checkpointer = MagicMock()
        assert runner.has_checkpointer is True


class TestBuildConfig:
    """Tests for the _build_config helper."""

    def test_thread_id_is_user_colon_session(self, runner: AgentRunner) -> None:
        """Test that the thread_id is composed as 'user_id:session_id'."""
        config = runner._build_config("user-1", "session-42")  # pylint: disable=protected-access
        assert config["configurable"]["thread_id"] == "user-1:session-42"

    def test_different_users_produce_different_configs(self, runner: AgentRunner) -> None:
        """Test that different user/session pairs produce distinct thread IDs."""
        a = runner._build_config("u1", "s1")  # pylint: disable=protected-access
        b = runner._build_config("u2", "s1")  # pylint: disable=protected-access
        assert a["configurable"]["thread_id"] != b["configurable"]["thread_id"]


class TestBuildMessage:
    """Tests for the _build_message helper."""

    def test_text_only_message(self, runner: AgentRunner) -> None:
        """Test that a text-only call produces a single text content block."""
        msg = runner._build_message("hello", None)  # pylint: disable=protected-access
        assert isinstance(msg, HumanMessage)
        assert msg.content == [{"type": "text", "text": "hello"}]

    def test_image_url_appended(self, runner: AgentRunner) -> None:
        """Test that a string URL is appended as an image URL content block."""
        msg = runner._build_message("describe", "http://x.com/img.jpg")  # pylint: disable=protected-access
        assert len(msg.content) == 2
        assert msg.content[1] == {"type": "image", "url": "http://x.com/img.jpg"}

    def test_image_type_appended_as_base64(self, runner: AgentRunner) -> None:
        """Test that an ImageType is appended with mime_type and base64 content block."""
        img = _make_image_type(mime_type="image/jpeg", base64="abc=")
        msg = runner._build_message("describe", img)  # pylint: disable=protected-access
        assert len(msg.content) == 2
        assert msg.content[1] == {"type": "image", "mime_type": "image/jpeg", "base64": "abc="}

    def test_text_block_always_first(self, runner: AgentRunner) -> None:
        """Test that the text content block is always the first element."""
        msg = runner._build_message("hi", _make_image_type())  # pylint: disable=protected-access
        assert msg.content[0] == {"type": "text", "text": "hi"}


class TestRun:
    """Tests for the AgentRunner.run async method."""

    @pytest.mark.asyncio
    async def test_returns_structured_response(
        self, runner: AgentRunner, mock_agent: MagicMock
    ) -> None:
        """Test that run() returns the 'structured_response' value from the agent output."""
        expected = MagicMock()
        mock_agent.ainvoke = AsyncMock(return_value={"structured_response": expected})
        result = await runner.run("u1", "s1", "analyze this")
        assert result is expected

    @pytest.mark.asyncio
    async def test_agent_invoked_with_message_and_config(
        self, runner: AgentRunner, mock_agent: MagicMock
    ) -> None:
        """Test that ainvoke is called with the constructed message and correct config."""
        mock_agent.ainvoke = AsyncMock(return_value={"structured_response": MagicMock()})
        await runner.run("user-A", "sess-B", "hello")
        call_args = mock_agent.ainvoke.call_args
        input_messages = call_args.args[0]["messages"]
        config = call_args.kwargs["config"]
        assert len(input_messages) == 1
        assert isinstance(input_messages[0], HumanMessage)
        assert config["configurable"]["thread_id"] == "user-A:sess-B"

    @pytest.mark.asyncio
    async def test_run_with_image_url(self, runner: AgentRunner, mock_agent: MagicMock) -> None:
        """Test that run() builds a message with an image URL when img is a string."""
        mock_agent.ainvoke = AsyncMock(return_value={"structured_response": MagicMock()})
        await runner.run("u1", "s1", "describe", img="http://img.com/a.jpg")
        message: HumanMessage = mock_agent.ainvoke.call_args.args[0]["messages"][0]
        assert any(
            part.get("type") == "image" and part.get("url") == "http://img.com/a.jpg"
            for part in message.content
            if isinstance(part, dict)
        )

    @pytest.mark.asyncio
    async def test_run_with_image_type(self, runner: AgentRunner, mock_agent: MagicMock) -> None:
        """Test that run() builds a message with base64 data when img is an ImageType."""
        mock_agent.ainvoke = AsyncMock(return_value={"structured_response": MagicMock()})
        img = _make_image_type(mime_type="image/png", base64="ZGF0YQ==")
        await runner.run("u1", "s1", "describe", img=img)
        message: HumanMessage = mock_agent.ainvoke.call_args.args[0]["messages"][0]
        assert any(
            part.get("type") == "image" and part.get("base64") == "ZGF0YQ=="
            for part in message.content
            if isinstance(part, dict)
        )


class TestGetMsgHistory:
    """Tests for the AgentRunner.get_msg_history async method."""

    @pytest.mark.asyncio
    async def test_raises_without_checkpointer(
        self, runner: AgentRunner, mock_agent: MagicMock
    ) -> None:
        """Test that get_msg_history raises RuntimeError when no checkpointer is set."""
        mock_agent.checkpointer = None
        with pytest.raises(RuntimeError, match="checkpointer"):
            await runner.get_msg_history("u1", "s1")

    @pytest.mark.asyncio
    async def test_returns_messages_from_state(
        self, runner: AgentRunner, mock_agent: MagicMock
    ) -> None:
        """Test that get_msg_history returns the messages list from the agent state."""
        messages = [HumanMessage(content="hi"), AIMessage(content="hello")]
        mock_state = MagicMock()
        mock_state.values = {"messages": messages}
        mock_agent.checkpointer = MagicMock()
        mock_agent.aget_state = AsyncMock(return_value=mock_state)
        result = await runner.get_msg_history("u1", "s1")
        assert result == messages

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_messages_key(
        self, runner: AgentRunner, mock_agent: MagicMock
    ) -> None:
        """Test that get_msg_history returns an empty list when state has no 'messages' key."""
        mock_state = MagicMock()
        mock_state.values = {}
        mock_agent.checkpointer = MagicMock()
        mock_agent.aget_state = AsyncMock(return_value=mock_state)
        result = await runner.get_msg_history("u1", "s1")
        assert result == []

    @pytest.mark.asyncio
    async def test_state_queried_with_correct_config(
        self, runner: AgentRunner, mock_agent: MagicMock
    ) -> None:
        """Test that aget_state is called with the thread_id config for the given user/session."""
        mock_state = MagicMock()
        mock_state.values = {"messages": []}
        mock_agent.checkpointer = MagicMock()
        mock_agent.aget_state = AsyncMock(return_value=mock_state)
        await runner.get_msg_history("user-X", "sess-Y")
        config = mock_agent.aget_state.call_args.args[0]
        assert config["configurable"]["thread_id"] == "user-X:sess-Y"


class TestGetStateHistory:
    """Tests for the AgentRunner.get_state_history async method."""

    @pytest.mark.asyncio
    async def test_raises_without_checkpointer(
        self, runner: AgentRunner, mock_agent: MagicMock
    ) -> None:
        """Test that get_state_history raises RuntimeError when no checkpointer is set."""
        mock_agent.checkpointer = None
        with pytest.raises(RuntimeError, match="checkpointer"):
            await runner.get_state_history("u1", "s1")

    @pytest.mark.asyncio
    async def test_returns_list_of_snapshots(
        self, runner: AgentRunner, mock_agent: MagicMock
    ) -> None:
        """Test that get_state_history collects all yielded snapshots into a list."""
        snapshots = [MagicMock(), MagicMock()]

        async def _fake_history(_config: Any) -> Any:
            for s in snapshots:
                yield s

        mock_agent.checkpointer = MagicMock()
        mock_agent.aget_state_history = _fake_history
        result = await runner.get_state_history("u1", "s1")
        assert result == snapshots

    @pytest.mark.asyncio
    async def test_empty_history_returns_empty_list(
        self, runner: AgentRunner, mock_agent: MagicMock
    ) -> None:
        """Test that an empty history yields an empty list."""

        async def _empty(_config: Any) -> Any:
            return
            yield

        mock_agent.checkpointer = MagicMock()
        mock_agent.aget_state_history = _empty
        result = await runner.get_state_history("u1", "s1")
        assert result == []

    @pytest.mark.asyncio
    async def test_history_queried_with_correct_config(
        self, runner: AgentRunner, mock_agent: MagicMock
    ) -> None:
        """Test that aget_state_history is called with the correct thread_id config."""
        received_configs: list[Any] = []

        async def _capture(config: Any) -> Any:
            received_configs.append(config)
            return
            yield

        mock_agent.checkpointer = MagicMock()
        mock_agent.aget_state_history = _capture
        await runner.get_state_history("user-1", "sess-2")
        assert received_configs[0]["configurable"]["thread_id"] == "user-1:sess-2"

"""Agent runner class to manage graph state and execution."""

import logging
from typing import Any

from langchain.messages import HumanMessage
from langchain_core.messages.base import BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StateSnapshot
from pydantic import BaseModel

from data_processing.image_processor import ImageType

logger = logging.getLogger(__name__)


class AgentRunner:
    """Manages invocation and history retrieval for a compiled LangGraph agent."""

    def __init__(self, agent: CompiledStateGraph) -> None:
        self._agent = agent

    @property
    def has_checkpointer(self) -> bool:
        """Whether the underlying agent has a checkpointer attached."""
        return self._agent.checkpointer is not None

    def _require_checkpointer(self) -> None:
        if not self.has_checkpointer:
            raise RuntimeError(
                "This operation requires a checkpointer. "
                "Create the agent with checkpointer=True to enable history."
            )

    def _build_config(self, user_id: str, session_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": f"{user_id}:{session_id}"}}

    def _build_message(self, text: str, img: str | ImageType | None) -> HumanMessage:
        content: list[str | dict[str, Any]] = [{"type": "text", "text": text}]
        if img is not None:
            if isinstance(img, str):
                logger.debug("Building message with image URL: %s", img)
                content.append({"type": "image", "url": img})
            else:
                logger.debug("Building message with image data: %s", img.id)
                content.append({"type": "image", "mime_type": img.mime_type, "base64": img.base64})
        return HumanMessage(content=content)

    async def run(
        self, user_id: str, session_id: str, text: str, img: str | ImageType | None = None
    ) -> BaseModel:
        """Invoke the agent asynchronously and return the structured result.

        Args:
            user_id: The ID of the user making the request.
            session_id: The session ID for the conversation thread.
            text: The text prompt to send to the agent.
            img: Optional image url or data to include in the message.

        Returns:
            The agent's output as a structured response.
        """
        message = self._build_message(text, img)
        response = await self._agent.ainvoke(
            {"messages": [message]},
            config=self._build_config(user_id, session_id),
        )
        return response["structured_response"]

    async def get_msg_history(self, user_id: str, session_id: str) -> list[BaseMessage]:
        """Retrieve the conversation messages for a given user/session.

        Args:
            user_id: The ID of the user.
            session_id: The session ID for the conversation thread.

        Returns:
            The list of messages in the current state.

        Raises:
            RuntimeError: If the agent was created without a checkpointer.
        """
        self._require_checkpointer()
        state = await self._agent.aget_state(self._build_config(user_id, session_id))
        return state.values.get("messages", [])

    async def get_state_history(self, user_id: str, session_id: str) -> list[StateSnapshot]:
        """Retrieve the full checkpoint history for a given user/session.

        Each entry is a StateSnapshot representing the graph state after each
        invocation. Snapshots are returned most-recent first.

        Args:
            user_id: The ID of the user.
            session_id: The session ID for the conversation thread.

        Returns:
            A list of StateSnapshot objects ordered most-recent first.

        Raises:
            RuntimeError: If the agent was created without a checkpointer.
        """
        self._require_checkpointer()
        return [
            snapshot
            async for snapshot in self._agent.aget_state_history(
                self._build_config(user_id, session_id)
            )
        ]

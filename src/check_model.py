#!/usr/bin/env python
"""Check the model's ability to process image inputs and generate annotations."""

import asyncio
import copy
import logging
from typing import Any

from agents.agent_runner import AgentRunner
from agents.analyzer import create_img_analysis_agent
from core.config import load_config
from core.logger import setup_logger
from data_processing.image_processor import process_image

logger = logging.getLogger(__name__)


def _redact_messages(messages: list) -> list:
    """Return a copy of messages with base64 image data replaced by a placeholder."""
    redacted = []
    for msg in messages:
        msg_copy = copy.copy(msg)
        if isinstance(msg_copy.content, list):
            new_content: list[Any] = []
            for block in msg_copy.content:
                if isinstance(block, dict) and "base64" in block:
                    block = {**block, "base64": "<redacted>"}
                new_content.append(block)
            msg_copy.content = new_content
        redacted.append(msg_copy)
    return redacted


async def main() -> None:
    """Main function to check the model."""
    setup_logger()
    config = load_config("./configs/config.yaml")

    agent = create_img_analysis_agent(
        project=config.project.id,
        agent_config=config.agents["analyzer"],
        checkpointer=True,
    )
    agent_runner = AgentRunner(agent)

    text_msg = "Can you annotate the following image?"
    img_url = (
        "https://image.hm.com/assets/hm/43/70/43708d15327691058a0d1b958f97ff0271f756d7.jpg?ver=2"
    )
    img = await process_image(img_url)
    user_id = "test_user"
    session_id = "test_session"

    response = await agent_runner.run(
        user_id=user_id,
        session_id=session_id,
        text=text_msg,
        img=img,
    )
    print("Agent response:\n", response)
    if agent_runner.has_checkpointer:
        print("\nConversation history:\n")
        print(
            _redact_messages(
                await agent_runner.get_msg_history(user_id=user_id, session_id=session_id)
            )
        )
        print("\nGraph state history:")
        for snapshot in await agent_runner.get_state_history(
            user_id=user_id, session_id=session_id
        ):
            msgs = _redact_messages(snapshot.values.get("messages", []))
            print({"messages": msgs, "metadata": snapshot.metadata})


if __name__ == "__main__":
    asyncio.run(main())

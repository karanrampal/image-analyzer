"""Image analysis agent"""

import logging

from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import before_model
from langchain.agents.structured_output import ProviderStrategy
from langchain.messages import RemoveMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import trim_messages as lc_trim_messages
from langchain_core.messages.base import BaseMessage
from langchain_google_genai import ChatGoogleGenerativeAI, HarmBlockThreshold, HarmCategory
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from agents.instructions.data_models import FashionImageAnnotation
from agents.instructions.system_prompts import ANALYZER_INSTRUCTION
from core.config import AgentConfig

logger = logging.getLogger(__name__)


_SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
}

_ALLOWED_MSGPACK_MODULES: list[tuple[str, str]] = [
    ("google.genai.types", "HarmCategory"),
    ("google.genai.types", "HarmBlockThreshold"),
    ("google.genai.types", "HarmProbability"),
    ("google.genai.types", "HarmSeverity"),
    ("agents.instructions.data_models", "ModelEnum"),
    ("agents.instructions.data_models", "YesNoEnum"),
    ("agents.instructions.data_models", "EnvironmentEnum"),
    ("agents.instructions.data_models", "SmileEnum"),
    ("agents.instructions.data_models", "ColorEnum"),
    ("agents.instructions.data_models", "MovementEnum"),
    ("agents.instructions.data_models", "EyesEnum"),
    ("agents.instructions.data_models", "FramingEnum"),
    ("agents.instructions.data_models", "LightingEnum"),
    ("agents.instructions.data_models", "PoseEnum"),
    ("agents.instructions.data_models", "HandPlacementEnum"),
    ("agents.instructions.data_models", "FashionImageAnnotation"),
]


def create_llm(
    project: str,
    agent_config: AgentConfig,
) -> BaseChatModel:
    """Create a langchain ChatModel instance with specified parameters.

    Args:
        project: The Google Cloud project ID where the language model instance is deployed.
        agent_config: Configuration for creating an agent.

    Returns:
        A langchain ChatModel instance configured with the specified parameters.
    """
    has_thinking = agent_config.thinking_level is not None
    is_vertexai = bool(project)

    extra: dict = {}
    if has_thinking:
        extra["thinking_level"] = agent_config.thinking_level
        extra["include_thoughts"] = True

    return ChatGoogleGenerativeAI(
        model=agent_config.model_name,
        project=project,
        location=agent_config.location or "global",
        vertexai=is_vertexai,
        temperature=agent_config.temperature,
        **extra,
        max_output_tokens=agent_config.max_output_tokens,
        timeout=agent_config.timeout,
        max_retries=agent_config.max_retries,
        safety_settings=_SAFETY_SETTINGS,
    )


@before_model
def trim_messages(state: AgentState, runtime: Runtime) -> dict[str, list[BaseMessage]] | None:  # pylint: disable=unused-argument
    """Keep only the last 10 messages (5 human/AI pairs) to fit context window."""
    messages = state["messages"]

    if len(messages) <= 10:
        return None

    kept = lc_trim_messages(
        messages, strategy="last", max_tokens=10, token_counter=len, start_on="human"
    )
    kept_ids = {m.id for m in kept}
    return {"messages": [RemoveMessage(id=str(m.id)) for m in messages if m.id not in kept_ids]}


def create_img_analysis_agent(
    project: str,
    agent_config: AgentConfig,
    *,
    checkpointer: bool = False,
) -> CompiledStateGraph:
    """Create an image analysis agent

    Args:
        project: The Google Cloud project ID where the language model instance is deployed.
        agent_config: Configuration for creating an agent.
        checkpointer: Whether to attach an in-memory checkpointer for conversation history. Disable
            for single-shot batch jobs to avoid unbounded memory growth.

    Returns:
        A langchain agent graph.
    """
    llm = create_llm(project, agent_config)
    saver = None
    middleware = []
    if checkpointer:
        saver = InMemorySaver(
            serde=JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_MSGPACK_MODULES)
        )
        middleware.append(trim_messages)
    return create_agent(
        llm,
        system_prompt=ANALYZER_INSTRUCTION,
        response_format=ProviderStrategy(FashionImageAnnotation),
        middleware=middleware,
        checkpointer=saver,
        name="image_analyzer",
    )

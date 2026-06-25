"""Scitrera Ecosystem Messaging Spec — Python reference implementation.

See ``docs/UNIVERSAL_MESSAGE_SPEC.md`` for the normative document.
"""
from typing import Any

from pydantic import TypeAdapter

from .adapters import (
    from_cowork_blocks,
    from_rt_envelope,
    to_anthropic_messages,
    to_openai_chat_completion,
)
from .events import (
    MessageFinalized,
    MessageStarted,
    PartAppended,
    PartUpdated,
    StreamEvent,
    TokenDelta,
    apply_event,
    parse_event,
)
from .schema import (
    SCHEMA_VERSION,
    ChatMessage,
    CitationPart,
    ContentPart,
    ControlPart,
    DynamicPart,
    FeedbackPart,
    FilePart,
    ImagePart,
    MessageAddress,
    MessageRef,
    ReasoningPart,
    Role,
    SubagentPart,
    SubagentStatus,
    TextPart,
    ToolCallPart,
    ToolCallStatus,
    ToolError,
    ToolResultPart,
    UnknownPart,
)
from .tools import (
    TOOLS_SCHEMA_VERSION,
    ToolDescriptor,
    ToolInvokeEnvelope,
)
from .memorylayer import (
    from_memorylayer_message,
    to_memorylayer_payload,
    to_memorylayer_payloads,
)
from .streaming import EventSink, MessageBuilder

__version__ = "1.0.1"


def chat_message_json_schema() -> dict[str, Any]:
    """Return the JSON Schema describing a canonical ``ChatMessage``."""
    return ChatMessage.model_json_schema()


def stream_event_json_schema() -> dict[str, Any]:
    """Return the JSON Schema describing the discriminated ``StreamEvent`` union."""
    return TypeAdapter(StreamEvent).json_schema()

__all__ = [
    "__version__",
    "chat_message_json_schema",
    "stream_event_json_schema",
    # schema
    "SCHEMA_VERSION",
    "Role",
    "ToolCallStatus",
    "SubagentStatus",
    "ChatMessage",
    "MessageAddress",
    "MessageRef",
    "ContentPart",
    "TextPart",
    "ImagePart",
    "FilePart",
    "ToolCallPart",
    "ToolResultPart",
    "ToolError",
    "CitationPart",
    "DynamicPart",
    "ReasoningPart",
    "SubagentPart",
    "ControlPart",
    "FeedbackPart",
    "UnknownPart",
    # tools (spec 1.1)
    "TOOLS_SCHEMA_VERSION",
    "ToolDescriptor",
    "ToolInvokeEnvelope",
    # events
    "MessageStarted",
    "PartAppended",
    "TokenDelta",
    "PartUpdated",
    "MessageFinalized",
    "StreamEvent",
    "parse_event",
    "apply_event",
    # streaming
    "MessageBuilder",
    "EventSink",
    # adapters
    # memorylayer
    "to_memorylayer_payload",
    "to_memorylayer_payloads",
    "from_memorylayer_message",
    # adapters
    "from_rt_envelope",
    "from_cowork_blocks",
    "to_openai_chat_completion",
    "to_anthropic_messages",
]

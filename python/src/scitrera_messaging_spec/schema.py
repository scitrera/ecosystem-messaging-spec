"""Universal ChatMessage schema (v1).

Defines the canonical, at-rest JSON shape for chat messages and content
parts across the Scitrera platform (frontend, office-addin, cowork,
workclaw, MemoryLayer-at-rest, Aether wire). See
``docs/UNIVERSAL_MESSAGE_SPEC.md`` for the normative spec.

Design choices baked in here:

- Inline content-block list: ``ChatMessage.content`` is an ordered list of
  ``ContentPart`` objects (text, image, file, tool_call, tool_result,
  citation, dynamic, reasoning, or unknown).
- Forward-compatible discriminator: parts with an unrecognized ``type``
  field deserialize into ``UnknownPart`` (which preserves all keys
  verbatim) instead of failing. Round-tripping an unknown part must
  re-emit the same JSON.
- Binary content is reference-only: ``ImagePart`` / ``FilePart`` carry
  ``vfs_ref`` or ``uri`` (or, as an escape hatch for images, ``data_uri``).
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag

SCHEMA_VERSION: str = "1.0"

# ---------------------------------------------------------------------------
# Content parts
# ---------------------------------------------------------------------------

_KNOWN_PART_TYPES = frozenset(
    {
        "text",
        "image",
        "file",
        "tool_call",
        "tool_result",
        "citation",
        "dynamic",
        "reasoning",
        "subagent",
        "control",
        "feedback",
    }
)


class _PartBase(BaseModel):
    model_config = ConfigDict(extra="allow")


class TextPart(_PartBase):
    type: Literal["text"] = "text"
    text: str = ""
    annotations: list[dict[str, Any]] | None = None


class ImagePart(_PartBase):
    type: Literal["image"] = "image"
    mime: str | None = None
    vfs_ref: str | None = None
    uri: str | None = None
    data_uri: str | None = None
    alt_text: str | None = None


class FilePart(_PartBase):
    """Generic non-image binary attachment (PDFs, audio, video, etc.)."""

    type: Literal["file"] = "file"
    vfs_ref: str | None = None
    uri: str | None = None
    mime: str | None = None
    file_name: str | None = None
    size_bytes: int | None = None
    purpose: Literal["attachment", "document", "generated"] | None = None


ToolCallStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


class ToolCallPart(_PartBase):
    type: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    status: ToolCallStatus = "pending"
    started_at: str | None = None
    finished_at: str | None = None
    meta: dict[str, Any] | None = None


class ToolError(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str | None = None
    message: str = ""


class ToolResultPart(_PartBase):
    type: Literal["tool_result"] = "tool_result"
    call_id: str
    name: str | None = None
    output: Any = None
    output_text: str | None = None
    is_error: bool = False
    error: ToolError | None = None
    meta: dict[str, Any] | None = None


class CitationPart(_PartBase):
    type: Literal["citation"] = "citation"
    id: str | None = None
    source: str | None = None
    title: str | None = None
    snippet: str | None = None
    span: tuple[int, int] | None = None
    meta: dict[str, Any] | None = None


class DynamicPart(_PartBase):
    type: Literal["dynamic"] = "dynamic"
    kind: str
    payload: Any = None
    interactive: bool = False


class ReasoningPart(_PartBase):
    type: Literal["reasoning"] = "reasoning"
    text: str = ""
    redacted: bool = False


SubagentStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


class SubagentPart(_PartBase):
    """A reference to a subagent's conversation.

    Subagents have their own thread (``thread_id``) whose messages are
    persisted independently and back-reference this part via
    ``MessageRef.parent_thread_id`` / ``MessageRef.parent_message_id``.
    The parent message carries only the reference + a short summary —
    the full subagent transcript lives on its own thread.
    """

    type: Literal["subagent"] = "subagent"
    id: str
    name: str
    thread_id: str
    input: Any = None
    status: SubagentStatus = "pending"
    summary: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    meta: dict[str, Any] | None = None


class ControlPart(_PartBase):
    """In-band control signal carried as a content part.

    Used for cross-process control signals (cancel, pause, resume, etc.)
    that need to travel on the same wire as the conversation rather than
    over a separate side channel. The first known ``kind`` is ``"cancel"``,
    which targets a specific ``task_id`` for abort.

    ``kind`` is an open registry — new control kinds may be added without
    bumping ``schema_version``. Consumers MUST preserve unknown kinds on
    round-trip (forward-compat per spec §3.10) and SHOULD ignore kinds
    they don't recognize rather than erroring.

    Required fields per kind:
      - ``kind == "cancel"`` requires ``task_id``.

    Future kinds may add their own required fields under the same
    ``extra="allow"`` extension policy used by other parts.
    """

    type: Literal["control"] = "control"
    kind: str
    task_id: str | None = None


class FeedbackPart(_PartBase):
    """User feedback on another message, carried as a content part.

    A feedback message is a ``ChatMessage`` whose ``content`` is a single
    ``FeedbackPart`` and whose ``ref.message_id`` points at the target
    message being rated. The carrier message uses ``role: "user"`` (the
    user is the actor) and ``ref.relationship == "feedback"``.

    Semantics:
      - Non-conversational metadata about another message. Persisted to
        MemoryLayer for analytics, but the LangChain adapter skips
        feedback-only messages so the model never sees them on resume.
      - ``sentiment`` is an integer (not a Literal) to leave room for
        richer scales later (e.g. ``-2..+2`` or per-axis ratings). The
        established convention is ``+1`` = positive, ``-1`` = negative,
        ``0`` = cleared / no opinion. Consumers MUST preserve unknown
        integer values on round-trip rather than validating as an enum.
      - ``text`` is an optional free-form reason.

    Like ``ControlPart``, the carrier-part is on an open extension
    namespace — new fields under ``extra="allow"`` round-trip verbatim.
    """

    type: Literal["feedback"] = "feedback"
    sentiment: int
    text: str | None = None


class UnknownPart(BaseModel):
    """Catch-all for content-part ``type`` values this code doesn't recognize.

    The original ``type`` string and every other key on the input dict are
    preserved verbatim so the part round-trips back to the wire unchanged.
    This is the mechanism that lets a new consumer add a content type next
    quarter without breaking older consumers.
    """

    model_config = ConfigDict(extra="allow")

    type: str


def _part_discriminator(value: Any) -> str:
    """Pydantic discriminator: dispatch known ``type`` values, else 'unknown'."""
    if isinstance(value, dict):
        t = value.get("type")
    else:
        t = getattr(value, "type", None)
    if isinstance(t, str) and t in _KNOWN_PART_TYPES:
        return t
    return "unknown"


ContentPart = Annotated[
    Union[
        Annotated[TextPart, Tag("text")],
        Annotated[ImagePart, Tag("image")],
        Annotated[FilePart, Tag("file")],
        Annotated[ToolCallPart, Tag("tool_call")],
        Annotated[ToolResultPart, Tag("tool_result")],
        Annotated[CitationPart, Tag("citation")],
        Annotated[DynamicPart, Tag("dynamic")],
        Annotated[ReasoningPart, Tag("reasoning")],
        Annotated[SubagentPart, Tag("subagent")],
        Annotated[ControlPart, Tag("control")],
        Annotated[FeedbackPart, Tag("feedback")],
        Annotated[UnknownPart, Tag("unknown")],
    ],
    Discriminator(_part_discriminator),
]


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


class MessageAddress(BaseModel):
    """Routing + indexing metadata.

    All fields optional. Carried on every ChatMessage so MemoryLayer and
    downstream tooling have a stable, indexable set of identifiers without
    spelunking into ``meta``.
    """

    model_config = ConfigDict(extra="allow")

    tenant_id: str | None = None
    workspace_id: str | None = None
    user_id: str | None = None
    thread_id: str | None = None
    app_id: str | None = None
    agent_id: str | None = None
    task_id: str | None = None
    request_id: str | None = None
    telemetry: dict[str, Any] | None = None


class MessageRef(BaseModel):
    """Optional inter-message relationships.

    ``parent_id`` / ``in_reply_to`` / ``edits_id`` refer to messages within
    the same thread. ``parent_thread_id`` + ``parent_message_id`` cross
    thread boundaries — used by subagent threads to back-reference the
    parent message that spawned them.
    """

    model_config = ConfigDict(extra="allow")

    parent_id: str | None = None
    in_reply_to: str | None = None
    edits_id: str | None = None
    parent_thread_id: str | None = None
    parent_message_id: str | None = None


Role = Literal["user", "assistant", "system", "tool"]


class ChatMessage(BaseModel):
    """Universal chat message (spec v1).

    The same JSON form is used at rest (MemoryLayer), on the wire (Aether
    payload, WebSocket relay final-form), and in each client's in-memory
    state. Streaming clients reconstruct this from the event vocabulary in
    :mod:`events`.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: str = SCHEMA_VERSION
    id: str
    role: Role
    created_at: str | None = None
    content: list[ContentPart] = Field(default_factory=list)
    addr: MessageAddress = Field(default_factory=MessageAddress)
    meta: dict[str, Any] = Field(default_factory=dict)
    ref: MessageRef | None = None


__all__ = [
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
]

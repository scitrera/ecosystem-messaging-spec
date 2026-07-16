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
        "todo",
        "approval_request",
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


# Dynamic-part kinds (open registry; §3.7). Each consumer ships its own renderer.
DYNAMIC_JSX = "jsx"
DYNAMIC_TOOL_CALL_PROGRESS = "tool_call_progress"

ProgressStatus = Literal["running", "done", "error"]


class ToolCallProgressPayload(BaseModel):
    """Standardized payload for a dynamic ``tool_call_progress`` part.

    A live tqdm-style progress bar streamed from long-running tool / in-sandbox
    code execution. ``bar_id`` is the STABLE identity — consumers key the
    rendered bar on it, and it maps to the streamed part id (``part_appended`` on
    first sighting, ``part_updated`` after). Timing fields are best-effort
    snapshots.
    """

    model_config = ConfigDict(extra="allow")

    bar_id: str
    desc: str | None = None
    n: float = 0.0
    total: float | None = None  # None = unknown length
    elapsed_s: float | None = None
    rate: float | None = None  # iterations per second
    eta_s: float | None = None  # best-effort seconds remaining
    unit: str = "it"
    status: ProgressStatus = "running"
    nest: int = 0  # nesting depth for concurrent / nested bars
    meta: dict[str, Any] | None = None


def make_tool_call_progress_part(
    payload: "ToolCallProgressPayload | dict[str, Any]",
) -> DynamicPart:
    """Build a dynamic ``tool_call_progress`` part (a live progress bar)."""
    if isinstance(payload, ToolCallProgressPayload):
        data = payload.model_dump(exclude_none=True)
    else:
        data = dict(payload)
    return DynamicPart(kind=DYNAMIC_TOOL_CALL_PROGRESS, payload=data, interactive=False)


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
      - ``kind == "rename"`` requires ``payload.title`` (non-empty); targets
        ``addr.thread_id``.

    Future kinds may add their own required fields under the same
    ``extra="allow"`` extension policy used by other parts.
    """

    type: Literal["control"] = "control"
    kind: str
    task_id: str | None = None
    # Used by the approve/deny kinds to resolve a specific approval_request
    # (request_id = the approval_request's id; scope = once|session|always,
    # ignored for deny).
    request_id: str | None = None
    scope: str | None = None
    # Optional per-kind data (mirrors ``DynamicPart.payload``, spec §3.7). Its
    # shape is defined by convention per ``kind`` — e.g. the ``rename`` kind
    # carries ``{"title": "..."}``. The fields above are cross-cutting correlation
    # ids that generic handlers route on; kind-specific data lives here so new
    # kinds (or new per-kind fields) need no schema change.
    payload: Any = None


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


TodoStatus = Literal["pending", "in_progress", "completed", "cancelled"]


class TodoItem(BaseModel):
    """A single entry in a todo content part."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    content: str = ""
    status: TodoStatus = "pending"
    # Present-tense label shown while the item is in_progress (e.g. "Wiring
    # sahara commit"); optional.
    active_form: str | None = None


class TodoPart(_PartBase):
    """A shared, mutable checklist surfaced in the conversation.

    The agent writes the full list on each update; live updates ride
    ``part_updated`` (patch ``{items}``). It persists via the MemoryLayer
    codec like any other part. The ``id`` is stable so consumers can render
    the latest todo part as the live board across turns.
    """

    type: Literal["todo"] = "todo"
    id: str | None = None
    title: str | None = None
    items: list[TodoItem] = Field(default_factory=list)
    meta: dict[str, Any] | None = None


ApprovalStatus = Literal["pending", "approved", "denied", "expired"]


class ApprovalRequestPart(_PartBase):
    """A human-in-the-loop permission prompt.

    The agent asks the user to authorize a tool call that is not
    pre-authorized. The user answers with a ``ControlPart`` (kind
    ``approve``/``deny``, ``request_id`` == this part's ``id``). The part is
    mutated in place (``part_updated``) to flip ``status`` as it resolves, and
    persists like any other part.
    """

    type: Literal["approval_request"] = "approval_request"
    id: str
    tool: str
    summary: str | None = None
    args: Any = None
    # Scopes the user may grant (subset of once|session|always).
    options: list[str] = Field(default_factory=list)
    status: ApprovalStatus = "pending"
    reason: str | None = None
    meta: dict[str, Any] | None = None


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
        Annotated[TodoPart, Tag("todo")],
        Annotated[ApprovalRequestPart, Tag("approval_request")],
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
    "DYNAMIC_JSX",
    "DYNAMIC_TOOL_CALL_PROGRESS",
    "ProgressStatus",
    "ToolCallProgressPayload",
    "make_tool_call_progress_part",
    "ReasoningPart",
    "SubagentPart",
    "ControlPart",
    "FeedbackPart",
    "TodoStatus",
    "TodoItem",
    "TodoPart",
    "ApprovalStatus",
    "ApprovalRequestPart",
    "UnknownPart",
]

"""Sender-side helpers for constructing ChatMessages and emitting stream events.

:class:`MessageBuilder` is the canonical sender-side counterpart to
:func:`scitrera_messaging_spec.events.apply_event`. It maintains an
in-memory ``ChatMessage`` and shoves a typed stream event through a
``sink`` callable each time you mutate the message. When you call
``finalize()``, the message-in-hand is bit-for-bit equal to what
``apply_event`` would have reconstructed on the receiver from the same
event sequence.

Typical use::

    events: list[StreamEvent] = []
    b = MessageBuilder.start(
        id="msg_1",
        role="assistant",
        addr=MessageAddress(workspace_id="w1", thread_id="t1"),
        sink=events.append,
    )
    text_idx = b.add_text()
    b.append_token(text_idx, "Looking up the report.")
    call_idx = b.add_tool_call(id="c1", name="vfs_fetch", args={"path": "/r.pdf"})
    b.update_tool_status("c1", "running")
    b.add_tool_result("c1", output_text="Q3 revenue was $4.2M.")
    b.update_tool_status("c1", "completed")
    b.add_text("Q3 revenue was **$4.2M**.")
    b.add_citation(source="vfs://r.pdf", title="Q3 Report")
    final = b.finalize()

The ``sink`` is a plain synchronous callable. Async senders should
adapt by pushing into a queue / scheduling a task inside the sink.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Iterator

from pydantic import BaseModel

from .events import (
    MessageFinalized,
    MessageStarted,
    PartAppended,
    PartUpdated,
    StreamEvent,
    TokenDelta,
)
from .schema import (
    ChatMessage,
    CitationPart,
    ContentPart,
    DynamicPart,
    FilePart,
    ImagePart,
    MessageAddress,
    ReasoningPart,
    Role,
    SubagentPart,
    SubagentStatus,
    TextPart,
    ToolCallPart,
    ToolCallStatus,
    ToolError,
    ToolResultPart,
)

EventSink = Callable[[StreamEvent], Any]

# Re-use the events module's adapter for re-validating patched parts.
from .events import _part_adapter  # noqa: E402  (intentional internal import)


class MessageBuilder:
    """Incremental ChatMessage builder that emits spec stream events."""

    __slots__ = (
        "_msg",
        "_sink",
        "_tool_call_index",
        "_subagent_index",
        "_finalized",
    )

    def __init__(self, message: ChatMessage, sink: EventSink) -> None:
        self._msg = message
        self._sink = sink
        self._tool_call_index: dict[str, int] = {}
        self._subagent_index: dict[str, int] = {}
        self._finalized = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def start(
        cls,
        *,
        id: str,
        sink: EventSink,
        role: Role = "assistant",
        addr: MessageAddress | None = None,
        meta: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> "MessageBuilder":
        """Open a new in-flight message and emit ``message_started``."""
        if created_at is None:
            created_at = datetime.now(timezone.utc).isoformat()
        msg = ChatMessage(
            id=id,
            role=role,
            addr=addr or MessageAddress(),
            meta=meta or {},
            created_at=created_at,
            content=[],
        )
        b = cls(msg, sink)
        b._emit(MessageStarted(message=msg.model_copy(deep=True)))
        return b

    def finalize(self) -> ChatMessage:
        """Emit ``message_finalized`` and return a deep copy of the message.

        Calling ``finalize`` a second time is a no-op (returns the same
        snapshot, no second event).
        """
        snapshot = self._msg.model_copy(deep=True)
        if not self._finalized:
            self._emit(MessageFinalized(message_id=snapshot.id, message=snapshot))
            self._finalized = True
        return snapshot

    @property
    def message(self) -> ChatMessage:
        """Read-only snapshot of the in-flight message (deep-copied)."""
        return self._msg.model_copy(deep=True)

    def set_meta(self, namespace: str, values: dict[str, Any]) -> None:
        """Merge ``values`` into ``message.meta[namespace]`` in place.

        Meta updates are *not* streamed as events in v1 — they show up on the
        receiver only via the ``message_finalized`` event's full snapshot.
        Use this for terminal-state stamping (stop_reason, error info,
        aborted flag, etc.) right before :meth:`finalize`.
        """
        bucket = self._msg.meta.setdefault(namespace, {})
        bucket.update(values)

    @property
    def id(self) -> str:
        return self._msg.id

    # ------------------------------------------------------------------
    # Append helpers
    # ------------------------------------------------------------------

    def add_text(self, text: str = "", *, annotations: list[dict[str, Any]] | None = None) -> int:
        """Append a new text part. Returns the content index."""
        return self.append_part(TextPart(text=text, annotations=annotations))

    def append_token(self, index: int, text: str) -> None:
        """Append ``text`` to a previously-added text or reasoning part."""
        if not text:
            return
        if not (0 <= index < len(self._msg.content)):
            raise IndexError(f"part index {index} out of range")
        part = self._msg.content[index]
        cur = getattr(part, "text", None)
        if not isinstance(cur, str):
            raise TypeError(
                f"append_token target at index {index} is not a text/reasoning part"
            )
        new_part = part.model_copy(update={"text": cur + text})
        self._msg.content[index] = new_part
        self._emit(TokenDelta(message_id=self._msg.id, index=index, text=text))

    def add_tool_call(
        self,
        id: str,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        status: ToolCallStatus = "pending",
        started_at: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> int:
        """Append a tool_call part and index it by ``id``."""
        if id in self._tool_call_index:
            raise ValueError(f"duplicate tool_call id: {id!r}")
        part = ToolCallPart(
            id=id,
            name=name,
            args=args or {},
            status=status,
            started_at=started_at,
            meta=meta,
        )
        idx = self.append_part(part)
        self._tool_call_index[id] = idx
        return idx

    def update_tool_status(
        self,
        call_id: str,
        status: ToolCallStatus,
        *,
        finished_at: str | None = None,
        meta_patch: dict[str, Any] | None = None,
    ) -> None:
        """Patch a previously-added tool_call's status (and optionally finished_at/meta)."""
        idx = self._tool_call_index.get(call_id)
        if idx is None:
            raise KeyError(f"unknown tool_call id: {call_id!r}")
        patch: dict[str, Any] = {"status": status}
        if finished_at is not None:
            patch["finished_at"] = finished_at
        if meta_patch is not None:
            # Builder helper merges into existing meta dict so callers don't
            # accidentally clobber prior keys.
            existing = self._msg.content[idx].meta or {}  # type: ignore[union-attr]
            patch["meta"] = {**existing, **meta_patch}
        self.patch_part(idx, patch)

    def add_tool_result(
        self,
        call_id: str,
        *,
        name: str | None = None,
        output: Any = None,
        output_text: str | None = None,
        is_error: bool = False,
        error: ToolError | dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> int:
        if isinstance(error, dict):
            error = ToolError.model_validate(error)
        part = ToolResultPart(
            call_id=call_id,
            name=name,
            output=output,
            output_text=output_text,
            is_error=is_error or bool(error),
            error=error,
            meta=meta,
        )
        return self.append_part(part)

    def add_citation(
        self,
        *,
        id: str | None = None,
        source: str | None = None,
        title: str | None = None,
        snippet: str | None = None,
        span: tuple[int, int] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> int:
        return self.append_part(
            CitationPart(
                id=id, source=source, title=title, snippet=snippet, span=span, meta=meta
            )
        )

    def add_file(
        self,
        *,
        vfs_ref: str | None = None,
        uri: str | None = None,
        mime: str | None = None,
        file_name: str | None = None,
        size_bytes: int | None = None,
        purpose: str | None = None,
    ) -> int:
        return self.append_part(
            FilePart(
                vfs_ref=vfs_ref,
                uri=uri,
                mime=mime,
                file_name=file_name,
                size_bytes=size_bytes,
                purpose=purpose,  # type: ignore[arg-type]
            )
        )

    def add_image(
        self,
        *,
        vfs_ref: str | None = None,
        uri: str | None = None,
        data_uri: str | None = None,
        mime: str | None = None,
        alt_text: str | None = None,
    ) -> int:
        return self.append_part(
            ImagePart(
                vfs_ref=vfs_ref, uri=uri, data_uri=data_uri, mime=mime, alt_text=alt_text
            )
        )

    def add_dynamic(self, kind: str, payload: Any = None, *, interactive: bool = False) -> int:
        return self.append_part(DynamicPart(kind=kind, payload=payload, interactive=interactive))

    def add_reasoning(self, text: str = "", *, redacted: bool = False) -> int:
        return self.append_part(ReasoningPart(text=text, redacted=redacted))

    def add_subagent(
        self,
        id: str,
        name: str,
        thread_id: str,
        *,
        input: Any = None,
        status: SubagentStatus = "pending",
        summary: str | None = None,
        started_at: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> int:
        """Append a subagent reference part and index it by ``id``."""
        if id in self._subagent_index:
            raise ValueError(f"duplicate subagent id: {id!r}")
        part = SubagentPart(
            id=id,
            name=name,
            thread_id=thread_id,
            input=input,
            status=status,
            summary=summary,
            started_at=started_at,
            meta=meta,
        )
        idx = self.append_part(part)
        self._subagent_index[id] = idx
        return idx

    def update_subagent_status(
        self,
        subagent_id: str,
        status: SubagentStatus,
        *,
        summary: str | None = None,
        finished_at: str | None = None,
        meta_patch: dict[str, Any] | None = None,
    ) -> None:
        """Patch a previously-added subagent's status (and optionally summary/finished_at/meta)."""
        idx = self._subagent_index.get(subagent_id)
        if idx is None:
            raise KeyError(f"unknown subagent id: {subagent_id!r}")
        patch: dict[str, Any] = {"status": status}
        if summary is not None:
            patch["summary"] = summary
        if finished_at is not None:
            patch["finished_at"] = finished_at
        if meta_patch is not None:
            existing = self._msg.content[idx].meta or {}  # type: ignore[union-attr]
            patch["meta"] = {**existing, **meta_patch}
        self.patch_part(idx, patch)

    def append_part(self, part: ContentPart) -> int:
        """Append a pre-built ContentPart. Returns the resulting index."""
        idx = len(self._msg.content)
        self._msg.content.append(part)
        self._emit(PartAppended(message_id=self._msg.id, index=idx, part=part))
        return idx

    def patch_part(self, index: int, patch: dict[str, Any]) -> None:
        """Shallow-merge ``patch`` into the part at ``index`` and emit a PartUpdated."""
        if not (0 <= index < len(self._msg.content)):
            raise IndexError(f"part index {index} out of range")
        part = self._msg.content[index]
        merged = {**part.model_dump(exclude_none=False), **patch}
        new_part = _part_adapter.validate_python(merged)
        self._msg.content[index] = new_part
        self._emit(PartUpdated(message_id=self._msg.id, index=index, patch=patch))

    # ------------------------------------------------------------------
    # Iteration / context-manager sugar
    # ------------------------------------------------------------------

    def __enter__(self) -> "MessageBuilder":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # Best-effort finalization. If the caller bailed via exception
        # without finalizing, still emit a message_finalized snapshot so
        # the receiver has a definitive end state. This mirrors how the
        # spec receiver treats finalization as authoritative.
        if not self._finalized:
            self.finalize()

    def __iter__(self) -> Iterator[ContentPart]:
        return iter(self._msg.content)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _emit(self, event: StreamEvent) -> None:
        # Cast through model_dump/model_validate? No — sink receives typed
        # event models. Consumers serialize as needed at the wire boundary.
        if isinstance(event, BaseModel):
            self._sink(event)
        else:  # pragma: no cover  — defense
            raise TypeError(f"refusing to emit non-model event: {event!r}")


__all__ = ["MessageBuilder", "EventSink"]

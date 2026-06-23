"""Streaming event vocabulary for the universal ChatMessage spec.

A small, ordered set of events that mutate an in-flight :class:`ChatMessage`
on the receiver. The final reconstructed message must equal the
``MessageFinalized.message`` payload exactly — i.e. the events are a
verbatim, sender-controlled view of how the canonical at-rest message was
assembled.

Usage pattern::

    state: dict[str, ChatMessage] = {}
    for event in stream:
        state = apply_event(state, event)
    # state[message_id] is now the final ChatMessage

A TypeScript sibling lives at ``typescript/src/applyEvent.ts`` and must
agree fixture-for-fixture with this reducer.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Discriminator, Tag, TypeAdapter

from .schema import ChatMessage, ContentPart


class _EventBase(BaseModel):
    model_config = ConfigDict(extra="allow")


class MessageStarted(_EventBase):
    """Open a new in-flight message on the receiver."""

    event: Literal["message_started"] = "message_started"
    message: ChatMessage


class PartAppended(_EventBase):
    """Append a new content part at ``index`` (the resulting position)."""

    event: Literal["part_appended"] = "part_appended"
    message_id: str
    index: int
    part: ContentPart


class TokenDelta(_EventBase):
    """Append text to the ``text`` field of the part at ``index``.

    Hot path for streaming model output. The targeted part must be a
    ``text`` or ``reasoning`` part. Clients that don't want to special-case
    deltas may reconstruct via successive ``part_updated`` events on
    ``text`` instead.
    """

    event: Literal["token_delta"] = "token_delta"
    message_id: str
    index: int
    text: str


class PartUpdated(_EventBase):
    """Shallow-merge ``patch`` into the part at ``index``.

    Patch keys overwrite existing keys; ``None`` clears a key. Nested
    objects (e.g. ``meta``) are *not* deep-merged — re-emit the whole
    sub-object if you need to update it.
    """

    event: Literal["part_updated"] = "part_updated"
    message_id: str
    index: int
    patch: dict[str, Any]


class MessageFinalized(_EventBase):
    """Authoritative end-of-stream announcement.

    Carries the full canonical ``ChatMessage`` so clients that joined late,
    dropped events, or want to verify their reconstruction can sync to a
    known-good final state.
    """

    event: Literal["message_finalized"] = "message_finalized"
    message_id: str
    message: ChatMessage


StreamEvent = Annotated[
    Union[
        Annotated[MessageStarted, Tag("message_started")],
        Annotated[PartAppended, Tag("part_appended")],
        Annotated[TokenDelta, Tag("token_delta")],
        Annotated[PartUpdated, Tag("part_updated")],
        Annotated[MessageFinalized, Tag("message_finalized")],
    ],
    Discriminator(lambda v: v.get("event") if isinstance(v, dict) else getattr(v, "event", None)),
]

_event_adapter: TypeAdapter[StreamEvent] = TypeAdapter(StreamEvent)
_part_adapter: TypeAdapter[ContentPart] = TypeAdapter(ContentPart)


def parse_event(value: Any) -> Any:
    """Parse a JSON-shaped event dict (or model) into the right subclass."""
    return _event_adapter.validate_python(value)


def apply_event(
    messages: dict[str, ChatMessage],
    event: Any,
) -> dict[str, ChatMessage]:
    """Pure reducer: apply ``event`` to a ``{message_id: ChatMessage}`` map.

    Returns a new dict (does not mutate the input).
    """
    parsed = event if isinstance(event, _EventBase) else parse_event(event)

    if isinstance(parsed, MessageStarted):
        return {**messages, parsed.message.id: parsed.message.model_copy(deep=True)}

    if isinstance(parsed, PartAppended):
        msg = messages.get(parsed.message_id)
        if msg is None:
            return messages
        new_content = list(msg.content)
        part = (
            parsed.part
            if isinstance(parsed.part, BaseModel)
            else _part_adapter.validate_python(parsed.part)
        )
        idx = max(0, min(parsed.index, len(new_content)))
        new_content.insert(idx, part)
        return {**messages, msg.id: msg.model_copy(update={"content": new_content})}

    if isinstance(parsed, TokenDelta):
        msg = messages.get(parsed.message_id)
        if msg is None or not (0 <= parsed.index < len(msg.content)):
            return messages
        part = msg.content[parsed.index]
        cur = getattr(part, "text", None)
        if not isinstance(cur, str):
            return messages
        new_part = part.model_copy(update={"text": cur + parsed.text})
        new_content = list(msg.content)
        new_content[parsed.index] = new_part
        return {**messages, msg.id: msg.model_copy(update={"content": new_content})}

    if isinstance(parsed, PartUpdated):
        msg = messages.get(parsed.message_id)
        if msg is None or not (0 <= parsed.index < len(msg.content)):
            return messages
        part = msg.content[parsed.index]
        merged = {**part.model_dump(exclude_none=False), **parsed.patch}
        new_part = _part_adapter.validate_python(merged)
        new_content = list(msg.content)
        new_content[parsed.index] = new_part
        return {**messages, msg.id: msg.model_copy(update={"content": new_content})}

    if isinstance(parsed, MessageFinalized):
        return {**messages, parsed.message_id: parsed.message.model_copy(deep=True)}

    return messages


__all__ = [
    "MessageStarted",
    "PartAppended",
    "TokenDelta",
    "PartUpdated",
    "MessageFinalized",
    "StreamEvent",
    "parse_event",
    "apply_event",
]

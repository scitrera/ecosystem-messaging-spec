"""LangChain ↔ spec ChatMessage converters.

Installable via the ``[langchain]`` extra::

    pip install scitrera-messaging-spec[langchain]

This is the single canonical place for LC adapters — consumers using
LangChain (cowork today; future agents tomorrow) should not maintain
their own. Anything LC-version-specific belongs here so consumers stay
clean.

Two directions:

- :func:`to_lc_messages` — spec ``ChatMessage`` list → LangChain
  ``BaseMessage`` list. Assistant turns split into ``AIMessage`` +
  ``ToolMessage`` per LC convention; citation / dynamic / reasoning
  parts are dropped (no LC equivalent).
- :func:`from_lc_messages` — LangChain ``BaseMessage`` list → spec
  ``ChatMessage`` list. Adjacent ``AIMessage`` + ``ToolMessage``\\(s) are
  merged into a single assistant ``ChatMessage`` so the spec's inline
  tool_call/tool_result pairing is preserved.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Iterable

try:
    from langchain_core.messages import (
        AIMessage,
        BaseMessage,
        HumanMessage,
        SystemMessage,
        ToolMessage,
    )
except ImportError as e:  # pragma: no cover  — import-time guard
    raise ImportError(
        "scitrera_messaging_spec.langchain requires langchain-core. "
        "Install with: pip install scitrera-messaging-spec[langchain]"
    ) from e

from .schema import (
    ChatMessage,
    ContentPart,
    FeedbackPart,
    FilePart,
    ImagePart,
    MessageAddress,
    Role,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)


# ---------------------------------------------------------------------------
# spec → LangChain
# ---------------------------------------------------------------------------


def to_lc_messages(messages: Iterable[ChatMessage]) -> list[BaseMessage]:
    """Convert a sequence of spec ChatMessages to LangChain BaseMessages.

    Feedback messages — those whose ``content`` is non-empty and contains
    only :class:`FeedbackPart` entries — are SKIPPED. Feedback is
    non-conversational metadata about another message (persisted to
    MemoryLayer for analytics) and the model should never see it as input
    on resume. Messages that MIX feedback with other parts (not expected
    in practice — feedback messages are pure) preserve the non-feedback
    parts in the LC output; the feedback parts are dropped.
    """
    out: list[BaseMessage] = []
    for msg in messages:
        if _is_feedback_only(msg):
            continue
        out.extend(_chat_message_to_lc(msg))
    return out


def _is_feedback_only(msg: ChatMessage) -> bool:
    """True when ``msg.content`` is non-empty and every part is feedback."""
    if not msg.content:
        return False
    return all(isinstance(p, FeedbackPart) for p in msg.content)


def _chat_message_to_lc(msg: ChatMessage) -> list[BaseMessage]:
    if msg.role == "user":
        return [HumanMessage(content=_user_content_to_lc(msg.content))]

    if msg.role == "system":
        return [SystemMessage(content=_gather_text(msg.content))]

    if msg.role == "tool":
        # Single tool_result part by spec invariant; tolerate edge cases.
        out: list[BaseMessage] = []
        for part in msg.content:
            if isinstance(part, ToolResultPart):
                out.append(_tool_result_to_lc(part))
        return out

    # assistant — preserve chronological order.
    #
    # Walk parts in order, grouping each block of preceding text part(s)
    # with the immediately-following tool_call part(s) into one AIMessage.
    # Trailing tool_results follow the AIMessage that introduced their
    # calls; text appearing AFTER a tool_result begins a new AIMessage so
    # the model's post-tool reasoning is not retroactively attributed to
    # the pre-tool turn.
    #
    # Examples (see spec tests):
    #   [text1, call_1, text2, call_2, final_text]
    #     -> AI(text1,[call_1]) Tool(1) AI(text2,[call_2]) Tool(2) AI(final_text,[])
    #   [text, call_1, call_2, final_text]
    #     -> AI(text,[call_1, call_2]) Tool(1) Tool(2) AI(final_text,[])
    #   [text]                   -> AI(text,[])
    #   [call_1, call_2]         -> AI("",[call_1, call_2]) Tool(1) Tool(2)
    #   []                       -> AI("",[])  (gap #5: empty assistant turn)
    out: list[BaseMessage] = []
    pending_text_chunks: list[str] = []
    pending_tool_calls: list[dict[str, Any]] = []
    pending_tool_results: list[BaseMessage] = []
    saw_any_emit = False

    def _flush_ai_group() -> None:
        """Emit the current AI group: AIMessage + its trailing ToolMessages.

        Called when we hit text after a tool_result (starts a new turn) and
        once at end-of-message.
        """
        nonlocal pending_text_chunks, pending_tool_calls, pending_tool_results, saw_any_emit
        if not (pending_text_chunks or pending_tool_calls or pending_tool_results):
            return
        ai_content: Any = (
            "\n".join(pending_text_chunks) if pending_text_chunks else ""
        )
        ai_kwargs: dict[str, Any] = {"content": ai_content}
        if pending_tool_calls:
            ai_kwargs["tool_calls"] = pending_tool_calls
        out.append(AIMessage(**ai_kwargs))
        out.extend(pending_tool_results)
        pending_text_chunks = []
        pending_tool_calls = []
        pending_tool_results = []
        saw_any_emit = True

    # State machine: track whether the last non-text part we processed
    # was a tool_result. If text appears after tool_result(s), that's the
    # signal to close the current AI group and start a fresh one.
    last_was_tool_result = False

    for part in msg.content:
        if isinstance(part, TextPart):
            if last_was_tool_result:
                _flush_ai_group()
                last_was_tool_result = False
            pending_text_chunks.append(part.text)
        elif isinstance(part, ToolCallPart):
            # If a tool_result already landed in this group, the model is
            # making a fresh round of calls — close the prior group first
            # so its calls + results aren't conflated with the new ones.
            if last_was_tool_result:
                _flush_ai_group()
                last_was_tool_result = False
            pending_tool_calls.append(
                {
                    "id": part.id,
                    "name": part.name,
                    "args": part.args,
                    "type": "tool_call",
                }
            )
        elif isinstance(part, ToolResultPart):
            pending_tool_results.append(_tool_result_to_lc(part))
            last_was_tool_result = True
        # Citation / dynamic / reasoning / file / image / feedback
        # (assistant-side): dropped. Feedback-only messages are filtered
        # upstream by ``_is_feedback_only``; a feedback part appearing in
        # a mixed-content message is dropped here. Render to text
        # upstream if you need other types in the LC view.

    _flush_ai_group()

    # Gap #5: an assistant turn with no renderable parts still emits a
    # single empty AIMessage so downstream consumers see the turn at all.
    if not saw_any_emit:
        out.append(AIMessage(content=""))

    return out


def _user_content_to_lc(parts: list[ContentPart]) -> Any:
    """Render user-message content for LangChain.

    Returns either a plain string (text-only) or a list of LC content
    blocks (when images are present, per LangChain's multimodal format).
    """
    has_image = any(isinstance(p, ImagePart) for p in parts)
    if not has_image:
        text = _gather_text(parts)
        file_breadcrumbs = [
            f"[file: {p.file_name or p.vfs_ref or p.uri or 'file'}]"
            for p in parts
            if isinstance(p, FilePart)
        ]
        joined = "\n".join(filter(None, [text, *file_breadcrumbs]))
        return joined

    # Mixed content → LC's list-of-blocks shape (text + image_url entries).
    blocks: list[dict[str, Any]] = []
    for p in parts:
        if isinstance(p, TextPart) and p.text:
            blocks.append({"type": "text", "text": p.text})
        elif isinstance(p, ImagePart):
            url = p.uri or p.data_uri
            if url:
                blocks.append({"type": "image_url", "image_url": {"url": url}})
        elif isinstance(p, FilePart):
            label = p.file_name or p.vfs_ref or p.uri or "file"
            blocks.append({"type": "text", "text": f"[file: {label}]"})
    return blocks


def _tool_result_to_lc(part: ToolResultPart) -> ToolMessage:
    content: str
    if part.output_text is not None:
        content = part.output_text
    elif isinstance(part.output, str):
        content = part.output
    elif part.output is None:
        content = ""
    else:
        content = json.dumps(part.output, ensure_ascii=False, default=str)
    return ToolMessage(content=content, tool_call_id=part.call_id)


def _gather_text(parts: Iterable[ContentPart]) -> str:
    chunks: list[str] = []
    for p in parts:
        if isinstance(p, TextPart) and p.text:
            chunks.append(p.text)
    return "\n".join(chunks)


# ---------------------------------------------------------------------------
# LangChain → spec
# ---------------------------------------------------------------------------


def from_lc_messages(
    messages: Iterable[BaseMessage],
    *,
    addr: MessageAddress | None = None,
) -> list[ChatMessage]:
    """Convert LangChain BaseMessages to spec ChatMessages.

    Adjacent ``AIMessage`` + ``ToolMessage``\\(s) are merged into a single
    assistant ``ChatMessage`` (the spec's preferred shape — tool_result
    parts sit inline on the assistant turn).
    """
    out: list[ChatMessage] = []
    pending_assistant: ChatMessage | None = None

    def _flush() -> None:
        nonlocal pending_assistant
        if pending_assistant is not None:
            out.append(pending_assistant)
            pending_assistant = None

    base_addr = addr or MessageAddress()

    for m in messages:
        if isinstance(m, HumanMessage):
            _flush()
            out.append(
                ChatMessage(
                    id=_new_id("msg"),
                    role="user",
                    content=_user_content_from_lc(m.content),
                    addr=base_addr,
                )
            )
        elif isinstance(m, SystemMessage):
            _flush()
            out.append(
                ChatMessage(
                    id=_new_id("msg"),
                    role="system",
                    content=_text_only_parts(m.content),
                    addr=base_addr,
                )
            )
        elif isinstance(m, AIMessage):
            _flush()
            parts: list[ContentPart] = []
            text = _flatten_lc_string(m.content)
            if text:
                parts.append(TextPart(text=text))
            for tc in (getattr(m, "tool_calls", None) or []):
                parts.append(
                    ToolCallPart(
                        id=str(tc.get("id") or _new_id("call")),
                        name=str(tc.get("name") or ""),
                        args=dict(tc.get("args") or {}),
                        status="completed",
                    )
                )
            pending_assistant = ChatMessage(
                id=_new_id("msg"),
                role="assistant",
                content=parts,
                addr=base_addr,
            )
        elif isinstance(m, ToolMessage):
            tool_result = ToolResultPart(
                call_id=str(m.tool_call_id),
                output_text=_flatten_lc_string(m.content) or None,
                output=m.content if not isinstance(m.content, str) else None,
            )
            if pending_assistant is not None:
                pending_assistant.content.append(tool_result)
            else:
                # Orphan tool message — emit standalone tool-role message.
                out.append(
                    ChatMessage(
                        id=_new_id("msg"),
                        role="tool",
                        content=[tool_result],
                        addr=base_addr,
                    )
                )
        else:
            # Unknown LC subclass: render as a system breadcrumb so it's
            # not lost. Adjust upstream if you need richer handling.
            _flush()
            out.append(
                ChatMessage(
                    id=_new_id("msg"),
                    role="system",
                    content=[TextPart(text=str(m.content))],
                    addr=base_addr,
                )
            )

    _flush()
    return out


def _user_content_from_lc(content: Any) -> list[ContentPart]:
    if isinstance(content, str):
        return [TextPart(text=content)] if content else []
    if isinstance(content, list):
        parts: list[ContentPart] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append(TextPart(text=str(block.get("text", ""))))
            elif btype == "image_url":
                url_field = block.get("image_url")
                if isinstance(url_field, dict):
                    url = url_field.get("url")
                else:
                    url = url_field
                if isinstance(url, str):
                    if url.startswith("data:"):
                        parts.append(ImagePart(data_uri=url))
                    else:
                        parts.append(ImagePart(uri=url))
        return parts
    return []


def _text_only_parts(content: Any) -> list[ContentPart]:
    text = _flatten_lc_string(content)
    return [TextPart(text=text)] if text else []


def _flatten_lc_string(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                chunks.append(str(block.get("text", "")))
        return "\n".join(chunks)
    return str(content)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


__all__ = [
    "to_lc_messages",
    "from_lc_messages",
]


# ---------------------------------------------------------------------------
# Role-typing fix-up
# ---------------------------------------------------------------------------


# ``Role`` is imported only for the public type contract; keep it visible
# to silent linters even though we don't reference it above.
_ = Role

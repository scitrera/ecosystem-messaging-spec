"""Adapters between the universal ChatMessage spec and legacy/foreign shapes.

These functions are pure: they take a value of one shape and return a
value of another. No I/O, no global state.

Coverage:

- :func:`from_rt_envelope` — Scitrera backend ``MessageEnvelope`` (rt_schema)
  dict → ChatMessage.
- :func:`from_cowork_blocks` — cowork's persisted turn-block list →
  ChatMessage.
- :func:`to_openai_chat_completion` — ChatMessage → OpenAI Chat Completions
  ``messages`` list (one input message may expand into multiple OpenAI items
  because tool results are split into ``role:"tool"`` entries).
- :func:`to_anthropic_messages` — ChatMessage → Anthropic Messages API
  ``messages`` list with content-block arrays.

These adapters intentionally do *not* round-trip 1:1; they translate to
foreign formats that drop information (e.g. citations, dynamic blocks).
Consumers that need lossless transport must pass the canonical ChatMessage.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Iterable

from .schema import (
    ChatMessage,
    CitationPart,
    ContentPart,
    DynamicPart,
    FilePart,
    ImagePart,
    MessageAddress,
    ReasoningPart,
    TextPart,
    ToolCallPart,
    ToolError,
    ToolResultPart,
    UnknownPart,
)

# ---------------------------------------------------------------------------
# rt_schema.MessageEnvelope → ChatMessage
# ---------------------------------------------------------------------------


def from_rt_envelope(envelope: Any) -> ChatMessage:
    """Convert a backend ``MessageEnvelope`` (or its dump dict) to a ChatMessage.

    The legacy envelope is text-first with optional ``attachments`` (vfs_refs),
    ``documents`` (vfs_refs), and ``dynamic`` (arbitrary). Tool calls live in
    ``envelope.arguments`` by convention and were never structured. This
    adapter loses no information: anything it can't classify is folded into
    ``meta["x-rt_envelope"]`` for later forensics.
    """
    env = envelope.model_dump() if hasattr(envelope, "model_dump") else dict(envelope)

    content_obj = env.get("content") or {}
    role = (content_obj.get("role") or "user").lower()
    if role not in {"user", "assistant", "system", "tool"}:
        role = "user"

    parts: list[ContentPart] = []
    text = content_obj.get("text") or ""
    if text:
        parts.append(TextPart(text=text))
    for ref in content_obj.get("attachments") or []:
        parts.append(FilePart(vfs_ref=str(ref), purpose="attachment"))
    for ref in content_obj.get("documents") or []:
        parts.append(FilePart(vfs_ref=str(ref), purpose="document"))
    dyn = content_obj.get("dynamic")
    if dyn is not None:
        parts.append(DynamicPart(kind="rt_envelope_dynamic", payload=dyn))

    src = env.get("source") or {}
    tgt = env.get("target") or {}
    addr = MessageAddress(
        tenant_id=src.get("tenant"),
        workspace_id=env.get("workspace") or src.get("workspace"),
        user_id=src.get("user") or tgt.get("user"),
        thread_id=None,
        agent_id=src.get("agent") if role == "assistant" else tgt.get("agent"),
        task_id=src.get("task") or tgt.get("task"),
        request_id=env.get("request_id") or src.get("request_id"),
        telemetry=src.get("telemetry"),
    )

    meta: dict[str, Any] = {}
    if env.get("arguments"):
        meta.setdefault("x-rt_envelope", {})["arguments"] = env["arguments"]
    if env.get("options"):
        meta.setdefault("x-rt_envelope", {})["options"] = env["options"]

    return ChatMessage(
        id=env.get("request_id") or _new_id("msg"),
        role=role,  # type: ignore[arg-type]
        content=parts,
        addr=addr,
        meta=meta,
    )


# ---------------------------------------------------------------------------
# cowork turn-block list → ChatMessage
# ---------------------------------------------------------------------------


_COWORK_TO_SPEC_TYPE = {
    "text": "text",
    "tool_call": "tool_call",
    "tool_result": "tool_result",
    "citation": "citation",
    "attachment": "file",
    "document": "file",
    "dynamic": "dynamic",
}


def from_cowork_blocks(
    blocks: Iterable[dict[str, Any]],
    *,
    role: str = "assistant",
    message_id: str | None = None,
    addr: MessageAddress | None = None,
) -> ChatMessage:
    """Convert cowork's persisted ``[{type, data, ...}, ...]`` turn-block list.

    Cowork stores assistant turns as an ordered list of typed blocks where
    most have a ``data`` sub-dict carrying type-specific payload. This
    adapter unwraps ``data`` into the matching :class:`ContentPart`.
    """
    parts: list[ContentPart] = []
    for raw in blocks:
        if not isinstance(raw, dict):
            continue
        btype = raw.get("type") or ""
        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
        merged = {**raw, **data}
        merged.pop("data", None)
        spec_type = _COWORK_TO_SPEC_TYPE.get(btype, btype)

        if spec_type == "text":
            parts.append(TextPart(text=str(merged.get("text", ""))))
        elif spec_type == "tool_call":
            parts.append(
                ToolCallPart(
                    id=str(merged.get("id") or _new_id("call")),
                    name=str(merged.get("name") or ""),
                    args=_coerce_args(merged.get("args") or merged.get("input")),
                    status=merged.get("status") or "completed",
                    started_at=merged.get("started_at"),
                    finished_at=merged.get("finished_at"),
                )
            )
        elif spec_type == "tool_result":
            err = merged.get("error")
            parts.append(
                ToolResultPart(
                    call_id=str(merged.get("tool_call_id") or merged.get("call_id") or ""),
                    name=merged.get("name"),
                    output=merged.get("output", merged.get("content")),
                    output_text=merged.get("output_text"),
                    is_error=bool(merged.get("is_error") or err),
                    error=_coerce_error(err),
                )
            )
        elif spec_type == "citation":
            parts.append(
                CitationPart(
                    id=merged.get("id"),
                    source=merged.get("source") or merged.get("url"),
                    title=merged.get("title"),
                    snippet=merged.get("snippet") or merged.get("text"),
                )
            )
        elif spec_type == "file":
            parts.append(
                FilePart(
                    vfs_ref=merged.get("vfs_ref") or merged.get("ref"),
                    uri=merged.get("uri"),
                    mime=merged.get("mime") or merged.get("content_type"),
                    file_name=merged.get("file_name") or merged.get("name"),
                    size_bytes=merged.get("size_bytes"),
                    purpose="attachment" if btype == "attachment" else "document",
                )
            )
        elif spec_type == "dynamic":
            parts.append(
                DynamicPart(
                    kind=merged.get("kind") or "cowork_dynamic",
                    payload=merged.get("payload") or merged.get("content"),
                    interactive=bool(merged.get("interactive")),
                )
            )
        else:
            parts.append(UnknownPart.model_validate({"type": spec_type or "unknown", **merged}))

    if role not in {"user", "assistant", "system", "tool"}:
        role = "assistant"
    return ChatMessage(
        id=message_id or _new_id("msg"),
        role=role,  # type: ignore[arg-type]
        content=parts,
        addr=addr or MessageAddress(),
    )


# ---------------------------------------------------------------------------
# ChatMessage → OpenAI Chat Completions
# ---------------------------------------------------------------------------


def to_openai_chat_completion(message: ChatMessage) -> list[dict[str, Any]]:
    """Render a ChatMessage as one-or-more OpenAI Chat Completions entries.

    Returns a list because tool-result parts split off into their own
    ``role:"tool"`` entries per the OpenAI wire format. Citations,
    dynamic blocks, and reasoning are dropped (not representable).
    """
    out: list[dict[str, Any]] = []

    text_chunks: list[str] = []
    content_blocks: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    tail_tool_results: list[dict[str, Any]] = []

    for part in message.content:
        if isinstance(part, TextPart):
            text_chunks.append(part.text)
            content_blocks.append({"type": "text", "text": part.text})
        elif isinstance(part, ImagePart):
            url = part.uri or part.data_uri
            if url:
                content_blocks.append({"type": "image_url", "image_url": {"url": url}})
        elif isinstance(part, FilePart):
            label = part.file_name or part.vfs_ref or part.uri or "file"
            text_chunks.append(f"[file: {label}]")
        elif isinstance(part, ToolCallPart):
            tool_calls.append(
                {
                    "id": part.id,
                    "type": "function",
                    "function": {
                        "name": part.name,
                        "arguments": json.dumps(part.args, ensure_ascii=False),
                    },
                }
            )
        elif isinstance(part, ToolResultPart):
            tail_tool_results.append(
                {
                    "role": "tool",
                    "tool_call_id": part.call_id,
                    "content": part.output_text
                    if isinstance(part.output_text, str)
                    else json.dumps(part.output, ensure_ascii=False, default=str),
                }
            )

    base: dict[str, Any] = {"role": message.role}
    if message.role == "tool":
        if tail_tool_results:
            out.extend(tail_tool_results)
        else:
            base["content"] = "\n".join(text_chunks)
            out.append(base)
        return out

    has_image = any(b.get("type") == "image_url" for b in content_blocks)
    if has_image:
        base["content"] = content_blocks
    else:
        base["content"] = "\n".join(text_chunks) if text_chunks else None
    if tool_calls:
        base["tool_calls"] = tool_calls

    out.append(base)
    out.extend(tail_tool_results)
    return out


# ---------------------------------------------------------------------------
# ChatMessage → Anthropic Messages
# ---------------------------------------------------------------------------


def to_anthropic_messages(message: ChatMessage) -> list[dict[str, Any]]:
    """Render a ChatMessage as Anthropic ``messages`` entries.

    Anthropic supports content-block arrays natively (text, image,
    tool_use, tool_result), so this mapping is mostly 1:1. Tool results
    that arrive on an assistant message become a separate ``user`` entry
    (Anthropic's convention: tool_result blocks live on user messages).
    """
    blocks: list[dict[str, Any]] = []
    pending_tool_results: list[dict[str, Any]] = []

    for part in message.content:
        if isinstance(part, TextPart):
            blocks.append({"type": "text", "text": part.text})
        elif isinstance(part, ImagePart):
            if part.uri:
                blocks.append(
                    {
                        "type": "image",
                        "source": {"type": "url", "url": part.uri},
                    }
                )
            elif part.data_uri and part.data_uri.startswith("data:"):
                head, _, payload = part.data_uri.partition(",")
                media_type = head.removeprefix("data:").split(";")[0] or "image/png"
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": payload,
                        },
                    }
                )
        elif isinstance(part, ToolCallPart):
            blocks.append(
                {
                    "type": "tool_use",
                    "id": part.id,
                    "name": part.name,
                    "input": part.args,
                }
            )
        elif isinstance(part, ToolResultPart):
            pending_tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": part.call_id,
                    "content": part.output_text
                    if isinstance(part.output_text, str)
                    else json.dumps(part.output, ensure_ascii=False, default=str),
                    "is_error": part.is_error,
                }
            )

    out: list[dict[str, Any]] = []
    if message.role == "tool" or (message.role != "user" and pending_tool_results and not blocks):
        out.append({"role": "user", "content": pending_tool_results})
        return out

    if blocks:
        out.append({"role": _map_role_anthropic(message.role), "content": blocks})
    if pending_tool_results:
        out.append({"role": "user", "content": pending_tool_results})
    return out


def _map_role_anthropic(role: str) -> str:
    if role == "system":
        return "user"
    if role == "tool":
        return "user"
    return role


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _coerce_args(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}


def _coerce_error(value: Any) -> ToolError | None:
    if value is None or value is False:
        return None
    if isinstance(value, ToolError):
        return value
    if isinstance(value, dict):
        return ToolError(type=value.get("type"), message=str(value.get("message") or ""))
    return ToolError(message=str(value))


__all__ = [
    "from_rt_envelope",
    "from_cowork_blocks",
    "to_openai_chat_completion",
    "to_anthropic_messages",
]

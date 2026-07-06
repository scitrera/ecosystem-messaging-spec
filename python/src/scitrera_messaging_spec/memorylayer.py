"""MemoryLayer ↔ spec ChatMessage conversion helpers.

MemoryLayer's chat history API (`append_messages`, `get_messages`) takes
a generic content-block shape::

    {"role": ..., "content": str | [{"type": str, "text": ?, "data": ?}], "metadata": {...}}

This module produces / consumes that shape from a typed spec
:class:`ChatMessage` losslessly: spec parts with no MemoryLayer-native
field set go through ``data``, and the original spec metadata fields
(``id``, ``addr``, ``ref``, ``schema_version``, ``created_at``) ride in
``metadata`` under the ``scitrera.*`` namespace.

These helpers carry NO MemoryLayer SDK dependency — they just produce /
consume dicts. Callers wire a real MemoryLayer client themselves.
"""
from __future__ import annotations

from typing import Any, Iterable

from pydantic import TypeAdapter

from .schema import ChatMessage, ContentPart, MessageAddress, MessageRef

_part_adapter: TypeAdapter[ContentPart] = TypeAdapter(ContentPart)

# Reserved metadata namespace for spec-only fields stashed alongside
# MemoryLayer's native metadata. Round-tripping a ChatMessage through
# MemoryLayer round-trips these keys verbatim.
_NS = "scitrera"

# Spec-OWNED keys stored under the reserved ``scitrera`` namespace by
# ``_build_ml_metadata``. On read they are harvested into dedicated ChatMessage
# fields; every OTHER ``scitrera.*`` key is producer/consumer data (e.g. the
# per-message agent display name ``agent_name``, ``feedback``, ``telemetry``,
# ``authority_grant_id``) and MUST survive on ``meta.scitrera`` or it is silently
# lost on history reload. Keep in sync with the keys written in ``_build_ml_metadata``.
_RESERVED_SCITRERA_KEYS = frozenset({"schema_version", "message_id", "created_at", "addr", "ref"})

# Top-level MemoryLayer message-metadata key carrying the originating app
# workspace at write time. Mirrors ``memorylayer.MESSAGE_META_APP_WORKSPACE_KEY``
# (SDK) and ``memorylayer_server.models.chat.MESSAGE_META_APP_WORKSPACE_KEY``
# (server). The spec deliberately avoids a runtime dep on the MemoryLayer SDK,
# so the value is hardcoded here — MUST match the SDK + server constants.
_MEMORYLAYER_APP_WORKSPACE_KEY = "app_workspace"


def to_memorylayer_payload(message: ChatMessage) -> dict[str, Any]:
    """Convert a spec ``ChatMessage`` to a MemoryLayer ``append_messages`` entry.

    The returned dict matches MemoryLayer's payload shape and is safe to
    pass into ``client.append_messages(thread_id, [payload], ...)``.
    """
    return {
        "role": message.role,
        "content": [_part_to_ml_content(p) for p in message.content],
        "metadata": _build_ml_metadata(message),
    }


def from_memorylayer_message(ml_message: dict[str, Any]) -> ChatMessage:
    """Convert a MemoryLayer chat message (or dict from one) back to a spec ChatMessage.

    ``ml_message`` is the JSON-shaped dict MemoryLayer returns (e.g. from
    ``client.get_messages``'s items, ``model_dump()``-ed). Reconstructs
    the original spec ``ChatMessage`` losslessly when the message was
    written via :func:`to_memorylayer_payload`.

    For messages written by other producers (non-Scitrera consumers),
    best-effort reconstruction: missing ``scitrera.*`` metadata keys
    fall back to MemoryLayer's native fields (thread_id, role, etc.).
    """
    ml_meta = dict(ml_message.get("metadata") or {})
    spec_extras = ml_meta.pop(_NS, {}) if isinstance(ml_meta.get(_NS), dict) else {}

    addr_dump = spec_extras.get("addr") or {}
    # Fill addr.thread_id from MemoryLayer's native field if the metadata
    # didn't carry it (non-Scitrera writer).
    if "thread_id" not in addr_dump and ml_message.get("thread_id"):
        addr_dump["thread_id"] = ml_message["thread_id"]
    # Fall back to top-level ``metadata.app_workspace`` for addr.workspace_id
    # when the nested ``scitrera.addr`` namespace didn't carry it — this is
    # the path SDK-only writers (no spec layer) use to stash origin context.
    if "workspace_id" not in addr_dump:
        fallback_ws = ml_meta.get(_MEMORYLAYER_APP_WORKSPACE_KEY)
        if isinstance(fallback_ws, str) and fallback_ws:
            addr_dump["workspace_id"] = fallback_ws
    addr = MessageAddress.model_validate(addr_dump) if addr_dump else MessageAddress()

    ref_dump = spec_extras.get("ref")
    ref = MessageRef.model_validate(ref_dump) if ref_dump else None

    content = _ml_content_to_parts(ml_message.get("content"))

    # Re-attach non-reserved scitrera.* metadata (agent_name, feedback, telemetry, …)
    # so the round-trip is lossless. ``spec_extras`` was popped off ``ml_meta`` above and
    # only the spec-owned keys are harvested into dedicated fields; without this, every
    # other scitrera key — e.g. the per-message agent display name — is dropped on reload.
    residual_scitrera = {k: v for k, v in spec_extras.items() if k not in _RESERVED_SCITRERA_KEYS}
    if residual_scitrera:
        ml_meta[_NS] = residual_scitrera

    raw: dict[str, Any] = {
        "schema_version": spec_extras.get("schema_version", "1.0"),
        "id": spec_extras.get("message_id") or ml_message.get("id") or "",
        "role": ml_message.get("role", "assistant"),
        "created_at": spec_extras.get("created_at") or _isoformat(ml_message.get("created_at")),
        "content": [p.model_dump() if hasattr(p, "model_dump") else p for p in content],
        "addr": addr.model_dump(),
        "meta": ml_meta,
        "ref": ref.model_dump() if ref else None,
    }
    return ChatMessage.model_validate(raw)


def to_memorylayer_payloads(messages: Iterable[ChatMessage]) -> list[dict[str, Any]]:
    """Bulk variant of :func:`to_memorylayer_payload`."""
    return [to_memorylayer_payload(m) for m in messages]


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


def _part_to_ml_content(part: ContentPart) -> dict[str, Any]:
    """Render one spec ContentPart as a MemoryLayer ChatMessageContent dict.

    - ``text`` parts go to the native ``text`` field so MemoryLayer can
      run text search / token counting on it. Annotations + any extras
      ride in ``data``.
    - All other parts stash the full part dump (minus ``type``, which
      becomes the top-level field) under ``data``.
    """
    # ``exclude_none=True`` keeps the stored shape compact and avoids
    # littering ``data`` with explicit nulls for unset optionals.
    dump = part.model_dump(exclude_none=True) if hasattr(part, "model_dump") else dict(part)
    ptype = dump.pop("type", "unknown")

    if ptype == "text":
        text = dump.pop("text", "")
        out: dict[str, Any] = {"type": "text", "text": text}
        if dump:  # leftover annotations / extras
            out["data"] = dump
        return out

    return {"type": ptype, "data": dump}


def _ml_content_to_parts(content: Any) -> list[ContentPart]:
    """Inverse of :func:`_part_to_ml_content`. Accepts either a string
    (legacy plain-text message) or a list of MemoryLayer content blocks.
    """
    if isinstance(content, str):
        return [_part_adapter.validate_python({"type": "text", "text": content})] if content else []
    if not isinstance(content, list):
        return []
    parts: list[ContentPart] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type") or "unknown"
        if btype == "text":
            inner: dict[str, Any] = {"type": "text", "text": block.get("text", "")}
            extras = block.get("data") or {}
            if isinstance(extras, dict):
                inner.update(extras)
            parts.append(_part_adapter.validate_python(inner))
        else:
            inner = {"type": btype}
            data = block.get("data")
            if isinstance(data, dict):
                inner.update(data)
            # Text-on-text-only fields can sit on the block itself; preserve.
            if block.get("text") is not None and "text" not in inner:
                inner["text"] = block["text"]
            parts.append(_part_adapter.validate_python(inner))
    return parts


def _build_ml_metadata(message: ChatMessage) -> dict[str, Any]:
    spec_extras: dict[str, Any] = {
        "schema_version": message.schema_version,
        "message_id": message.id,
    }
    if message.created_at is not None:
        spec_extras["created_at"] = message.created_at
    addr_dump = message.addr.model_dump(exclude_none=True)
    if addr_dump:
        spec_extras["addr"] = addr_dump
    if message.ref is not None:
        ref_dump = message.ref.model_dump(exclude_none=True)
        if ref_dump:
            spec_extras["ref"] = ref_dump

    metadata = dict(message.meta)
    # Top-level ``app_workspace`` carries the originating app workspace
    # from ``addr.workspace_id`` using MemoryLayer's native naming
    # (see ``_MEMORYLAYER_APP_WORKSPACE_KEY``). This keeps origin context
    # queryable / indexable on the message row for memorylayer-native
    # consumers, alongside the spec-native ``scitrera.addr.workspace_id``
    # path used by spec readers. ``setdefault`` so a caller who explicitly
    # put a value there wins.
    if message.addr.workspace_id:
        metadata.setdefault(_MEMORYLAYER_APP_WORKSPACE_KEY, message.addr.workspace_id)
    # Reserve the scitrera namespace; warn-by-overwrite. Spec-aware
    # callers should never put their own data under ``meta["scitrera"]``
    # that conflicts with these reserved keys.
    existing = metadata.get(_NS)
    if isinstance(existing, dict):
        merged = {**existing, **spec_extras}
        metadata[_NS] = merged
    else:
        metadata[_NS] = spec_extras
    return metadata


def _isoformat(value: Any) -> str | None:
    """Return an RFC3339-ish string for a datetime / str / None."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return str(value)


__all__ = [
    "to_memorylayer_payload",
    "from_memorylayer_message",
    "to_memorylayer_payloads",
]

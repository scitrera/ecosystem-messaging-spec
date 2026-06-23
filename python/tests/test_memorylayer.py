"""Tests for the MemoryLayer ↔ spec ChatMessage conversion helpers."""
from __future__ import annotations

from datetime import datetime, timezone

from scitrera_messaging_spec import (
    ChatMessage,
    CitationPart,
    DynamicPart,
    FilePart,
    ImagePart,
    MessageAddress,
    MessageRef,
    ReasoningPart,
    SubagentPart,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)
from scitrera_messaging_spec.memorylayer import (
    from_memorylayer_message,
    to_memorylayer_payload,
    to_memorylayer_payloads,
)


def _fixture() -> ChatMessage:
    return ChatMessage(
        id="msg_1",
        role="assistant",
        created_at="2026-05-26T15:30:00Z",
        addr=MessageAddress(
            tenant_id="t1",
            workspace_id="w1",
            user_id="u1",
            thread_id="thr_1",
            agent_id="ag1",
            task_id="task_1",
        ),
        content=[
            TextPart(text="Looking up."),
            ToolCallPart(id="c1", name="fetch", args={"x": 1}, status="completed"),
            ToolResultPart(call_id="c1", name="fetch", output_text="42"),
            TextPart(text="Done."),
            CitationPart(id="cit_1", source="vfs://x", title="X"),
            FilePart(vfs_ref="vfs://a", file_name="a.pdf", purpose="document"),
            ImagePart(uri="https://x/i.png", mime="image/png"),
            DynamicPart(kind="jsx", payload={"x": 1}),
            ReasoningPart(text="thinking", redacted=False),
            SubagentPart(
                id="sub_1", name="researcher", thread_id="thr_sub_1", status="completed"
            ),
        ],
        meta={"scitrera": {"feedback": "thumbs_up"}, "x-cowork": {"trace": "abc"}},
        ref=MessageRef(parent_thread_id="thr_main", parent_message_id="msg_p"),
    )


# ---------------------------------------------------------------------------
# to_memorylayer_payload
# ---------------------------------------------------------------------------


def test_to_ml_payload_shape() -> None:
    msg = _fixture()
    payload = to_memorylayer_payload(msg)

    assert payload["role"] == "assistant"
    assert isinstance(payload["content"], list)
    assert isinstance(payload["metadata"], dict)


def test_to_ml_payload_text_part_uses_native_text_field() -> None:
    """Text parts should put text on the native ``text`` field so MemoryLayer
    can run text search / index."""
    msg = ChatMessage(id="m", role="user", content=[TextPart(text="hi")])
    payload = to_memorylayer_payload(msg)
    assert payload["content"][0]["type"] == "text"
    assert payload["content"][0]["text"] == "hi"
    # No ``data`` for a plain text part.
    assert "data" not in payload["content"][0]


def test_to_ml_payload_non_text_parts_go_to_data() -> None:
    msg = ChatMessage(
        id="m",
        role="assistant",
        content=[ToolCallPart(id="c1", name="t", args={"x": 1}, status="completed")],
    )
    payload = to_memorylayer_payload(msg)
    block = payload["content"][0]
    assert block["type"] == "tool_call"
    assert "text" not in block
    assert block["data"]["id"] == "c1"
    assert block["data"]["name"] == "t"
    assert block["data"]["args"] == {"x": 1}


def test_to_ml_payload_metadata_carries_scitrera_namespace() -> None:
    msg = _fixture()
    payload = to_memorylayer_payload(msg)
    sc = payload["metadata"]["scitrera"]
    # Pre-existing user-set ``scitrera.feedback`` is preserved.
    assert sc["feedback"] == "thumbs_up"
    assert sc["schema_version"] == "1.0"
    assert sc["message_id"] == "msg_1"
    assert sc["addr"]["thread_id"] == "thr_1"
    assert sc["addr"]["workspace_id"] == "w1"
    assert sc["ref"]["parent_thread_id"] == "thr_main"


def test_to_ml_payload_user_namespaces_preserved() -> None:
    msg = _fixture()
    payload = to_memorylayer_payload(msg)
    assert payload["metadata"]["x-cowork"] == {"trace": "abc"}


# ---------------------------------------------------------------------------
# from_memorylayer_message — round-trip
# ---------------------------------------------------------------------------


def test_round_trip_preserves_all_content_and_meta() -> None:
    msg = _fixture()
    payload = to_memorylayer_payload(msg)
    # Simulate what MemoryLayer would return from get_messages.
    ml_record = {
        "id": "ml_id_1",
        "thread_id": msg.addr.thread_id,
        "message_index": 0,
        "role": payload["role"],
        "content": payload["content"],
        "metadata": payload["metadata"],
        "created_at": datetime(2026, 5, 26, 15, 30, 0, tzinfo=timezone.utc),
    }
    back = from_memorylayer_message(ml_record)

    # Identity on content shape:
    original_types = [p.type for p in msg.content]  # type: ignore[union-attr]
    back_types = [p.type for p in back.content]  # type: ignore[union-attr]
    assert back_types == original_types

    assert back.id == msg.id
    assert back.role == msg.role
    assert back.addr.thread_id == msg.addr.thread_id
    assert back.addr.workspace_id == msg.addr.workspace_id
    assert back.ref is not None
    assert back.ref.parent_thread_id == "thr_main"
    # Non-scitrera meta survives.
    assert back.meta["x-cowork"] == {"trace": "abc"}


def test_round_trip_tool_call_args_preserved() -> None:
    """Structured tool_call args must survive the round trip."""
    msg = ChatMessage(
        id="m",
        role="assistant",
        addr=MessageAddress(thread_id="thr_1"),
        content=[
            ToolCallPart(id="c1", name="t", args={"a": 1, "b": [2, 3]}, status="completed"),
            ToolResultPart(call_id="c1", output={"ok": True}),
        ],
    )
    payload = to_memorylayer_payload(msg)
    ml_record = {
        "id": "x",
        "thread_id": "thr_1",
        "message_index": 0,
        "role": payload["role"],
        "content": payload["content"],
        "metadata": payload["metadata"],
        "created_at": "2026-05-26T00:00:00Z",
    }
    back = from_memorylayer_message(ml_record)
    tc = back.content[0]
    assert isinstance(tc, ToolCallPart)
    assert tc.args == {"a": 1, "b": [2, 3]}
    tr = back.content[1]
    assert isinstance(tr, ToolResultPart)
    assert tr.output == {"ok": True}


def test_from_ml_message_for_non_scitrera_writer() -> None:
    """A plain MemoryLayer record (no scitrera metadata) still parses to a spec ChatMessage.

    Forward-compat / interop: external writers (other SDK users) shouldn't
    need to know about our spec to land in MemoryLayer.
    """
    record = {
        "id": "ml_xyz",
        "thread_id": "thr_x",
        "message_index": 0,
        "role": "user",
        "content": "just plain text",
        "metadata": {},
        "created_at": "2026-05-26T12:00:00Z",
    }
    back = from_memorylayer_message(record)
    assert back.role == "user"
    assert back.addr.thread_id == "thr_x"
    assert len(back.content) == 1
    assert back.content[0].type == "text"  # type: ignore[union-attr]
    assert back.content[0].text == "just plain text"  # type: ignore[union-attr]


def test_unknown_part_type_survives_round_trip() -> None:
    """Forward-compat: a part with an unrecognized type is preserved verbatim."""
    raw = {
        "id": "m",
        "role": "assistant",
        "addr": {"thread_id": "thr_x"},
        "meta": {},
        "content": [
            {"type": "screencast", "url": "https://x", "duration_ms": 1234},
        ],
    }
    msg = ChatMessage.model_validate(raw)
    payload = to_memorylayer_payload(msg)
    ml_record = {
        "id": "x",
        "thread_id": "thr_x",
        "message_index": 0,
        "role": payload["role"],
        "content": payload["content"],
        "metadata": payload["metadata"],
        "created_at": "2026-05-26T00:00:00Z",
    }
    back = from_memorylayer_message(ml_record)
    assert back.content[0].type == "screencast"  # type: ignore[union-attr]
    dumped = back.content[0].model_dump()  # type: ignore[union-attr]
    assert dumped["url"] == "https://x"
    assert dumped["duration_ms"] == 1234


def test_bulk_to_ml_payloads() -> None:
    msgs = [
        ChatMessage(id="m1", role="user", content=[TextPart(text="hi")]),
        ChatMessage(id="m2", role="assistant", content=[TextPart(text="hello")]),
    ]
    out = to_memorylayer_payloads(msgs)
    assert [p["role"] for p in out] == ["user", "assistant"]


# ─── app_workspace round-trip (MemoryLayer native metadata key) ────────

def test_to_ml_payload_emits_top_level_app_workspace_from_addr():
    """addr.workspace_id is stamped on top-level metadata['app_workspace']
    so memorylayer-native consumers can index/filter on it without
    descending into the scitrera namespace."""
    msg = ChatMessage(
        id="m_aw",
        role="user",
        addr=MessageAddress(workspace_id="ws-real", thread_id="thr_1"),
        content=[TextPart(text="hi")],
    )
    payload = to_memorylayer_payload(msg)
    assert payload["metadata"]["app_workspace"] == "ws-real"
    # Also still present in scitrera nested addr (spec-native path).
    assert payload["metadata"]["scitrera"]["addr"]["workspace_id"] == "ws-real"


def test_to_ml_payload_user_app_workspace_in_meta_wins_over_addr():
    """When the caller explicitly set ``meta['app_workspace']`` we don't
    overwrite — ``setdefault`` semantics preserve the explicit value."""
    msg = ChatMessage(
        id="m_aw2",
        role="user",
        addr=MessageAddress(workspace_id="ws-from-addr", thread_id="thr_1"),
        content=[TextPart(text="hi")],
        meta={"app_workspace": "ws-explicit"},
    )
    payload = to_memorylayer_payload(msg)
    assert payload["metadata"]["app_workspace"] == "ws-explicit"


def test_to_ml_payload_skips_app_workspace_when_addr_workspace_unset():
    """No addr.workspace_id → no top-level app_workspace stamped."""
    msg = ChatMessage(
        id="m_aw3",
        role="user",
        addr=MessageAddress(thread_id="thr_1"),  # no workspace_id
        content=[TextPart(text="hi")],
    )
    payload = to_memorylayer_payload(msg)
    assert "app_workspace" not in payload["metadata"]


def test_from_ml_message_falls_back_to_app_workspace_when_scitrera_missing():
    """A non-spec writer (SDK-only, no scitrera.addr namespace) can still
    yield a spec ChatMessage with addr.workspace_id populated from the
    top-level metadata['app_workspace']."""
    ml_msg = {
        "id": "srv_id_1",
        "thread_id": "thr_1",
        "role": "user",
        "content": [{"type": "text", "text": "hi"}],
        "metadata": {"app_workspace": "ws-from-sdk"},
    }
    spec_msg = from_memorylayer_message(ml_msg)
    assert spec_msg.addr.workspace_id == "ws-from-sdk"
    assert spec_msg.addr.thread_id == "thr_1"


def test_from_ml_message_scitrera_addr_workspace_id_wins_over_app_workspace():
    """When both nested ``scitrera.addr.workspace_id`` and top-level
    ``app_workspace`` are present (typical for spec-written rows after
    the SDK substitution path also stamped its own copy), the nested
    spec-native value wins."""
    ml_msg = {
        "id": "srv_id_2",
        "thread_id": "thr_1",
        "role": "user",
        "content": [{"type": "text", "text": "hi"}],
        "metadata": {
            "app_workspace": "ws-fallback",
            "scitrera": {
                "schema_version": "1.0",
                "message_id": "m_xyz",
                "addr": {"thread_id": "thr_1", "workspace_id": "ws-spec"},
            },
        },
    }
    spec_msg = from_memorylayer_message(ml_msg)
    assert spec_msg.addr.workspace_id == "ws-spec"


def test_app_workspace_round_trip_via_spec_path():
    """End-to-end: a spec ChatMessage with addr.workspace_id round-trips
    losslessly even when reading via the app_workspace fallback path."""
    original = ChatMessage(
        id="m_rt",
        role="assistant",
        addr=MessageAddress(workspace_id="ws-orig", thread_id="thr_rt"),
        content=[TextPart(text="round-tripped")],
    )
    payload = to_memorylayer_payload(original)
    # Simulate a non-spec reader path by stripping the scitrera namespace
    # (as if the row was written by an SDK-only producer without spec extras).
    stripped = dict(payload)
    stripped_meta = dict(payload["metadata"])
    stripped_meta.pop("scitrera", None)
    stripped["metadata"] = stripped_meta
    stripped["thread_id"] = "thr_rt"

    recovered = from_memorylayer_message(stripped)
    assert recovered.addr.workspace_id == "ws-orig"
    assert recovered.addr.thread_id == "thr_rt"

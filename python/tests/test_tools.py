"""Tests for tool transport types (spec 1.1).

Mirrors typescript/test/tools.test.ts. The reply to a ToolInvokeEnvelope
is the existing ToolResultPart from schema.py.
"""
from __future__ import annotations

import json

from scitrera_messaging_spec import (
    TOOLS_SCHEMA_VERSION,
    MessageAddress,
    ToolDescriptor,
    ToolInvokeEnvelope,
    ToolResultPart,
)


# ── version ───────────────────────────────────────────────────────────


def test_tools_schema_version_is_1_1() -> None:
    """Transport layer is spec 1.1; ChatMessage stays 1.0."""
    assert TOOLS_SCHEMA_VERSION == "1.1"


# ── ToolDescriptor ─────────────────────────────────────────────────────


def test_tool_descriptor_roundtrip_describe_form() -> None:
    d = ToolDescriptor(
        name="read_file",
        title="Read File",
        description="Read a file from the VFS.",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        kind="backend",
        awaits_result=True,
        toolsets=["files", "core"],
        meta={"category": "io"},
    )
    raw = d.model_dump_json()
    back = ToolDescriptor.model_validate_json(raw)
    assert back.model_dump() == d.model_dump()


def test_tool_descriptor_search_form_omits_input_schema() -> None:
    d = ToolDescriptor(
        name="read_file",
        description="Read a file from the VFS.",
        kind="backend",
        awaits_result=True,
    )
    raw = json.loads(d.model_dump_json())
    assert raw["input_schema"] is None
    back = ToolDescriptor.model_validate_json(d.model_dump_json())
    assert back.input_schema is None


def test_tool_descriptor_preserves_extra_fields() -> None:
    raw = {
        "name": "send_email",
        "description": "Send an email.",
        "kind": "office",
        "awaits_result": False,
        "future_field": {"v": 7},
    }
    d = ToolDescriptor.model_validate(raw)
    dumped = d.model_dump()
    assert dumped["future_field"] == {"v": 7}
    assert dumped["awaits_result"] is False


def test_tool_descriptor_uses_awaits_result_not_await() -> None:
    """``await`` is a Python reserved keyword; field must be awaits_result."""
    d = ToolDescriptor(
        name="fire",
        description="fire and forget",
        kind="frontend",
        awaits_result=False,
    )
    fields = set(type(d).model_fields)
    assert "await" not in fields
    assert "awaits_result" in fields


# ── ToolInvokeEnvelope ─────────────────────────────────────────────────


def test_tool_invoke_envelope_roundtrip() -> None:
    env = ToolInvokeEnvelope(
        call_id="call_1",
        name="read_file",
        args={"path": "/a.txt"},
        addr=MessageAddress(tenant_id="t1", task_id="task_turn", request_id="win_1"),
        awaits_result=True,
        meta={"window_id": "win_1"},
    )
    raw = env.model_dump_json()
    back = ToolInvokeEnvelope.model_validate_json(raw)
    assert back.model_dump() == env.model_dump()
    assert env.schema_version == TOOLS_SCHEMA_VERSION


def test_tool_invoke_envelope_preserves_extra_fields() -> None:
    raw = {
        "schema_version": "1.1",
        "call_id": "call_2",
        "name": "t",
        "args": {},
        "addr": {},
        "future_field": "keep_me",
    }
    env = ToolInvokeEnvelope.model_validate(raw)
    assert env.model_dump()["future_field"] == "keep_me"


def test_tool_invoke_envelope_defaults() -> None:
    """Pydantic defaults mirror the TS builder."""
    env = ToolInvokeEnvelope(call_id="c", name="n")
    assert env.schema_version == TOOLS_SCHEMA_VERSION
    assert env.args == {}
    assert env.addr == MessageAddress()
    assert env.meta is None
    assert env.awaits_result is None


def test_tool_result_part_is_the_reply_payload() -> None:
    env = ToolInvokeEnvelope(call_id="call_42", name="read_file")
    reply = ToolResultPart(
        call_id=env.call_id,
        name=env.name,
        output={"bytes": 12},
        output_text="hello world",
        is_error=False,
    )
    raw = reply.model_dump_json()
    back = ToolResultPart.model_validate_json(raw)
    assert back.model_dump() == reply.model_dump()
    assert reply.call_id == env.call_id


# ── cross-language JSON identity (field names / shape) ──────────────────


def test_descriptor_wire_field_names_match_ts() -> None:
    d = ToolDescriptor(
        name="n",
        title="t",
        description="d",
        input_schema={},
        kind="backend",
        awaits_result=True,
        toolsets=["x"],
        meta={},
    )
    raw = json.loads(d.model_dump_json())
    assert set(raw.keys()) == {
        "name",
        "title",
        "description",
        "input_schema",
        "kind",
        "awaits_result",
        "toolsets",
        "meta",
    }


def test_envelope_wire_field_names_match_ts() -> None:
    env = ToolInvokeEnvelope(
        call_id="c",
        name="n",
        args={},
        addr=MessageAddress(),
        awaits_result=True,
        meta={},
    )
    raw = json.loads(env.model_dump_json())
    assert set(raw.keys()) == {
        "schema_version",
        "call_id",
        "name",
        "args",
        "addr",
        "awaits_result",
        "meta",
    }
    # addr serializes to the MessageAddress shape (all-None defaults present)
    assert "tenant_id" in raw["addr"]

"""Tests for the json_schema export functions."""
from __future__ import annotations

from scitrera_messaging_spec import (
    chat_message_json_schema,
    stream_event_json_schema,
)


def test_chat_message_schema_has_expected_top_level() -> None:
    s = chat_message_json_schema()
    assert s["title"] == "ChatMessage"
    props = s["properties"]
    for required_field in ("id", "role", "content", "addr", "meta", "schema_version"):
        assert required_field in props


def test_stream_event_schema_covers_all_five_event_kinds() -> None:
    s = stream_event_json_schema()
    # Pydantic emits a oneOf / discriminated mapping; rather than depending
    # on the exact structure, walk the full JSON looking for our event tags.
    blob = repr(s)
    for tag in (
        "message_started",
        "part_appended",
        "token_delta",
        "part_updated",
        "message_finalized",
    ):
        assert tag in blob, f"{tag!r} missing from stream-event schema"

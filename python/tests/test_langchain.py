"""Tests for the LangChain ↔ spec converters.

Skipped automatically when langchain-core isn't installed (the optional
``[langchain]`` extra).
"""
from __future__ import annotations

import pytest

pytest.importorskip("langchain_core")

from langchain_core.messages import (  # noqa: E402
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from scitrera_messaging_spec import (  # noqa: E402
    ChatMessage,
    CitationPart,
    DynamicPart,
    FilePart,
    ImagePart,
    MessageAddress,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)
from scitrera_messaging_spec.langchain import (  # noqa: E402
    from_lc_messages,
    to_lc_messages,
)


def test_to_lc_simple_text_user_message() -> None:
    msgs = [ChatMessage(id="m1", role="user", content=[TextPart(text="hello")])]
    lc = to_lc_messages(msgs)
    assert len(lc) == 1
    assert isinstance(lc[0], HumanMessage)
    assert lc[0].content == "hello"


def test_to_lc_user_with_image_uses_block_list() -> None:
    msgs = [
        ChatMessage(
            id="m1",
            role="user",
            content=[
                TextPart(text="look"),
                ImagePart(uri="https://x/p.png"),
            ],
        )
    ]
    lc = to_lc_messages(msgs)
    assert lc[0].content == [
        {"type": "text", "text": "look"},
        {"type": "image_url", "image_url": {"url": "https://x/p.png"}},
    ]


def test_to_lc_assistant_with_tool_call_and_result_splits_into_ai_plus_tool() -> None:
    """Trailing text after a tool_result begins a fresh AIMessage.

    Pre-fix behavior conflated pre- and post-tool text onto a single
    AIMessage at the head, losing chronology. The new behavior preserves
    the order: AI("calling",[c1]) -> Tool(c1) -> AI("done",[]).
    """
    msgs = [
        ChatMessage(
            id="m1",
            role="assistant",
            content=[
                TextPart(text="calling"),
                ToolCallPart(id="c1", name="t", args={"x": 1}, status="completed"),
                ToolResultPart(call_id="c1", output_text="ok"),
                TextPart(text="done"),
            ],
        )
    ]
    lc = to_lc_messages(msgs)
    assert len(lc) == 3
    assert isinstance(lc[0], AIMessage)
    assert lc[0].content == "calling"
    assert lc[0].tool_calls == [{"id": "c1", "name": "t", "args": {"x": 1}, "type": "tool_call"}]
    assert isinstance(lc[1], ToolMessage)
    assert lc[1].tool_call_id == "c1"
    assert lc[1].content == "ok"
    assert isinstance(lc[2], AIMessage)
    assert lc[2].content == "done"
    assert not getattr(lc[2], "tool_calls", None)


def test_to_lc_interleaved_text_and_tool_calls_preserves_order() -> None:
    """[text1, call_1, text2, call_2, final_text] keeps chronology."""
    msgs = [
        ChatMessage(
            id="m1",
            role="assistant",
            content=[
                TextPart(text="text1"),
                ToolCallPart(id="c1", name="t", args={"a": 1}, status="completed"),
                ToolResultPart(call_id="c1", output_text="r1"),
                TextPart(text="text2"),
                ToolCallPart(id="c2", name="t", args={"a": 2}, status="completed"),
                ToolResultPart(call_id="c2", output_text="r2"),
                TextPart(text="final_text"),
            ],
        )
    ]
    lc = to_lc_messages(msgs)
    kinds = [type(m).__name__ for m in lc]
    assert kinds == [
        "AIMessage", "ToolMessage",
        "AIMessage", "ToolMessage",
        "AIMessage",
    ]
    assert lc[0].content == "text1"
    assert [c["id"] for c in lc[0].tool_calls] == ["c1"]
    assert lc[1].tool_call_id == "c1" and lc[1].content == "r1"
    assert lc[2].content == "text2"
    assert [c["id"] for c in lc[2].tool_calls] == ["c2"]
    assert lc[3].tool_call_id == "c2" and lc[3].content == "r2"
    assert lc[4].content == "final_text"
    assert not getattr(lc[4], "tool_calls", None)


def test_to_lc_sequential_tool_calls_then_trailing_text() -> None:
    """[text, call_1, call_2, results..., final_text] groups calls, trails text."""
    msgs = [
        ChatMessage(
            id="m1",
            role="assistant",
            content=[
                TextPart(text="text"),
                ToolCallPart(id="c1", name="t", args={"a": 1}, status="completed"),
                ToolCallPart(id="c2", name="t", args={"a": 2}, status="completed"),
                ToolResultPart(call_id="c1", output_text="r1"),
                ToolResultPart(call_id="c2", output_text="r2"),
                TextPart(text="final_text"),
            ],
        )
    ]
    lc = to_lc_messages(msgs)
    kinds = [type(m).__name__ for m in lc]
    assert kinds == ["AIMessage", "ToolMessage", "ToolMessage", "AIMessage"]
    assert lc[0].content == "text"
    assert [c["id"] for c in lc[0].tool_calls] == ["c1", "c2"]
    assert lc[1].tool_call_id == "c1" and lc[1].content == "r1"
    assert lc[2].tool_call_id == "c2" and lc[2].content == "r2"
    assert lc[3].content == "final_text"
    assert not getattr(lc[3], "tool_calls", None)


def test_to_lc_sequential_tool_calls_no_trailing_text() -> None:
    """[text, call_1, call_2, results...] with no trailing text — no extra AIMessage."""
    msgs = [
        ChatMessage(
            id="m1",
            role="assistant",
            content=[
                TextPart(text="text"),
                ToolCallPart(id="c1", name="t", args={}, status="completed"),
                ToolCallPart(id="c2", name="t", args={}, status="completed"),
                ToolResultPart(call_id="c1", output_text="r1"),
                ToolResultPart(call_id="c2", output_text="r2"),
            ],
        )
    ]
    lc = to_lc_messages(msgs)
    kinds = [type(m).__name__ for m in lc]
    assert kinds == ["AIMessage", "ToolMessage", "ToolMessage"]
    assert lc[0].content == "text"
    assert [c["id"] for c in lc[0].tool_calls] == ["c1", "c2"]


def test_to_lc_all_tools_no_text() -> None:
    """[call_1, call_2, results...] — single AIMessage with empty content."""
    msgs = [
        ChatMessage(
            id="m1",
            role="assistant",
            content=[
                ToolCallPart(id="c1", name="t", args={}, status="completed"),
                ToolCallPart(id="c2", name="t", args={}, status="completed"),
                ToolResultPart(call_id="c1", output_text="r1"),
                ToolResultPart(call_id="c2", output_text="r2"),
            ],
        )
    ]
    lc = to_lc_messages(msgs)
    kinds = [type(m).__name__ for m in lc]
    assert kinds == ["AIMessage", "ToolMessage", "ToolMessage"]
    assert lc[0].content == ""
    assert [c["id"] for c in lc[0].tool_calls] == ["c1", "c2"]


def test_to_lc_text_only_assistant_turn() -> None:
    """[text] — single AIMessage, no tool_calls."""
    msgs = [
        ChatMessage(
            id="m1",
            role="assistant",
            content=[TextPart(text="text")],
        )
    ]
    lc = to_lc_messages(msgs)
    assert len(lc) == 1
    assert isinstance(lc[0], AIMessage)
    assert lc[0].content == "text"
    assert not getattr(lc[0], "tool_calls", None)


def test_to_lc_empty_assistant_turn_still_emits_one_aimessage() -> None:
    """[] — emit a single empty AIMessage (gap #5 documented behavior)."""
    msgs = [
        ChatMessage(id="m1", role="assistant", content=[]),
    ]
    lc = to_lc_messages(msgs)
    assert len(lc) == 1
    assert isinstance(lc[0], AIMessage)
    assert lc[0].content == ""
    assert not getattr(lc[0], "tool_calls", None)


def test_to_lc_drops_citation_dynamic_reasoning_silently() -> None:
    msgs = [
        ChatMessage(
            id="m",
            role="assistant",
            content=[
                TextPart(text="hi"),
                CitationPart(source="x"),
                DynamicPart(kind="jsx", payload={"y": 1}),
            ],
        )
    ]
    lc = to_lc_messages(msgs)
    assert len(lc) == 1
    assert isinstance(lc[0], AIMessage)
    assert lc[0].content == "hi"
    assert not getattr(lc[0], "tool_calls", None)


def test_from_lc_merges_adjacent_ai_and_tool_into_one_assistant() -> None:
    lc = [
        HumanMessage(content="hello"),
        AIMessage(
            content="checking",
            tool_calls=[{"id": "c1", "name": "t", "args": {"x": 1}, "type": "tool_call"}],
        ),
        ToolMessage(content="ok", tool_call_id="c1"),
    ]
    msgs = from_lc_messages(lc)
    assert len(msgs) == 2  # user + merged assistant
    assert msgs[0].role == "user"
    assert msgs[1].role == "assistant"
    types = [type(p).__name__ for p in msgs[1].content]
    assert types == ["TextPart", "ToolCallPart", "ToolResultPart"]
    tool_call = msgs[1].content[1]
    assert isinstance(tool_call, ToolCallPart)
    assert tool_call.id == "c1"
    assert tool_call.args == {"x": 1}


def test_from_lc_orphan_tool_message_becomes_tool_role_message() -> None:
    lc = [ToolMessage(content="ok", tool_call_id="c_xx")]
    msgs = from_lc_messages(lc)
    assert len(msgs) == 1
    assert msgs[0].role == "tool"
    assert isinstance(msgs[0].content[0], ToolResultPart)
    assert msgs[0].content[0].call_id == "c_xx"


def test_from_lc_addr_is_threaded_through_all_messages() -> None:
    addr = MessageAddress(tenant_id="t1", workspace_id="w1", thread_id="th1")
    lc = [HumanMessage(content="hi"), AIMessage(content="bye")]
    msgs = from_lc_messages(lc, addr=addr)
    for m in msgs:
        assert m.addr.tenant_id == "t1"
        assert m.addr.workspace_id == "w1"


def test_from_lc_user_image_url_block_becomes_image_part() -> None:
    lc = [
        HumanMessage(
            content=[
                {"type": "text", "text": "look"},
                {"type": "image_url", "image_url": {"url": "https://x/p.png"}},
            ]
        )
    ]
    msgs = from_lc_messages(lc)
    types = [type(p).__name__ for p in msgs[0].content]
    assert types == ["TextPart", "ImagePart"]


def test_lc_roundtrip_preserves_text_and_tool_structure() -> None:
    """to_lc → from_lc → to_lc should converge after one round."""
    original = [
        ChatMessage(
            id="m1",
            role="user",
            content=[TextPart(text="check Q3")],
        ),
        ChatMessage(
            id="m2",
            role="assistant",
            content=[
                TextPart(text="looking"),
                ToolCallPart(id="c1", name="fetch", args={"k": "v"}, status="completed"),
                ToolResultPart(call_id="c1", output_text="42"),
                TextPart(text="answer is 42"),
            ],
        ),
    ]
    lc1 = to_lc_messages(original)
    back = from_lc_messages(lc1)
    lc2 = to_lc_messages(back)

    # Content (text & tool structure) must be identical after the round trip;
    # message ids are regenerated by from_lc so we compare on shape only.
    def _shape(msgs):
        out = []
        for m in msgs:
            entry = {"type": type(m).__name__, "content": m.content}
            tc = getattr(m, "tool_calls", None)
            if tc:
                entry["tool_calls"] = tc
            tcid = getattr(m, "tool_call_id", None)
            if tcid:
                entry["tool_call_id"] = tcid
            out.append(entry)
        return out

    assert _shape(lc1) == _shape(lc2)


def test_file_part_becomes_text_breadcrumb_in_lc_view() -> None:
    msgs = [
        ChatMessage(
            id="m",
            role="user",
            content=[
                TextPart(text="Summarize this."),
                FilePart(vfs_ref="vfs://abc", file_name="Q3.pdf", purpose="attachment"),
            ],
        )
    ]
    lc = to_lc_messages(msgs)
    assert lc[0].content == "Summarize this.\n[file: Q3.pdf]"


def test_system_message_roundtrips_as_plain_text() -> None:
    msgs = [
        ChatMessage(
            id="m",
            role="system",
            content=[TextPart(text="You are helpful.")],
        )
    ]
    lc = to_lc_messages(msgs)
    assert isinstance(lc[0], SystemMessage)
    assert lc[0].content == "You are helpful."

    back = from_lc_messages(lc)
    assert back[0].role == "system"
    assert isinstance(back[0].content[0], TextPart)
    assert back[0].content[0].text == "You are helpful."

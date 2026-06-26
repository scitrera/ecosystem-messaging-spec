"""Tests for the todo content part — shared task tracking.

Mirrors go/todo_test.go and typescript/test/todo.test.ts.
"""
from __future__ import annotations

from scitrera_messaging_spec import (
    ChatMessage,
    MessageAddress,
    TodoItem,
    TodoPart,
)
from scitrera_messaging_spec.memorylayer import (
    from_memorylayer_message,
    to_memorylayer_payload,
)


def _msg() -> ChatMessage:
    return ChatMessage(
        id="m1",
        role="assistant",
        addr=MessageAddress(thread_id="thr"),
        content=[
            TodoPart(
                id="todo_main",
                title="Release",
                items=[
                    TodoItem(id="t1", content="Port codec", status="completed", active_form="Porting codec"),
                    TodoItem(id="t2", content="Wire sahara", status="in_progress"),
                ],
            )
        ],
    )


def test_todo_part_discriminates_and_round_trips() -> None:
    msg = _msg()
    part = msg.content[0]
    assert isinstance(part, TodoPart)
    assert part.items[1].status == "in_progress"

    back = ChatMessage.model_validate(msg.model_dump())
    assert isinstance(back.content[0], TodoPart)
    assert back.content[0].items[0].status == "completed"
    assert back.content[0].items[0].active_form == "Porting codec"


def test_todo_part_survives_memorylayer_codec() -> None:
    payload = to_memorylayer_payload(_msg())
    ml_record = {
        "id": "ml",
        "thread_id": "thr",
        "role": payload["role"],
        "content": payload["content"],
        "metadata": payload["metadata"],
    }
    back = from_memorylayer_message(ml_record)
    todo = back.content[0]
    assert isinstance(todo, TodoPart)
    assert len(todo.items) == 2
    assert todo.items[1].status == "in_progress"

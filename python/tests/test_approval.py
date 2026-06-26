"""Tests for the approval_request content part + approve/deny control kinds.

Mirrors go/approval_test.go and typescript/test/approval.test.ts.
"""
from __future__ import annotations

from scitrera_messaging_spec import (
    ApprovalRequestPart,
    ChatMessage,
    ControlPart,
    MessageAddress,
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
            ApprovalRequestPart(
                id="appr_1",
                tool="shell",
                summary="Run: npm test",
                args={"command": "npm test"},
                options=["once", "session", "always"],
                reason="shell is not pre-authorized",
            )
        ],
    )


def test_approval_part_discriminates_and_defaults_pending() -> None:
    part = _msg().content[0]
    assert isinstance(part, ApprovalRequestPart)
    assert part.status == "pending"
    assert part.options == ["once", "session", "always"]
    assert part.args == {"command": "npm test"}


def test_approval_part_survives_memorylayer_codec() -> None:
    payload = to_memorylayer_payload(_msg())
    ml_record = {
        "id": "ml",
        "thread_id": "thr",
        "role": payload["role"],
        "content": payload["content"],
        "metadata": payload["metadata"],
    }
    back = from_memorylayer_message(ml_record)
    part = back.content[0]
    assert isinstance(part, ApprovalRequestPart)
    assert part.id == "appr_1"
    assert part.tool == "shell"
    assert part.status == "pending"


def test_control_approve_carries_request_id_and_scope() -> None:
    ctrl = ControlPart.model_validate(
        {"type": "control", "kind": "approve", "request_id": "appr_1", "scope": "session"}
    )
    assert ctrl.kind == "approve"
    assert ctrl.request_id == "appr_1"
    assert ctrl.scope == "session"

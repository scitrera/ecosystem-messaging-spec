"""Tool transport types (spec 1.1).

These are the *transport* types used to actually invoke a tool over
Aether's ``TOOL_CALL`` message type. They are NOT content parts — they
are not members of the ``ContentPart`` union. The reply to a
``ToolInvokeEnvelope`` is the EXISTING ``ToolResultPart`` from
:mod:`scitrera_messaging_spec.schema` (reused; no new result type is
introduced).

Versioning: the tool transport layer is introduced at spec 1.1
(``TOOLS_SCHEMA_VERSION``). ``ChatMessage``'s wire format is untouched
and remains at spec ``SCHEMA_VERSION = "1.0"``.

Mirror of ``typescript/src/tools.ts``. JSON round-trips between Python
and TS must be identity; if you change one side, change the other. See
``docs/UNIVERSAL_MESSAGE_SPEC.md`` for the normative spec.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .schema import MessageAddress

TOOLS_SCHEMA_VERSION: str = "1.1"


class ToolDescriptor(BaseModel):
    """A tool catalog entry.

    ``tool_describe`` returns the full form; ``tool_search`` may return it
    with ``input_schema`` omitted.

    ``kind`` is an open string for forward-compat — same philosophy as the
    open ``ControlPart.kind`` registry. Documented known values are
    ``"frontend" | "backend" | "remote" | "office"``.

    ``awaits_result`` is named that way (not ``await``) because ``await``
    is a reserved keyword in Python and cannot be a field name.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    title: str | None = None
    description: str
    input_schema: dict[str, Any] | None = None
    kind: str
    awaits_result: bool
    toolsets: list[str] | None = None
    meta: dict[str, Any] | None = None


class ToolInvokeEnvelope(BaseModel):
    """The payload carried as the Aether ``TOOL_CALL`` body (UTF-8 JSON).

    The reply is the EXISTING ``ToolResultPart`` (reuse it; do not make a
    new result type).

    ``addr`` reuses the existing ``MessageAddress``. Per the
    execution-routing convention, ``request_id`` is the window target and
    ``task_id`` is the turn's chat task.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: str = TOOLS_SCHEMA_VERSION
    call_id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    addr: MessageAddress = Field(default_factory=MessageAddress)
    awaits_result: bool | None = None
    meta: dict[str, Any] | None = None


__all__ = [
    "TOOLS_SCHEMA_VERSION",
    "ToolDescriptor",
    "ToolInvokeEnvelope",
]

/**
 * Tool transport types (spec 1.1) — TypeScript types.
 *
 * Mirror of python/src/scitrera_messaging_spec/tools.py. JSON
 * round-trips between Python and TS must be identity; if you change one
 * side, change the other.
 *
 * These are the *transport* types used to actually invoke a tool over
 * Aether's ``TOOL_CALL`` message type. They are NOT content parts — they
 * are not members of the ``ContentPart`` union. The reply to a
 * ``ToolInvokeEnvelope`` is the EXISTING ``ToolResultPart`` from
 * ``schema.ts`` (reused; no new result type is introduced).
 *
 * Versioning: the tool transport layer is introduced at spec 1.1
 * (``TOOLS_SCHEMA_VERSION``). ``ChatMessage``'s wire format is untouched
 * and remains at spec ``MESSAGING_SCHEMA_VERSION = "1.0"``.
 *
 * See docs/UNIVERSAL_MESSAGE_SPEC.md for the normative spec.
 */

import type {MessageAddress} from './schema';

export const TOOLS_SCHEMA_VERSION = '1.1' as const;

/**
 * A tool catalog entry.
 *
 * ``tool_describe`` returns the full form; ``tool_search`` may return it
 * with ``input_schema`` omitted.
 *
 * ``kind`` is an open string for forward-compat — same philosophy as the
 * open ``ControlPart.kind`` registry. Documented known values are
 * ``"frontend" | "backend" | "remote" | "office"``.
 */
export interface ToolDescriptor {
    /** Unique catalog key. */
    name: string;
    title?: string | null;
    /** LLM-facing description. */
    description: string;
    /** JSON Schema; present on describe, may be omitted on search. */
    input_schema?: Record<string, unknown> | null;
    /** Open string registry: known values "frontend" | "backend" | "remote" | "office". */
    kind: string;
    /** ``false`` = fire-and-forget. Named ``awaits_result`` (not ``await``) for Python compat. */
    awaits_result: boolean;
    /** Tags for the availability/visibility predicate. */
    toolsets?: string[] | null;
    meta?: Record<string, unknown> | null;
    [extra: string]: unknown;
}

/**
 * The payload carried as the Aether ``TOOL_CALL`` body (UTF-8 JSON).
 *
 * The reply is the EXISTING ``ToolResultPart`` (reuse it; do not make a
 * new result type).
 *
 * ``addr`` reuses the existing ``MessageAddress``. Per the
 * execution-routing convention, ``request_id`` is the window target and
 * ``task_id`` is the turn's chat task.
 */
export interface ToolInvokeEnvelope {
    schema_version: string;
    /** Correlation id == the tool_call id. */
    call_id: string;
    /** Tool to invoke. */
    name: string;
    /** Arguments as a record, NOT a JSON string. */
    args: Record<string, unknown>;
    /** Reuses MessageAddress (tenant/workspace/user/thread/app/agent/task/request ids). */
    addr: MessageAddress;
    /** Optional override of the descriptor's default. */
    awaits_result?: boolean | null;
    /** Turn extras with no first-class MessageAddress home (window_id, app_workspace, authority_grant_id). */
    meta?: Record<string, unknown> | null;
    [extra: string]: unknown;
}

/** Builder helper — fills spec defaults so callers only pass what they care about. */
export function makeToolInvokeEnvelope(
    input: Partial<ToolInvokeEnvelope> & {call_id: string; name: string},
): ToolInvokeEnvelope {
    return {
        schema_version: TOOLS_SCHEMA_VERSION,
        args: {},
        addr: {},
        meta: null,
        ...input,
    };
}

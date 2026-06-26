/**
 * Universal ChatMessage schema (v1) — TypeScript types.
 *
 * Mirror of python/src/scitrera_messaging_spec/schema.py. JSON
 * round-trips between Python and TS must be identity; if you change one
 * side, change the other.
 *
 * See docs/UNIVERSAL_MESSAGE_SPEC.md for the normative spec.
 */

export const MESSAGING_SCHEMA_VERSION = '1.0' as const;

// ─── Content parts ───────────────────────────────────────────────────

export type ToolCallStatus =
    | 'pending'
    | 'running'
    | 'completed'
    | 'failed'
    | 'cancelled';

export interface TextPart {
    type: 'text';
    text: string;
    annotations?: Record<string, unknown>[] | null;
    [extra: string]: unknown;
}

export interface ImagePart {
    type: 'image';
    mime?: string | null;
    vfs_ref?: string | null;
    uri?: string | null;
    /** data:image/...;base64,... — escape hatch; prefer vfs_ref/uri. */
    data_uri?: string | null;
    alt_text?: string | null;
    [extra: string]: unknown;
}

export interface FilePart {
    type: 'file';
    vfs_ref?: string | null;
    uri?: string | null;
    mime?: string | null;
    file_name?: string | null;
    size_bytes?: number | null;
    purpose?: 'attachment' | 'document' | 'generated' | null;
    [extra: string]: unknown;
}

export interface ToolCallPart {
    type: 'tool_call';
    id: string;
    name: string;
    args: Record<string, unknown>;
    status: ToolCallStatus;
    started_at?: string | null;
    finished_at?: string | null;
    meta?: Record<string, unknown> | null;
    [extra: string]: unknown;
}

export interface ToolError {
    type?: string | null;
    message: string;
    [extra: string]: unknown;
}

export interface ToolResultPart {
    type: 'tool_result';
    call_id: string;
    name?: string | null;
    output?: unknown;
    output_text?: string | null;
    is_error: boolean;
    error?: ToolError | null;
    meta?: Record<string, unknown> | null;
    [extra: string]: unknown;
}

export interface CitationPart {
    type: 'citation';
    id?: string | null;
    source?: string | null;
    title?: string | null;
    snippet?: string | null;
    /** Char-offset span into the preceding text part. */
    span?: [number, number] | null;
    meta?: Record<string, unknown> | null;
    [extra: string]: unknown;
}

export interface DynamicPart {
    type: 'dynamic';
    kind: string;
    payload?: unknown;
    interactive: boolean;
    [extra: string]: unknown;
}

export interface ReasoningPart {
    type: 'reasoning';
    text: string;
    redacted: boolean;
    [extra: string]: unknown;
}

export type SubagentStatus =
    | 'pending'
    | 'running'
    | 'completed'
    | 'failed'
    | 'cancelled';

/**
 * In-band control signal carried as a content part.
 *
 * Used for cross-process control signals (cancel, pause, resume, etc.)
 * that need to travel on the same wire as the conversation rather than
 * over a separate side channel. The first known ``kind`` is ``"cancel"``,
 * which targets a specific ``task_id`` for abort.
 *
 * ``kind`` is an open registry — new control kinds may be added without
 * bumping ``schema_version``. Consumers MUST preserve unknown kinds on
 * round-trip (forward-compat per spec §3.10) and SHOULD ignore kinds
 * they don't recognize rather than erroring.
 *
 * Required fields per kind:
 *   - ``kind === "cancel"`` requires ``task_id``.
 */
export interface ControlPart {
    type: 'control';
    kind: string;
    task_id?: string | null;
    [extra: string]: unknown;
}

/**
 * Reference to a subagent's conversation.
 *
 * Subagents have their own thread (``thread_id``) whose messages live on
 * a separate thread and back-reference this part via
 * ``MessageRef.parent_thread_id`` / ``parent_message_id``. The parent
 * message carries only the reference + a short summary; the full
 * subagent transcript lives on its own thread.
 */
export interface SubagentPart {
    type: 'subagent';
    id: string;
    name: string;
    thread_id: string;
    input?: unknown;
    status: SubagentStatus;
    summary?: string | null;
    started_at?: string | null;
    finished_at?: string | null;
    meta?: Record<string, unknown> | null;
    [extra: string]: unknown;
}

/**
 * User feedback on another message, carried as a content part.
 *
 * A feedback message is a ``ChatMessage`` whose ``content`` is a single
 * ``FeedbackPart`` and whose ``ref.message_id`` points at the target
 * message being rated. The carrier message uses ``role: "user"`` (the
 * user is the actor) and ``ref.relationship === "feedback"``.
 *
 * Semantics:
 *   - Non-conversational metadata about another message. Persisted to
 *     MemoryLayer for analytics, but the LangChain adapter skips
 *     feedback-only messages so the model never sees them on resume.
 *   - ``sentiment`` is a plain ``number`` (not a Literal) to leave room
 *     for richer scales later (e.g. ``-2..+2`` or per-axis ratings). The
 *     established convention is ``+1`` = positive, ``-1`` = negative,
 *     ``0`` = cleared / no opinion. Consumers MUST preserve unknown
 *     numeric values on round-trip rather than validating as an enum.
 *   - ``text`` is an optional free-form reason.
 */
export interface FeedbackPart {
    type: 'feedback';
    sentiment: number;
    text?: string | null;
    [extra: string]: unknown;
}

export type TodoStatus = 'pending' | 'in_progress' | 'completed' | 'cancelled';

/** A single entry in a todo content part. */
export interface TodoItem {
    id?: string | null;
    content: string;
    status: TodoStatus;
    /** Present-tense label shown while the item is in_progress
     * (e.g. "Wiring sahara commit"); optional. */
    active_form?: string | null;
    [extra: string]: unknown;
}

/**
 * A shared, mutable checklist surfaced in the conversation.
 *
 * The agent writes the full list on each update; live updates ride
 * ``part_updated`` (patch ``{items}``). It persists via the MemoryLayer codec
 * like any other part. ``id`` is stable so consumers can render the latest todo
 * part as the live board across turns.
 */
export interface TodoPart {
    type: 'todo';
    id?: string | null;
    title?: string | null;
    items: TodoItem[];
    meta?: Record<string, unknown> | null;
    [extra: string]: unknown;
}

/**
 * Catch-all for content parts whose ``type`` this consumer doesn't recognize.
 *
 * Spec invariant: unknown parts MUST round-trip through this consumer
 * verbatim — do not drop unrecognized keys.
 */
export interface UnknownPart {
    type: string;
    [extra: string]: unknown;
}

export type KnownPartType =
    | 'text'
    | 'image'
    | 'file'
    | 'tool_call'
    | 'tool_result'
    | 'citation'
    | 'dynamic'
    | 'reasoning'
    | 'subagent'
    | 'control'
    | 'feedback'
    | 'todo';

const KNOWN_PART_TYPES: ReadonlySet<string> = new Set([
    'text',
    'image',
    'file',
    'tool_call',
    'tool_result',
    'citation',
    'dynamic',
    'reasoning',
    'subagent',
    'control',
    'feedback',
    'todo',
]);

export function isKnownPartType(t: unknown): t is KnownPartType {
    return typeof t === 'string' && KNOWN_PART_TYPES.has(t);
}

export type ContentPart =
    | TextPart
    | ImagePart
    | FilePart
    | ToolCallPart
    | ToolResultPart
    | CitationPart
    | DynamicPart
    | ReasoningPart
    | SubagentPart
    | ControlPart
    | FeedbackPart
    | TodoPart
    | UnknownPart;

// ─── Envelope ────────────────────────────────────────────────────────

export type Role = 'user' | 'assistant' | 'system' | 'tool';

export interface MessageAddress {
    tenant_id?: string | null;
    workspace_id?: string | null;
    user_id?: string | null;
    thread_id?: string | null;
    app_id?: string | null;
    agent_id?: string | null;
    task_id?: string | null;
    request_id?: string | null;
    telemetry?: Record<string, unknown> | null;
    [extra: string]: unknown;
}

export interface MessageRef {
    parent_id?: string | null;
    in_reply_to?: string | null;
    edits_id?: string | null;
    /** Cross-thread parent — used by subagent threads to back-reference their parent. */
    parent_thread_id?: string | null;
    parent_message_id?: string | null;
    [extra: string]: unknown;
}

export interface ChatMessage {
    schema_version: string;
    id: string;
    role: Role;
    created_at?: string | null;
    content: ContentPart[];
    addr: MessageAddress;
    meta: Record<string, unknown>;
    ref?: MessageRef | null;
    [extra: string]: unknown;
}

/** Builder helper — fills in spec defaults so callers only pass what they care about. */
export function makeChatMessage(input: Partial<ChatMessage> & {id: string; role: Role}): ChatMessage {
    return {
        schema_version: MESSAGING_SCHEMA_VERSION,
        created_at: new Date().toISOString(),
        content: [],
        addr: {},
        meta: {},
        ref: null,
        ...input,
    };
}

/**
 * MemoryLayer ↔ spec ChatMessage conversion helpers.
 *
 * MemoryLayer's chat history API (append_messages, get_messages) takes a
 * generic content-block shape:
 *
 *     {"role": ..., "content": string | [{"type": string, "text"?, "data"?}], "metadata": {...}}
 *
 * These helpers produce / consume that shape from a typed spec {@link ChatMessage}
 * losslessly: spec parts with no MemoryLayer-native field set go through
 * ``data``, and the spec metadata fields (id, addr, ref, schema_version,
 * created_at) ride in ``metadata`` under the ``scitrera.*`` namespace. Mirrors
 * the Python (scitrera_messaging_spec.memorylayer) and Go reference codecs.
 *
 * The helpers carry NO MemoryLayer SDK dependency — they produce / consume
 * plain objects. Callers wire a real MemoryLayer client themselves.
 */
import {
    MESSAGING_SCHEMA_VERSION,
    type ChatMessage,
    type ContentPart,
    type MessageAddress,
    type MessageRef,
    type Role,
} from './schema';

/** Reserved metadata namespace for spec-only fields stashed alongside
 * MemoryLayer's native metadata. Round-tripping a ChatMessage through
 * MemoryLayer round-trips these keys verbatim. */
const MEMORYLAYER_NS = 'scitrera';

/** Top-level MemoryLayer message-metadata key carrying the originating app
 * workspace at write time. Mirrors the SDK + server MESSAGE_META_APP_WORKSPACE_KEY
 * constants; kept in sync by value (the spec avoids a runtime dep on the SDK). */
const MEMORYLAYER_APP_WORKSPACE_KEY = 'app_workspace';

/** A single MemoryLayer content block. */
export interface MemoryLayerContentBlock {
    type: string;
    text?: string;
    data?: Record<string, unknown>;
}

/** A MemoryLayer append_messages entry. */
export interface MemoryLayerPayload {
    role: string;
    content: MemoryLayerContentBlock[];
    metadata: Record<string, unknown>;
}

/** The JSON-shaped object MemoryLayer returns from get_messages. */
export interface MemoryLayerMessage {
    id?: string;
    thread_id?: string;
    role?: string;
    content?: unknown;
    metadata?: Record<string, unknown> | null;
    created_at?: unknown;
    [extra: string]: unknown;
}

/**
 * Convert a spec {@link ChatMessage} to a MemoryLayer append_messages entry.
 * The result is safe to pass into the MemoryLayer client's append call.
 */
export function toMemoryLayerPayload(message: ChatMessage): MemoryLayerPayload {
    return {
        role: message.role,
        content: message.content.map(partToMLContent),
        metadata: buildMLMetadata(message),
    };
}

/** Bulk variant of {@link toMemoryLayerPayload}. */
export function toMemoryLayerPayloads(messages: ChatMessage[]): MemoryLayerPayload[] {
    return messages.map(toMemoryLayerPayload);
}

/**
 * Convert a MemoryLayer chat message back to a spec {@link ChatMessage}.
 * Reconstructs losslessly when the message was written via
 * {@link toMemoryLayerPayload}; for other producers (no scitrera.* metadata)
 * it falls back to MemoryLayer's native fields (thread_id, role, …).
 */
export function fromMemoryLayerMessage(mlMessage: MemoryLayerMessage): ChatMessage {
    const mlMeta: Record<string, unknown> = {...(mlMessage.metadata ?? {})};
    let specExtras: Record<string, unknown> = {};
    const sc = mlMeta[MEMORYLAYER_NS];
    if (isObject(sc)) {
        specExtras = sc;
        delete mlMeta[MEMORYLAYER_NS];
    }

    // addr: prefer the spec-native scitrera.addr namespace, then fall back to
    // MemoryLayer's native thread_id and the top-level app_workspace key.
    const addrDump: Record<string, unknown> = {...(isObject(specExtras.addr) ? specExtras.addr : {})};
    if (addrDump.thread_id === undefined && typeof mlMessage.thread_id === 'string' && mlMessage.thread_id) {
        addrDump.thread_id = mlMessage.thread_id;
    }
    if (addrDump.workspace_id === undefined) {
        const fallbackWs = mlMeta[MEMORYLAYER_APP_WORKSPACE_KEY];
        if (typeof fallbackWs === 'string' && fallbackWs) {
            addrDump.workspace_id = fallbackWs;
        }
    }

    let ref: MessageRef | null = null;
    if (isObject(specExtras.ref) && Object.keys(specExtras.ref).length > 0) {
        ref = specExtras.ref as MessageRef;
    }

    const schemaVersion = nonEmptyString(specExtras.schema_version) ?? MESSAGING_SCHEMA_VERSION;
    const id = nonEmptyString(specExtras.message_id) ?? (typeof mlMessage.id === 'string' ? mlMessage.id : '');
    const role = (nonEmptyString(mlMessage.role) ?? 'assistant') as Role;
    const createdAt = nonEmptyString(specExtras.created_at) ?? isoformat(mlMessage.created_at);

    return {
        schema_version: schemaVersion,
        id,
        role,
        created_at: createdAt ?? null,
        content: mlContentToParts(mlMessage.content),
        addr: addrDump as MessageAddress,
        meta: mlMeta,
        ref,
    };
}

// ---------------------------------------------------------------------------
// internals
// ---------------------------------------------------------------------------

/**
 * Render one spec ContentPart as a MemoryLayer content block. text parts use
 * the native ``text`` field (so MemoryLayer can run text search), with extras
 * under ``data``; all other parts stash their body (minus ``type``) under ``data``.
 */
function partToMLContent(part: ContentPart): MemoryLayerContentBlock {
    const dump = compact({...(part as Record<string, unknown>)});
    const ptype = nonEmptyString(dump.type) ?? 'unknown';
    delete dump.type;

    if (ptype === 'text') {
        const text = typeof dump.text === 'string' ? dump.text : '';
        delete dump.text;
        const out: MemoryLayerContentBlock = {type: 'text', text};
        if (Object.keys(dump).length > 0) {
            out.data = dump; // leftover annotations / extras
        }
        return out;
    }
    return {type: ptype, data: dump};
}

/** Inverse of {@link partToMLContent}. Accepts a string (legacy plain-text
 * message) or a list of MemoryLayer content blocks. */
function mlContentToParts(content: unknown): ContentPart[] {
    if (typeof content === 'string') {
        return content ? [{type: 'text', text: content} as ContentPart] : [];
    }
    if (!Array.isArray(content)) {
        return [];
    }
    const parts: ContentPart[] = [];
    for (const raw of content) {
        if (!isObject(raw)) {
            continue;
        }
        const btype = nonEmptyString(raw.type) ?? 'unknown';
        const inner: Record<string, unknown> = {type: btype};
        if (btype === 'text') {
            inner.text = typeof raw.text === 'string' ? raw.text : '';
        }
        if (isObject(raw.data)) {
            Object.assign(inner, raw.data);
        }
        // A text field sitting on the block itself is preserved.
        if (raw.text != null && inner.text === undefined) {
            inner.text = raw.text;
        }
        parts.push(inner as ContentPart);
    }
    return parts;
}

function buildMLMetadata(message: ChatMessage): Record<string, unknown> {
    const specExtras: Record<string, unknown> = {
        schema_version: message.schema_version || MESSAGING_SCHEMA_VERSION,
        message_id: message.id,
    };
    if (message.created_at != null) {
        specExtras.created_at = message.created_at;
    }
    const addrDump = compact({...(message.addr as Record<string, unknown>)});
    if (Object.keys(addrDump).length > 0) {
        specExtras.addr = addrDump;
    }
    if (message.ref != null) {
        const refDump = compact({...(message.ref as Record<string, unknown>)});
        if (Object.keys(refDump).length > 0) {
            specExtras.ref = refDump;
        }
    }

    const metadata: Record<string, unknown> = {...message.meta};

    // Top-level app_workspace carries addr.workspace_id using MemoryLayer's
    // native naming so memorylayer-native consumers can index/filter on it.
    // setdefault: a value the caller explicitly placed there wins.
    const ws = message.addr?.workspace_id;
    if (typeof ws === 'string' && ws && metadata[MEMORYLAYER_APP_WORKSPACE_KEY] === undefined) {
        metadata[MEMORYLAYER_APP_WORKSPACE_KEY] = ws;
    }

    // Reserve the scitrera namespace, merging into any existing object so a
    // caller's own scitrera.* keys (e.g. feedback) survive alongside spec extras.
    const existing = metadata[MEMORYLAYER_NS];
    metadata[MEMORYLAYER_NS] = isObject(existing) ? {...existing, ...specExtras} : specExtras;
    return metadata;
}

/** Drop top-level keys whose value is null/undefined (mirrors Python's
 * model_dump(exclude_none=True) for the flat envelope fields). */
function compact(obj: Record<string, unknown>): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(obj)) {
        if (v !== null && v !== undefined) {
            out[k] = v;
        }
    }
    return out;
}

function isObject(v: unknown): v is Record<string, unknown> {
    return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function nonEmptyString(v: unknown): string | undefined {
    return typeof v === 'string' && v !== '' ? v : undefined;
}

function isoformat(value: unknown): string | undefined {
    if (value == null) {
        return undefined;
    }
    if (typeof value === 'string') {
        return value;
    }
    if (value instanceof Date) {
        return value.toISOString();
    }
    return String(value);
}

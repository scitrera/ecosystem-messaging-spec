/**
 * Pure reducer for the universal ChatMessage streaming event vocabulary.
 *
 * Sibling of python/src/scitrera_messaging_spec/events.py::apply_event.
 * The two implementations must agree fixture-for-fixture.
 *
 * Contract:
 *   - Inputs are never mutated. The function returns a new state map (or
 *     the same reference if no-op).
 *   - Unknown event kinds are silently dropped (forward-compat).
 *   - The final reconstructed message must equal the
 *     ``message_finalized.message`` payload exactly.
 */
import type {
    ChatMessage,
    ContentPart,
    ReasoningPart,
    TextPart,
} from './schema';
import type {
    MessageFinalizedEvent,
    MessageStartedEvent,
    PartAppendedEvent,
    PartUpdatedEvent,
    StreamEvent,
    TokenDeltaEvent,
} from './events';

export type MessageState = Readonly<Record<string, ChatMessage>>;

export function applyEvent(state: MessageState, event: StreamEvent): MessageState {
    switch (event.event) {
        case 'message_started':
            return applyMessageStarted(state, event);
        case 'part_appended':
            return applyPartAppended(state, event);
        case 'token_delta':
            return applyTokenDelta(state, event);
        case 'part_updated':
            return applyPartUpdated(state, event);
        case 'message_finalized':
            return applyMessageFinalized(state, event);
        default:
            return state;
    }
}

/** Replay a sequence of events into a fresh state map. */
export function reduceEvents(events: Iterable<StreamEvent>): MessageState {
    let state: MessageState = {};
    for (const e of events) {
        state = applyEvent(state, e);
    }
    return state;
}

// ─── handlers ─────────────────────────────────────────────────────────

function applyMessageStarted(state: MessageState, event: MessageStartedEvent): MessageState {
    return {...state, [event.message.id]: cloneMessage(event.message)};
}

function applyPartAppended(state: MessageState, event: PartAppendedEvent): MessageState {
    const msg = state[event.message_id];
    if (!msg) return state;
    const content = [...msg.content];
    const idx = clampInsert(event.index, content.length);
    content.splice(idx, 0, structuredClone(event.part));
    return {...state, [msg.id]: {...msg, content}};
}

function applyTokenDelta(state: MessageState, event: TokenDeltaEvent): MessageState {
    const msg = state[event.message_id];
    if (!msg) return state;
    if (event.index < 0 || event.index >= msg.content.length) return state;
    const part = msg.content[event.index];
    if (!part || (part.type !== 'text' && part.type !== 'reasoning')) return state;
    const textPart = part as TextPart | ReasoningPart;
    const updated: ContentPart = {...textPart, text: (textPart.text ?? '') + event.text};
    const content = [...msg.content];
    content[event.index] = updated;
    return {...state, [msg.id]: {...msg, content}};
}

function applyPartUpdated(state: MessageState, event: PartUpdatedEvent): MessageState {
    const msg = state[event.message_id];
    if (!msg) return state;
    if (event.index < 0 || event.index >= msg.content.length) return state;
    const part = msg.content[event.index];
    if (!part) return state;
    const merged: ContentPart = {...part, ...event.patch} as ContentPart;
    const content = [...msg.content];
    content[event.index] = merged;
    return {...state, [msg.id]: {...msg, content}};
}

function applyMessageFinalized(state: MessageState, event: MessageFinalizedEvent): MessageState {
    return {...state, [event.message_id]: cloneMessage(event.message)};
}

// ─── helpers ──────────────────────────────────────────────────────────

function clampInsert(index: number, len: number): number {
    if (index < 0) return 0;
    if (index > len) return len;
    return index;
}

function cloneMessage(msg: ChatMessage): ChatMessage {
    return {
        ...msg,
        content: msg.content.map((p) => structuredClone(p)),
        addr: {...msg.addr},
        meta: {...msg.meta},
        ref: msg.ref ? {...msg.ref} : msg.ref,
    };
}

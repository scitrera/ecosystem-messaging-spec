/**
 * Streaming event vocabulary for the universal ChatMessage spec.
 *
 * Mirror of python/src/scitrera_messaging_spec/events.py.
 */
import type {ChatMessage, ContentPart} from './schema';

export interface MessageStartedEvent {
    event: 'message_started';
    message: ChatMessage;
}

export interface PartAppendedEvent {
    event: 'part_appended';
    message_id: string;
    index: number;
    part: ContentPart;
}

export interface TokenDeltaEvent {
    event: 'token_delta';
    message_id: string;
    index: number;
    text: string;
}

export interface PartUpdatedEvent {
    event: 'part_updated';
    message_id: string;
    index: number;
    patch: Record<string, unknown>;
}

export interface MessageFinalizedEvent {
    event: 'message_finalized';
    message_id: string;
    message: ChatMessage;
}

export type StreamEvent =
    | MessageStartedEvent
    | PartAppendedEvent
    | TokenDeltaEvent
    | PartUpdatedEvent
    | MessageFinalizedEvent;

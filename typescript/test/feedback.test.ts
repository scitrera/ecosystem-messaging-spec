/**
 * Tests for FeedbackPart — spec §3.12.
 *
 * Mirrors python/tests/test_feedback.py coverage on the TS side. The two
 * implementations must agree fixture-for-fixture on round-trip behavior.
 */
import {describe, expect, it} from 'vitest';
import {
    applyEvent,
    isKnownPartType,
    makeChatMessage,
    reduceEvents,
    type ChatMessage,
    type ContentPart,
    type FeedbackPart,
    type StreamEvent,
} from '../src/index';

describe('FeedbackPart', () => {
    it('is in the known part type set', () => {
        expect(isKnownPartType('feedback')).toBe(true);
    });

    it('round-trips through JSON (thumbs up with text)', () => {
        const msg: ChatMessage = makeChatMessage({
            id: 'msg_feedback_1',
            role: 'user',
            addr: {thread_id: 'thr_1', user_id: 'u1'},
            content: [
                {
                    type: 'feedback',
                    sentiment: 1,
                    text: 'great answer',
                } satisfies FeedbackPart,
            ],
            ref: {message_id: 'msg_target_1', relationship: 'feedback'},
        });
        const back: ChatMessage = JSON.parse(JSON.stringify(msg));
        expect(back).toEqual(msg);
        const part = back.content[0] as FeedbackPart;
        expect(part.type).toBe('feedback');
        expect(part.sentiment).toBe(1);
        expect(part.text).toBe('great answer');
    });

    it('round-trips with no text (thumbs down)', () => {
        const msg: ChatMessage = makeChatMessage({
            id: 'msg_fb_down',
            role: 'user',
            content: [{type: 'feedback', sentiment: -1} satisfies FeedbackPart],
            ref: {message_id: 'msg_target_2', relationship: 'feedback'},
        });
        const back: ChatMessage = JSON.parse(JSON.stringify(msg));
        const part = back.content[0] as FeedbackPart;
        expect(part.sentiment).toBe(-1);
        expect(part.text).toBeUndefined();
    });

    it('sentiment=0 means "cleared / no opinion"', () => {
        const part: FeedbackPart = {type: 'feedback', sentiment: 0};
        expect(part.sentiment).toBe(0);
    });

    it('unknown sentiment values round-trip verbatim (forward-compat)', () => {
        // Spec intentionally does NOT validate sentiment as an enum — wider
        // scales must round-trip unchanged so future ratings (e.g. -2..+2)
        // work without a schema bump.
        const raw = {type: 'feedback', sentiment: 5, text: 'wow'};
        const msg: ChatMessage = makeChatMessage({
            id: 'msg_fc',
            role: 'user',
            content: [raw as ContentPart],
        });
        const back: ChatMessage = JSON.parse(JSON.stringify(msg));
        const part = back.content[0] as FeedbackPart;
        expect(part.type).toBe('feedback');
        expect(part.sentiment).toBe(5);
        expect(part.text).toBe('wow');
    });

    it('preserves unknown extra fields (e.g. tags, confidence)', () => {
        const raw = {
            type: 'feedback',
            sentiment: 1,
            text: 'good',
            tags: ['accurate', 'concise'],
            confidence: 0.95,
        };
        const msg: ChatMessage = makeChatMessage({
            id: 'msg_extras',
            role: 'user',
            content: [raw as ContentPart],
        });
        const back: ChatMessage = JSON.parse(JSON.stringify(msg));
        const part = back.content[0] as FeedbackPart & {tags: string[]; confidence: number};
        expect(part.tags).toEqual(['accurate', 'concise']);
        expect(part.confidence).toBe(0.95);
    });

    it('FeedbackPart is a member of the ContentPart discriminated union', () => {
        // Type-level check: the compiler accepts FeedbackPart where
        // ContentPart is expected.
        const part: ContentPart = {type: 'feedback', sentiment: 1, text: 'ok'};
        expect(part.type).toBe('feedback');
    });
});

describe('applyEvent + FeedbackPart', () => {
    it('message_finalized with a feedback part round-trips without error', () => {
        const final: ChatMessage = makeChatMessage({
            id: 'msg_fb_stream',
            role: 'user',
            addr: {thread_id: 'thr_2'},
            content: [
                {
                    type: 'feedback',
                    sentiment: 1,
                    text: 'great',
                } satisfies FeedbackPart,
            ],
            ref: {message_id: 'msg_target_3', relationship: 'feedback'},
        });

        const events: StreamEvent[] = [
            {event: 'message_started', message: {...final, content: []}},
            {
                event: 'part_appended',
                message_id: final.id,
                index: 0,
                part: {type: 'feedback', sentiment: 1, text: 'great'},
            },
            {event: 'message_finalized', message_id: final.id, message: final},
        ];

        const state = reduceEvents(events);
        expect(state[final.id]).toEqual(final);
    });

    it('token_delta on a feedback part is a no-op (not a text part)', () => {
        const msg = makeChatMessage({
            id: 'm',
            role: 'user',
            content: [{type: 'feedback', sentiment: 1} satisfies FeedbackPart],
        });
        const after = applyEvent(
            {[msg.id]: msg},
            {event: 'token_delta', message_id: 'm', index: 0, text: 'oops'},
        );
        expect(after[msg.id]).toEqual(msg);
    });

    it('part_updated can patch the sentiment', () => {
        const msg = makeChatMessage({
            id: 'm',
            role: 'user',
            content: [{type: 'feedback', sentiment: 1} satisfies FeedbackPart],
        });
        const after = applyEvent(
            {[msg.id]: msg},
            {event: 'part_updated', message_id: 'm', index: 0, patch: {sentiment: -1}},
        );
        const part = after[msg.id]?.content[0] as FeedbackPart;
        expect(part.sentiment).toBe(-1);
    });
});

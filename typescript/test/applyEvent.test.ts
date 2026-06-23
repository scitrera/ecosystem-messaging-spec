/**
 * Mirrors python/tests/test_messaging.py — the two implementations must
 * produce identical state from identical event streams.
 */
import {describe, expect, it} from 'vitest';
import {
    applyEvent,
    isKnownPartType,
    makeChatMessage,
    MESSAGING_SCHEMA_VERSION,
    reduceEvents,
    type ChatMessage,
    type StreamEvent,
} from '../src/index';

function fixtureMessage(): ChatMessage {
    return makeChatMessage({
        id: 'msg_1',
        role: 'assistant',
        addr: {
            tenant_id: 't1',
            workspace_id: 'w1',
            user_id: 'u1',
            thread_id: 'th1',
            agent_id: 'ag1',
            request_id: 'req_1',
        },
        meta: {scitrera: {feedback: 'thumbs_up'}, 'x-cowork': {trace: 'abc'}},
        content: [
            {type: 'text', text: 'Looking up the report.'},
            {type: 'tool_call', id: 'call_1', name: 'vfs_fetch', args: {path: '/r.pdf'}, status: 'running'},
            {type: 'tool_result', call_id: 'call_1', name: 'vfs_fetch', output: {ok: true}, output_text: 'ok', is_error: false},
            {type: 'text', text: 'Done.'},
            {type: 'citation', id: 'cit_1', source: 'vfs://r.pdf', title: 'Q3 Report', snippet: '...'},
            {type: 'file', vfs_ref: 'vfs://r.pdf', mime: 'application/pdf', file_name: 'r.pdf', purpose: 'document'},
            {type: 'image', uri: 'https://example.com/img.png', mime: 'image/png'},
            {type: 'dynamic', kind: 'jsx', payload: {component: 'Chart'}, interactive: false},
            {type: 'reasoning', text: 'user wants a summary', redacted: false},
        ],
    });
}

describe('applyEvent', () => {
    it('rebuilds the canonical message from a typical event stream', () => {
        const final = fixtureMessage();

        const events: StreamEvent[] = [
            {
                event: 'message_started',
                message: {...final, content: []},
            },
        ];

        final.content.forEach((part, i) => {
            if (part.type === 'text') {
                events.push({event: 'part_appended', message_id: final.id, index: i, part: {type: 'text', text: ''}});
                events.push({event: 'token_delta', message_id: final.id, index: i, text: (part as {text: string}).text});
            } else if (part.type === 'tool_call') {
                events.push({
                    event: 'part_appended',
                    message_id: final.id,
                    index: i,
                    part: {...part, status: 'pending'},
                });
                events.push({event: 'part_updated', message_id: final.id, index: i, patch: {status: part.status}});
            } else {
                events.push({event: 'part_appended', message_id: final.id, index: i, part});
            }
        });

        events.push({event: 'message_finalized', message_id: final.id, message: final});

        const state = reduceEvents(events);
        expect(state[final.id]).toEqual(final);
    });

    it('does not mutate input state', () => {
        const msg = makeChatMessage({
            id: 'm',
            role: 'assistant',
            content: [{type: 'text', text: ''}],
        });
        const before: Record<string, ChatMessage> = {[msg.id]: msg};
        const snapshot = JSON.stringify(before);
        applyEvent(before, {event: 'token_delta', message_id: 'm', index: 0, text: '!'});
        expect(JSON.stringify(before)).toBe(snapshot);
    });

    it('token_delta is a no-op on non-text parts', () => {
        const msg = makeChatMessage({
            id: 'm',
            role: 'assistant',
            content: [{type: 'tool_call', id: 'c', name: 't', args: {}, status: 'pending'}],
        });
        const after = applyEvent({[msg.id]: msg}, {event: 'token_delta', message_id: 'm', index: 0, text: 'x'});
        expect(after[msg.id]?.content[0]).toEqual(msg.content[0]);
    });

    it('drops unknown event kinds without throwing', () => {
        const msg = makeChatMessage({id: 'm', role: 'assistant', content: []});
        const after = applyEvent(
            {[msg.id]: msg},
            {event: 'future_event', message_id: 'm'} as unknown as StreamEvent,
        );
        expect(after[msg.id]).toEqual(msg);
    });

    it('part_updated can morph a part to a different type', () => {
        const msg = makeChatMessage({
            id: 'm',
            role: 'assistant',
            content: [{type: 'text', text: 'hi'}],
        });
        const after = applyEvent(
            {[msg.id]: msg},
            {event: 'part_updated', message_id: 'm', index: 0, patch: {type: 'reasoning', redacted: false}},
        );
        expect(after[msg.id]?.content[0]?.type).toBe('reasoning');
    });
});

describe('messaging types', () => {
    it('exposes the spec version', () => {
        expect(MESSAGING_SCHEMA_VERSION).toBe('1.0');
    });

    it('isKnownPartType matches the spec', () => {
        expect(isKnownPartType('text')).toBe(true);
        expect(isKnownPartType('tool_call')).toBe(true);
        expect(isKnownPartType('screencast')).toBe(false);
        expect(isKnownPartType(undefined)).toBe(false);
    });
});

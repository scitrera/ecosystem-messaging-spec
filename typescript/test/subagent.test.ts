/**
 * Tests for SubagentPart + cross-thread MessageRef on the TS side.
 */
import {describe, expect, it} from 'vitest';
import {
    applyEvent,
    isKnownPartType,
    makeChatMessage,
    reduceEvents,
    type ChatMessage,
    type StreamEvent,
    type SubagentPart,
} from '../src/index';

describe('SubagentPart', () => {
    it('is in the known part type set', () => {
        expect(isKnownPartType('subagent')).toBe(true);
    });

    it('round-trips through JSON', () => {
        const msg: ChatMessage = makeChatMessage({
            id: 'msg_p',
            role: 'assistant',
            addr: {thread_id: 'thr_main'},
            content: [
                {type: 'text', text: 'Delegating to researcher.'},
                {
                    type: 'subagent',
                    id: 'sub_1',
                    name: 'researcher',
                    thread_id: 'thr_sub_001',
                    input: {query: 'Q3 revenue'},
                    status: 'running',
                    started_at: '2026-05-26T15:30:00Z',
                },
            ],
        });
        const back: ChatMessage = JSON.parse(JSON.stringify(msg));
        expect(back).toEqual(msg);
        const sub = back.content[1] as SubagentPart;
        expect(sub.type).toBe('subagent');
        expect(sub.thread_id).toBe('thr_sub_001');
    });

    it('cross-thread MessageRef fields are typed and serializable', () => {
        const child: ChatMessage = makeChatMessage({
            id: 'msg_c',
            role: 'user',
            addr: {thread_id: 'thr_sub_001'},
            ref: {parent_thread_id: 'thr_main', parent_message_id: 'msg_p'},
        });
        const raw = JSON.stringify(child);
        const back: ChatMessage = JSON.parse(raw);
        expect(back.ref?.parent_thread_id).toBe('thr_main');
        expect(back.ref?.parent_message_id).toBe('msg_p');
    });
});

describe('applyEvent + SubagentPart', () => {
    it('rebuilds an assistant message that contains a subagent reference', () => {
        const final: ChatMessage = makeChatMessage({
            id: 'msg_p',
            role: 'assistant',
            addr: {thread_id: 'thr_main'},
            content: [
                {type: 'text', text: 'Delegating.'},
                {
                    type: 'subagent',
                    id: 'sub_1',
                    name: 'researcher',
                    thread_id: 'thr_sub_001',
                    input: {q: 'Q3'},
                    status: 'completed',
                    summary: 'Q3 revenue was $4.2M',
                },
                {type: 'text', text: 'Got it.'},
            ],
        });

        const events: StreamEvent[] = [
            {event: 'message_started', message: {...final, content: []}},
            {event: 'part_appended', message_id: 'msg_p', index: 0, part: {type: 'text', text: ''}},
            {event: 'token_delta', message_id: 'msg_p', index: 0, text: 'Delegating.'},
            {
                event: 'part_appended',
                message_id: 'msg_p',
                index: 1,
                part: {
                    type: 'subagent',
                    id: 'sub_1',
                    name: 'researcher',
                    thread_id: 'thr_sub_001',
                    input: {q: 'Q3'},
                    status: 'running',
                },
            },
            {
                event: 'part_updated',
                message_id: 'msg_p',
                index: 1,
                patch: {status: 'completed', summary: 'Q3 revenue was $4.2M'},
            },
            {event: 'part_appended', message_id: 'msg_p', index: 2, part: {type: 'text', text: ''}},
            {event: 'token_delta', message_id: 'msg_p', index: 2, text: 'Got it.'},
            {event: 'message_finalized', message_id: 'msg_p', message: final},
        ];

        const state = reduceEvents(events);
        expect(state['msg_p']).toEqual(final);
    });

    it('token_delta on a subagent part is a no-op', () => {
        const msg = makeChatMessage({
            id: 'm',
            role: 'assistant',
            content: [
                {
                    type: 'subagent',
                    id: 'sub_1',
                    name: 'x',
                    thread_id: 'thr_x',
                    status: 'pending',
                },
            ],
        });
        const after = applyEvent(
            {[msg.id]: msg},
            {event: 'token_delta', message_id: 'm', index: 0, text: 'oops'},
        );
        expect(after[msg.id]).toEqual(msg);
    });
});

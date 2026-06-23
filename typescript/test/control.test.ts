/**
 * Tests for ControlPart — spec §3.11.
 *
 * Mirrors python/tests/test_messaging.py coverage for ControlPart.
 */
import {describe, expect, it} from 'vitest';
import {
    applyEvent,
    isKnownPartType,
    makeChatMessage,
    reduceEvents,
    type ChatMessage,
    type ContentPart,
    type ControlPart,
    type StreamEvent,
} from '../src/index';

describe('ControlPart', () => {
    it('is in the known part type set', () => {
        expect(isKnownPartType('control')).toBe(true);
    });

    it('round-trips through JSON', () => {
        const msg: ChatMessage = makeChatMessage({
            id: 'msg_ctrl_1',
            role: 'user',
            addr: {thread_id: 'thr_1', task_id: 'task_abc'},
            content: [
                {
                    type: 'control',
                    kind: 'cancel',
                    task_id: 'task_abc',
                } satisfies ControlPart,
            ],
        });
        const back: ChatMessage = JSON.parse(JSON.stringify(msg));
        expect(back).toEqual(msg);
        const part = back.content[0] as ControlPart;
        expect(part.type).toBe('control');
        expect(part.kind).toBe('cancel');
        expect(part.task_id).toBe('task_abc');
    });

    it('cancel example shape matches spec §3.11', () => {
        const part: ControlPart = {
            type: 'control',
            kind: 'cancel',
            task_id: 'task_xyz',
        };
        expect(part.type).toBe('control');
        expect(part.kind).toBe('cancel');
        expect(part.task_id).toBe('task_xyz');
    });

    it('task_id is optional (non-cancel kinds need not supply it)', () => {
        const part: ControlPart = {
            type: 'control',
            kind: 'pause',
        };
        expect(part.task_id).toBeUndefined();
    });

    it('unknown kind round-trips verbatim (forward-compat §3.10)', () => {
        const raw = {type: 'control', kind: 'future_signal', extra_field: 42};
        const msg: ChatMessage = makeChatMessage({
            id: 'msg_fc',
            role: 'user',
            content: [raw as ContentPart],
        });
        const back: ChatMessage = JSON.parse(JSON.stringify(msg));
        const part = back.content[0] as ControlPart & {extra_field: number};
        expect(part.type).toBe('control');
        expect(part.kind).toBe('future_signal');
        expect(part.extra_field).toBe(42);
    });

    it('ControlPart is a member of the ContentPart discriminated union', () => {
        // Type-level check: the compiler accepts ControlPart where ContentPart is expected.
        const part: ContentPart = {type: 'control', kind: 'cancel', task_id: 'task_1'};
        expect(part.type).toBe('control');
    });
});

describe('applyEvent + ControlPart', () => {
    it('message_finalized with a control part round-trips without error', () => {
        const final: ChatMessage = makeChatMessage({
            id: 'msg_ctrl_2',
            role: 'user',
            addr: {thread_id: 'thr_2'},
            content: [
                {type: 'text', text: 'Please cancel.'},
                {type: 'control', kind: 'cancel', task_id: 'task_42'} satisfies ControlPart,
            ],
        });

        const events: StreamEvent[] = [
            {event: 'message_started', message: {...final, content: []}},
            {event: 'part_appended', message_id: final.id, index: 0, part: {type: 'text', text: ''}},
            {event: 'token_delta', message_id: final.id, index: 0, text: 'Please cancel.'},
            {
                event: 'part_appended',
                message_id: final.id,
                index: 1,
                part: {type: 'control', kind: 'cancel', task_id: 'task_42'},
            },
            {event: 'message_finalized', message_id: final.id, message: final},
        ];

        const state = reduceEvents(events);
        expect(state[final.id]).toEqual(final);
    });

    it('token_delta on a control part is a no-op', () => {
        const msg = makeChatMessage({
            id: 'm',
            role: 'user',
            content: [{type: 'control', kind: 'cancel', task_id: 'task_1'} satisfies ControlPart],
        });
        const after = applyEvent(
            {[msg.id]: msg},
            {event: 'token_delta', message_id: 'm', index: 0, text: 'oops'},
        );
        expect(after[msg.id]).toEqual(msg);
    });

    it('part_updated can patch a control part kind', () => {
        const msg = makeChatMessage({
            id: 'm',
            role: 'user',
            content: [{type: 'control', kind: 'cancel', task_id: 'task_1'} satisfies ControlPart],
        });
        const after = applyEvent(
            {[msg.id]: msg},
            {event: 'part_updated', message_id: 'm', index: 0, patch: {kind: 'pause'}},
        );
        const part = after[msg.id]?.content[0] as ControlPart;
        expect(part.kind).toBe('pause');
    });
});

/**
 * Tests for the todo content part — shared task tracking.
 *
 * Mirrors go/todo_test.go and python/tests/test_todo.py, and exercises the live
 * update path (part_appended → part_updated) through the reducer.
 */
import {describe, expect, it} from 'vitest';
import {
    fromMemoryLayerMessage,
    reduceEvents,
    toMemoryLayerPayload,
    type ChatMessage,
    type MessageStartedEvent,
    type PartAppendedEvent,
    type PartUpdatedEvent,
    type TodoItem,
    type TodoPart,
} from '../src/index';

function todoPart(items: TodoItem[]): TodoPart {
    return {type: 'todo', id: 'todo_main', items};
}

describe('todo part', () => {
    it('streams live: part_appended then part_updated replaces items via shallow merge', () => {
        const msg: ChatMessage = {
            schema_version: '1.0', id: 'm1', role: 'assistant',
            addr: {thread_id: 'thr'}, meta: {}, content: [],
        };
        const state = reduceEvents([
            {event: 'message_started', message: msg} as MessageStartedEvent,
            {
                event: 'part_appended', message_id: 'm1', index: 0,
                part: todoPart([{id: 't1', content: 'A', status: 'pending'}]),
            } as PartAppendedEvent,
            {
                event: 'part_updated', message_id: 'm1', index: 0,
                patch: {items: [
                    {id: 't1', content: 'A', status: 'completed'},
                    {id: 't2', content: 'B', status: 'in_progress'},
                ]},
            } as PartUpdatedEvent,
        ]);
        const part = state['m1']!.content[0] as TodoPart;
        expect(part.type).toBe('todo');
        expect(part.items).toHaveLength(2);
        expect(part.items[0]!.status).toBe('completed');
        expect(part.items[1]!.status).toBe('in_progress');
    });

    it('round-trips through the MemoryLayer codec', () => {
        const msg: ChatMessage = {
            schema_version: '1.0', id: 'm1', role: 'assistant',
            addr: {thread_id: 'thr'}, meta: {},
            content: [todoPart([{id: 't1', content: 'A', status: 'in_progress', active_form: 'Doing A'}])],
        };
        const payload = toMemoryLayerPayload(msg);
        const rec = JSON.parse(JSON.stringify({
            id: 'ml', thread_id: 'thr', role: payload.role,
            content: payload.content, metadata: payload.metadata,
        }));
        const back = fromMemoryLayerMessage(rec);
        const part = back.content[0] as TodoPart;
        expect(part.type).toBe('todo');
        expect(part.items[0]!.status).toBe('in_progress');
        expect(part.items[0]!.active_form).toBe('Doing A');
    });
});

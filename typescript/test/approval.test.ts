/**
 * Tests for the approval_request content part + approve/deny control kinds.
 *
 * Mirrors go/approval_test.go and python/tests/test_approval.py, and exercises
 * the resolve path (part_appended pending → part_updated status flip).
 */
import {describe, expect, it} from 'vitest';
import {
    fromMemoryLayerMessage,
    reduceEvents,
    toMemoryLayerPayload,
    type ApprovalRequestPart,
    type ChatMessage,
    type ControlPart,
    type MessageStartedEvent,
    type PartAppendedEvent,
    type PartUpdatedEvent,
} from '../src/index';

function approvalPart(): ApprovalRequestPart {
    return {
        type: 'approval_request',
        id: 'appr_1',
        tool: 'shell',
        summary: 'Run: npm test',
        args: {command: 'npm test'},
        options: ['once', 'session', 'always'],
        status: 'pending',
        reason: 'shell is not pre-authorized',
    };
}

describe('approval_request part', () => {
    it('resolves live: part_appended (pending) then part_updated flips status', () => {
        const msg: ChatMessage = {
            schema_version: '1.0', id: 'm1', role: 'assistant',
            addr: {thread_id: 'thr'}, meta: {}, content: [],
        };
        const state = reduceEvents([
            {event: 'message_started', message: msg} as MessageStartedEvent,
            {event: 'part_appended', message_id: 'm1', index: 0, part: approvalPart()} as PartAppendedEvent,
            {event: 'part_updated', message_id: 'm1', index: 0, patch: {status: 'approved'}} as PartUpdatedEvent,
        ]);
        const part = state['m1']!.content[0] as ApprovalRequestPart;
        expect(part.type).toBe('approval_request');
        expect(part.status).toBe('approved');
        expect(part.tool).toBe('shell'); // other fields preserved by shallow merge
    });

    it('round-trips through the MemoryLayer codec', () => {
        const msg: ChatMessage = {
            schema_version: '1.0', id: 'm1', role: 'assistant',
            addr: {thread_id: 'thr'}, meta: {}, content: [approvalPart()],
        };
        const payload = toMemoryLayerPayload(msg);
        const rec = JSON.parse(JSON.stringify({
            id: 'ml', thread_id: 'thr', role: payload.role,
            content: payload.content, metadata: payload.metadata,
        }));
        const back = fromMemoryLayerMessage(rec);
        const part = back.content[0] as ApprovalRequestPart;
        expect(part.type).toBe('approval_request');
        expect(part.id).toBe('appr_1');
        expect(part.status).toBe('pending');
    });

    it('control approve carries request_id + scope', () => {
        const ctrl: ControlPart = {
            type: 'control', kind: 'approve', request_id: 'appr_1', scope: 'session',
        };
        expect(ctrl.kind).toBe('approve');
        expect(ctrl.request_id).toBe('appr_1');
        expect(ctrl.scope).toBe('session');
    });
});

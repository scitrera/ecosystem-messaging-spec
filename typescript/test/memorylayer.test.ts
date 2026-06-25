/**
 * Tests for the MemoryLayer ↔ spec ChatMessage conversion helpers.
 *
 * Mirrors python/tests/test_memorylayer.py and go/memorylayer_test.go — the
 * three implementations must agree fixture-for-fixture on round-trip behavior.
 */
import {describe, expect, it} from 'vitest';
import {
    fromMemoryLayerMessage,
    toMemoryLayerPayload,
    toMemoryLayerPayloads,
    type ChatMessage,
    type MemoryLayerMessage,
} from '../src/index';

function fixture(): ChatMessage {
    return {
        schema_version: '1.0',
        id: 'msg_1',
        role: 'assistant',
        created_at: '2026-05-26T15:30:00Z',
        addr: {
            tenant_id: 't1',
            workspace_id: 'w1',
            user_id: 'u1',
            thread_id: 'thr_1',
            agent_id: 'ag1',
            task_id: 'task_1',
        },
        content: [
            {type: 'text', text: 'Looking up.'},
            {type: 'tool_call', id: 'c1', name: 'fetch', args: {x: 1}, status: 'completed'},
            {type: 'tool_result', call_id: 'c1', name: 'fetch', output_text: '42', is_error: false},
            {type: 'text', text: 'Done.'},
            {type: 'reasoning', text: 'thinking', redacted: false},
        ],
        meta: {scitrera: {feedback: 'thumbs_up'}, 'x-cowork': {trace: 'abc'}},
        ref: {parent_thread_id: 'thr_main', parent_message_id: 'msg_p'},
    };
}

/** Round-trip a payload through JSON to mimic exactly what get_messages returns. */
function simulateRecord(threadID: string, payload: ReturnType<typeof toMemoryLayerPayload>): MemoryLayerMessage {
    return JSON.parse(
        JSON.stringify({
            id: 'ml_id_1',
            thread_id: threadID,
            message_index: 0,
            role: payload.role,
            content: payload.content,
            metadata: payload.metadata,
            created_at: '2026-05-26T15:30:00Z',
        }),
    ) as MemoryLayerMessage;
}

describe('toMemoryLayerPayload', () => {
    it('produces the MemoryLayer payload shape', () => {
        const payload = toMemoryLayerPayload(fixture());
        expect(payload.role).toBe('assistant');
        expect(Array.isArray(payload.content)).toBe(true);
        expect(typeof payload.metadata).toBe('object');
    });

    it('puts text parts on the native text field with no data', () => {
        const payload = toMemoryLayerPayload({
            schema_version: '1.0', id: 'm', role: 'user', addr: {}, meta: {},
            content: [{type: 'text', text: 'hi'}],
        });
        expect(payload.content[0]).toEqual({type: 'text', text: 'hi'});
        expect(payload.content[0]!.data).toBeUndefined();
    });

    it('routes non-text parts to data', () => {
        const payload = toMemoryLayerPayload({
            schema_version: '1.0', id: 'm', role: 'assistant', addr: {}, meta: {},
            content: [{type: 'tool_call', id: 'c1', name: 't', args: {x: 1}, status: 'completed'}],
        });
        const block = payload.content[0]!;
        expect(block.type).toBe('tool_call');
        expect(block.text).toBeUndefined();
        expect(block.data).toMatchObject({id: 'c1', name: 't', args: {x: 1}});
    });

    it('carries spec fields + preexisting scitrera keys under the scitrera namespace', () => {
        const sc = toMemoryLayerPayload(fixture()).metadata.scitrera as Record<string, any>;
        expect(sc.feedback).toBe('thumbs_up');
        expect(sc.schema_version).toBe('1.0');
        expect(sc.message_id).toBe('msg_1');
        expect(sc.addr.thread_id).toBe('thr_1');
        expect(sc.addr.workspace_id).toBe('w1');
        expect(sc.ref.parent_thread_id).toBe('thr_main');
    });

    it('preserves user (non-scitrera) metadata namespaces', () => {
        const payload = toMemoryLayerPayload(fixture());
        expect(payload.metadata['x-cowork']).toEqual({trace: 'abc'});
    });

    it('emits top-level app_workspace from addr.workspace_id', () => {
        const payload = toMemoryLayerPayload({
            schema_version: '1.0', id: 'm_aw', role: 'user', meta: {},
            addr: {workspace_id: 'ws-real', thread_id: 'thr_1'},
            content: [{type: 'text', text: 'hi'}],
        });
        expect(payload.metadata.app_workspace).toBe('ws-real');
        expect((payload.metadata.scitrera as any).addr.workspace_id).toBe('ws-real');
    });

    it('lets an explicit meta.app_workspace win over addr', () => {
        const payload = toMemoryLayerPayload({
            schema_version: '1.0', id: 'm_aw2', role: 'user',
            addr: {workspace_id: 'ws-from-addr', thread_id: 'thr_1'},
            content: [{type: 'text', text: 'hi'}],
            meta: {app_workspace: 'ws-explicit'},
        });
        expect(payload.metadata.app_workspace).toBe('ws-explicit');
    });

    it('skips app_workspace when addr.workspace_id is unset', () => {
        const payload = toMemoryLayerPayload({
            schema_version: '1.0', id: 'm_aw3', role: 'user', meta: {},
            addr: {thread_id: 'thr_1'},
            content: [{type: 'text', text: 'hi'}],
        });
        expect('app_workspace' in payload.metadata).toBe(false);
    });
});

describe('fromMemoryLayerMessage — round trip', () => {
    it('preserves content types, meta, addr and ref', () => {
        const msg = fixture();
        const back = fromMemoryLayerMessage(simulateRecord('thr_1', toMemoryLayerPayload(msg)));
        expect(back.content.map((p) => p.type)).toEqual(msg.content.map((p) => p.type));
        expect(back.id).toBe('msg_1');
        expect(back.role).toBe('assistant');
        expect(back.addr.thread_id).toBe('thr_1');
        expect(back.addr.workspace_id).toBe('w1');
        expect(back.ref?.parent_thread_id).toBe('thr_main');
        expect(back.meta['x-cowork']).toEqual({trace: 'abc'});
    });

    it('preserves structured tool_call args and tool_result output', () => {
        const msg: ChatMessage = {
            schema_version: '1.0', id: 'm', role: 'assistant', addr: {thread_id: 'thr_1'}, meta: {},
            content: [
                {type: 'tool_call', id: 'c1', name: 't', args: {a: 1, b: [2, 3]}, status: 'completed'},
                {type: 'tool_result', call_id: 'c1', output: {ok: true}, is_error: false},
            ],
        };
        const back = fromMemoryLayerMessage(simulateRecord('thr_1', toMemoryLayerPayload(msg)));
        expect((back.content[0] as any).args).toEqual({a: 1, b: [2, 3]});
        expect((back.content[1] as any).output).toEqual({ok: true});
    });

    it('parses a plain (non-scitrera) record with string content', () => {
        const back = fromMemoryLayerMessage({
            id: 'ml_xyz', thread_id: 'thr_x', role: 'user',
            content: 'just plain text', metadata: {}, created_at: '2026-05-26T12:00:00Z',
        });
        expect(back.role).toBe('user');
        expect(back.addr.thread_id).toBe('thr_x');
        expect(back.content).toHaveLength(1);
        expect(back.content[0]).toMatchObject({type: 'text', text: 'just plain text'});
    });

    it('round-trips an unknown part type verbatim', () => {
        const msg: ChatMessage = {
            schema_version: '1.0', id: 'm', role: 'assistant', addr: {thread_id: 'thr_x'}, meta: {},
            content: [{type: 'screencast', url: 'https://x', duration_ms: 1234}],
        };
        const back = fromMemoryLayerMessage(simulateRecord('thr_x', toMemoryLayerPayload(msg)));
        expect(back.content[0]!.type).toBe('screencast');
        expect(back.content[0]).toMatchObject({url: 'https://x', duration_ms: 1234});
    });

    it('falls back to top-level app_workspace when scitrera is absent', () => {
        const back = fromMemoryLayerMessage({
            id: 'srv_id_1', thread_id: 'thr_1', role: 'user',
            content: [{type: 'text', text: 'hi'}],
            metadata: {app_workspace: 'ws-from-sdk'},
        });
        expect(back.addr.workspace_id).toBe('ws-from-sdk');
        expect(back.addr.thread_id).toBe('thr_1');
    });

    it('prefers scitrera.addr.workspace_id over top-level app_workspace', () => {
        const back = fromMemoryLayerMessage({
            id: 'srv_id_2', thread_id: 'thr_1', role: 'user',
            content: [{type: 'text', text: 'hi'}],
            metadata: {
                app_workspace: 'ws-fallback',
                scitrera: {schema_version: '1.0', message_id: 'm_xyz', addr: {thread_id: 'thr_1', workspace_id: 'ws-spec'}},
            },
        });
        expect(back.addr.workspace_id).toBe('ws-spec');
    });
});

describe('toMemoryLayerPayloads (bulk)', () => {
    it('maps each message in order', () => {
        const out = toMemoryLayerPayloads([
            {schema_version: '1.0', id: 'm1', role: 'user', addr: {}, meta: {}, content: [{type: 'text', text: 'hi'}]},
            {schema_version: '1.0', id: 'm2', role: 'assistant', addr: {}, meta: {}, content: [{type: 'text', text: 'hello'}]},
        ]);
        expect(out.map((p) => p.role)).toEqual(['user', 'assistant']);
    });
});

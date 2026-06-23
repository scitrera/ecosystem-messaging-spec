/**
 * Tests for tool transport types (spec 1.1).
 *
 * Mirrors python/tests/test_tools.py. The reply to a ToolInvokeEnvelope
 * is the existing ToolResultPart from schema.ts.
 */
import {describe, expect, it} from 'vitest';
import {
    TOOLS_SCHEMA_VERSION,
    makeToolInvokeEnvelope,
    type ToolDescriptor,
    type ToolInvokeEnvelope,
    type ToolResultPart,
} from '../src/index';

describe('TOOLS_SCHEMA_VERSION', () => {
    it('is 1.1 (transport layer; ChatMessage stays 1.0)', () => {
        expect(TOOLS_SCHEMA_VERSION).toBe('1.1');
    });
});

describe('ToolDescriptor', () => {
    it('round-trips through JSON (full describe form)', () => {
        const d: ToolDescriptor = {
            name: 'read_file',
            title: 'Read File',
            description: 'Read a file from the VFS.',
            input_schema: {type: 'object', properties: {path: {type: 'string'}}},
            kind: 'backend',
            awaits_result: true,
            toolsets: ['files', 'core'],
            meta: {category: 'io'},
        };
        const back: ToolDescriptor = JSON.parse(JSON.stringify(d));
        expect(back).toEqual(d);
    });

    it('search form may omit input_schema', () => {
        const d: ToolDescriptor = {
            name: 'read_file',
            description: 'Read a file from the VFS.',
            kind: 'backend',
            awaits_result: true,
        };
        const back: ToolDescriptor = JSON.parse(JSON.stringify(d));
        expect(back).toEqual(d);
        expect(back.input_schema).toBeUndefined();
    });

    it('preserves unknown extra fields on round-trip (forward-compat)', () => {
        const raw = {
            name: 'send_email',
            description: 'Send an email.',
            kind: 'office',
            awaits_result: false,
            future_field: {v: 7},
        };
        const back = JSON.parse(JSON.stringify(raw)) as ToolDescriptor & {
            future_field: {v: number};
        };
        expect(back.future_field).toEqual({v: 7});
        expect(back.awaits_result).toBe(false);
    });

    it('uses field name awaits_result, not await', () => {
        const d: ToolDescriptor = {
            name: 'fire',
            description: 'fire and forget',
            kind: 'frontend',
            awaits_result: false,
        };
        expect('await' in d).toBe(false);
        expect(d.awaits_result).toBe(false);
    });
});

describe('ToolInvokeEnvelope', () => {
    it('round-trips through JSON', () => {
        const env: ToolInvokeEnvelope = {
            schema_version: TOOLS_SCHEMA_VERSION,
            call_id: 'call_1',
            name: 'read_file',
            args: {path: '/a.txt'},
            addr: {tenant_id: 't1', task_id: 'task_turn', request_id: 'win_1'},
            awaits_result: true,
            meta: {window_id: 'win_1'},
        };
        const back: ToolInvokeEnvelope = JSON.parse(JSON.stringify(env));
        expect(back).toEqual(env);
    });

    it('preserves unknown extra fields on round-trip (forward-compat)', () => {
        const raw = {
            schema_version: '1.1',
            call_id: 'call_2',
            name: 't',
            args: {},
            addr: {},
            future_field: 'keep_me',
        };
        const back = JSON.parse(JSON.stringify(raw)) as ToolInvokeEnvelope & {
            future_field: string;
        };
        expect(back.future_field).toBe('keep_me');
    });

    it('builder fills spec defaults', () => {
        const env = makeToolInvokeEnvelope({call_id: 'c', name: 'n'});
        expect(env.schema_version).toBe(TOOLS_SCHEMA_VERSION);
        expect(env.args).toEqual({});
        expect(env.addr).toEqual({});
        expect(env.meta).toBeNull();
        expect(env.call_id).toBe('c');
        expect(env.name).toBe('n');
    });

    it('builder lets caller override defaults', () => {
        const env = makeToolInvokeEnvelope({
            call_id: 'c',
            name: 'n',
            args: {x: 1},
            addr: {request_id: 'win'},
            awaits_result: false,
        });
        expect(env.args).toEqual({x: 1});
        expect(env.addr.request_id).toBe('win');
        expect(env.awaits_result).toBe(false);
    });

    it('reuses ToolResultPart as the reply payload', () => {
        const env = makeToolInvokeEnvelope({call_id: 'call_42', name: 'read_file'});
        const reply: ToolResultPart = {
            type: 'tool_result',
            call_id: env.call_id,
            name: env.name,
            output: {bytes: 12},
            output_text: 'hello world',
            is_error: false,
        };
        const back: ToolResultPart = JSON.parse(JSON.stringify(reply));
        expect(back).toEqual(reply);
        expect(back.call_id).toBe(env.call_id);
    });
});

describe('cross-language JSON identity', () => {
    it('emits documented snake_case field names', () => {
        const d: ToolDescriptor = {
            name: 'n',
            title: 't',
            description: 'd',
            input_schema: {},
            kind: 'backend',
            awaits_result: true,
            toolsets: ['x'],
            meta: {},
        };
        const json = JSON.parse(JSON.stringify(d));
        expect(Object.keys(json).sort()).toEqual(
            [
                'awaits_result',
                'description',
                'input_schema',
                'kind',
                'meta',
                'name',
                'title',
                'toolsets',
            ].sort(),
        );

        const env: ToolInvokeEnvelope = {
            schema_version: '1.1',
            call_id: 'c',
            name: 'n',
            args: {},
            addr: {},
            awaits_result: true,
            meta: {},
        };
        const ejson = JSON.parse(JSON.stringify(env));
        expect(Object.keys(ejson).sort()).toEqual(
            [
                'addr',
                'args',
                'awaits_result',
                'call_id',
                'meta',
                'name',
                'schema_version',
            ].sort(),
        );
    });
});

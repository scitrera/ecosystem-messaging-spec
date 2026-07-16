/**
 * Tests for the dynamic tool_call_progress part (live progress bar).
 *
 * Mirrors go/progress_test.go and python/tests/test_progress.py.
 */
import {describe, expect, it} from 'vitest';
import {
    DYNAMIC_TOOL_CALL_PROGRESS,
    makeToolCallProgressPart,
    type ToolCallProgressPayload,
} from '../src/index';

describe('tool_call_progress dynamic part', () => {
    it('builds a dynamic part with status/unit defaults', () => {
        const part = makeToolCallProgressPart({bar_id: 'stqdm_0', desc: 'Scoring', n: 42, total: 100});
        expect(part.type).toBe('dynamic');
        expect(part.kind).toBe(DYNAMIC_TOOL_CALL_PROGRESS);
        expect(part.interactive).toBe(false);
        const pl = part.payload as ToolCallProgressPayload;
        expect(pl.bar_id).toBe('stqdm_0');
        expect(pl.n).toBe(42);
        expect(pl.total).toBe(100);
        expect(pl.status).toBe('running');
        expect(pl.unit).toBe('it');
    });

    it('lets an explicit status/unit override the default', () => {
        const part = makeToolCallProgressPart({bar_id: 'b', n: 10, total: 10, status: 'done', unit: 'file'});
        const pl = part.payload as ToolCallProgressPayload;
        expect(pl.status).toBe('done');
        expect(pl.unit).toBe('file');
    });
});

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mockRequest as m } from '../src/api/mock.ts';

type Any = any; // eslint-disable-line

async function drain(id: string): Promise<Any> {
    for (let i = 0; i < 50; i++) { const r: Any = await m('/runs/' + id); if (r.status === 'completed') return r; }
    throw new Error('run never completed');
}
async function startRun(): Promise<string> { const r: Any = await m('/runs', { method: 'POST' }); await drain(r.id); return r.id; }
const open = (id: string): Promise<Any[]> => m('/runs/' + id + '/items', { query: { status: 'needs_approval' } });
const decide = (id: string, body: object): Promise<Any> => m('/items/' + id + '/decision', { method: 'POST', body });
const reset = (): Promise<Any> => m('/demo/reset', { method: 'POST' });

test('deciding an item that is not needs_approval is a 409 and leaves the difference unchanged', async () => {
    await reset();
    const items = await open(await startRun());
    const first: Any = await decide(items[0].id, { decision: 'approve' });
    await assert.rejects(decide(items[0].id, { decision: 'approve' }), (e: Any) => e.code === 'item_not_pending' && e.status === 409 && e.message === `Item ${items[0].id} is approved; only needs_approval items can be decided`);
    const st: Any = await m('/statement');
    assert.equal(st.unreconciled_difference, first.statement.unreconciled_difference);
});

test('an unknown item id is a 404 item_not_found', async () => {
    await assert.rejects(decide('no-such-item', { decision: 'approve' }), (e: Any) => e.code === 'item_not_found' && e.status === 404);
});

test('reset reports learned rules once, then zero', async () => {
    await reset();
    const items = await open(await startRun());
    await decide(items[0].id, { decision: 'approve', remember: true });
    assert.equal((await reset()).rules_deleted, 1);
    assert.equal((await reset()).rules_deleted, 0);
});

test('learning loop: remember the interest, run 2 starts at 845.00, the rest reach 0.00', async () => {
    await reset();
    const run1 = await startRun();
    const items = await open(run1);
    const interest = items.filter(i => i.kind === 'interest_missing_in_gl' && i.amount_delta === '12.50');
    assert.equal(interest.length, 1);
    await decide(interest[0].id, { decision: 'approve', remember: true });
    const run2 = await startRun();
    const st: Any = await m('/statement');
    assert.equal(st.unreconciled_difference, '845.00');
    assert.equal(st.run_id, run2);
    const rest = await open(run2);
    assert.equal(rest.length, 3);
    let last: Any = st;
    for (const i of rest) last = (await decide(i.id, { decision: 'approve' })).statement;
    assert.equal(last.unreconciled_difference, '0.00');
    await reset();
});

test('an unknown run is a 404 run_not_found on run, items and audit', async () => {
    for (const path of ['/runs/nope', '/runs/nope/items', '/runs/nope/audit'])
        await assert.rejects(m(path), (e: Any) => e.code === 'run_not_found' && e.status === 404, path);
});

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
const forgetAll = (): Promise<Any> => m('/rules', { method: 'DELETE' });
const forget = (id: number | string): Promise<Any> => m('/rules/' + id, { method: 'DELETE' });
const rules = (): Promise<Any[]> => m('/rules');
// A clean slate: reset keeps learned rules now, so tests that need none forget them first.
const clean = async () => { await forgetAll(); await reset(); };

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

test('reset keeps learned rules and reports them as rules_kept', async () => {
    await clean();
    const items = await open(await startRun());
    const fee = items.find(i => i.kind === 'bank_fee_missing_in_gl');
    const decided: Any = await decide(fee.id, { decision: 'approve', remember: true });
    assert.equal(typeof decided.rule_id, 'number');
    const first: Any = await reset();
    assert.equal(first.rules_kept, 1);
    assert.equal('rules_deleted' in first, false);
    assert.equal((await reset()).rules_kept, 1);
    assert.ok((await rules()).some(r => r.id === decided.rule_id && r.origin === 'learned'));
    // The next run after a reset still applies the kept rule.
    const run2 = await m('/runs/' + (await startRun()) + '/items');
    assert.ok((run2 as Any[]).some(i => i.rule_id === decided.rule_id && i.status === 'auto_resolved' && i.learnable === false));
    await clean();
});

test('rule_id is set only when approving a learnable item with remember', async () => {
    await clean();
    const items = await open(await startRun());
    const learnable = items.filter(i => i.learnable);
    const notLearnable = items.filter(i => !i.learnable);
    assert.ok(learnable.length >= 2 && notLearnable.length >= 1);
    assert.equal((await decide(learnable[0].id, { decision: 'approve', remember: false })).rule_id, null);
    assert.equal((await decide(learnable[1].id, { decision: 'reject', remember: true })).rule_id, null);
    assert.equal((await decide(notLearnable[0].id, { decision: 'approve', remember: true })).rule_id, null);
    assert.equal((await rules()).filter(r => r.origin === 'learned').length, 0);
    await clean();
});

test('DELETE /rules/{id} forgets a learned rule; 404 for unknown, 409 for seeded', async () => {
    await clean();
    const items = await open(await startRun());
    const { rule_id: id }: Any = await decide(items.find(i => i.learnable).id, { decision: 'approve', remember: true });
    assert.deepEqual(await forget(id), { rule_id: id });
    assert.equal((await rules()).some(r => r.id === id), false);
    await assert.rejects(forget(id), (e: Any) => e.code === 'rule_not_found' && e.status === 404);
    const seeded = (await rules()).find(r => r.origin === 'seeded');
    await assert.rejects(forget(seeded.id), (e: Any) => e.code === 'rule_not_deletable' && e.status === 409);
    assert.ok((await rules()).some(r => r.id === seeded.id));
    await clean();
});

test('DELETE /rules forgets learned rules only and counts them', async () => {
    await clean();
    const items = await open(await startRun());
    for (const i of items.filter(x => x.learnable)) await decide(i.id, { decision: 'approve', remember: true });
    const learned = (await rules()).filter(r => r.origin === 'learned').length;
    assert.ok(learned >= 1);
    assert.deepEqual(await forgetAll(), { rules_deleted: learned });
    const left = await rules();
    assert.ok(left.length > 0 && left.every(r => r.origin === 'seeded'));
    assert.deepEqual(await forgetAll(), { rules_deleted: 0 });
});

test('learning loop: remember the interest, run 2 starts at 845.00, the rest reach 0.00', async () => {
    await clean();
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
    await clean();
});

test('an unknown run is a 404 run_not_found on run, items and audit', async () => {
    for (const path of ['/runs/nope', '/runs/nope/items', '/runs/nope/audit'])
        await assert.rejects(m(path), (e: Any) => e.code === 'run_not_found' && e.status === 404, path);
});

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { QueryClient, QueryObserver } from '@tanstack/query-core';
import { keys, writeStatement } from '../src/api/keys.ts';

type S = { dataset: string; run_id: string | null; v: string };
const st = (dataset: string, run_id: string | null, v: string): S => ({ dataset, run_id, v });

test('writeStatement updates the live and own-run statements, not older runs or other datasets', () => {
    const client = new QueryClient();
    client.setQueryData(keys.statement('d1'), st('d1', 'run-2', 'old'));
    client.setQueryData(keys.statement('d1', 'run-2'), st('d1', 'run-2', 'old'));
    client.setQueryData(keys.statement('d1', 'run-1'), st('d1', 'run-1', 'old'));
    client.setQueryData(keys.statement('d2'), st('d2', 'run-9', 'old'));
    writeStatement(client, st('d1', 'run-2', 'new'));
    assert.equal((client.getQueryData(keys.statement('d1')) as S).v, 'new');
    assert.equal((client.getQueryData(keys.statement('d1', 'run-2')) as S).v, 'new');
    assert.equal((client.getQueryData(keys.statement('d1', 'run-1')) as S).v, 'old');
    assert.equal((client.getQueryData(keys.statement('d2')) as S).v, 'old');
});

test('a stale statement GET landing after the decision is corrected by the settle invalidation', async () => {
    const client = new QueryClient();
    const key = keys.statement('d1');
    let server = st('d1', 'run-1', 'before');
    let releaseStale!: () => void;
    const staleGate = new Promise<void>(r => { releaseStale = r; });
    let calls = 0;
    const queryFn = async () => { const snap = server; if (calls++ === 0) await staleGate; return snap; };
    client.setQueryData(key, st('d1', 'run-1', 'before'));
    const unsubscribe = new QueryObserver(client, { queryKey: key, queryFn, staleTime: Infinity }).subscribe(() => undefined); // the mounted statement card
    await client.cancelQueries({ queryKey: keys.statements });           // onMutate
    const stale = client.fetchQuery({ queryKey: key, queryFn, staleTime: 0 }); // effect-triggered GET while POST in flight
    server = st('d1', 'run-1', 'after');                                  // POST commits
    writeStatement(client, server);                                       // onSuccess
    releaseStale();
    await stale.catch(() => undefined);                                   // stale GET resolves with the old snapshot
    await client.invalidateQueries({ queryKey: keys.statements });        // onSettled
    unsubscribe();
    assert.equal((client.getQueryData(key) as S).v, 'after');
});

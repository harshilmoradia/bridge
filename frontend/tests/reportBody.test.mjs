// SSR test for ReportBody: loads the real component through Vite and renders it to a string.
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { createElement } from 'react';
import { renderToString } from 'react-dom/server';
import { createServer } from 'vite';

let server;
let ReportBody;
before(async () => {
    server = await createServer({ appType: 'custom', server: { middlewareMode: true, hmr: false, ws: false }, logLevel: 'silent' });
    ({ ReportBody } = await server.ssrLoadModule('/src/pages/Pages.tsx'));
});
after(async () => { await server?.close(); });

const run = (over = {}) => ({
    id: 'r1', dataset: 'd', period_start: '2026-10-01', period_end: '2026-10-31', status: 'completed', created_at: '', updated_at: '',
    steps: [], counts: {}, report: '## Report', error: null, ...over,
});
const html = r => renderToString(createElement(ReportBody, { run: r }));

test('a failed run with no report shows the error banner', () => {
    const out = html(run({ status: 'failed', report: null, error: { code: 'x', message: 'boom' } }));
    assert.match(out, /role="alert"/);
    assert.match(out, /boom/);
});
test('a failed run that still has a report shows the banner and the template note when the report step failed', () => {
    const out = html(run({ status: 'failed', error: { code: 'x', message: 'boom' }, steps: [{ agent: 'report', status: 'failed' }] }));
    assert.match(out, /boom/);
    assert.match(out, /Template report/);
});
test('no template note when the report step succeeded', () => {
    const out = html(run({ steps: [{ agent: 'report', status: 'completed' }] }));
    assert.doesNotMatch(out, /Template report/);
});

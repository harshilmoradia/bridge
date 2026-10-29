import assert from 'node:assert/strict';
import { test } from 'node:test';
import { reportView } from '../src/lib/report.ts';

test('queued and running runs wait for the report', () => {
    assert.equal(reportView({ status: 'running', report: null }), 'waiting');
    assert.equal(reportView({ status: 'queued', report: null }), 'waiting');
});
test('completed run shows the report, or empty when null or blank', () => {
    assert.equal(reportView({ status: 'completed', report: '## Hi' }), 'report');
    assert.equal(reportView({ status: 'completed', report: null }), 'empty');
    assert.equal(reportView({ status: 'completed', report: '  \n' }), 'empty');
});
test('failed run is an error', () => {
    assert.equal(reportView({ status: 'failed', report: null }), 'failed');
});
test('a report wins over failed status', () => {
    assert.equal(reportView({ status: 'failed', report: '## t' }), 'report');
    assert.equal(reportView({ status: 'failed', report: '  ' }), 'failed');
    assert.equal(reportView({ status: 'running', report: '## t' }), 'report');
});

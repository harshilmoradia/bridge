// Copies aggregate eval scores into src/generated/evalSummary.json for the /evals page.
// Run from frontend/: npm run sync-evals. Never reads evals/ground_truth.json, scenarios.md or source/.
import { readdirSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildSummary, isResultFile } from './evalExtract.mjs';

const here = dirname(fileURLToPath(import.meta.url));
// Optional results dir: first CLI argument, else $EVALS_DIR, else ../evals/results.
const resultsDir = process.argv[2] ?? process.env.EVALS_DIR ?? join(here, '..', '..', 'evals', 'results');
const out = join(here, '..', 'src', 'generated', 'evalSummary.json');

let files = [];
try {
    files = readdirSync(resultsDir).filter(isResultFile);
} catch {
    console.warn(`No results dir at ${resultsDir}; writing an empty summary.`);
}
const reports = files.flatMap(f => {
    try {
        return [{ file: f, report: JSON.parse(readFileSync(join(resultsDir, f), 'utf8')) }];
    } catch {
        console.warn(`Skipping unreadable ${f}`);
        return [];
    }
});
const summary = buildSummary(reports);
mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, JSON.stringify(summary, null, 2) + '\n');
console.log(`Wrote ${out}: ${Object.keys(summary.pipelines).join(', ') || 'no pipelines'}`);

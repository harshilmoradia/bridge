// Pure helpers for sync-evals.mjs. Reads eval result reports (evals/results/*.json) and keeps ONLY aggregate scores.
// Per-item fields (missed_truth_ids, kind_accuracy_by_kind, ...) are dropped on purpose: the output is committed.

const RATIOS = ['match_precision', 'match_recall', 'kind_accuracy', 'correct_escalations', 'entry_correctness'];

const isRatio = v => v !== null && typeof v === 'object' && Number.isInteger(v.hit) && Number.isInteger(v.total) && v.hit >= 0 && v.hit <= v.total
    && (v.total === 0
        // scoring.py reports value None (null) for an empty ratio; 0 is tolerated too.
        ? v.value === null || v.value === 0
        : typeof v.value === 'number' && Number.isFinite(v.value) && v.value >= 0 && v.value <= 1 && Math.abs(v.value - v.hit / v.total) <= 0.0001);
const num = v => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : null);
const int = v => (Number.isInteger(v) && v >= 0 ? v : null);
// Money stays a decimal string; numbers are rejected so no float ever stands in for money.
const dec = v => (typeof v === 'string' && /^-?\d+(\.\d+)?$/.test(v) ? v : null);

// Latency, tokens and cost may sit at the top level or inside `scores`, and may not exist yet.
const pick = (report, key) => report[key] ?? report.scores?.[key];

// Only timestamped result files are read, so other JSON in the directory is never opened.
export const RESULT_FILE = /^\d{8}T\d{6}Z-[a-z_]+\.json$/;
export const isResultFile = name => RESULT_FILE.test(name);

export function extractSummary(report) {
    const scores = report?.scores;
    if (typeof report?.pipeline !== 'string' || !scores) return null;
    const ratios = {};
    for (const key of RATIOS) {
        if (!isRatio(scores[key])) return null;
        const { hit, total, value } = scores[key];
        ratios[key] = { hit, total, value };
    }
    const falseAutos = Array.isArray(scores.false_auto_resolutions) ? scores.false_auto_resolutions.length : int(scores.false_auto_resolutions);
    const finalDifference = dec(scores.final_difference);
    if (falseAutos === null || finalDifference === null) return null;
    return {
        pipeline: report.pipeline,
        created_at: String(report.created_at ?? ''),
        dataset: String(report.dataset ?? ''),
        git_sha: String(report.git_sha ?? ''),
        ...ratios,
        false_auto_resolutions: falseAutos,
        final_difference: finalDifference,
        difference_after_approvals: dec(scores.difference_after_approvals),
        expected_difference: dec(scores.expected_difference),
        latency_ms: num(pick(report, 'latency_ms')),
        tokens_in: int(pick(report, 'tokens_in')),
        tokens_out: int(pick(report, 'tokens_out')),
        cost_usd: dec(pick(report, 'cost_usd')),
        calls: int(pick(report, 'calls')),
        // null when the report predates the field; the page then falls back to a static guess.
        price_placeholder_tiers: Array.isArray(report.price_placeholder_tiers) && report.price_placeholder_tiers.every(t => typeof t === 'string') ? [...report.price_placeholder_tiers] : null,
    };
}

// Latest result per pipeline by parsed created_at. Reports with an unparseable date are skipped; ties break by filename.
// Input: [{ file, report }]. Pipelines live in a prototype-less map so names like __proto__ stay plain keys.
export function buildSummary(entries) {
    const best = Object.create(null);
    for (const { file, report } of entries) {
        const s = extractSummary(report);
        if (!s) continue;
        const t = Date.parse(s.created_at);
        if (Number.isNaN(t)) continue;
        const prev = best[s.pipeline];
        if (!prev || t > prev.t || (t === prev.t && String(file) > prev.file)) best[s.pipeline] = { t, file: String(file), s };
    }
    const pipelines = Object.create(null);
    for (const [name, { s }] of Object.entries(best)) {
        delete s.pipeline;
        pipelines[name] = s;
    }
    return { pipelines };
}

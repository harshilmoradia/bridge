// API v1 shapes (docs/architecture.md "API v1"). Money is always a decimal string; never parse it to a float.
// Matches docs/fixtures/ (Ben, v1).

export type Money = string;

export type ReconStatus =
    | 'matched' | 'auto_resolved' | 'reconciling_item' | 'needs_approval' | 'approved' | 'rejected' | 'unmatched';

export interface Dataset { id: string; label: string; period_start: string; period_end: string }

// Computed server-side with the same masking and injection check the agents' prompts use.
export interface Guardrail {
    injection_flagged: boolean; pii_masked: boolean; sent_to_model: string; sent_counterparty: string | null;
}

export interface BankTransaction {
    txn_id: string; posted_date: string; description: string; amount: Money; type: string;
    check_number: string | null; running_balance: Money | null;
    recon_status: ReconStatus; item_id: string | null; guardrail: Guardrail;
}

export interface GlEntry {
    entry_id: string; date: string; description: string; amount: Money; method: string;
    check_number: string | null; account: string; counter_account: string; counterparty: string | null;
    recon_status: ReconStatus; item_id: string | null; guardrail: Guardrail;
}

export interface StatementLine {
    item_id: string; kind: string; label: string; amount: Money; status: ReconStatus; applied: boolean;
    bank_ids: string[]; gl_ids: string[];
}

export interface StatementSide { closing_balance: Money; lines: StatementLine[]; adjusted_balance: Money }

export interface Statement {
    dataset: string; run_id: string | null; company: string; cash_account: string; period_start: string; period_end: string;
    raw_difference: Money; bank: StatementSide; book: StatementSide; unreconciled_difference: Money;
}

export type RunStatus = 'queued' | 'running' | 'completed' | 'failed';
export type StepStatus = 'pending' | 'running' | 'completed' | 'failed';
export type ModelTier = 'code' | 'nano' | 'super' | 'ultra';

export interface ApiErrorBody { code: string; message: string }

// Steps sharing a `position` run in parallel.
export interface RunStep {
    id: string; position: number; agent: string; label: string; tier: ModelTier; model: string | null; status: StepStatus;
    started_at: string | null; finished_at: string | null; latency_ms: number | null;
    tokens_in: number | null; tokens_out: number | null; output_summary: string | null; error: ApiErrorBody | null;
}

export interface RunCounts {
    bank_transactions: number; gl_entries: number; items: number; matched: number; auto_resolved: number;
    reconciling_item: number; needs_approval: number; approved: number; rejected: number; unmatched: number;
}

export interface Run {
    id: string; dataset: string; period_start: string; period_end: string; status: RunStatus;
    created_at: string; updated_at: string; steps: RunStep[]; counts: RunCounts;
    report: string | null; error: ApiErrorBody | null;
}

export interface CreateRunRequest { dataset: string; period_start: string; period_end: string }
export interface CreateRunResponse { id: string; status: RunStatus }

export interface ProposedEntry {
    id: string; debit_account: string; credit_account: string; amount: Money; memo: string; status: string;
}
export interface EvidenceRef { type: string; id: string; note: string | null }

export interface Item {
    id: string; run_id: string; kind: string; resolution: string; status: ReconStatus;
    bank_ids: string[]; gl_ids: string[]; amount_delta: Money; reasoning: string; evidence: EvidenceRef[];
    flags: string[]; model: string | null; confidence: number | null; rule_id: number | null;
    proposed_entry: ProposedEntry | null; created_at: string;
}

export interface DecisionRequest {
    decision: 'approve' | 'reject'; entry_override?: Partial<Pick<ProposedEntry, 'debit_account' | 'credit_account' | 'amount' | 'memo'>>;
    remember: boolean; note: string | null;
}
export interface DemoResetResponse { dataset: string; runs_deleted: number; rules_deleted: number }

export interface DecisionResponse { item: Item; statement: Statement }

export interface Rule {
    id: number; kind: string; pattern: Record<string, unknown>; action: Record<string, unknown>;
    source_item: string | null; created_by: string; active: boolean; created_at: string;
    dataset?: string | null; origin?: string | null;
}

export interface RangeParams { dataset: string; from?: string; to?: string }

// One audit_log row, from GET /runs/{id}/audit (oldest first).
export type AuditEntityType = 'run' | 'item' | 'entry' | 'rule' | 'guardrail' | 'dataset';
export interface AuditEntry {
    id: number; run_id: string | null; entity_type: AuditEntityType; entity_id: string | null;
    action: string; actor: string; model: string | null; detail: Record<string, unknown>; created_at: string;
}

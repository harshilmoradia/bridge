import { useRef, useState, type FormEvent } from 'react';
import { Link } from 'react-router';
import { ArrowUpRight, Bot, LoaderCircle, MessageSquareText, RotateCcw, Send, UserRound } from 'lucide-react';
import { toast } from 'sonner';
import { useDatasets, useRagChat } from '../api/hooks';
import type { Dataset, RagChatRequest, RagChatSource } from '../api/types';
import { GuardrailCallouts } from '../components/recon/GuardrailCallouts';
import { StatusChip } from '../components/StatusChip';
import { Money } from '../components/Money';
import { QueryState } from '../components/QueryState';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '../components/ui/card';
import { Page } from './Pages';

interface Turn {
    id: string;
    question: string;
    answer?: string;
    sources?: RagChatSource[];
    citations?: string[];
    noEvidence?: boolean;
    model?: string;
    error?: string;
}

const inputClass = 'min-h-24 w-full resize-y rounded-lg border bg-background px-3 py-2.5 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60';
const selectClass = 'h-9 rounded-md border bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

function ChatSourceCard({ source, dataset }: { source: RagChatSource; dataset: string }) {
    const item = source.item;
    const counterparty = source.counterparty;
    return (
        <Card size="sm" data-testid="chat-source-card" className="min-w-0">
            <CardHeader className="gap-2 border-b pb-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                        <CardTitle className="flex flex-wrap items-center gap-2">
                            <span className="font-mono text-sm">{source.source_id}</span>
                            <StatusChip status={source.status} />
                        </CardTitle>
                        <p className="mt-1 text-xs text-muted-foreground">
                            {source.source_type === 'bank_transaction' ? 'Bank transaction' : 'Ledger entry'} · {source.date}
                        </p>
                    </div>
                    <Money value={source.amount} className="text-right text-sm font-semibold" />
                </div>
                <p className="break-words text-sm leading-relaxed">{source.description}</p>
                <GuardrailCallouts
                    guardrail={source.guardrail}
                    original={{ description: source.description, counterparty }}
                />
            </CardHeader>
            <CardContent className="grid gap-x-4 gap-y-2 py-3 text-xs sm:grid-cols-2">
                <p><span className="text-muted-foreground">{source.source_type === 'bank_transaction' ? 'Type' : 'Method'}:</span> {source.type}</p>
                {source.check_number && <p><span className="text-muted-foreground">Check:</span> {source.check_number}</p>}
                {source.running_balance && <p><span className="text-muted-foreground">Running balance:</span> <Money value={source.running_balance} /></p>}
                {source.account && <p><span className="text-muted-foreground">Account:</span> <span className="font-mono">{source.account}</span></p>}
                {source.counter_account && <p><span className="text-muted-foreground">Counter account:</span> <span className="font-mono">{source.counter_account}</span></p>}
                {counterparty && <p className="break-words"><span className="text-muted-foreground">Counterparty:</span> {counterparty}</p>}
                <p className="flex flex-wrap gap-1 sm:col-span-2">
                    {source.matched_by.map(method => <span key={method} className="rounded-full border px-2 py-0.5 text-[10px] font-medium text-muted-foreground">{method === 'full_text' ? 'Keyword' : method === 'vector' ? 'Meaning' : 'Exact'}</span>)}
                </p>
                {item && (
                    <div className="space-y-1 rounded-md bg-muted/50 p-2 sm:col-span-2">
                        <p className="font-semibold">{item.kind.replaceAll('_', ' ')}</p>
                        <p className="text-muted-foreground">Current item status: {item.status.replaceAll('_', ' ')}</p>
                        {item.proposed_entry && (
                            <p className="break-words text-muted-foreground">
                                Draft entry · DR <span className="font-mono">{item.proposed_entry.debit_account}</span>
                                {' / '}CR <span className="font-mono">{item.proposed_entry.credit_account}</span>
                                {' · '}<Money value={item.proposed_entry.amount} /> · {item.proposed_entry.memo}
                            </p>
                        )}
                    </div>
                )}
            </CardContent>
            {item?.status === 'needs_approval' && (
                <CardFooter className="justify-end">
                    <Button asChild size="sm" variant="outline">
                        <Link to={`/reconcile?dataset=${encodeURIComponent(dataset)}&itemId=${encodeURIComponent(item.id)}`}>
                            Review in approvals <ArrowUpRight aria-hidden="true" />
                        </Link>
                    </Button>
                </CardFooter>
            )}
        </Card>
    );
}

function Conversation({ turns, busy, dataset, onRetry }: { turns: Turn[]; busy: boolean; dataset: string; onRetry: (turn: Turn) => void }) {
    const logRef = useRef<HTMLDivElement>(null);
    if (turns.length === 0 && !busy) {
        return (
            <div className="grid min-h-64 place-items-center rounded-lg border border-dashed bg-card px-6 py-10 text-center">
                <div className="flex max-w-lg flex-col items-center gap-2">
                    <span className="grid size-10 place-items-center rounded-full bg-primary-soft text-primary"><MessageSquareText className="size-5" aria-hidden="true" /></span>
                    <h2 className="font-semibold">Ask about your transactions</h2>
                    <p className="text-sm text-muted-foreground">Search by meaning, exact ID, amount, date, or approval status. Results include current source records and a link to the existing review flow.</p>
                </div>
            </div>
        );
    }
    return (
        <div ref={logRef} role="log" aria-live="polite" aria-label="Bridge chat conversation" className="space-y-5">
            {turns.map(turn => (
                <div key={turn.id} className="space-y-3" data-testid="chat-turn">
                    <div className="ml-auto flex max-w-[85%] items-start justify-end gap-2.5">
                        <p className="rounded-2xl rounded-tr-sm bg-primary px-4 py-3 text-sm text-primary-foreground">{turn.question}</p>
                        <span className="grid size-8 shrink-0 place-items-center rounded-full border bg-card"><UserRound className="size-4" aria-hidden="true" /></span>
                    </div>
                    {(turn.answer || turn.error) && (
                        <div className="flex items-start gap-2.5">
                            <span className="grid size-8 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground"><Bot className="size-4" aria-hidden="true" /></span>
                            <div className="min-w-0 flex-1 space-y-3">
                                <div className={turn.error ? 'rounded-xl border border-destructive/40 bg-destructive-soft p-3 text-sm text-destructive' : 'rounded-xl rounded-tl-sm border bg-card p-3 text-sm leading-relaxed'}>
                                    <p>{turn.error ?? turn.answer}</p>
                                    {turn.error && <Button variant="ghost" size="sm" className="mt-1" onClick={() => onRetry(turn)}><RotateCcw aria-hidden="true" />Try again</Button>}
                                </div>
                                {turn.noEvidence && <p className="text-xs text-muted-foreground">No source cards were returned; Bridge does not guess when it cannot retrieve evidence.</p>}
                                {turn.sources && turn.sources.length > 0 && (
                                    <div className="grid gap-3 lg:grid-cols-2">
                                        {turn.sources.map(source => <ChatSourceCard key={`${source.source_type}:${source.source_id}`} source={source} dataset={dataset} />)}
                                    </div>
                                )}
                                {turn.citations && turn.citations.length > 0 && (
                                    <p className="text-xs text-muted-foreground">Cited records: {turn.citations.join(', ')}</p>
                                )}
                                {turn.model && <p className="text-right text-[10px] text-muted-foreground">{turn.model}</p>}
                            </div>
                        </div>
                    )}
                </div>
            ))}
            {busy && <p role="status" className="flex items-center gap-2 pl-10 text-sm text-muted-foreground"><LoaderCircle className="size-4 animate-spin" aria-hidden="true" />Searching current records…</p>}
        </div>
    );
}

function ChatWorkspace({ datasets }: { datasets: Dataset[] }) {
    const [datasetId, setDatasetId] = useState(datasets[0].id);
    const dataset = datasets.find(entry => entry.id === datasetId) ?? datasets[0];
    const [status, setStatus] = useState('');
    const [sourceType, setSourceType] = useState('');
    const [dateFrom, setDateFrom] = useState('');
    const [dateTo, setDateTo] = useState('');
    const [amount, setAmount] = useState('');
    const [question, setQuestion] = useState('');
    const [turns, setTurns] = useState<Turn[]>([]);
    const chat = useRagChat();
    const busy = chat.isPending;

    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const value = question.trim();
        if (!value || busy) return;
        const id = crypto.randomUUID();
        const previous = turns;
        setQuestion('');
        setTurns(list => [...list, { id, question: value }]);
        const body: RagChatRequest = {
            dataset: dataset.id,
            question: value,
            history: previous.flatMap(turn => turn.answer
                ? [{ role: 'user' as const, content: turn.question }, { role: 'assistant' as const, content: turn.answer }]
                : []).slice(-6),
            ...(status ? { status: status as RagChatRequest['status'] } : {}),
            ...(sourceType ? { source_type: sourceType as RagChatRequest['source_type'] } : {}),
            ...(dateFrom ? { date_from: dateFrom } : {}),
            ...(dateTo ? { date_to: dateTo } : {}),
            ...(amount ? { amount } : {}),
        };
        chat.mutate(body, {
            onSuccess: response => setTurns(list => list.map(turn => turn.id === id
                ? { ...turn, answer: response.message.content, sources: response.sources, citations: response.citations, noEvidence: response.no_evidence, model: response.model }
                : turn)),
            onError: error => {
                toast.error(error.message);
                setTurns(list => list.map(turn => turn.id === id ? { ...turn, error: error.message } : turn));
            },
        });
    };

    const retry = (turn: Turn) => {
        setTurns(list => list.filter(entry => entry.id !== turn.id));
        setQuestion(turn.question);
    };

    const clear = () => {
        setTurns([]);
        setQuestion('');
        chat.reset();
    };

    return (
        <Page title="Ask Bridge" subtitle="Search bank and ledger records by meaning, exact details, or current review status.">
            <div className="flex flex-wrap items-end gap-2 rounded-lg border bg-card p-3">
                {datasets.length > 1 && <label className="flex flex-col gap-1 text-xs text-muted-foreground">Dataset
                    <select className={selectClass} value={dataset.id} onChange={event => { setDatasetId(event.target.value); clear(); }}>
                        {datasets.map(entry => <option key={entry.id} value={entry.id}>{entry.label}</option>)}
                    </select>
                </label>}
                <label className="flex flex-col gap-1 text-xs text-muted-foreground">Record type
                    <select className={selectClass} value={sourceType} onChange={event => setSourceType(event.target.value)}>
                        <option value="">Bank + ledger</option><option value="bank_transaction">Bank only</option><option value="gl_entry">Ledger only</option>
                    </select>
                </label>
                <label className="flex flex-col gap-1 text-xs text-muted-foreground">Review status
                    <select className={selectClass} value={status} onChange={event => setStatus(event.target.value)}>
                        <option value="">Any status</option><option value="needs_approval">Needs approval</option>
                        <option value="approved">Approved</option><option value="rejected">Rejected</option>
                        <option value="unmatched">Unmatched</option><option value="auto_resolved">Auto-resolved</option>
                        <option value="matched">Matched</option><option value="reconciling_item">Reconciling item</option>
                    </select>
                </label>
                <label className="flex flex-col gap-1 text-xs text-muted-foreground">From date
                    <input type="date" className={selectClass} value={dateFrom} max={dateTo || undefined} onChange={event => setDateFrom(event.target.value)} />
                </label>
                <label className="flex flex-col gap-1 text-xs text-muted-foreground">To date
                    <input type="date" className={selectClass} value={dateTo} min={dateFrom || undefined} onChange={event => setDateTo(event.target.value)} />
                </label>
                <label className="flex flex-col gap-1 text-xs text-muted-foreground">Exact amount
                    <input type="text" inputMode="decimal" className={`${selectClass} w-28`} value={amount} placeholder="-25.00" onChange={event => setAmount(event.target.value)} />
                </label>
                <span className="flex-1" />
                <Button variant="outline" disabled={busy && turns.length === 0} onClick={clear}><RotateCcw aria-hidden="true" />Clear chat</Button>
            </div>

            <Conversation turns={turns} busy={busy} dataset={dataset.id} onRetry={retry} />

            <Card>
                <CardContent className="space-y-2 pt-4">
                    <form onSubmit={submit} className="space-y-2">
                        <label htmlFor="bridge-question" className="text-xs font-medium text-muted-foreground">Your question</label>
                        <textarea id="bridge-question" className={inputClass} value={question} maxLength={500}
                            disabled={busy} onChange={event => setQuestion(event.target.value)}
                            placeholder="e.g. Which service charges still need review?" />
                        <div className="flex flex-wrap items-center gap-2">
                            <p className="mr-auto text-[11px] text-muted-foreground">PII is screened before model calls. Bridge returns source records and never approves from chat.</p>
                            <span className="text-xs tabular-nums text-muted-foreground">{question.length}/500</span>
                            <Button type="submit" disabled={!question.trim() || busy}><Send aria-hidden="true" />Ask Bridge</Button>
                        </div>
                    </form>
                    <div className="flex flex-wrap gap-1.5" aria-label="Example questions">
                        {['What bank fees need review?', 'Find transaction BANK074', 'Show unmatched payroll entries'].map(example => (
                            <button key={example} type="button" disabled={busy} onClick={() => setQuestion(example)}
                                className="rounded-full border px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted disabled:opacity-50">{example}</button>
                        ))}
                    </div>
                </CardContent>
            </Card>
            <div className="sr-only" aria-live="polite">{busy ? 'Bridge is searching.' : chat.isSuccess ? 'Answer received.' : ''}</div>
        </Page>
    );
}

export function ChatPage() {
    const datasets = useDatasets();
    return (
        <QueryState query={datasets} isEmpty={list => list.length === 0} emptyMessage="No datasets are available to search.">
            {list => <ChatWorkspace datasets={list} />}
        </QueryState>
    );
}

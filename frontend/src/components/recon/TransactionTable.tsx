import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react';
import { distinct, emptyFilters, filterRows, sortRows, trimSelection, type SortKey, type SortState, type TableFilters, type TxRow } from '../../lib/tableModel';
import { StatusChip } from '../StatusChip';
import { STATUS_LABEL } from '../../lib/statusLabel';
import { Money } from '../Money';
import { GuardrailCallouts } from './GuardrailCallouts';
import { Button } from '../ui/button';
import { cn } from '../../lib/utils';
import type { ReconStatus } from '../../api/types';

const field = 'h-8 rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';
const STATUSES = Object.keys(STATUS_LABEL) as ReconStatus[];

const COLUMNS: { key: SortKey; label: string; align?: 'right' }[] = [
    { key: 'date', label: 'Date' }, { key: 'description', label: 'Description' }, { key: 'type', label: 'Type' },
    { key: 'amount', label: 'Amount', align: 'right' }, { key: 'status', label: 'Status' },
];

interface Props {
    rows: TxRow[];
    typeLabel?: string; // heading of the type/method filter
    selectable?: boolean;
    onSelectionChange?: (ids: string[]) => void;
    highlightItemId?: string | null; // rows sharing this item_id are tinted (U-05 builds on it)
    onRowClick?: (row: TxRow) => void;
}

// Sortable, filterable transaction list. Rows are already display-shaped (see lib/tableModel.ts).
export function TransactionTable({ rows, typeLabel = 'Type', selectable = true, onSelectionChange, highlightItemId, onRowClick }: Props) {
    const [filters, setFilters] = useState<TableFilters>(emptyFilters);
    const [sort, setSort] = useState<SortState>({ key: 'date', dir: 'asc' });
    const [chosen, setSelected] = useState<ReadonlySet<string>>(new Set());

    const types = useMemo(() => distinct(rows.map(r => r.type)), [rows]);
    const visible = useMemo(() => sortRows(filterRows(rows, filters), sort), [rows, filters, sort]);
    const selected = useMemo(() => trimSelection(chosen, visible), [chosen, visible]);
    const selectAllRef = useRef<HTMLInputElement>(null);
    useEffect(() => { if (selectAllRef.current) selectAllRef.current.indeterminate = selected.size > 0 && selected.size < visible.length; }, [selected, visible]);
    // Filter changes also trim the selection, so hidden rows are never counted or reported.
    const applyFilters = (next: TableFilters) => {
        setFilters(next);
        const keep = trimSelection(chosen, filterRows(rows, next));
        if (keep.size !== chosen.size) { setSelected(keep); onSelectionChange?.([...keep]); }
    };
    const set = (patch: Partial<TableFilters>) => applyFilters({ ...filters, ...patch });
    const filtered = JSON.stringify(filters) !== JSON.stringify(emptyFilters);

    const commit = (next: Set<string>) => { setSelected(next); onSelectionChange?.([...next]); };
    const toggle = (id: string) => { const next = new Set(selected); if (!next.delete(id)) next.add(id); commit(next); };
    const allVisible = visible.length > 0 && visible.every(r => selected.has(r.id));
    const toggleAll = () => {
        const next = new Set(selected);
        for (const r of visible) { if (allVisible) next.delete(r.id); else next.add(r.id); }
        commit(next);
    };
    const sortBy = (key: SortKey) => setSort(s => ({ key, dir: s.key === key && s.dir === 'asc' ? 'desc' : 'asc' }));

    return (
        <div className="space-y-3">
            <div className="flex flex-wrap items-end gap-3" role="search">
                <input type="search" aria-label="Search" placeholder="Search description, amount, id..." value={filters.search}
                    onChange={e => set({ search: e.target.value })} className={cn(field, 'w-64')} />
                <label className="flex flex-col text-xs text-muted-foreground">From
                    <input type="date" value={filters.from} max={filters.to || undefined} onChange={e => set({ from: e.target.value })} className={field} />
                </label>
                <label className="flex flex-col text-xs text-muted-foreground">To
                    <input type="date" value={filters.to} min={filters.from || undefined} onChange={e => set({ to: e.target.value })} className={field} />
                </label>
                <label className="flex flex-col text-xs text-muted-foreground">{typeLabel}
                    <select value={filters.type} onChange={e => set({ type: e.target.value })} className={field}>
                        <option value="">All</option>{types.map(t => <option key={t} value={t}>{t}</option>)}
                    </select>
                </label>
                <label className="flex flex-col text-xs text-muted-foreground">Status
                    <select value={filters.status} onChange={e => set({ status: e.target.value })} className={field}>
                        <option value="">All</option>{STATUSES.map(s => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
                    </select>
                </label>
                {filtered && <Button variant="ghost" size="sm" onClick={() => applyFilters(emptyFilters)}>Clear filters</Button>}
                <p className="ml-auto text-xs text-muted-foreground" aria-live="polite">
                    {visible.length} of {rows.length} rows{selected.size > 0 && ` · ${selected.size} selected`}
                </p>
            </div>

            <div className="max-h-[70vh] overflow-auto rounded-lg border">
                <table className="w-full caption-bottom text-sm">
                    <thead className="sticky top-0 z-10 bg-muted text-left shadow-[0_1px_0_var(--color-border)]">
                        <tr>
                            {selectable && (
                                <th className="w-10 px-2">
                                    <input type="checkbox" ref={selectAllRef} aria-label="Select all visible rows" checked={allVisible} disabled={visible.length === 0} onChange={toggleAll} />
                                </th>
                            )}
                            {COLUMNS.map(col => {
                                const active = sort.key === col.key;
                                const Icon = !active ? ArrowUpDown : sort.dir === 'asc' ? ArrowUp : ArrowDown;
                                return (
                                    <th key={col.key} className={cn('h-10 px-2 font-medium', col.align === 'right' && 'text-right')}
                                        aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                                        <button type="button" onClick={() => sortBy(col.key)} className={cn('inline-flex items-center gap-1 hover:text-foreground', !active && 'text-muted-foreground')}>
                                            {col.label}<Icon className="size-3" aria-hidden="true" />
                                        </button>
                                    </th>
                                );
                            })}
                        </tr>
                    </thead>
                    <tbody>
                        {visible.map(r => (
                            <tr key={r.id} data-row-id={r.id} aria-selected={selected.has(r.id)} onClick={() => onRowClick?.(r)}
                                tabIndex={onRowClick ? 0 : undefined}
                                onKeyDown={onRowClick ? e => { if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onRowClick(r); } } : undefined}
                                className={cn('border-t hover:bg-muted/50', onRowClick && 'cursor-pointer',
                                    selected.has(r.id) && 'bg-muted/70', highlightItemId && r.itemId === highlightItemId && 'bg-primary/10')}>
                                {selectable && (
                                    <td className="px-2" onClick={e => e.stopPropagation()}>
                                        <input type="checkbox" aria-label={`Select ${r.id}`} checked={selected.has(r.id)} onChange={() => toggle(r.id)} />
                                    </td>
                                )}
                                <td className="whitespace-nowrap p-2 tabular-nums">{r.date}</td>
                                {/* Descriptions are untrusted text: rendered as text only, never HTML. */}
                                <td className="max-w-md p-2">
                                    <span className="line-clamp-2">{r.description}</span>
                                    <span className="text-xs text-muted-foreground">{r.id}{r.extra && ` · ${r.extra}`}</span>
                                    <GuardrailCallouts guardrail={r.guardrail} original={r.original} />
                                </td>
                                <td className="p-2">{r.type}</td>
                                <td className="p-2 text-right"><Money value={r.amount} /></td>
                                <td className="p-2"><StatusChip status={r.status} /></td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                {visible.length === 0 && (
                    <p className="p-6 text-center text-sm text-muted-foreground">
                        {rows.length === 0 ? 'No transactions.' : 'No rows match these filters.'}
                    </p>
                )}
            </div>
        </div>
    );
}

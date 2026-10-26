import type { ReactNode } from 'react';
import type { UseQueryResult } from '@tanstack/react-query';
import { Skeleton } from './ui/skeleton';
import { Button } from './ui/button';

interface QueryStateProps<T> {
    query: UseQueryResult<T>;
    isEmpty?: (data: T) => boolean;
    emptyMessage?: string;
    children: (data: T) => ReactNode;
}

// One place for the loading, error and empty states every data view needs.
export function QueryState<T>({ query, isEmpty, emptyMessage = 'Nothing to show yet.', children }: QueryStateProps<T>) {
    if (query.isPending) {
        return (
            <div role="status" aria-label="Loading" className="space-y-2">
                <Skeleton className="h-8 w-full" /><Skeleton className="h-8 w-full" /><Skeleton className="h-8 w-2/3" />
            </div>
        );
    }
    if (query.isError) {
        return (
            <div role="alert" className="rounded-lg border border-destructive/40 p-4 text-sm">
                <p className="font-medium text-destructive">{query.error instanceof Error ? query.error.message : 'Something went wrong.'}</p>
                <Button variant="outline" size="sm" className="mt-3" onClick={() => void query.refetch()}>Try again</Button>
            </div>
        );
    }
    if (isEmpty?.(query.data)) return <p className="text-sm text-muted-foreground">{emptyMessage}</p>;
    return <>{children(query.data)}</>;
}

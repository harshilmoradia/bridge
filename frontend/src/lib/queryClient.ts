import { QueryClient } from '@tanstack/react-query';
import { ApiError } from '../api/http';

// Client errors (4xx) will not change on retry, so surface them immediately.
const retry = (count: number, error: Error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 1;

export const queryClient = new QueryClient({
    defaultOptions: { queries: { staleTime: 30_000, retry, refetchOnWindowFocus: false } },
});

export class ApiError extends Error {
    readonly code: string;
    readonly status: number;
    constructor(code: string, message: string, status: number) {
        super(message);
        this.name = 'ApiError';
        this.code = code;
        this.status = status;
    }
}

export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true';
const BASE = `${(import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')}/api/v1`;

export type Query = Record<string, string | undefined>;

export function withQuery(path: string, query?: Query): string {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query ?? {})) if (value) params.set(key, value);
    const text = params.toString();
    return text ? `${path}?${text}` : path;
}

export interface RequestOptions { method?: 'GET' | 'POST'; query?: Query; body?: unknown; signal?: AbortSignal }

// Errors from the backend look like {"detail": {"code", "message"}}.
async function toApiError(response: Response): Promise<ApiError> {
    try {
        const payload: unknown = await response.json();
        const detail = typeof payload === 'object' && payload !== null && 'detail' in payload ? payload.detail : null;
        if (typeof detail === 'object' && detail !== null && 'code' in detail && 'message' in detail) {
            return new ApiError(String(detail.code), String(detail.message), response.status);
        }
    } catch { /* body was not JSON */ }
    return new ApiError('http_error', `Request failed (${response.status})`, response.status);
}

export async function liveRequest<T>(path: string, { method = 'GET', query, body, signal }: RequestOptions = {}): Promise<T> {
    let response: Response;
    try {
        response = await fetch(BASE + withQuery(path, query), {
            method, signal,
            headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
            body: body === undefined ? undefined : JSON.stringify(body),
        });
    } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') throw error;
        throw new ApiError('network_error', 'Could not reach the server.', 0);
    }
    if (!response.ok) throw await toApiError(response);
    return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

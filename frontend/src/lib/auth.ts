export type AuthMode = 'login' | 'signup' | 'reset' | 'update';

export interface Identity {
    id: string;
    email: string;
    displayName: string;
    isDemo: boolean;
}

export interface AuthFields {
    email: string;
    password: string;
    confirmPassword: string;
    displayName: string;
}

export function validateAuthFields(mode: AuthMode, fields: AuthFields): string | null {
    if (mode !== 'update' && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(fields.email.trim())) return 'Enter a valid email address.';
    if (mode === 'signup' && (!fields.displayName.trim() || fields.displayName.trim().length > 100)) return 'Enter a name between 1 and 100 characters.';
    if (mode === 'login' && !fields.password) return 'Enter your password.';
    if (mode === 'signup' || mode === 'update') {
        if (fields.password.length < 12) return 'Use a password with at least 12 characters.';
        if (fields.password !== fields.confirmPassword) return 'Passwords do not match.';
    }
    return null;
}

// Only a publishable key or legacy anon key belongs in a browser bundle.
export function isPublicSupabaseKey(key: string): boolean {
    if (key.startsWith('sb_publishable_')) return key.length > 'sb_publishable_'.length;
    try {
        const payload = key.split('.')[1];
        if (!payload) return false;
        const claims: unknown = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')));
        return typeof claims === 'object' && claims !== null && 'role' in claims && claims.role === 'anon';
    } catch { return false; }
}

export function isSupabaseUrl(value: string): boolean {
    try {
        const parsed = new URL(value);
        if (parsed.username || parsed.password || parsed.search || parsed.hash || (parsed.pathname !== '/' && parsed.pathname !== '')) return false;
        return parsed.protocol === 'https:' || (parsed.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(parsed.hostname));
    } catch { return false; }
}

export function getInitials(name: string): string {
    const words = name.trim().split(/\s+/).filter(Boolean);
    return (words.length > 1 ? words[0][0] + words[words.length - 1][0] : (words[0] || 'AC').slice(0, 2)).toUpperCase();
}

export type Profile = {
    id: string;
    display_name: string;
    created_at: string;
    updated_at: string;
};

export interface Database {
    public: {
        Tables: {
            profiles: {
                Row: Profile;
                Insert: { id: string; display_name: string; created_at?: string; updated_at?: string };
                Update: { display_name?: string };
                Relationships: [];
            };
        };
        Views: Record<string, never>;
        Functions: Record<string, never>;
        Enums: Record<string, never>;
        CompositeTypes: Record<string, never>;
    };
}

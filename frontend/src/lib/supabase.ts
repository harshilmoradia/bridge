import { createClient } from '@supabase/supabase-js';
import { isPublicSupabaseKey, isSupabaseUrl, type Database } from './auth';

const url = import.meta.env.VITE_SUPABASE_URL?.trim() || '';
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY?.trim() || '';

// Keep auth usable for this tab if the browser blocks persistent storage.
const memoryStorage = new Map<string, string>();
let storageBlocked = false;
const storage = {
    getItem(name: string): string | null {
        if (storageBlocked) return memoryStorage.get(name) ?? null;
        try { return localStorage.getItem(name); }
        catch { storageBlocked = true; return memoryStorage.get(name) ?? null; }
    },
    setItem(name: string, value: string) {
        memoryStorage.set(name, value);
        try { localStorage.setItem(name, value); } catch { storageBlocked = true; }
    },
    removeItem(name: string) {
        memoryStorage.delete(name);
        try { localStorage.removeItem(name); } catch { /* Storage is blocked. */ }
    },
};

export const supabase = isSupabaseUrl(url) && isPublicSupabaseKey(key)
    ? createClient<Database>(url, key, {
        auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true, flowType: 'implicit', storage },
    })
    : null;

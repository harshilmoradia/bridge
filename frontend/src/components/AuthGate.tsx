import { useEffect, useState, type ReactNode } from 'react';
import type { Session } from '@supabase/supabase-js';
import { AuthShell, LoginScreen } from './LoginScreen';
import { supabase } from '../lib/supabase';
import type { AuthFields, AuthMode, Identity, Profile } from '../lib/auth';

function clearRecoveryUrl() {
    const url = new URL(window.location.href);
    url.searchParams.delete('auth');
    window.history.replaceState(null, '', url.pathname + url.search + url.hash);
}

function authError(error: unknown): string {
    const code = typeof error === 'object' && error !== null && 'code' in error ? error.code : '';
    if (code === 'invalid_credentials') return 'Email or password is incorrect.';
    if (code === 'email_not_confirmed') return 'Confirm your email before signing in.';
    if (code === 'over_email_send_rate_limit' || code === 'over_request_rate_limit') return 'Too many attempts. Please wait before trying again.';
    if (code === 'weak_password') return 'Choose a stronger password and try again.';
    if (code === 'same_password') return 'Choose a password different from your current password.';
    return 'We couldn’t complete that request. Please try again.';
}

interface AuthGateProps {
    children: (identity: Identity, signOut: () => Promise<void>, signingOut: boolean) => ReactNode;
}

export function AuthGate({ children }: AuthGateProps) {
    const [session, setSession] = useState<Session | null>(null);
    const [loading, setLoading] = useState(Boolean(supabase));
    const [busy, setBusy] = useState(false);
    const [demo, setDemo] = useState(false);
    const [mode, setMode] = useState<AuthMode>('login');
    const [recovering, setRecovering] = useState(false);
    const [error, setError] = useState(() => new URLSearchParams(window.location.hash.slice(1)).has('error') ? 'This email link is invalid or has expired. Please request a new link.' : '');
    const [notice, setNotice] = useState('');
    const [profileResult, setProfileResult] = useState<{ userId: string; attempt: number; data: Profile | null; failed: boolean } | null>(null);
    const [profileAttempt, setProfileAttempt] = useState(0);

    useEffect(() => {
        const client = supabase;
        if (!client) return;
        let active = true;
        const recoveryRequested = new URLSearchParams(window.location.search).get('auth') === 'recovery';
        const params = new URLSearchParams(window.location.hash.slice(1));
        if (params.has('error')) {
            window.history.replaceState(null, '', window.location.pathname);
        }
        const { data: { subscription } } = client.auth.onAuthStateChange((event, nextSession) => {
            if (!active) return;
            setSession(nextSession);
            setLoading(false);
            if (event === 'PASSWORD_RECOVERY' || (event === 'INITIAL_SESSION' && recoveryRequested && nextSession)) {
                setRecovering(true);
                setMode('update');
                setDemo(false);
            }
            if (event === 'INITIAL_SESSION' && recoveryRequested && !nextSession) {
                setMode('reset');
                setError('This reset link is invalid or has expired. Please request a new link.');
                clearRecoveryUrl();
            }
            if (event === 'SIGNED_OUT') {
                setRecovering(false);
                setDemo(false);
                setMode('login');
                setProfileResult(null);
            }
        });
        // Auth events own the session state; this catches initialization failures.
        void client.auth.getSession().then(({ error: sessionError }) => {
            if (active && sessionError) {
                setError('Your session could not be restored. Please sign in again.');
                setLoading(false);
            }
        }).catch(() => {
            if (active) {
                setError('Your session could not be restored. Please sign in again.');
                setLoading(false);
            }
        });
        return () => { active = false; subscription.unsubscribe(); };
    }, []);

    const userId = session?.user.id;
    const currentProfile = profileResult && profileResult.userId === userId && profileResult.attempt === profileAttempt ? profileResult : null;
    const profile = currentProfile?.data;
    const profileError = currentProfile?.failed;
    useEffect(() => {
        const client = supabase;
        if (!client || !userId || recovering || demo) return;
        let active = true;
        const controller = new AbortController();
        const timeout = window.setTimeout(() => controller.abort(), 10000);
        void Promise.resolve(client.from('profiles').select('id, display_name, created_at, updated_at').eq('id', userId).abortSignal(controller.signal).single())
            .then(({ data, error: databaseError }) => {
                if (!active) return;
                setProfileResult({ userId, attempt: profileAttempt, data: data || null, failed: Boolean(databaseError || !data) });
            }, () => { if (active) setProfileResult({ userId, attempt: profileAttempt, data: null, failed: true }); })
            .finally(() => window.clearTimeout(timeout));
        return () => { active = false; controller.abort(); window.clearTimeout(timeout); };
    }, [userId, recovering, demo, profileAttempt]);

    const changeMode = (next: AuthMode) => {
        setMode(next);
        setError('');
        setNotice('');
    };

    const signOut = async () => {
        if (busy) return;
        setBusy(true);
        setError('');
        try {
            if (demo) setDemo(false);
            else if (supabase) {
                const { error: signOutError } = await supabase.auth.signOut({ scope: 'local' });
                if (signOutError) throw signOutError;
            }
            setRecovering(false);
            setMode('login');
            setNotice('');
            clearRecoveryUrl();
        } catch (signOutError) {
            setError(authError(signOutError));
        } finally { setBusy(false); }
    };

    const submit = async (fields: AuthFields) => {
        if (!supabase || busy) return;
        setBusy(true);
        setError('');
        setNotice('');
        const email = fields.email.trim();
        const redirectTo = window.location.origin + '/';
        try {
            if (mode === 'login') {
                const { error: loginError } = await supabase.auth.signInWithPassword({ email, password: fields.password });
                if (loginError) throw loginError;
            } else if (mode === 'signup') {
                const { data, error: signupError } = await supabase.auth.signUp({
                    email, password: fields.password,
                    options: { data: { display_name: fields.displayName.trim() }, emailRedirectTo: redirectTo },
                });
                if (signupError) throw signupError;
                if (!data.session) {
                    setMode('login');
                    setNotice('Check your email for a confirmation link, then sign in. If you already have an account, sign in or reset your password.');
                }
            } else if (mode === 'reset') {
                const { error: resetError } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: redirectTo + '?auth=recovery' });
                if (resetError) throw resetError;
                setNotice('If an account exists for that email, you’ll receive a password reset link.');
            } else {
                if (!session || !recovering) throw new Error('No recovery session');
                const { error: updateError } = await supabase.auth.updateUser({ password: fields.password });
                if (updateError) throw updateError;
                // Require a new sign-in after recovery. Keep this screen if sign-out fails.
                const { error: signOutError } = await supabase.auth.signOut({ scope: 'local' });
                if (signOutError) throw signOutError;
                setRecovering(false);
                setMode('login');
                clearRecoveryUrl();
                setNotice('Password updated. Sign in with your new password.');
            }
        } catch (requestError) { setError(authError(requestError)); }
        finally { setBusy(false); }
    };

    if (loading) return <AuthShell><p role="status" className="text-center">Restoring your session…</p></AuthShell>;
    if (demo) return children({ id: 'demo', email: 'demo@bridge.ai', displayName: 'Demo User', isDemo: true }, signOut, busy);
    if (session && !recovering) {
        if (profile?.id === session.user.id) return <>
            {error && <div role="alert" className="fixed top-4 right-4 z-50 max-w-sm rounded-lg bg-card border border-border p-4 shadow-lg">{error}</div>}
            {children({ id: session.user.id, email: session.user.email || '', displayName: profile.display_name, isDemo: false }, signOut, busy)}
        </>;
        return <AuthShell>
            <h1 className="text-xl font-bold text-center">{profileError ? 'Your profile could not be loaded' : 'Opening your workspace…'}</h1>
            {profileError ? <>
                <p role="alert" className="text-sm text-muted-foreground my-4">You’re signed in, but your profile is unavailable. Try again or contact your administrator.</p>
                <button type="button" disabled={busy} onClick={() => setProfileAttempt(value => value + 1)} className="w-full bg-primary text-primary-foreground rounded-xl py-3">Try again</button>
            </> : <p role="status" className="text-center text-sm my-4">Loading your profile…</p>}
            {error && <p role="alert" className="text-sm text-destructive mt-4">{error}</p>}
            <button type="button" disabled={busy} onClick={() => void signOut()} className="w-full text-primary mt-4">{busy ? 'Signing out…' : 'Sign out'}</button>
        </AuthShell>;
    }
    return <LoginScreen key={mode} configured={Boolean(supabase)} mode={mode} busy={busy} error={error} notice={notice} onModeChange={changeMode} onSubmit={submit}
        onDemo={() => { setDemo(true); setError(''); setNotice(''); }} onCancelRecovery={() => void signOut()} />;
}

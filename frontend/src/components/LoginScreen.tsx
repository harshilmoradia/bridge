import { useState, type FormEvent, type ReactNode } from 'react';
import { Check, Eye, EyeOff, X } from 'lucide-react';
import { useTheme } from '../context/theme';
import { validateAuthFields, type AuthFields, type AuthMode } from '../lib/auth';

export function AuthShell({ children }: { children: ReactNode }) {
    const { theme, toggleTheme } = useTheme();
    return (
        <div className="min-h-dvh flex items-center justify-center bg-background text-foreground relative px-4 py-20 fade-in">
            <div aria-hidden="true" className="absolute inset-0 overflow-hidden pointer-events-none">
                <div className="absolute top-[10%] left-[20%] w-[40vw] h-[40vw] rounded-full bg-indigo-500/10 blur-[100px]" />
                <div className="absolute bottom-[10%] right-[20%] w-[30vw] h-[30vw] rounded-full bg-pink-500/10 blur-[100px]" />
            </div>
            <div className="w-full max-w-md bg-card p-6 sm:p-10 rounded-[2rem] shadow-xl z-10 border border-border">
                <div aria-hidden="true" className="w-14 h-14 rounded-2xl bg-primary mx-auto flex items-center justify-center shadow-md mb-5">
                    <i className="ri-infinity-line text-primary-foreground font-bold text-3xl" />
                </div>
                {children}
            </div>
            <button type="button" aria-label={theme === 'dark' ? 'Use light theme' : 'Use dark theme'} onClick={toggleTheme} className="absolute top-6 right-6 w-10 h-10 rounded-full bg-card flex items-center justify-center hover:bg-muted border border-border">
                <i aria-hidden="true" className={theme === 'dark' ? 'ri-sun-line' : 'ri-moon-line'} />
            </button>
        </div>
    );
}

interface LoginScreenProps {
    configured: boolean;
    mode: AuthMode;
    busy: boolean;
    error: string;
    notice: string;
    onModeChange: (mode: AuthMode) => void;
    onSubmit: (fields: AuthFields) => Promise<void>;
    onDemo: () => void;
    onCancelRecovery: () => void;
}

const headings: Record<AuthMode, string> = {
    login: 'Sign in to Bridge', signup: 'Create your account', reset: 'Reset your password', update: 'Choose a new password',
};
const actions: Record<AuthMode, string> = {
    login: 'Sign in', signup: 'Create account', reset: 'Send reset link', update: 'Save new password',
};
const inputClass = 'w-full bg-background border border-border rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50';

interface PasswordInputProps {
    id: string;
    label: string;
    name: string;
    value: string;
    onChange: (value: string) => void;
    autoComplete: 'new-password' | 'current-password';
    minLength?: number;
    describedBy?: string;
    matchState: 'idle' | 'match' | 'mismatch';
}

function PasswordInput({ id, label, name, value, onChange, autoComplete, minLength, describedBy, matchState }: PasswordInputProps) {
    const [visible, setVisible] = useState(false);
    const borderClass = matchState === 'match' ? 'border-emerald-600 dark:border-emerald-400' : matchState === 'mismatch' ? 'border-destructive' : '';
    const VisibilityIcon = visible ? EyeOff : Eye;
    return <div>
        <label htmlFor={id} className="block text-sm font-medium mb-1">{label}</label>
        <div className="relative">
            <input id={id} name={name} type={visible ? 'text' : 'password'} autoComplete={autoComplete} required minLength={minLength}
                value={value} onChange={event => onChange(event.target.value)} className={`${inputClass} pr-12 ${borderClass}`}
                aria-describedby={describedBy} aria-invalid={matchState === 'mismatch' ? true : undefined} />
            <button type="button" onClick={() => setVisible(previous => !previous)} aria-label={`${visible ? 'Hide' : 'Show'} ${label.toLowerCase()}`}
                aria-pressed={visible} aria-controls={id}
                className="absolute right-1 top-1 bottom-1 w-10 flex items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed">
                <VisibilityIcon aria-hidden="true" size={18} />
            </button>
        </div>
    </div>;
}

export function LoginScreen({ configured, mode, busy, error, notice, onModeChange, onSubmit, onDemo, onCancelRecovery }: LoginScreenProps) {
    const [fields, setFields] = useState<AuthFields>({ email: '', password: '', confirmPassword: '', displayName: '' });
    const [validationError, setValidationError] = useState('');
    const needsNewPassword = mode === 'signup' || mode === 'update';
    const matchState = needsNewPassword && fields.password && fields.confirmPassword
        ? (fields.password === fields.confirmPassword ? 'match' : 'mismatch') : 'idle';
    const longEnough = fields.password.length >= 12;
    const change = (name: keyof AuthFields, value: string) => {
        setFields(previous => ({ ...previous, [name]: value }));
        setValidationError('');
    };
    const submit = (event: FormEvent) => {
        event.preventDefault();
        if (busy) return;
        const message = validateAuthFields(mode, fields);
        setValidationError(message || '');
        if (!message) void onSubmit(fields);
    };

    return (
        <AuthShell>
            <h1 className="text-2xl font-bold tracking-tight text-center">{configured ? headings[mode] : 'Welcome to Bridge'}</h1>
            <p className="text-sm text-muted-foreground mt-2 mb-6 text-center">
                {configured ? (mode === 'reset' ? 'We’ll email you a link to reset your password.' : 'Your reconciliation workspace') : 'Account sign-in is not available yet. Explore the sample workspace below.'}
            </p>
            {(validationError || error) && <p role="alert" className="text-sm text-destructive mb-4">{validationError || error}</p>}
            {notice && <p role="status" className="text-sm text-muted-foreground mb-4">{notice}</p>}
            {configured && (
                <form onSubmit={submit} className="space-y-4">
                    <fieldset disabled={busy} className="space-y-4 disabled:opacity-70">
                        {mode === 'signup' && <div>
                            <label htmlFor="display-name" className="block text-sm font-medium mb-1">Full name</label>
                            <input id="display-name" name="name" autoComplete="name" required maxLength={100} value={fields.displayName} onChange={event => change('displayName', event.target.value)} className={inputClass} />
                        </div>}
                        {mode !== 'update' && <div>
                            <label htmlFor="auth-email" className="block text-sm font-medium mb-1">Email</label>
                            <input id="auth-email" name="email" type="email" autoComplete="email" required value={fields.email} onChange={event => change('email', event.target.value)} className={inputClass} />
                        </div>}
                        {mode !== 'reset' && <div>
                            <PasswordInput id="auth-password" name="password" label={mode === 'update' ? 'New password' : 'Password'}
                                value={fields.password} onChange={value => change('password', value)} autoComplete={needsNewPassword ? 'new-password' : 'current-password'}
                                minLength={needsNewPassword ? 12 : undefined} describedBy={needsNewPassword ? 'password-hint password-match' : undefined} matchState={matchState} />
                            {needsNewPassword && <p id="password-hint" className={`flex items-center gap-1.5 text-xs mt-2 ${longEnough ? 'text-emerald-700 dark:text-emerald-400' : fields.password ? 'text-destructive' : 'text-muted-foreground'}`}>
                                {longEnough && <Check aria-hidden="true" size={14} />}Use at least 12 characters.
                            </p>}
                        </div>}
                        {needsNewPassword && <div>
                            <PasswordInput id="confirm-password" name="confirm-password" label="Confirm password" value={fields.confirmPassword}
                                onChange={value => change('confirmPassword', value)} autoComplete="new-password" describedBy="password-match" matchState={matchState} />
                            <p id="password-match" role="status" aria-live="polite" aria-atomic="true"
                                className={`flex items-center gap-1.5 text-xs mt-2 ${matchState === 'match' ? 'text-emerald-700 dark:text-emerald-400' : matchState === 'mismatch' ? 'text-destructive' : 'text-muted-foreground'}`}>
                                {matchState === 'match' ? <><Check aria-hidden="true" size={14} />Passwords match.</>
                                    : matchState === 'mismatch' ? <><X aria-hidden="true" size={14} />Passwords do not match.</>
                                        : fields.confirmPassword ? 'Enter your password above.' : 'Re-enter your password to confirm.'}
                            </p>
                        </div>}
                        <button type="submit" className="w-full bg-primary text-primary-foreground font-semibold rounded-xl py-3 hover:opacity-90">{busy ? 'Please wait…' : actions[mode]}</button>
                    </fieldset>
                    {mode === 'login' ? <div className="flex justify-between gap-3 text-sm">
                        <button type="button" disabled={busy} onClick={() => onModeChange('reset')} className="text-primary hover:underline">Forgot password?</button>
                        <button type="button" disabled={busy} onClick={() => onModeChange('signup')} className="text-primary hover:underline">Create account</button>
                    </div> : <button type="button" disabled={busy} onClick={() => mode === 'update' ? onCancelRecovery() : onModeChange('login')} className="w-full text-sm text-primary hover:underline">{mode === 'update' ? 'Cancel and sign out' : 'Back to sign in'}</button>}
                </form>
            )}
            {mode !== 'update' && <div className="mt-6 border-t border-border pt-5">
                <button type="button" disabled={busy} onClick={onDemo} className="w-full bg-muted text-foreground font-semibold rounded-xl py-3 border border-border hover:bg-muted/80">Explore demo</button>
                <p className="text-xs text-muted-foreground mt-3 text-center">Sample transactions and simulated replies. No ERP posting.</p>
            </div>}
        </AuthShell>
    );
}

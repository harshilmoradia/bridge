import { useState, type FormEvent, type ReactNode } from 'react';
import { Check, Eye, EyeOff, X } from 'lucide-react';
import { useTheme } from '../context/theme';
import { validateAuthFields, type AuthFields, type AuthMode } from '../lib/auth';

export function AuthShell({ children }: { children: ReactNode }) {
    const { theme, toggleTheme } = useTheme();
    return (
        <div className="min-h-dvh flex items-center justify-center bg-background text-foreground relative px-4 py-20 fade-in">
            <div className="w-full max-w-sm bg-card p-6 sm:p-8 rounded-xl shadow-card z-10 border border-border">
                <div aria-hidden="true" className="size-10 rounded-lg bg-foreground text-background mx-auto grid place-items-center mb-5">
                    <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M2 17c4-8 16-8 20 0M6 17v-4.5M12 17v-6.5M18 17v-4.5M2 17h20" /></svg>
                </div>
                {children}
            </div>
            <button type="button" aria-label={theme === 'dark' ? 'Use light theme' : 'Use dark theme'} onClick={toggleTheme} className="absolute top-6 right-6 w-9 h-9 rounded-md bg-card flex items-center justify-center hover:bg-muted border border-border">
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
const inputClass = 'w-full bg-card border border-input rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50';

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
                {configured ? (mode === 'reset' ? 'We’ll email you a link to reset your password.' : 'Sign in to reconcile your own books.') : 'Account sign-in is not available yet. Explore the sample workspace below.'}
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
                        <button type="submit" className="w-full bg-primary text-primary-foreground font-semibold rounded-md py-2.5 hover:opacity-90">{busy ? 'Please wait…' : actions[mode]}</button>
                    </fieldset>
                    {mode === 'login' ? <div className="flex justify-between gap-3 text-sm">
                        <button type="button" disabled={busy} onClick={() => onModeChange('reset')} className="text-primary hover:underline">Forgot password?</button>
                        <button type="button" disabled={busy} onClick={() => onModeChange('signup')} className="text-primary hover:underline">Create account</button>
                    </div> : <button type="button" disabled={busy} onClick={() => mode === 'update' ? onCancelRecovery() : onModeChange('login')} className="w-full text-sm text-primary hover:underline">{mode === 'update' ? 'Cancel and sign out' : 'Back to sign in'}</button>}
                </form>
            )}
            {mode !== 'update' && <div className="mt-6 border-t border-border pt-5">
                <button type="button" disabled={busy} onClick={onDemo} className="w-full text-foreground font-semibold rounded-md py-2.5 border border-border hover:bg-muted">Back to the demo</button>
                <p className="text-xs text-muted-foreground mt-3 text-center">The demo uses sample transactions. Nothing posts to an ERP.</p>
            </div>}
        </AuthShell>
    );
}

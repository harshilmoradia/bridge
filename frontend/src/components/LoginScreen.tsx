import React from 'react';
import { useTheme } from '../context/theme';

interface LoginScreenProps {
    loginLoading: boolean;
    userEmailInput: string;
    setUserEmailInput: (val: string) => void;
    handleLogin: (email: string) => void;
}

export const LoginScreen: React.FC<LoginScreenProps> = ({
    loginLoading,
    userEmailInput,
    setUserEmailInput,
    handleLogin
}) => {
    const { theme, toggleTheme } = useTheme();

    return (
        <div className="h-screen flex items-center justify-center bg-background text-foreground relative overflow-hidden fade-in transition-colors">
            <div className="absolute inset-0 z-0 overflow-hidden pointer-events-none">
                <div className="absolute top-[10%] left-[20%] w-[40vw] h-[40vw] rounded-full bg-indigo-500/10 blur-[100px]"></div>
                <div className="absolute bottom-[10%] right-[20%] w-[30vw] h-[30vw] rounded-full bg-pink-500/10 blur-[100px]"></div>
            </div>

            <div className="w-full max-w-md bg-card p-10 rounded-[2rem] shadow-[0_10px_40px_-10px_rgba(0,0,0,0.1)] z-10 border border-border relative animate-in">
                <div className="text-center mb-8">
                    <div className="w-14 h-14 rounded-2xl bg-primary mx-auto flex items-center justify-center shadow-md mb-5">
                        <i aria-hidden="true" className="ri-infinity-line text-primary-foreground font-bold text-3xl"></i>
                    </div>
                    <h1 className="text-2xl font-bold tracking-tight">Explore the Bridge Demo</h1>
                    <p className="text-sm text-muted-foreground mt-2">Sample reconciliation workspace — no account required</p>
                </div>

                <form onSubmit={e => { e.preventDefault(); handleLogin(userEmailInput); }} className="space-y-5">
                    <div className="space-y-1.5">
                        <label htmlFor="demo-email" className="text-xs font-bold text-muted-foreground uppercase tracking-wider ml-1">Demo Email</label>
                        <input
                            type="email"
                            id="demo-email" autoComplete="email"
                            required
                            value={userEmailInput}
                            onChange={(e) => setUserEmailInput(e.target.value)}
                            placeholder="name@company.com"
                            className="w-full bg-background border border-border rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all text-foreground"
                        />
                    </div>
                    <div className="pt-4 space-y-3">
                        <button type="submit" disabled={loginLoading} className="w-full bg-primary text-primary-foreground font-semibold rounded-xl py-3 shadow-md hover:opacity-90 transition-all active:scale-[0.98] flex items-center justify-center gap-2">
                            {loginLoading ? <i aria-hidden="true" className="ri-loader-4-line animate-spin text-lg"></i> : null}
                            {loginLoading ? 'Opening Demo...' : 'Enter Demo'}
                        </button>

                        <button
                            type="button"
                            disabled={loginLoading}
                            onClick={() => handleLogin('demo@bridge.ai')}
                            className="w-full bg-muted text-foreground font-semibold rounded-xl py-3 border border-border shadow-sm hover:bg-muted/80 transition-all active:scale-[0.98] flex items-center justify-center gap-2"
                        >
                            <i aria-hidden="true" className="ri-user-star-line text-lg text-primary"></i>
                            Use Demo Account
                        </button>
                    </div>
                </form>

                <div className="mt-8 flex items-center justify-center gap-2 text-xs text-muted-foreground font-medium">
                    <i aria-hidden="true" className="ri-shield-check-line text-green-500"></i> Sample data and simulated replies. No ERP posting.
                </div>
            </div>

            <div className="absolute top-6 right-6 z-10">
                <button aria-label={theme === 'dark' ? 'Use light theme' : 'Use dark theme'} onClick={toggleTheme} className="w-10 h-10 rounded-full bg-card flex items-center justify-center hover:bg-muted transition-colors border border-border shadow-sm text-foreground">
                    <i aria-hidden="true" className={theme === 'dark' ? 'ri-sun-line' : 'ri-moon-line'}></i>
                </button>
            </div>
        </div>
    );
};

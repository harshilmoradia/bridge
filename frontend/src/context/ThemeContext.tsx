import { useState, useEffect, type ReactNode } from 'react';

import { ThemeContext, type Theme } from './theme';

export const ThemeProvider = ({ children }: { children: ReactNode }) => {
    const [theme, setTheme] = useState<Theme>(() => {
        try {
            const saved = localStorage.getItem('bridge-theme');
            return (saved === 'dark' || saved === 'light') ? saved : 'light';
        } catch { return 'light'; }
    });

    useEffect(() => {
        const root = document.documentElement;
        root.classList.remove('light', 'dark');
        root.classList.add(theme);
        try { localStorage.setItem('bridge-theme', theme); } catch { /* Keep the theme usable without storage. */ }
    }, [theme]);

    const toggleTheme = () => setTheme(prev => prev === 'dark' ? 'light' : 'dark');

    return (
        <ThemeContext.Provider value={{ theme, toggleTheme }}>
            {children}
        </ThemeContext.Provider>
    );
};

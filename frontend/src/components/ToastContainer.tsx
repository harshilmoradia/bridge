interface ToastItem {
    id: string;
    message: string;
    type: 'success' | 'info';
}

export const ToastContainer = ({ toasts }: { toasts: ToastItem[] }) => {
    if (toasts.length === 0) return null;

    return (
        <div role="status" aria-live="polite" className="fixed bottom-6 right-6 z-[200] flex flex-col gap-2 pointer-events-none">
            {toasts.map(toast => (
                <div
                    key={toast.id}
                    className="animate-in pointer-events-auto bg-card border border-border rounded-xl px-5 py-3 shadow-[0_10px_40px_-10px_rgba(0,0,0,0.15)] flex items-center gap-3 text-sm font-semibold text-foreground min-w-[280px]"
                >
                    <div className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 ${toast.type === 'success' ? 'bg-green-100 dark:bg-green-500/20 text-green-600 dark:text-green-400' : 'bg-primary/10 text-primary'}`}>
                        <i aria-hidden="true" className={toast.type === 'success' ? 'ri-check-line text-sm' : 'ri-information-line text-sm'}></i>
                    </div>
                    {toast.message}
                </div>
            ))}
        </div>
    );
};

export function BrandMark({ size = 'md' }: { size?: 'md' | 'lg' }) {
    return (
        <div aria-hidden="true" className={`grid shrink-0 place-items-center bg-foreground text-background ${size === 'lg' ? 'size-12 rounded-xl' : 'size-7 rounded-[7px]'}`}>
            <svg viewBox="0 0 24 24" className={size === 'lg' ? 'size-6' : 'size-4'} fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
                <path d="M2 17c4-8 16-8 20 0M6 17v-4.5M12 17v-6.5M18 17v-4.5M2 17h20" />
            </svg>
        </div>
    );
}

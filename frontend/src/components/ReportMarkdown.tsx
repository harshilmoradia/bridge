import Markdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

// Safe by construction: react-markdown drops raw HTML (no rehype-raw) and strips unsafe URLs.
// react-markdown passes its AST `node` prop; drop it so it never reaches the DOM.
function clean<T extends { node?: unknown }>(props: T): Omit<T, 'node'> {
    const rest = { ...props };
    delete rest.node;
    return rest;
}

const components: Components = {
    h1: p0 => <h1 className="mb-3 mt-6 text-2xl font-bold tracking-tight first:mt-0" {...clean(p0)} />,
    h2: p0 => <h2 className="mb-2 mt-6 text-xl font-semibold tracking-tight first:mt-0" {...clean(p0)} />,
    h3: p0 => <h3 className="mb-2 mt-4 text-base font-semibold" {...clean(p0)} />,
    p: p0 => <p className="my-3 text-sm leading-6" {...clean(p0)} />,
    ul: p0 => <ul className="my-3 list-disc space-y-1 pl-6 text-sm" {...clean(p0)} />,
    ol: p0 => <ol className="my-3 list-decimal space-y-1 pl-6 text-sm" {...clean(p0)} />,
    a: p0 => {
        const { href, ...rest } = clean(p0);
        return href?.trim()
            ? <a className="font-medium text-primary underline" rel="noreferrer noopener" target="_blank" href={href} {...rest} />
            : <span {...rest} />;
    },
    code: p0 => <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs" {...clean(p0)} />,
    blockquote: p0 => <blockquote className="my-3 border-l-2 pl-4 text-sm text-muted-foreground" {...clean(p0)} />,
    table: p0 => <div className="my-3 overflow-x-auto"><table className="w-full border-collapse text-sm tabular-nums" {...clean(p0)} /></div>,
    th: p0 => <th className="border-b px-3 py-1.5 text-left font-medium" {...clean(p0)} />,
    td: p0 => <td className="border-b px-3 py-1.5" {...clean(p0)} />,
};

export default function ReportMarkdown({ source }: { source: string }) {
    return <div data-testid="report-markdown"><Markdown remarkPlugins={[remarkGfm]} components={components} disallowedElements={['img']}>{source}</Markdown></div>;
}

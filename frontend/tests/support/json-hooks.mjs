// Node loader hooks so node can import the mock layer as Vite does: JSON without attributes, extensionless .ts specifiers.
import { readFile } from 'node:fs/promises';
export async function resolve(specifier, context, nextResolve) {
    try { return await nextResolve(specifier, context); } catch (e) {
        if (specifier.startsWith('.') && e.code === 'ERR_MODULE_NOT_FOUND') return nextResolve(specifier + '.ts', context);
        throw e;
    }
}
export async function load(url, context, nextLoad) {
    if (url.endsWith('.json')) return { format: 'json', source: await readFile(new URL(url)), shortCircuit: true };
    if (url.endsWith('.ts') && url.includes('/src/')) {
        // Vite supplies import.meta.env; default to mock mode so the mock layer is what runs.
        return { format: 'module-typescript', source: "import.meta.env ??= { VITE_USE_MOCKS: 'true' };" + await readFile(new URL(url), 'utf8'), shortCircuit: true };
    }
    return nextLoad(url, context);
}

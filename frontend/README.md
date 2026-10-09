# Bridge frontend

React, TypeScript, Vite, Tailwind CSS, and Recharts.

## Development and checks

Use Node.js 22.16 or newer (Node 22 LTS recommended).

```sh
npm ci
npm run dev
npm run lint
npm test
npm run build
```

The test command uses Node's built-in test runner and TypeScript stripping; no extra test dependency is needed. Regression tests cover search and tab-scoped selection, approval mappings, duplicate approvals, dashboard counts, and saved demo data validation.

## Demo behavior

This frontend currently runs as a demo. The email identifies the demo user; it does not authenticate an account, and no password is requested. Chat and document uploads are simulated. File contents are not parsed, and approvals do not post to an ERP.

Demo transactions and audit history are saved under `bridge-demo-ledger-v1` in this browser's local storage. Clear that key to reset the sample data. Invalid stored data falls back to the initial samples. If storage is unavailable, the app remains usable and explains that changes last only for the current session.

The backend has a chat endpoint, but authentication, uploads, and ledger posting still require API integration before production use.

## Screenshots

See the [desktop and mobile screenshots](../docs/screenshots/frontend/README.md) for the dashboard and centered transaction review dialog.

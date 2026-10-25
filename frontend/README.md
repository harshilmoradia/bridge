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

The test command uses Node's built-in test runner and TypeScript stripping. PGlite runs the profiles migration in PostgreSQL for grant/RLS checks. Tests also cover signup/reset validation, public-key configuration, ledger approvals, and demo persistence.

## Authentication

Email/password signup, login, email confirmation, password recovery and sign-out use Supabase. Set `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` in `.env.local`, and apply the profiles migration before signing in. The frontend loads the signed-in user's profile using their session and RLS. Session tokens refresh automatically; if browser storage is blocked, they last only in the current tab.

Follow [the Supabase setup guide](../docs/supabase-setup.md) for project creation, SQL, email delivery and redirect configuration. Never use a secret/service_role key in a frontend variable. The build rejects privileged keys.

## Demo behavior

**Explore demo** provides sample access without an account, including when Supabase is not configured. Signed-in users currently see the same sample reconciliation features. Chat and document uploads are simulated. File contents are not parsed, approvals do not post to an ERP, and transactions are not yet stored in Supabase.

Demo transactions and audit history are saved under `bridge-demo-ledger-v1` in this browser's local storage. Clear that key to reset the sample data. Invalid stored data falls back to the initial samples. If storage is unavailable, the app remains usable and explains that changes last only for the current session.

The backend chat endpoint requires a Supabase bearer token. The sample chat UI does not call it yet. Uploads and ledger posting still require API integration before production use.

## Screenshots

See the [desktop and mobile screenshots](../docs/screenshots/frontend/README.md) for the dashboard and centered transaction review dialog.

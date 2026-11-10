# apps/web — PayPal Autopilot frontend

Next.js App Router, React, TypeScript, Tailwind CSS, shadcn/ui.

Product and architecture live in the repo-root [`docs/`](../../docs). This
README is only the local frontend workflow.

## Commands

```powershell
cd apps/web
npm install
npm run dev      # http://localhost:3000
npm run lint
npm run build
```

The API base URL is `NEXT_PUBLIC_API_BASE_URL` (default
`http://localhost:8000`, see the repo-root `.env.example`).

## Routes

```
/                      landing
/login  /register      session cookie against the API
/app                   workspace overview (requires a session)
/app/projects          create and list projects
/app/customers         create and list customers
/app/contractors       create and list contractors
```

Authenticated routes export `instant = false`. They read the session on
every request, so they are blocking routes under Cache Components.

`src/lib/api/client.ts` is the browser client (`credentials: "include"`).
`src/lib/api/server.ts` forwards the incoming cookie from Server Components.
Invoices, approvals, and the command bar are not built yet.

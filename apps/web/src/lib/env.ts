/**
 * Public environment. Next.js inlines NEXT_PUBLIC_* at build time.
 * The default matches local Docker/dev so `npm run dev` works before a
 * `.env` file is copied.
 */
const serverBase = process.env.API_INTERNAL_BASE_URL ?? "http://127.0.0.1:8000";

export const env = {
  // The browser calls the Next.js origin, which proxies /api to the FastAPI process.
  // A direct localhost:8000 call fails when that name resolves to IPv6 and the API
  // is listening on 127.0.0.1. Server components call the API directly.
  apiBaseUrl: typeof window === "undefined" ? serverBase : "",
} as const;

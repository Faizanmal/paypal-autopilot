import { env } from "@/lib/env";
import type { ApiErrorBody } from "@/lib/api/types";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  cookie?: string;
};

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers();
  if (options.body !== undefined) {
    headers.set("content-type", "application/json");
  }
  if (options.cookie) {
    headers.set("cookie", options.cookie);
  }

  const response = await fetch(`${env.apiBaseUrl}${path}`, {
    method: options.method ?? (options.body === undefined ? "GET" : "POST"),
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    credentials: "include",
    cache: "no-store",
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const payload = (await response.json().catch(() => null)) as
    | (T & ApiErrorBody & { detail?: unknown })
    | null;
  if (!response.ok) {
    throw new ApiError(
      response.status,
      payload?.error?.code ?? "request_failed",
      payload?.error?.message ?? formatApiFailure(response.status, payload),
    );
  }
  return payload as T;
}

function formatApiFailure(status: number, payload: { detail?: unknown } | null): string {
  const detail = payload?.detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (!item || typeof item !== "object") {
          return null;
        }
        const row = item as { loc?: unknown; msg?: unknown };
        const loc = Array.isArray(row.loc)
          ? row.loc.filter((part) => part !== "body").join(".")
          : "";
        const msg = typeof row.msg === "string" ? row.msg : null;
        if (!msg) {
          return null;
        }
        return loc ? `${loc}: ${msg}` : msg;
      })
      .filter((part): part is string => Boolean(part));
    if (parts.length > 0) {
      return parts.join("; ");
    }
  }
  return `Request failed (${status}).`;
}

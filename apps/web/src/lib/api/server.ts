import "server-only";

import { cookies } from "next/headers";

import { ApiError, api } from "@/lib/api/client";

export async function serverApi<T>(path: string): Promise<T | null> {
  const cookieStore = await cookies();
  try {
    return await api<T>(path, { cookie: cookieStore.toString() });
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return null;
    }
    // Auth gate pages must not crash the shell when the API is down or returns 5xx.
    if (path === "/api/v1/auth/me") {
      return null;
    }
    throw error;
  }
}

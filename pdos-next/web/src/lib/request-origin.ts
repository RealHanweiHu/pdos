import type { NextRequest } from "next/server";

export function sameOrigin(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  if (!origin || !host) return false;
  try {
    const parsed = new URL(origin);
    // Next's internal URL may use localhost when the browser uses 127.0.0.1.
    return parsed.host === host && parsed.protocol === request.nextUrl.protocol;
  } catch { return false; }
}

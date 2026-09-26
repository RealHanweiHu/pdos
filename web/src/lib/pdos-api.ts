import { cookies } from "next/headers";
import { NextResponse } from "next/server";

export const SESSION_COOKIE_NAME = "pdos_access_token";
const MAX_REQUEST_BYTES = 16_384;
const MAX_TOKEN_LENGTH = 4_096;

export type TokenResponse = {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
};

export class InvalidRequestBodyError extends Error {}
export class InvalidUpstreamResponseError extends Error {}

function apiBaseUrl() {
  const configured = process.env.PDOS_API_INTERNAL_URL ?? "http://127.0.0.1:8000";
  const url = new URL(configured);
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new InvalidUpstreamResponseError("Unsupported PDOS API protocol");
  }
  return url;
}

export async function pdosApiFetch(path: string, init?: RequestInit, timeoutMs = 5_000) {
  return fetch(new URL(path, apiBaseUrl()), {
    ...init,
    cache: "no-store",
    signal: AbortSignal.timeout(timeoutMs),
    headers: {
      Accept: "application/json",
      ...init?.headers,
    },
  });
}

export async function readBoundedJson(request: Request, maxBytes = MAX_REQUEST_BYTES): Promise<Record<string, unknown>> {
  const contentType = request.headers.get("content-type")?.split(";", 1)[0];
  if (contentType !== "application/json") {
    throw new InvalidRequestBodyError("JSON request required");
  }
  if (!request.body) throw new InvalidRequestBodyError("JSON body required");
  const reader = request.body.getReader();
  const decoder = new TextDecoder();
  let bodyText = "";
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) {
        await reader.cancel();
        throw new InvalidRequestBodyError("Request body too large");
      }
      bodyText += decoder.decode(value, { stream: true });
    }
    bodyText += decoder.decode();
  } finally {
    reader.releaseLock();
  }
  let body: unknown;
  try {
    body = JSON.parse(bodyText);
  } catch {
    throw new InvalidRequestBodyError("Valid JSON required");
  }
  if (body === null || typeof body !== "object" || Array.isArray(body)) {
    throw new InvalidRequestBodyError("JSON object required");
  }
  return body as Record<string, unknown>;
}

export function parseTokenResponse(body: unknown): TokenResponse {
  if (
    body === null ||
    typeof body !== "object" ||
    !("access_token" in body) ||
    !("token_type" in body) ||
    !("expires_in" in body)
  ) {
    throw new InvalidUpstreamResponseError("Malformed authentication response");
  }
  const token = body as Record<string, unknown>;
  if (
    typeof token.access_token !== "string" ||
    token.access_token.length === 0 ||
    token.access_token.length > MAX_TOKEN_LENGTH ||
    token.token_type !== "bearer" ||
    typeof token.expires_in !== "number" ||
    !Number.isInteger(token.expires_in) ||
    token.expires_in < 60 ||
    token.expires_in > 86_400
  ) {
    throw new InvalidUpstreamResponseError("Malformed authentication response");
  }
  return token as TokenResponse;
}

export async function readTokenResponse(response: Response): Promise<TokenResponse> {
  return parseTokenResponse(await response.json());
}

export async function persistSession(token: TokenResponse) {
  const store = await cookies();
  store.set(SESSION_COOKIE_NAME, token.access_token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: token.expires_in,
  });
}

export async function currentSessionToken() {
  const store = await cookies();
  return store.get(SESSION_COOKIE_NAME)?.value ?? null;
}

export async function clearSession() {
  const store = await cookies();
  store.set(SESSION_COOKIE_NAME, "", {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 0,
  });
}

export async function forwardJson(response: Response) {
  const body = await response.text();
  return new NextResponse(body || null, {
    status: response.status,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/json",
    },
  });
}

export function sessionJson(body: object, status = 200) {
  return NextResponse.json(body, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

export function sessionError(status: number, code: string, message: string) {
  return sessionJson({ detail: { code, message } }, status);
}

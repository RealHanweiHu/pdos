import { beforeEach, describe, expect, it, vi } from "vitest";

const setCookie = vi.fn();

vi.mock("next/headers", () => ({
  cookies: async () => ({ set: setCookie }),
}));

import { POST } from "./route";
import { resetLoginRateLimiterForTests } from "@/lib/login-rate-limit";

function loginRequest() {
  return new Request("http://localhost/api/session/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tenant_slug: "beepump",
      username: "owner",
      password: "correct horse battery staple",
    }),
  });
}

describe("POST /api/session/login", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    resetLoginRateLimiterForTests();
    vi.stubGlobal("fetch", fetchMock);
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("stores the upstream token only in a hardened cookie", async () => {
    fetchMock.mockResolvedValueOnce(
      Response.json({
        access_token: "signed.jwt.value",
        token_type: "bearer",
        expires_in: 1800,
      }),
    );

    const response = await POST(loginRequest());
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({ authenticated: true, expires_in: 1800 });
    expect(JSON.stringify(body)).not.toContain("signed.jwt.value");
    expect(setCookie).toHaveBeenCalledWith(
      "pdos_access_token",
      "signed.jwt.value",
      expect.objectContaining({
        httpOnly: true,
        sameSite: "lax",
        path: "/",
        maxAge: 1800,
      }),
    );
  });

  it("does not create a cookie when the upstream rejects credentials", async () => {
    fetchMock.mockResolvedValueOnce(
      Response.json(
        { detail: { code: "INVALID_CREDENTIALS", message: "Invalid" } },
        { status: 401 },
      ),
    );

    const response = await POST(loginRequest());

    expect(response.status).toBe(401);
    expect(setCookie).not.toHaveBeenCalled();
  });

  it("rate limits repeated credential failures before another upstream call", async () => {
    fetchMock.mockImplementation(async () =>
      Response.json(
        { detail: { code: "INVALID_CREDENTIALS", message: "Invalid" } },
        { status: 401 },
      ),
    );

    for (let attempt = 0; attempt < 10; attempt += 1) {
      expect((await POST(loginRequest())).status).toBe(401);
    }
    const blocked = await POST(loginRequest());

    expect(blocked.status).toBe(429);
    expect(blocked.headers.get("Retry-After")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(10);
    expect(setCookie).not.toHaveBeenCalled();
  });
});

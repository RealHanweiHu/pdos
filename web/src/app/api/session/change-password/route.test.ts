import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie, setCookie } = vi.hoisted(() => ({
  getCookie: vi.fn(),
  setCookie: vi.fn(),
}));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie, set: setCookie }),
}));

import { POST } from "./route";

function request(body: string) {
  return new Request("http://localhost/api/session/change-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
}

describe("POST /api/session/change-password", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
  });

  it("forwards the server-side session and clears it after a successful change", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ changed: true }));

    const response = await POST(
      request(JSON.stringify({
        current_password: "correct horse battery staple",
        new_password: "rotated production passphrase",
      })),
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ changed: true, reauthentication_required: true });
    expect(fetchMock).toHaveBeenCalledWith(
      new URL("http://127.0.0.1:8000/api/auth/change-password"),
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: "Bearer signed.jwt.value" }),
      }),
    );
    expect(setCookie).toHaveBeenCalledWith(
      "pdos_access_token",
      "",
      expect.objectContaining({ maxAge: 0 }),
    );
  });

  it("fails closed without a session and preserves it when validation fails", async () => {
    getCookie.mockReturnValue(undefined);
    expect((await POST(request("{}"))).status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();

    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    fetchMock.mockResolvedValueOnce(
      Response.json(
        { detail: { code: "INVALID_CURRENT_PASSWORD", message: "Current password is incorrect" } },
        { status: 400 },
      ),
    );
    const rejected = await POST(request(JSON.stringify({
      current_password: "wrong current password",
      new_password: "rotated production passphrase",
    })));
    expect(rejected.status).toBe(400);
    expect(setCookie).not.toHaveBeenCalled();
  });
});

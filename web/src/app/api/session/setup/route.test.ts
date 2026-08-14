import { beforeEach, describe, expect, it, vi } from "vitest";

const { setCookie } = vi.hoisted(() => ({ setCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ set: setCookie }),
}));

import { POST } from "./route";

function setupRequest() {
  return new Request("http://localhost/api/session/setup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tenant_slug: "beepump",
      tenant_name: "Beehive Technology",
      username: "owner",
      display_name: "Initial Owner",
      password: "correct horse battery staple",
    }),
  });
}

describe("POST /api/session/setup", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("bootstraps, signs in, and never returns the password or token", async () => {
    fetchMock
      .mockResolvedValueOnce(
        Response.json({
          tenant: { id: "tenant-1", slug: "beepump", name: "Beehive" },
          user: { id: "user-1", username: "owner", role: "owner" },
        }),
      )
      .mockResolvedValueOnce(
        Response.json({
          access_token: "signed.jwt.value",
          token_type: "bearer",
          expires_in: 1800,
        }),
      );

    const response = await POST(setupRequest());
    const serialized = JSON.stringify(await response.json());

    expect(response.status).toBe(200);
    expect(serialized).toBe('{"authenticated":true}');
    expect(serialized).not.toContain("signed.jwt.value");
    expect(serialized).not.toContain("correct horse battery staple");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(setCookie).toHaveBeenCalledWith(
      "pdos_access_token",
      "signed.jwt.value",
      expect.objectContaining({ httpOnly: true, sameSite: "lax" }),
    );
  });

  it("does not attempt login when one-time setup is rejected", async () => {
    fetchMock.mockResolvedValueOnce(
      Response.json(
        { detail: { code: "SETUP_ALREADY_COMPLETED", message: "Completed" } },
        { status: 403 },
      ),
    );

    const response = await POST(setupRequest());

    expect(response.status).toBe(403);
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(setCookie).not.toHaveBeenCalled();
  });
});

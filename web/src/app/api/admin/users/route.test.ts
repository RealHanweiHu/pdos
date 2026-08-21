import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: getCookie }),
}));

import { PATCH } from "./[userId]/route";
import { POST as RESET } from "./[userId]/reset-password/route";
import { GET, POST as CREATE } from "./route";

const context = { params: Promise.resolve({ userId: "user/one" }) };

function jsonRequest(path: string, method: "PATCH" | "POST", body: string) {
  return new Request(`http://localhost${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body,
  });
}

describe("/api/admin/users BFF", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("fails closed without a server-side session", async () => {
    getCookie.mockReturnValue(undefined);

    expect((await GET()).status).toBe(401);
    expect((await CREATE(jsonRequest("/api/admin/users", "POST", "{}"))).status).toBe(401);
    expect((await PATCH(jsonRequest("/api/admin/users/user-one", "PATCH", "{}"), context)).status).toBe(401);
    expect((await RESET(jsonRequest("/api/admin/users/user-one/reset-password", "POST", "{}"), context)).status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forwards list, create, update, and reset with bearer auth and encoded ids", async () => {
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    fetchMock.mockImplementation(() => Promise.resolve(Response.json({ id: "user-one" })));
    const create = { username: "engineer-one", password: "temporary passphrase 2026" };
    const update = { role: "quality" };
    const reset = { password: "rotated production passphrase" };

    await GET();
    await CREATE(jsonRequest("/api/admin/users", "POST", JSON.stringify(create)));
    await PATCH(jsonRequest("/api/admin/users/user-one", "PATCH", JSON.stringify(update)), context);
    await RESET(
      jsonRequest("/api/admin/users/user-one/reset-password", "POST", JSON.stringify(reset)),
      context,
    );

    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("http://127.0.0.1:8000/api/admin/users");
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(expect.objectContaining({
      method: "POST",
      body: JSON.stringify(create),
      headers: expect.objectContaining({ Authorization: "Bearer signed.jwt.value" }),
    }));
    expect(String(fetchMock.mock.calls[2]?.[0])).toBe(
      "http://127.0.0.1:8000/api/admin/users/user%2Fone",
    );
    expect(fetchMock.mock.calls[2]?.[1]).toEqual(expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify(update),
    }));
    expect(String(fetchMock.mock.calls[3]?.[0])).toBe(
      "http://127.0.0.1:8000/api/admin/users/user%2Fone/reset-password",
    );
    expect(fetchMock.mock.calls[3]?.[1]).toEqual(expect.objectContaining({
      method: "POST",
      body: JSON.stringify(reset),
    }));
  });

  it("rejects invalid JSON before contacting the API", async () => {
    getCookie.mockReturnValue({ value: "signed.jwt.value" });

    expect((await CREATE(jsonRequest("/api/admin/users", "POST", "not-json"))).status).toBe(400);
    expect((await PATCH(jsonRequest("/api/admin/users/user-one", "PATCH", "not-json"), context)).status).toBe(400);
    expect((await RESET(jsonRequest("/api/admin/users/user-one/reset-password", "POST", "not-json"), context)).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

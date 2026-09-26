// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
const { cookieGet } = vi.hoisted(() => ({ cookieGet: vi.fn(() => ({ value: "test-token" })) }));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: cookieGet }) }));
import { POST } from "./route";
import { InvalidRequestBodyError, readBoundedJson } from "@/lib/pdos-api";

const makeRequest = (text: string) => new Request("http://localhost/api/ai/findings/finding/review", {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision: "accepted", edited_payload: { text } }),
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("bounded plan review payload", () => {
  it.each([8000, 90000])("forwards a versioned review with %i UTF-8 characters above the generic 16 KiB limit", async (length) => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "finding" })));
    vi.stubGlobal("fetch", fetcher);
    const response = await POST(makeRequest("测".repeat(length)), { params: Promise.resolve({ findingId: "finding" }) });
    expect(response.status).toBe(200);
    expect(JSON.parse(fetcher.mock.calls[0][1].body).edited_payload.text.length).toBe(length);
  });
  it("rejects an oversized review before forwarding and keeps other endpoints bounded", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    // The review endpoint allows 1 MiB; size is measured in UTF-8 bytes.
    const response = await POST(makeRequest("测".repeat(Math.ceil(1024 * 1024 / 3))), { params: Promise.resolve({ findingId: "finding" }) });
    expect(response.status).toBe(400);
    expect(fetcher).not.toHaveBeenCalled();
    await expect(readBoundedJson(makeRequest("测".repeat(8000)))).rejects.toBeInstanceOf(InvalidRequestBodyError);
  });
});

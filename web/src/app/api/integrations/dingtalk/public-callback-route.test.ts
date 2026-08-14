import { beforeEach, describe, expect, it, vi } from "vitest";

import { POST as eventCallback } from "./callback/[routeKey]/route";
import { POST as cardCallback } from "./card-callback/[routeKey]/route";

const routeKey = "callback-route-key-001";
const eventSignature = "a".repeat(40);
const cardSignature = `${"A".repeat(43)}=`;
const context = { params: Promise.resolve({ routeKey }) };

describe("public DingTalk callback BFF", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
  });

  it("forwards only the signed AES callback fields without a PDOS session", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ encrypt: "ack" }));
    const body = JSON.stringify({ encrypt: "ciphertext" });
    const response = await eventCallback(
      new Request(
        `https://pdos.example/api/integrations/dingtalk/callback/${routeKey}?signature=${eventSignature}&timestamp=1700000000&nonce=n-1&ignored=drop-me`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body },
      ),
      context,
    );

    expect(response.status).toBe(200);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      `http://127.0.0.1:8000/api/integrations/dingtalk/callback/${routeKey}?signature=${eventSignature}&timestamp=1700000000&nonce=n-1`,
    );
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({
        method: "POST",
        body,
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
      }),
    );
  });

  it("normalizes DingTalk's documented callback query aliases", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ encrypt: "ack" }));
    const response = await eventCallback(
      new Request(
        `https://pdos.example/api/integrations/dingtalk/callback/${routeKey}?msg_signature=${eventSignature}&timeStamp=1700000000&nonce=n-2`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ encrypt: "ciphertext" }),
        },
      ),
      context,
    );

    expect(response.status).toBe(200);
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain(
      `?signature=${eventSignature}&timestamp=1700000000&nonce=n-2`,
    );
  });

  it("forwards only the two card signature headers without a PDOS session", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({}));
    const body = JSON.stringify({
      type: "actionCallback",
      corpId: "corp",
      userId: "staff-1",
      outTrackId: "card-1",
      content: JSON.stringify({ cardPrivateData: { params: { action: "acknowledge" } } }),
    });
    const response = await cardCallback(
      new Request(
        `https://pdos.example/api/integrations/dingtalk/card-callback/${routeKey}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "x-ddpaas-signature-timestamp": "1700000000",
            "x-ddpaas-signature": cardSignature,
            Authorization: "must-not-forward",
          },
          body,
        },
      ),
      context,
    );

    expect(response.status).toBe(200);
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({
        method: "POST",
        body,
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          "x-ddpaas-signature-timestamp": "1700000000",
          "x-ddpaas-signature": cardSignature,
        }),
      }),
    );
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get("authorization")).toBeNull();
  });

  it("leaves bounded envelope room around the card content field", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({}));
    const body = JSON.stringify({ content: "x".repeat(20_000) });
    const response = await cardCallback(
      new Request(
        `https://pdos.example/api/integrations/dingtalk/card-callback/${routeKey}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "Application/JSON; charset=utf-8",
            "x-ddpaas-signature-timestamp": "1700000000",
            "x-ddpaas-signature": cardSignature,
          },
          body,
        },
      ),
      context,
    );

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("rejects invalid routes, missing signatures, and oversized bodies before upstream", async () => {
    const invalidRoute = await eventCallback(
      new Request("https://pdos.example/api/integrations/dingtalk/callback/short", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      }),
      { params: Promise.resolve({ routeKey: "short" }) },
    );
    const missingCardSignature = await cardCallback(
      new Request(
        `https://pdos.example/api/integrations/dingtalk/card-callback/${routeKey}`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
      ),
      context,
    );
    const malformedEventSignature = await eventCallback(
      new Request(
        `https://pdos.example/api/integrations/dingtalk/callback/${routeKey}?signature=bad&timestamp=1700000000&nonce=n-1`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
      ),
      context,
    );
    const oversized = await eventCallback(
      new Request(
        `https://pdos.example/api/integrations/dingtalk/callback/${routeKey}?signature=${eventSignature}&timestamp=1700000000&nonce=n-1`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "x".repeat(1_500_001),
        },
      ),
      context,
    );
    const oversizedCard = await cardCallback(
      new Request(
        `https://pdos.example/api/integrations/dingtalk/card-callback/${routeKey}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "x-ddpaas-signature-timestamp": "1700000000",
            "x-ddpaas-signature": cardSignature,
          },
          body: "x".repeat(65_537),
        },
      ),
      context,
    );

    expect(invalidRoute.status).toBe(404);
    expect(missingCardSignature.status).toBe(400);
    expect(malformedEventSignature.status).toBe(400);
    expect(oversized.status).toBe(413);
    expect(oversizedCard.status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

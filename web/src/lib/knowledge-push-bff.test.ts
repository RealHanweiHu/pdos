import { beforeEach, describe, expect, it, vi } from "vitest";

const { getCookie } = vi.hoisted(() => ({ getCookie: vi.fn() }));

vi.mock("next/headers", () => ({ cookies: async () => ({ get: getCookie }) }));

import {
  forwardEngage,
  forwardKnowledgePush,
  forwardPushMetrics,
} from "./knowledge-push-bff";

const projectId = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";
const entityId = "11111111-bbbb-4ccc-8ddd-222222222222";
const pushId = "33333333-bbbb-4ccc-8ddd-444444444444";

describe("knowledge push BFF", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    getCookie.mockReturnValue({ value: "signed.jwt.value" });
    process.env.PDOS_API_INTERNAL_URL = "http://127.0.0.1:8000";
    fetchMock.mockImplementation(async () => Response.json({ items: [] }));
  });

  it("forwards a valid push context and the metrics read", async () => {
    await forwardKnowledgePush(
      new Request(
        `http://localhost/api/projects/${projectId}/knowledge-push?context_kind=change_request&context_entity_id=${entityId}`,
      ),
      projectId,
    );
    await forwardPushMetrics();
    await forwardEngage(pushId);

    expect(fetchMock.mock.calls.map((call) => String(call[0]))).toEqual([
      `http://127.0.0.1:8000/api/projects/${projectId}/knowledge-push?context_kind=change_request&context_entity_id=${entityId}`,
      "http://127.0.0.1:8000/api/knowledge/push-metrics",
      `http://127.0.0.1:8000/api/knowledge/pushes/${pushId}/engage`,
    ]);
  });

  it("rejects a malformed context here rather than passing it to the backend", async () => {
    const bad = [
      `?context_kind=Change-Request&context_entity_id=${entityId}`,
      "?context_kind=change_request&context_entity_id=not-a-uuid",
      "?context_kind=change_request",
      "",
    ];
    for (const query of bad) {
      const response = await forwardKnowledgePush(
        new Request(`http://localhost/api/x${query}`),
        projectId,
      );
      expect(response.status).toBe(400);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("only forwards the two parameters the server declares", async () => {
    await forwardKnowledgePush(
      new Request(
        `http://localhost/api/x?context_kind=change_request&context_entity_id=${entityId}&limit=999&tenant_id=someone-else`,
      ),
      projectId,
    );
    // Extra query parameters are dropped, not relayed.
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      `http://127.0.0.1:8000/api/projects/${projectId}/knowledge-push?context_kind=change_request&context_entity_id=${entityId}`,
    );
  });

  it("fails closed without a session and on a bad push id", async () => {
    expect((await forwardEngage("not-a-uuid")).status).toBe(404);

    getCookie.mockReturnValue(undefined);
    expect((await forwardPushMetrics()).status).toBe(401);
    expect((await forwardEngage(pushId)).status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

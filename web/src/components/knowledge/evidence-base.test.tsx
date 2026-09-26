import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EvidenceBase } from "./evidence-base";

const sourceId = "aaaaaaaa-1111-4222-8333-444444444444";

const source = {
  id: sourceId,
  name: "竞品官网",
  source_type: "web",
  base_url: "https://example.com/products",
  license_note: "公开页面，仅内部分析",
  allowed_use: "internal_analysis",
  collection_frequency: "weekly",
  retention_policy: "standard",
  trust_tier: "public",
  status: "active",
};

function snapshot(overrides: Record<string, unknown> = {}) {
  return {
    id: "bbbbbbbb-1111-4222-8333-555555555555",
    source_id: sourceId,
    url: "https://example.com/spec",
    captured_at: "2026-09-01T00:00:00Z",
    content_digest: "a".repeat(64),
    source_version: "2026-08",
    trust_tier: "public",
    taint: "untrusted_external",
    superseded_by_id: null,
    conflicts_with_id: null,
    conflict_note: null,
    is_stale: false,
    ...overrides,
  };
}

function mockFetch(sources: unknown[], snapshots: unknown[]) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/sources")) return Response.json({ items: sources });
    return Response.json({ items: snapshots });
  }) as unknown as typeof fetch;
}

describe("EvidenceBase", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(cleanup);

  it("shows a source's licence, allowed use and retention", async () => {
    vi.stubGlobal("fetch", mockFetch([source], []));

    render(<EvidenceBase />);

    expect(await screen.findByText("竞品官网")).toBeTruthy();
    // The metadata line carries type, trust, allowed use, retention, cadence.
    expect(screen.getByText(/保留 standard/)).toBeTruthy();
    expect(screen.getByText(/许可：公开页面，仅内部分析/)).toBeTruthy();
  });

  it("labels external material as untrusted rather than hiding it", async () => {
    vi.stubGlobal("fetch", mockFetch([source], [snapshot()]));

    render(<EvidenceBase />);

    // D25 标注不拦截: the snapshot is listed, carrying its label.
    expect(await screen.findByText("外部·未验证")).toBeTruthy();
    expect(screen.getByText(/https:\/\/example.com\/spec/)).toBeTruthy();
  });

  it("a superseded snapshot is shown as stale and says the original is kept", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch(
        [source],
        [snapshot({ superseded_by_id: "cccccccc-1111-4222-8333-666666666666", is_stale: true })],
      ),
    );

    render(<EvidenceBase />);

    expect(await screen.findByText("陈旧")).toBeTruthy();
    expect(screen.getByText(/原快照保留，不可覆盖/)).toBeTruthy();
  });

  it("filters to stale snapshots on request", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch(
        [source],
        [snapshot({ id: "fresh" }), snapshot({ id: "old", is_stale: true })],
      ),
    );

    render(<EvidenceBase />);
    await screen.findByText(/共 2 份/);
    expect(screen.getByText(/已过期或被取代 1 份/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "只看陈旧的" }));
    expect(screen.getByText("陈旧")).toBeTruthy();
  });

  it("shows a recorded conflict rather than silently picking a side", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch(
        [source],
        [snapshot({ conflicts_with_id: "dddddddd-1111-4222-8333-777777777777", conflict_note: "官方标称与实测差 1.5 bar" })],
      ),
    );

    render(<EvidenceBase />);

    expect(await screen.findByText(/官方标称与实测差 1.5 bar/)).toBeTruthy();
  });

  it("surfaces a refusal rather than an empty evidence base", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json(
          { detail: { code: "EVIDENCE_FORBIDDEN", message: "Evidence access denied" } },
          { status: 403 },
        ),
      ) as unknown as typeof fetch,
    );

    render(<EvidenceBase />);

    expect(await screen.findByText("Evidence access denied")).toBeTruthy();
    expect(screen.queryByText("尚无证据快照。")).toBeNull();
  });
});

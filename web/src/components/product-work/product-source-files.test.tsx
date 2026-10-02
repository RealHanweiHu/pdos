import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProductSourceFiles } from "./product-source-files";
vi.mock("./product-ai-runs", () => ({ ProductAiRuns: ({ prepared }: { prepared: unknown }) => <output aria-label="准备范围">{JSON.stringify(prepared)}</output> }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const file = { id: "original", filename: "RFQ.xlsx", classification: "internal", status: "extracted", error_code: null, revoked_at: null, size_bytes: 100, fragment_count: 2 };
it("selects explicit original fragments and invalidates preparation after changing selection", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [file], truncated: false })).mockResolvedValueOnce(Response.json({ ...file, fragments: [{ ordinal: 1, locator: "cell:C1", text: "120 kPa" }, { ordinal: 2, locator: "cell:C2", text: "another row" }], next_after: null })).mockResolvedValueOnce(Response.json({ digest: "a".repeat(64) }));
  vi.stubGlobal("fetch", fetcher);
  render(<ProductSourceFiles base="spaces/space" lineId="line"/>);
  fireEvent.click(await screen.findByRole("button", { name: "核对原文与出处" }));
  fireEvent.click(await screen.findByLabelText("cell:C1"));
  fireEvent.click(screen.getByRole("button", { name: "核对所选原文范围" }));
  await screen.findByText(/已核对1段原文/);
  expect(JSON.parse(String(fetcher.mock.calls[2][1]?.body))).toMatchObject({ capability: "rfq_requirements", product_line_id: "line", sources: [{ kind: "file", id: "original", ordinals: [1] }] });
  fireEvent.click(screen.getByLabelText("cell:C2"));
  expect(screen.getByLabelText("准备范围")).toHaveTextContent("null");
});
it("keeps confidential files available for manual reading but disables model selection", async () => {
  const secret = { ...file, classification: "confidential" };
  vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [secret], truncated: false })).mockResolvedValueOnce(Response.json({ ...secret, fragments: [{ ordinal: 1, locator: "page:1", text: "客户原文" }], next_after: null })));
  render(<ProductSourceFiles base="spaces/space" lineId={null}/>);
  fireEvent.click(await screen.findByRole("button", { name: "核对原文与出处" }));
  expect(await screen.findByLabelText("page:1")).toBeDisabled();
});

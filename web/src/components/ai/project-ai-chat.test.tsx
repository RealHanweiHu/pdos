import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectAiChat } from "./project-ai-chat";

function jsonResponse(body: object, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("ProjectAiChat", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders only server-mapped citations for an answered question", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValueOnce(jsonResponse({
      status: "answered",
      answer: "当前有一个高暴露风险。",
      error_code: null,
      citations: [{
        reference_id: "risk:risk-1",
        entity: "risk",
        entity_id: "risk-1",
        label: "电机交付风险",
        href: "/projects?project=project-1&tab=risks&risk_id=risk-1",
        excerpt: "likelihood=4 · impact=5",
      }],
    }));
    render(<ProjectAiChat projectId="project-1" />);
    await user.type(screen.getByLabelText("向项目 AI 提问"), "当前风险是什么？");
    await user.click(screen.getByRole("button", { name: "提问" }));

    expect(await screen.findByText("当前有一个高暴露风险。")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "跳转证据" })).toHaveAttribute(
      "href",
      "/projects?project=project-1&tab=risks&risk_id=risk-1",
    );
  });

  it("treats insufficient evidence and model removal as visible product states", async () => {
    const user = userEvent.setup();
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ status: "insufficient_evidence", answer: null, citations: [], error_code: null }))
      .mockResolvedValueOnce(jsonResponse({ status: "unavailable", answer: null, citations: [], error_code: "MODEL_UNAVAILABLE" }));
    render(<ProjectAiChat projectId="project-1" />);
    const input = screen.getByLabelText("向项目 AI 提问");
    await user.type(input, "没有证据的问题");
    await user.click(screen.getByRole("button", { name: "提问" }));
    expect(await screen.findByText("知识库无此依据")).toBeInTheDocument();
    await user.clear(input);
    await user.type(input, "再次提问");
    await user.click(screen.getByRole("button", { name: "提问" }));
    expect(await screen.findByText("AI 暂停")).toBeInTheDocument();
  });
});

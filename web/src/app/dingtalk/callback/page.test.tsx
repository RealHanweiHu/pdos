import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { routerReplace } = vi.hoisted(() => ({ routerReplace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplace }),
  useSearchParams: () =>
    new URLSearchParams("authCode=valid-code&state=one-time-state"),
}));

import DingTalkCallbackPage from "./page";

describe("DingTalkCallbackPage", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    routerReplace.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("consumes one-time OAuth state only once under React StrictMode", async () => {
    fetchMock.mockResolvedValueOnce(
      Response.json({ authenticated: true, expires_in: 1800, return_path: "/projects" }),
    );

    render(
      <StrictMode>
        <DingTalkCallbackPage />
      </StrictMode>,
    );

    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith("/projects"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/session/dingtalk/callback",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ auth_code: "valid-code", state: "one-time-state" }),
      }),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

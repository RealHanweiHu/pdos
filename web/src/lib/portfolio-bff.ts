import {
  currentSessionToken,
  forwardJson,
  pdosApiFetch,
  sessionError,
} from "@/lib/pdos-api";

/** Forwards a read-only cross-project view; the API scopes it to the caller's visible Projects. */
export async function forwardPortfolioView(view: "risks" | "my-tasks") {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    return forwardJson(
      await pdosApiFetch(`/api/portfolio/${view}`, {
        headers: { Authorization: `Bearer ${token}` },
      }),
    );
  } catch {
    return sessionError(503, "PORTFOLIO_UNAVAILABLE", "Portfolio view unavailable");
  }
}

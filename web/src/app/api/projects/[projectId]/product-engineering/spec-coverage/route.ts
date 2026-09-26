import {
  currentSessionToken,
  forwardJson,
  pdosApiFetch,
  sessionError,
} from "@/lib/pdos-api";

type Context = { params: Promise<{ projectId: string }> };

/** Requirement → specification coverage for the engineering register. */
export async function GET(_request: Request, context: Context) {
  const { projectId } = await context.params;
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    return forwardJson(
      await pdosApiFetch(
        `/api/projects/${encodeURIComponent(projectId)}/product-engineering/spec-coverage`,
        { method: "GET", headers: { Authorization: `Bearer ${token}` } },
      ),
    );
  } catch {
    return sessionError(
      503,
      "PRODUCT_ENGINEERING_UNAVAILABLE",
      "Product engineering service unavailable",
    );
  }
}

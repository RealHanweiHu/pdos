import { currentSessionToken, forwardJson, pdosApiFetch, sessionError } from "@/lib/pdos-api";

export async function GET() {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    return forwardJson(await pdosApiFetch("/api/projects/creation-templates", {
      headers: { Authorization: `Bearer ${token}` },
    }));
  } catch {
    return sessionError(503, "PROJECT_SERVICE_UNAVAILABLE", "项目模板暂不可用，请稍后重试");
  }
}

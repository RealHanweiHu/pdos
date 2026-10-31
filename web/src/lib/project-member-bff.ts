import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

type MemberRequest = {
  method: "GET" | "POST" | "DELETE";
  projectId: string;
  /** Extra path after `/members`, e.g. ["candidates"] or [userId]. */
  segments?: string[];
  request?: Request;
};

export async function forwardProjectMembers({ method, projectId, segments = [], request }: MemberRequest) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const path = ["api", "projects", projectId, "members", ...segments]
      .map((segment) => encodeURIComponent(segment))
      .join("/");
    const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
    const init: RequestInit = { method, headers };
    if (method === "POST" && request) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(await readBoundedJson(request));
    }
    return forwardJson(await pdosApiFetch(`/${path}`, init));
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "A bounded JSON object is required");
    }
    return sessionError(503, "PROJECT_MEMBERS_UNAVAILABLE", "Project members unavailable");
  }
}

import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

type WorkItemMethod = "GET" | "PATCH" | "POST";

type ForwardWorkItemOptions<T extends { projectId: string }> = {
  request: Request;
  context: { params: Promise<T> };
  collection: "tasks" | "issues" | "risks";
  method: WorkItemMethod;
  itemParam?: keyof T;
  transition?: boolean;
  preparation?: boolean;
  workCard?: boolean;
  templateFields?: boolean;
  intakeSources?: boolean;
  decisionIntakeSources?: boolean;
};

export async function forwardProjectWorkItem<T extends { projectId: string }>({
  request,
  context,
  collection,
  method,
  itemParam,
  transition = false,
  preparation = false,
  workCard = false,
  templateFields = false,
  intakeSources = false,
  decisionIntakeSources = false,
}: ForwardWorkItemOptions<T>) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");

  try {
    const params = await context.params;
    const segments = [
      "api",
      "projects",
      params.projectId,
      collection,
      ...(itemParam ? [params[itemParam]] : []),
      ...(workCard && method === "GET" ? ["work-card"] : []),
      ...(transition ? ["transitions"] : []),
      ...(decisionIntakeSources && collection === "issues" && method === "GET" ? ["decision-intake-sources"] : []),
      ...(intakeSources && collection === "issues" && method === "GET" ? ["intake-sources"] : []),
      ...(templateFields && ["issues", "tasks", "risks"].includes(collection) ? ["template-fields"] : []),
      ...(preparation && collection === "tasks" && method === "GET" ? ["preparation"] : []),
    ];
    const query = new URLSearchParams();
    if (decisionIntakeSources && method === "GET") for (const key of ["before_created_at", "before_id"]) { const value = new URL(request.url).searchParams.get(key); if (value) query.set(key, value); }
    const path = `/${segments.map((segment) => encodeURIComponent(String(segment))).join("/")}${query.size ? `?${query}` : ""}`;
    const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
    const init: RequestInit = { headers };
    if (method !== "GET") {
      const payload = await readBoundedJson(request);
      init.method = method;
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(payload);
    }
    return forwardJson(await pdosApiFetch(path, init));
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "A bounded JSON object is required");
    }
    return sessionError(503, "WORK_ITEM_SERVICE_UNAVAILABLE", "Work-item service unavailable");
  }
}

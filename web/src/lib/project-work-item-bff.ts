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
};

export async function forwardProjectWorkItem<T extends { projectId: string }>({
  request,
  context,
  collection,
  method,
  itemParam,
  transition = false,
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
      ...(transition ? ["transitions"] : []),
    ];
    const path = `/${segments.map((segment) => encodeURIComponent(String(segment))).join("/")}`;
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

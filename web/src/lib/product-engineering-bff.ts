import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

type ProductEngineeringMethod = "GET" | "POST";

type ForwardProductEngineeringOptions<T extends { projectId: string }> = {
  request: Request;
  context: { params: Promise<T> };
  collection: "boms" | "erp-references" | "specifications";
  method: ProductEngineeringMethod;
  bomItemParam?: keyof T;
};

export async function forwardProductEngineering<T extends { projectId: string }>({
  request,
  context,
  collection,
  method,
  bomItemParam,
}: ForwardProductEngineeringOptions<T>) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");

  try {
    const params = await context.params;
    const segments = [
      "api",
      "projects",
      params.projectId,
      "product-engineering",
      collection,
      ...(bomItemParam ? [params[bomItemParam], "items"] : []),
    ];
    const path = `/${segments.map((segment) => encodeURIComponent(String(segment))).join("/")}`;
    const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
    const init: RequestInit = { headers };
    if (method === "POST") {
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
    return sessionError(
      503,
      "PRODUCT_ENGINEERING_SERVICE_UNAVAILABLE",
      "Product engineering service unavailable",
    );
  }
}

export async function forwardEngineeringReview(method: "GET" | "POST", request: Request, context: { params: Promise<{ projectId: string; reviewPath?: string[] }> }) {
  const { projectId, reviewPath = [] } = await context.params;
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  if (!uuid.test(projectId) || !(reviewPath.length === 0 || (method === "GET" && reviewPath.length === 1 && (["options", "sources"].includes(reviewPath[0]) || uuid.test(reviewPath[0]))))) return sessionError(404, "REVIEW_ROUTE_NOT_FOUND", "评审入口不存在");
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const body = method === "POST" ? await readBoundedJson(request) : undefined;
    const path = `/api/projects/${encodeURIComponent(projectId)}/product-engineering/review-packages${reviewPath.length ? `/${reviewPath.map(encodeURIComponent).join("/")}` : ""}${method === "GET" ? new URL(request.url).search : ""}`;
    return forwardJson(await pdosApiFetch(path, { method, headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) }));
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) return sessionError(400, "INVALID_REQUEST", "评审输入不完整或超出限制");
    return sessionError(503, "ENGINEERING_REVIEW_UNAVAILABLE", "评审资料暂不可用");
  }
}

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

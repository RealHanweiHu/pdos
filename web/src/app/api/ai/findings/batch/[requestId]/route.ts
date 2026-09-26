import { forwardFindingLifecycle } from "@/lib/finding-lifecycle-bff";
import { sessionError } from "@/lib/pdos-api";
export async function GET(_request: Request, context: { params: Promise<{ requestId: string }> }) {
  const { requestId } = await context.params;
  if (!/^[a-f0-9-]{36}$/i.test(requestId)) return sessionError(400, "INVALID_REQUEST", "无效批次请求");
  return forwardFindingLifecycle("GET", `batch/${encodeURIComponent(requestId)}`);
}

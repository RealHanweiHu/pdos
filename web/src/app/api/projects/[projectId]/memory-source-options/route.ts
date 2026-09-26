import { forwardCorrection } from "@/lib/knowledge-corrections-bff";
export async function GET(request: Request, context: { params: Promise<{ projectId: string }> }) {
  const query = new URLSearchParams({ q: new URL(request.url).searchParams.get("q") ?? "" });
  return forwardCorrection(request, (await context.params).projectId, ["memory-source-options"], "GET", query);
}

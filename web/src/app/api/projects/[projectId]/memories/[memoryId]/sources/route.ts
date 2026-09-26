import { forwardCorrection } from "@/lib/knowledge-corrections-bff";
export async function GET(request: Request, context: { params: Promise<{ projectId: string; memoryId: string }> }) {
  const { projectId, memoryId } = await context.params;
  return forwardCorrection(request, projectId, ["memories", memoryId, "sources"], "GET");
}

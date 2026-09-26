import { forwardCorrection } from "@/lib/knowledge-corrections-bff";
export async function POST(request: Request, context: { params: Promise<{ projectId: string; memoryId: string }> }) {
  const { projectId, memoryId } = await context.params;
  return forwardCorrection(request, projectId, ["memories", memoryId, "corrections"], "POST");
}

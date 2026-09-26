import { forwardCorrection } from "@/lib/knowledge-corrections-bff";
export async function GET(request: Request, context: { params: Promise<{ projectId: string }> }) {
  return forwardCorrection(request, (await context.params).projectId, ["knowledge-corrections"], "GET");
}

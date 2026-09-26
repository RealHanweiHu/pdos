import { executionForward } from "@/lib/project-execution-bff";
export async function GET(request: Request, context: { params: Promise<{ projectId: string; recordId: string }> }) {
  const params=await context.params;
  return executionForward(request, params.projectId, "forecast-capacity", params.recordId);
}
export const POST=GET;

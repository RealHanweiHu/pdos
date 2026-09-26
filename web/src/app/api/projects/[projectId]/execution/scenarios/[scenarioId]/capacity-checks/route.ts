import { executionForward } from "@/lib/project-execution-bff";
export async function GET(request: Request, context: { params: Promise<{ projectId: string; scenarioId: string }> }) {
  const { projectId, scenarioId } = await context.params;
  return executionForward(request, projectId, "scenario-capacity", scenarioId);
}
export const POST = GET;

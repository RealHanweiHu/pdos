import { executionForward } from "@/lib/project-execution-bff";

export async function POST(request: Request, context: { params: Promise<{ projectId: string; nodeId: string }> }) {
  const { projectId, nodeId } = await context.params;
  return executionForward(request, projectId, "milestones", nodeId);
}

import { executionForward } from "@/lib/project-execution-bff";

export async function POST(request: Request, context: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await context.params;
  return executionForward(request, projectId, "resource-reallocation-preview");
}

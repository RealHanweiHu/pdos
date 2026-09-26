import { executionForward } from "@/lib/project-execution-bff";
export async function POST(request: Request, context: { params: Promise<{ projectId: string }> }) {
  return executionForward(request, (await context.params).projectId, "commitment-policies");
}

import { executionForward } from "@/lib/project-execution-bff";
export async function GET(request: Request, context: { params: Promise<{ projectId: string }> }) {
  return executionForward(request, (await context.params).projectId, "cross-project-dependencies");
}
export const POST = GET;

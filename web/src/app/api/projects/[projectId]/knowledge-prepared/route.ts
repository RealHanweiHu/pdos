import { forwardKnowledgePush } from "@/lib/knowledge-push-bff";

type Context = { params: Promise<{ projectId: string }> };
export async function GET(request: Request, context: Context) {
  const { projectId } = await context.params;
  return forwardKnowledgePush(request, projectId, true);
}

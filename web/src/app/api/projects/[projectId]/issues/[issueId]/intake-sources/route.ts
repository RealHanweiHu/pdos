import { forwardProjectWorkItem } from "@/lib/project-work-item-bff";
type Context = { params: Promise<{ projectId: string; issueId: string }> };
export function GET(request: Request, context: Context) {
  return forwardProjectWorkItem({ request, context, collection: "issues", itemParam: "issueId", method: "GET", intakeSources: true });
}

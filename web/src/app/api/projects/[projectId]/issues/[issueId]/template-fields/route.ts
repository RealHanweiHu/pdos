import { forwardProjectWorkItem } from "@/lib/project-work-item-bff";
type Context = { params: Promise<{ projectId: string; issueId: string }> };
export function GET(request: Request, context: Context) {
  return forwardProjectWorkItem({ request, context, collection: "issues", itemParam: "issueId", method: "GET", templateFields: true });
}
export function PATCH(request: Request, context: Context) {
  return forwardProjectWorkItem({ request, context, collection: "issues", itemParam: "issueId", method: "PATCH", templateFields: true });
}

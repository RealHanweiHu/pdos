import { forwardProjectWorkItem } from "@/lib/project-work-item-bff";
type Context = { params: Promise<{ projectId: string; riskId: string }> };
export function GET(request: Request, context: Context) {
  return forwardProjectWorkItem({ request, context, collection: "risks", itemParam: "riskId", method: "GET", workCard: true });
}

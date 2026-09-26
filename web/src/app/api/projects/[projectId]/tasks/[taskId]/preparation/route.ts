import { forwardProjectWorkItem } from "@/lib/project-work-item-bff";
export function GET(request: Request, context: { params: Promise<{ projectId: string; taskId: string }> }) {
  return forwardProjectWorkItem({ request, context, collection: "tasks", itemParam: "taskId", method: "GET", preparation: true });
}

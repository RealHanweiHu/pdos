import { forwardProjectWorkItem } from "@/lib/project-work-item-bff";

type Context = { params: Promise<{ projectId: string; taskId: string }> };

export function GET(request: Request, context: Context) {
  return forwardProjectWorkItem({
    request,
    context,
    collection: "tasks",
    itemParam: "taskId",
    method: "GET",
  });
}

export function PATCH(request: Request, context: Context) {
  return forwardProjectWorkItem({
    request,
    context,
    collection: "tasks",
    itemParam: "taskId",
    method: "PATCH",
  });
}

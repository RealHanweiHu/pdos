import { forwardProjectWorkItem } from "@/lib/project-work-item-bff";

type Context = { params: Promise<{ projectId: string; taskId: string }> };

export function POST(request: Request, context: Context) {
  return forwardProjectWorkItem({
    request,
    context,
    collection: "tasks",
    itemParam: "taskId",
    method: "POST",
    transition: true,
  });
}

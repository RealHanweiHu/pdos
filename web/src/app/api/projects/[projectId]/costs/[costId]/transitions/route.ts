import { forwardProjectWorkItem } from "@/lib/project-work-item-bff";

type Context = { params: Promise<{ projectId: string; costId: string }> };

export function POST(request: Request, context: Context) {
  return forwardProjectWorkItem({
    request,
    context,
    collection: "costs",
    itemParam: "costId",
    method: "POST",
    transition: true,
  });
}

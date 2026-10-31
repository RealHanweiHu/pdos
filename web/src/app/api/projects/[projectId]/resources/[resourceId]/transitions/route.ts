import { forwardProjectWorkItem } from "@/lib/project-work-item-bff";

type Context = { params: Promise<{ projectId: string; resourceId: string }> };

export function POST(request: Request, context: Context) {
  return forwardProjectWorkItem({
    request,
    context,
    collection: "resources",
    itemParam: "resourceId",
    method: "POST",
    transition: true,
  });
}

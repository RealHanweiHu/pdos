import { forwardProjectWorkItem } from "@/lib/project-work-item-bff";

type Context = { params: Promise<{ projectId: string; issueId: string }> };

export function POST(request: Request, context: Context) {
  return forwardProjectWorkItem({
    request,
    context,
    collection: "issues",
    itemParam: "issueId",
    method: "POST",
    transition: true,
  });
}

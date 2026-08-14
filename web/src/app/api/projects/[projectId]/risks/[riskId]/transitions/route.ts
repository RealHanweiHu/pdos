import { forwardProjectWorkItem } from "@/lib/project-work-item-bff";

type Context = { params: Promise<{ projectId: string; riskId: string }> };

export function POST(request: Request, context: Context) {
  return forwardProjectWorkItem({
    request,
    context,
    collection: "risks",
    itemParam: "riskId",
    method: "POST",
    transition: true,
  });
}

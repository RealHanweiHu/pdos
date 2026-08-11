import { forwardProjectWorkItem } from "@/lib/project-work-item-bff";

type Context = { params: Promise<{ projectId: string }> };

export function GET(request: Request, context: Context) {
  return forwardProjectWorkItem({ request, context, collection: "tasks", method: "GET" });
}

export function POST(request: Request, context: Context) {
  return forwardProjectWorkItem({ request, context, collection: "tasks", method: "POST" });
}

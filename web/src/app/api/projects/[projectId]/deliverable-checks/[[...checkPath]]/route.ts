import { forwardDeliverableChecks } from "@/lib/deliverable-checks-bff";

type Context = {
  params: Promise<{ projectId: string; checkPath?: string[] }>;
};

export function GET(request: Request, context: Context) {
  return forwardDeliverableChecks("GET", request, context);
}

export function POST(request: Request, context: Context) {
  return forwardDeliverableChecks("POST", request, context);
}

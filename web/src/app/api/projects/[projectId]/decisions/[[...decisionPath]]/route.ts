import { forwardDecisions } from "@/lib/decisions-bff";

type Context = {
  params: Promise<{ projectId: string; decisionPath?: string[] }>;
};

export function GET(request: Request, context: Context) {
  return forwardDecisions("GET", request, context);
}

export function POST(request: Request, context: Context) {
  return forwardDecisions("POST", request, context);
}

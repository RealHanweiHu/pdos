import { forwardChanges } from "@/lib/changes-bff";

type Context = {
  params: Promise<{ projectId: string; changePath?: string[] }>;
};

export function GET(request: Request, context: Context) {
  return forwardChanges("GET", request, context);
}

export function POST(request: Request, context: Context) {
  return forwardChanges("POST", request, context);
}

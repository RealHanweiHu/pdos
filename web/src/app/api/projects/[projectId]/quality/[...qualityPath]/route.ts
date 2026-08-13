import { forwardQuality } from "@/lib/quality-capa-bff";

type Context = {
  params: Promise<{ projectId: string; qualityPath: string[] }>;
};

export function GET(request: Request, context: Context) {
  return forwardQuality("GET", request, context);
}

export function POST(request: Request, context: Context) {
  return forwardQuality("POST", request, context);
}

import { forwardEvidence } from "@/lib/evidence-bff";

type Context = {
  params: Promise<{ evidencePath?: string[] }>;
};

export function GET(request: Request, context: Context) {
  return forwardEvidence("GET", request, context);
}

export function POST(request: Request, context: Context) {
  return forwardEvidence("POST", request, context);
}

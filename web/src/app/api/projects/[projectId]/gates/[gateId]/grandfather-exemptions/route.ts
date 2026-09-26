import { forwardGateDetail } from "@/lib/gate-detail-bff";

type Context = {
  params: Promise<{ projectId: string; gateId: string }>;
};

export function POST(request: Request, context: Context) {
  return forwardGateDetail("grandfather-exemptions", request, context);
}

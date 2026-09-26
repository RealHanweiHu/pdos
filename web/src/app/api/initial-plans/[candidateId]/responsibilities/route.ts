import { planningForward } from "@/lib/planning-bff";
export async function GET(request: Request, context: { params: Promise<{ candidateId: string }> }) {
  return planningForward(request, (await context.params).candidateId, "responsibilities");
}
export const POST = GET;

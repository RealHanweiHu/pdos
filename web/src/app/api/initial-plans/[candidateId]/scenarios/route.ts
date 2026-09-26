import { planningForward } from "@/lib/planning-bff";
export async function GET(request: Request, context: { params: Promise<{ candidateId: string }> }) { const { candidateId } = await context.params; return planningForward(request, candidateId); }
export const POST = GET;

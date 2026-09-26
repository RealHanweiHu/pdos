import { resourceCapacityForward } from "@/lib/capacity-bff";
export async function GET(request: Request, context: { params: Promise<{ candidateId: string; scenarioId: string }> }) {
  const { candidateId, scenarioId } = await context.params;
  return resourceCapacityForward(request, "checks", candidateId, scenarioId);
}
export const POST = GET;

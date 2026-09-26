import { planningForward } from "@/lib/planning-bff";
export async function POST(request: Request, context: { params: Promise<{ candidateId: string; reviewId?: string }> }) {
  const { candidateId, reviewId } = await context.params;
  return planningForward(request, candidateId, "reviews", reviewId);
}

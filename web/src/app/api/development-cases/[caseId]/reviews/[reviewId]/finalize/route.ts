import { forwardCaseReview } from "@/lib/case-review-bff";
export async function POST(request: Request, context: { params: Promise<{ caseId: string; reviewId: string }> }) { const { caseId, reviewId } = await context.params; return forwardCaseReview(request, caseId, "reviews", reviewId, "finalize"); }

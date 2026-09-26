import { forwardCaseReview } from "@/lib/case-review-bff";
export async function POST(request: Request, context: { params: Promise<{ caseId: string }> }) { const { caseId } = await context.params; return forwardCaseReview(request, caseId, "review-policies"); }

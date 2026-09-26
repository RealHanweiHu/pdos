import { forwardCaseReview } from "@/lib/case-review-bff";
export async function GET(request: Request, context: { params: Promise<{ caseId: string }> }) { const { caseId } = await context.params; return forwardCaseReview(request, caseId, "initial-plans"); }
export const POST = GET;

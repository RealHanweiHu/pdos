import { forwardCaseRequirement } from "@/lib/case-requirement-bff";
export async function GET(request: Request, context: { params: Promise<{ requirementId: string }> }) {
  const { requirementId } = await context.params;
  return forwardCaseRequirement(request, requirementId, "case-links");
}

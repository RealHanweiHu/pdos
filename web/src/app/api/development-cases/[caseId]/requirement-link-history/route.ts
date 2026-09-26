import { forwardCaseRequirement } from "@/lib/case-requirement-bff";
export async function GET(request: Request, context: { params: Promise<{ caseId: string }> }) {
  const { caseId } = await context.params;
  return forwardCaseRequirement(request, caseId, "requirement-link-history");
}

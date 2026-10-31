import { forwardProjectMembers } from "@/lib/project-member-bff";

type CandidatesRouteContext = { params: Promise<{ projectId: string }> };

export async function GET(_request: Request, context: CandidatesRouteContext) {
  const { projectId } = await context.params;
  return forwardProjectMembers({ method: "GET", projectId, segments: ["candidates"] });
}

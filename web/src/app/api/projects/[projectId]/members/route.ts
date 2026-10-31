import { forwardProjectMembers } from "@/lib/project-member-bff";

type MembersRouteContext = { params: Promise<{ projectId: string }> };

export async function GET(_request: Request, context: MembersRouteContext) {
  const { projectId } = await context.params;
  return forwardProjectMembers({ method: "GET", projectId });
}

export async function POST(request: Request, context: MembersRouteContext) {
  const { projectId } = await context.params;
  return forwardProjectMembers({ method: "POST", projectId, request });
}

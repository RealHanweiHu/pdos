import { forwardProjectMembers } from "@/lib/project-member-bff";

type MemberRouteContext = { params: Promise<{ projectId: string; userId: string }> };

export async function DELETE(_request: Request, context: MemberRouteContext) {
  const { projectId, userId } = await context.params;
  return forwardProjectMembers({ method: "DELETE", projectId, segments: [userId] });
}

import { forwardCorrection } from "@/lib/knowledge-corrections-bff";
import { sessionError } from "@/lib/pdos-api";
export async function POST(request: Request, context: { params: Promise<{ projectId: string; correctionId: string; action: string }> }) {
  const { projectId, correctionId, action } = await context.params;
  if (!["publish", "reject"].includes(action)) return sessionError(404, "CORRECTION_ACTION_NOT_FOUND", "此知识操作不存在");
  return forwardCorrection(request, projectId, ["knowledge-corrections", correctionId, action], "POST");
}

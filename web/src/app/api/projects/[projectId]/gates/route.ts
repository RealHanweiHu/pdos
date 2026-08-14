import { forwardProjectGateOrDocuments } from "@/lib/project-gate-document-bff";

type Context = { params: Promise<{ projectId: string }> };

export function GET(_: Request, context: Context) {
  return forwardProjectGateOrDocuments({ context, surface: "gates" });
}

import { forwardFindingLifecycle } from "@/lib/finding-lifecycle-bff";
export async function POST(_request: Request, context: { params: Promise<{ findingId: string }> }) {
  return forwardFindingLifecycle("POST", `${encodeURIComponent((await context.params).findingId)}/restore`);
}

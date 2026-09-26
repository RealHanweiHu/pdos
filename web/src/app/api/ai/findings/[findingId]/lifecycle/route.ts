import { forwardFindingLifecycle } from "@/lib/finding-lifecycle-bff";
export async function GET(request: Request, context: { params: Promise<{ findingId: string }> }) {
  const query = new URLSearchParams();
  for (const key of ["before_at", "before_id"]) {
    const value = new URL(request.url).searchParams.get(key); if (value) query.set(key, value);
  }
  return forwardFindingLifecycle("GET", `${encodeURIComponent((await context.params).findingId)}/lifecycle${query.size ? `?${query}` : ""}`);
}

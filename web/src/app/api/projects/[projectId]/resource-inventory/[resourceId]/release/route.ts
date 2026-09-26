import { reservationForward } from "@/lib/reservation-bff";
type Context = { params: Promise<{ projectId: string; resourceId: string }> };
async function forward(request: Request, context: Context) {
  const { projectId, resourceId } = await context.params;
  return reservationForward(request, projectId, resourceId, "allocation-release");
}
export const GET = forward;
export const POST = forward;

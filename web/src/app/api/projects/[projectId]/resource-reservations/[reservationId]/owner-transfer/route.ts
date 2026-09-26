import { reservationForward } from "@/lib/reservation-bff";
type Context = { params: Promise<{ projectId: string; reservationId: string }> };
async function forward(request: Request, context: Context) {
  const params = await context.params;
  return reservationForward(request, params.projectId, params.reservationId, "owner-transfer");
}
export const GET = forward;
export const POST = forward;

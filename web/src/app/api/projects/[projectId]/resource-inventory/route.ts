import { reservationForward } from "@/lib/reservation-bff";
export async function GET(request: Request, context: { params: Promise<{ projectId: string }> }) {
  return reservationForward(request, (await context.params).projectId, undefined, "resource-inventory");
}
export const POST = GET;

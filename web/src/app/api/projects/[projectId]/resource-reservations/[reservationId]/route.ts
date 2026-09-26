import { reservationForward } from "@/lib/reservation-bff";
export async function GET(request: Request, context: { params: Promise<{ projectId: string; reservationId?: string }> }) {
  const { projectId, reservationId } = await context.params;
  return reservationForward(request, projectId, reservationId);
}
export const POST = GET;

import { reservationForward } from "@/lib/reservation-bff";
export async function POST(request: Request, context: { params: Promise<{ projectId: string; reservationId: string }> }) {
  const params=await context.params;
  return reservationForward(request,params.projectId,params.reservationId,"replacement");
}

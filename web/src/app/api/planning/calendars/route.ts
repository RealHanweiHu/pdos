import { planningForward } from "@/lib/planning-bff";
export async function GET(request: Request) { return planningForward(request); }
export const POST = GET;

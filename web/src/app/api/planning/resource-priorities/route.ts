import { resourceCapacityForward } from "@/lib/capacity-bff";
export async function POST(request: Request) { return resourceCapacityForward(request, "resource-priorities"); }
export const GET = POST;

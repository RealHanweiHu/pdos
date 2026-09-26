import { resourceCapacityForward } from "@/lib/capacity-bff";
export async function GET(request: Request) { return resourceCapacityForward(request, "portfolio-health-policies"); }
export async function POST(request: Request) { return resourceCapacityForward(request, "portfolio-health-policies"); }

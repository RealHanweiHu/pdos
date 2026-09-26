import { forwardFindingLifecycle } from "@/lib/finding-lifecycle-bff";
export const POST = () => forwardFindingLifecycle("POST", "archive-stale");

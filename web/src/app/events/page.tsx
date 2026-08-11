import type { Metadata } from "next";

import { EventDebugger } from "@/components/events/event-debugger";

export const metadata: Metadata = { title: "事件流调试 · PDOS" };

export default function EventsPage() {
  return <EventDebugger />;
}

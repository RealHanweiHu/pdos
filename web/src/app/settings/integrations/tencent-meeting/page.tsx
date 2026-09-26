import type { Metadata } from "next";
import { TencentMeetingIntegration } from "@/components/integrations/tencent-meeting-integration";
export const metadata: Metadata = { title: "腾讯会议集成 · PDOS" };
export default function Page() { return <TencentMeetingIntegration />; }

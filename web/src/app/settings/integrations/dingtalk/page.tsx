import type { Metadata } from "next";

import { DingTalkIntegration } from "@/components/integrations/dingtalk-integration";

export const metadata: Metadata = {
  title: "钉钉集成 · PDOS",
  description: "PDOS DingTalk identity and reliable delivery status",
};

export default function DingTalkIntegrationPage() {
  return <DingTalkIntegration />;
}

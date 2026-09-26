import type { Metadata } from "next";

import { AiGovernance } from "@/components/governance/ai-governance";

export const metadata: Metadata = {
  title: "AI 治理 · PDOS",
  description: "PDOS tenant AI usage, capability contract, and touchpoint governance",
};

export default function AiGovernancePage() {
  return <AiGovernance />;
}

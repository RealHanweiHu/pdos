import type { Metadata } from "next";

import { ModelGovernance } from "@/components/governance/model-governance";

export const metadata: Metadata = {
  title: "模型与预算 · PDOS",
  description: "PDOS tenant model qualification and token budget governance",
};

export default function ModelGovernancePage() {
  return <ModelGovernance />;
}

import type { Metadata } from "next";

import { RequirementPool } from "@/components/requirements/requirement-pool";

export const metadata: Metadata = {
  title: "需求池 · PDOS",
  description: "录入、编辑并关联客户需求",
};

export default function RequirementsPage() {
  return <RequirementPool />;
}

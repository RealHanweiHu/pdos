import type { Metadata } from "next";

import { CaseWorkspace } from "@/components/cases/case-workspace";

export const metadata: Metadata = {
  title: "开发案例 · PDOS",
  description: "PDOS Development Case workspace",
};

export default function CasesPage() {
  return <CaseWorkspace />;
}

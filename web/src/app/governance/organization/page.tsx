import type { Metadata } from "next";

import { OrganizationGovernance } from "@/components/organization/organization-governance";

export const metadata: Metadata = {
  title: "组织与代理 · PDOS",
  description: "PDOS tenant organization, leave delegation, and responsibility handover",
};

export default function OrganizationGovernancePage() {
  return <OrganizationGovernance />;
}

import type { Metadata } from "next";

import { AccountSecurity } from "@/components/account/account-security";

export const metadata: Metadata = {
  title: "账户安全 · PDOS",
  description: "Change the current PDOS local account password",
};

export default function AccountSecurityPage() {
  return <AccountSecurity />;
}

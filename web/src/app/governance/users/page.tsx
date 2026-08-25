import type { Metadata } from "next";

import { UserManagement } from "@/components/users/user-management";

export const metadata: Metadata = {
  title: "成员与角色 · PDOS",
  description: "PDOS tenant member account and role administration",
};

export default function UserManagementPage() {
  return <UserManagement />;
}

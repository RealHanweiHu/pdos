import type { Metadata } from "next";
import { InvitationPage } from "@/features/account/invitation-page";

export const metadata: Metadata = { title: "设置密码 · PDOS", referrer: "no-referrer" };
export default function Page() {
  return <InvitationPage/>;
}

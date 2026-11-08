import type { Metadata } from "next";
import { SignInPage } from "@/features/account/sign-in-page";

export const metadata: Metadata = { title: "登录 · PDOS" };
export default function Page() {
  return <SignInPage/>;
}

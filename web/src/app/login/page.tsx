import type { Metadata } from "next";

import { AuthScreen } from "@/components/auth/auth-screen";

export const metadata: Metadata = {
  title: "登录 · PDOS",
  description: "建立 PDOS 租户与用户身份上下文",
};

export default function LoginPage() {
  return <AuthScreen />;
}

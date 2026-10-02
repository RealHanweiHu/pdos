import type { Metadata } from "next";
import { Suspense } from "react";
import { AskWorkspace } from "@/components/ai/ask-workspace";
export const metadata: Metadata = { title: "小Pai · 个人 Agent" };
export default function AskPage() { return <Suspense fallback={<p className="p-6 text-sm">正在打开会话…</p>}><AskWorkspace /></Suspense>; }

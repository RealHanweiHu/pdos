import type { Metadata } from "next";
import { Suspense } from "react";
import { GlobalSearch } from "@/components/search/global-search";

export const metadata: Metadata = { title: "搜索 · PDOS" };
export default function SearchPage() {
  return <Suspense fallback={<p className="p-6 text-sm">正在打开搜索…</p>}><GlobalSearch /></Suspense>;
}

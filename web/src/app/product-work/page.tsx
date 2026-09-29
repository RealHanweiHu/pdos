import { Suspense } from "react";

import type { Metadata } from "next";

import { ProductWorkspace } from "@/components/product-work/product-workspace";

export const metadata: Metadata = { title: "产品管理工作台 · PDOS" };

export default function ProductWorkPage() {
  return <Suspense fallback={<p className="p-6 text-sm">正在打开产品管理工作台…</p>}><ProductWorkspace /></Suspense>;
}

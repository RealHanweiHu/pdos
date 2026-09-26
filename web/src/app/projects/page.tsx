import { Suspense } from "react";

import type { Metadata } from "next";

import { ProjectWorkspace } from "@/components/projects/project-workspace";

export const metadata: Metadata = { title: "项目工作区 · PDOS" };

export default function ProjectsPage() {
  return <Suspense fallback={<p className="p-6 text-sm">正在打开项目工作区…</p>}><ProjectWorkspace /></Suspense>;
}

import type { Metadata } from "next";

import { ProjectWorkspace } from "@/components/projects/project-workspace";

export const metadata: Metadata = { title: "项目工作区 · PDOS" };

export default function ProjectsPage() {
  return <ProjectWorkspace />;
}

"use client";

import Link from "next/link";
import { ArrowUpRightIcon } from "@phosphor-icons/react";
import { useWorkPerspective } from "@/components/workspace-experience";
import type { WorkspaceIdentity } from "@/components/workspace-types";

export function WorkspaceJourney({ identity }: { identity: WorkspaceIdentity }) {
  const { perspective, available } = useWorkPerspective(identity);
  if (!available.length) return null;
  return <details className="mb-5 border-b pb-4" aria-label="当前工作路径">
    <summary className="flex min-h-11 cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 text-sm"><span className="font-medium">{perspective.label}的工作路径</span><span className="text-xs text-muted-foreground">{perspective.description}</span></summary>
    <ol className="grid gap-x-6 gap-y-4 pt-3 sm:grid-cols-2 xl:grid-cols-4">
      {perspective.steps.map((step, index) => <li key={`${step.href}:${step.label}`}><Link className="group block rounded-lg p-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring hover:bg-muted/50" href={step.href}><span className="flex items-center gap-2 text-sm font-medium"><span className="font-mono text-xs text-muted-foreground">{index + 1}</span>{step.label}<ArrowUpRightIcon aria-hidden className="ml-auto size-3.5 text-muted-foreground group-hover:text-foreground"/></span><span className="mt-1.5 block text-xs leading-5 text-muted-foreground">{step.description}</span></Link></li>)}
    </ol>
  </details>;
}

import type { Metadata } from "next";
import { InitialPlanWorkspace } from "@/components/cases/initial-plan-workspace";

export const metadata: Metadata = { title: "计划责任与接续 · PDOS" };

export default async function InitialPlanPage({ params, searchParams }: {
  params: Promise<{ candidateId: string }>;
  searchParams: Promise<{ node?: string }>;
}) {
  const { candidateId } = await params;
  const { node } = await searchParams;
  return <InitialPlanWorkspace key={candidateId} candidateId={candidateId} nodeKey={typeof node === "string" && /^[a-zA-Z0-9_.:-]{1,128}$/.test(node) ? node : undefined}/>;
}

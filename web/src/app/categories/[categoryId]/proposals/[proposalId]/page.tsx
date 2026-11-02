import { headers } from "next/headers";
import { AppShell } from "@/features/shell/app-shell";
import { localPreviewHost } from "@/lib/server/local-preview-server";
import { ProposalDocument } from "@/features/categories/preproject/proposal-document";

export default async function Page({ params }: { params: Promise<{ categoryId: string; proposalId: string }> }) {
  const { categoryId, proposalId } = await params;
  const localSession = Boolean(process.env.PDOS_NEXT_LOCAL_SESSION) && localPreviewHost((await headers()).get("host"));
  return <AppShell documentPage={{ categoryId }} localSession={localSession}><ProposalDocument categoryId={categoryId} proposalId={proposalId} /></AppShell>;
}

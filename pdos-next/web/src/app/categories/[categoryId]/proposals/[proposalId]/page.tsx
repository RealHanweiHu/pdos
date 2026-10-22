import { AppShell } from "@/components/app-shell";
import { ProposalDocument } from "@/components/preproject/proposal-document";

export default async function Page({ params }: { params: Promise<{ categoryId: string; proposalId: string }> }) {
  const { categoryId, proposalId } = await params;
  return <AppShell documentPage={{ categoryId }}><ProposalDocument categoryId={categoryId} proposalId={proposalId} /></AppShell>;
}

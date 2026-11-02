import { AppShell } from "@/features/shell/app-shell";
import { ProposalDocument } from "@/features/categories/preproject/proposal-document";

export default async function Page({ params }: { params: Promise<{ categoryId: string; proposalId: string }> }) {
  const { categoryId, proposalId } = await params;
  return <AppShell documentPage={{ categoryId }}><ProposalDocument categoryId={categoryId} proposalId={proposalId} /></AppShell>;
}

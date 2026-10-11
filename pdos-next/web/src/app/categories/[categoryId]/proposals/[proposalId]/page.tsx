import { ProposalDocument } from "@/components/preproject/proposal-document";

export default async function Page({ params }: { params: Promise<{ categoryId: string; proposalId: string }> }) {
  const { categoryId, proposalId } = await params;
  return <ProposalDocument categoryId={categoryId} proposalId={proposalId} />;
}

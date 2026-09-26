import { CaseReviewWorkspace } from "@/components/cases/case-review-workspace";

export default async function CaseReviewPage({ params, searchParams }: {
  params: Promise<{ caseId: string }>;
  searchParams: Promise<{ review?: string; policy?: string }>;
}) {
  const { caseId } = await params;
  const { review, policy } = await searchParams;
  return <CaseReviewWorkspace caseId={caseId} reviewId={review} policyId={policy}/>;
}

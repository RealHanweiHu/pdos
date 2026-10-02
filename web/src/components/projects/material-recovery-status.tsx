"use client";

export type MaterialClosureState = {
  ready: boolean; review_current: boolean; supply_ready: boolean; reasons: string[];
  reference: { exception_id: string; review_id: string; source_digest: string } | null;
};

export function MaterialRecoveryStatus({ projectId, issueId, closure, current }: {
  projectId: string; issueId: string; closure?: MaterialClosureState; current: boolean;
}) {
  if (!closure) return null;
  const reference = current && closure.ready ? closure.reference : null;
  const query = new URLSearchParams({ project: projectId, tab: "work-items", entity_id: issueId });
  if (reference) {
    query.set("material_exception_id", reference.exception_id);
    query.set("material_review_id", reference.review_id);
    query.set("material_source_digest", reference.source_digest);
  }
  return <section className="space-y-1 rounded-md border p-2 text-xs" aria-label="原异常恢复核对">
    <p className="font-medium">{reference ? "当前供给恢复已具名复核" : "原异常恢复尚待当前复核"}</p>
    {!current && <p>口径已变化，请先刷新当前依据。</p>}
    {closure.reasons.map(reason => <p key={reason}>{reason}</p>)}
    <p>供给观察及恢复核对保留历史；原问题须按关闭判据由具名验证人办理。</p>
    {reference && <a className="text-primary underline"
      href={`/projects?${query.toString()}#issue-${issueId}`}>到原问题进行具名验证</a>}
  </section>;
}

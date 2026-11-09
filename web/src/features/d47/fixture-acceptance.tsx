"use client";
// D306 (P95 第 5 项): named manufacturing acceptance of one imported fixture for one
// purpose and operation. Accept, reject or revoke; each is a new version.
import { useCallback, useEffect, useRef, useState } from "react";
import { SealCheck } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { NamedCommandReview } from "@/features/projects/named-command-review";
import { makeCommand } from "@/lib/named-command";
import type { ProjectApi } from "@/lib/project-plan-view";
import { fixtureStateNames, isoFromLocal, splitLines, timeText } from "@/lib/d47-records";
import { useNamedAction } from "./use-named-action";

type Acceptance = { id: string; revision: number; state: string; resource: { id: string; revision: number }; purpose: string; operation_id: string; valid_until: string | null; conditions: string[]; reason: string | null; recorded_at: string };
type Props = { api: ProjectApi; product: { id: string; revision: number }; build: { id: string; project_id: string }; resource: { id: string; revision: number }; purpose: string; operationId: string };

export function FixtureAcceptance({ api, product, build, resource, purpose, operationId }: Props) {
  const action = useNamedAction(api);
  const { setError } = action;
  const [current, setCurrent] = useState<Acceptance | null | undefined>(undefined);
  const [until, setUntil] = useState(""), [conditions, setConditions] = useState(""), [reason, setReason] = useState("");
  const alive = useRef(true);
  const refresh = useCallback(async () => {
    const value = await api<{ items: Acceptance[] }>(`v1/products/${product.id}/projects/${build.project_id}/fixture-acceptances`);
    const found = value.items.find(row => row.resource.id === resource.id && row.purpose === purpose && row.operation_id === operationId) ?? null;
    if (alive.current) setCurrent(found);
  }, [api, product.id, build.project_id, resource.id, purpose, operationId]);
  useEffect(() => { alive.current = true; void Promise.resolve().then(() => alive.current ? refresh() : undefined).catch(failure => setError((failure as Error).message)); return () => { alive.current = false; }; }, [refresh, setError]);
  function decide(kind: "accept" | "reject" | "revoke") {
    void action.start(() => {
      if (!reason.trim()) throw new Error("请写明验收理由。");
      const common = { action: kind, reason: reason.trim(), ...(kind === "accept" ? { valid_until: isoFromLocal(until), conditions: splitLines(conditions) } : {}) };
      const payload = current ? { acceptance: { id: current.id, revision: current.revision }, ...common } : { ...common, scope: { build_id: build.id, resource: { id: resource.id, revision: resource.revision }, purpose, operation_id: operationId } };
      return makeCommand(product, "npi.fixture.accept", payload);
    }, "T2");
  }
  return <div className="space-y-2 rounded-lg border border-border p-2 text-sm" aria-label="治具验收">
    <p className="flex items-center gap-1 font-medium"><SealCheck aria-hidden size={14}/>治具验收（制造具名）：{current === undefined ? "读取中…" : current ? `${fixtureStateNames[current.state]} · v${current.revision} · 有效至 ${timeText(current.valid_until)}` : "尚无验收，准备度显示未知"}</p>
    {current?.conditions?.length ? <p className="subtle text-xs">条件：{current.conditions.join("；")}</p> : null}
    {action.error && <p role="alert" className="text-xs text-destructive [overflow-wrap:anywhere]">{action.error}</p>}
    {action.notice && <p role="status" className="text-xs">{action.notice}</p>}
    {action.prepared ? <NamedCommandReview prepared={action.prepared} busy={action.busy} onCancel={action.cancel} onConfirm={() => void action.confirm("fixture_acceptance", "治具验收已保存，准备度按新决定计算。", refresh)}/> : <>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="block text-xs">有效期至（接受时可选）<input type="datetime-local" value={until} onChange={e => setUntil(e.target.value)}/></label>
        <label className="block text-xs">理由<input value={reason} onChange={e => setReason(e.target.value)}/></label>
      </div>
      <label className="block text-xs">条件（接受时可选，每行一条）<textarea value={conditions} onChange={e => setConditions(e.target.value)}/></label>
      <div className="flex flex-wrap gap-2">
        {(!current || current.state !== "accepted" || until) && <Button size="sm" variant="outline" disabled={action.busy} onClick={() => decide("accept")}>接受</Button>}
        {(!current || current.state === "accepted") && <Button size="sm" variant="outline" disabled={action.busy} onClick={() => decide("reject")}>拒绝</Button>}
        {current?.state === "accepted" && <Button size="sm" variant="ghost" disabled={action.busy} onClick={() => decide("revoke")}>撤销验收</Button>}
      </div></>}
  </div>;
}

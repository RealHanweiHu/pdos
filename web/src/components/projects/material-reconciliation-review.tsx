"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Preview = {
  digest: string;
  eligible: boolean;
  reasons: string[];
  basis: { previous_version: number; evidence: { filename: string } };
};

async function request<T>(path: string, body: object): Promise<T> {
  const response = await fetch(path, {
    method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const value: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new Error(
    isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string"
      ? value.detail.message : "余额核对未完成，请刷新当前来源或核对权限",
  );
  return value as T;
}

export function MaterialReconciliationReview({ projectId, sourceId, movementId, evidenceId,
  hasReview, onSaved }: {
  projectId: string; sourceId: string; movementId: string; evidenceId: string;
  hasReview: boolean; onSaved: () => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const [outcome, setOutcome] = useState("confirmed");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewKey, setPreviewKey] = useState("");
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const ids = useRef(new Map<string, string>());
  const path = `/api/projects/${projectId}/npi/material-movements/${movementId}/reconcile`;
  const selection = { supply_snapshot_id: sourceId, evidence_id: evidenceId, outcome, reason };
  const key = JSON.stringify({ projectId, movementId, ...selection });
  const current = preview !== null && key === previewKey;

  async function act(work: () => Promise<void>) {
    setBusy(true); setError(null);
    try { await work(); } catch (failure) {
      setError(failure instanceof Error ? failure.message : "余额核对未完成");
    } finally { setBusy(false); }
  }

  async function prepare(value: "confirmed" | "withdrawn") {
    const command = { ...selection, outcome: value };
    setChecked(false);
    const observed = await request<Preview>(`${path}/preview`, command);
    setOutcome(value); setPreview(observed);
    setPreviewKey(JSON.stringify({ projectId, movementId, ...command }));
  }

  async function save() {
    if (!preview || !current || !checked) return;
    const command = { ...selection, expected_version: preview.basis.previous_version,
      expected_digest: preview.digest };
    const signature = JSON.stringify({ projectId, movementId, ...command });
    let id = ids.current.get(signature);
    if (!id) { id = crypto.randomUUID(); ids.current.set(signature, id); }
    await request(path, { ...command, request_id: id });
    setNotice(outcome === "confirmed" ? "当前余额包含关系已具名保存。" : "原核对已具名撤回。");
    setChecked(false); await onSaved();
  }

  return <fieldset disabled={busy} className="space-y-2">
    <label className="block">ERP原交易与余额包含关系／撤回理由
      <textarea className="mt-1 w-full rounded-md border bg-background p-2 text-sm"
        maxLength={2048} value={reason} onChange={event => {
          setReason(event.target.value); setChecked(false);
        }}/>
    </label>
    <div className="flex flex-wrap gap-2">
      <Button size="sm" variant="outline" disabled={!evidenceId || !reason.trim()}
        onClick={() => void act(() => prepare("confirmed"))}>预览余额包含关系</Button>
      {hasReview && <Button size="sm" variant="outline" disabled={!evidenceId || !reason.trim()}
        onClick={() => void act(() => prepare("withdrawn"))}>预览撤回原核对</Button>}
    </div>
    {preview && <div className="space-y-2 rounded-md border p-2">
      <p>{current ? "当前具名预览" : "输入或证据已变化，请重新预览"} · {preview.basis.evidence.filename}</p>
      {preview.reasons.map(value => <p key={value} className="text-destructive">{value}</p>)}
      <p>原库存快照保留；仅记录所列出入库与本版余额的包含关系。</p>
      <label className="block"><input type="checkbox" disabled={!current}
        checked={current && checked} onChange={event => setChecked(event.target.checked)}/>
        已核对本版余额、全部所列出入库和所选原件，确认具名办理
      </label>
      <Button size="sm" disabled={!current || !checked || (outcome === "confirmed" && !preview.eligible)}
        onClick={() => void act(save)}>{outcome === "confirmed" ? "确认本版余额已反映" : "确认撤回原核对"}</Button>
    </div>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {notice && <p role="status">{notice}</p>}
  </fieldset>;
}

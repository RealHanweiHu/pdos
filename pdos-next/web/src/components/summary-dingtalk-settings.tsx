"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import type { WorkspaceApi } from "@/lib/automation-rules";
import type { SummarySelection } from "@/lib/personal-summary";
import { readSummaryChannels, readSummaryReceipts, reconcileSummaryReceipt, type SummaryChannelOptions, type SummaryDeliveryReceipt } from "@/lib/summary-channels";

export function SummaryDingTalkSettings(props: { api: WorkspaceApi; principalId: string; choice: SummarySelection; change: (choice: SummarySelection) => void }) {
  const [identity, setIdentity] = useState({ api: props.api, principalId: props.principalId, revision: 0 });
  if (identity.api !== props.api || identity.principalId !== props.principalId) { setIdentity({ api: props.api, principalId: props.principalId, revision: identity.revision + 1 }); return null; }
  return <Settings key={identity.revision} {...props}/>;
}
function Settings({ api, principalId, choice, change }: { api: WorkspaceApi; principalId: string; choice: SummarySelection; change: (choice: SummarySelection) => void }) {
  const [options, setOptions] = useState<SummaryChannelOptions | null>(null), [receipts, setReceipts] = useState<SummaryDeliveryReceipt[] | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const latest = useRef(0);
  async function read(kind: "bindings" | "receipts") { const stamp = ++latest.current; setBusy(true); setError(""); try { if (kind === "bindings") { setOptions(null); const v = await readSummaryChannels(api, principalId); if (stamp === latest.current) setOptions(v); } else { setReceipts(null); const v = await readSummaryReceipts(api, principalId); if (stamp === latest.current) setReceipts(v); } } catch (e) { if (stamp === latest.current) setError(e instanceof Error ? e.message : "暂未读取到当前记录。"); } finally { if (stamp === latest.current) setBusy(false); } }
  async function reconcile(id: string) { setBusy(true); setError(""); try { const value = await reconcileSummaryReceipt(api, id); setReceipts(rows => rows?.map(row => row.delivery_id === id ? value : row) ?? null); } catch (e) { setError(e instanceof Error ? e.message : "原投递回执尚未核实。"); } finally { setBusy(false); } }
  function select(bindingId: string) { const next = { ...choice }; delete next.dingtalk_binding_id; if (bindingId) next.dingtalk_binding_id = bindingId; change(next); }
  const labels = { planned: "等待投递", sending: "已登记发送", delivered: "已送达", unknown: "结果待核对", blocked: "已阻止", cancelled: "已取消" };
  return <section className="space-y-3 rounded-lg border p-3 text-sm" aria-label="本人摘要投递"><h4 className="font-medium">摘要投递</h4><p className="text-muted-foreground">默认保留在本人站内摘要。可同时私发至本人已验证的钉钉账号，随此规则预览和一次确认启用；暂停新受理、账号撤销与应用停用仍按原记录办理。</p><Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void read("bindings")}>读取本人钉钉绑定</Button><label className="block">投递位置<select className="mt-1 w-full rounded-lg border bg-background p-2" value={choice.dingtalk_binding_id ?? ""} onChange={e => select(e.target.value)}><option value="">仅站内摘要</option>{options?.configured && options.bindings.map(b => <option key={b.binding_id} value={b.binding_id}>站内及本人钉钉单聊 · 绑定第 {b.epoch} 版</option>)}{choice.dingtalk_binding_id && !options?.bindings.some(b => b.binding_id === choice.dingtalk_binding_id) && <option value={choice.dingtalk_binding_id}>原本人绑定（请重新读取核对）</option>}</select></label>{options && (!options.configured || !options.bindings.length) && <p className="text-muted-foreground">当前没有可用本人投递绑定，请到钉钉设置完成绑定；站内摘要仍可使用。</p>}<details><summary className="cursor-pointer">本人摘要投递回执</summary><div className="mt-2 space-y-2"><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void read("receipts")}>读取摘要投递回执</Button>{receipts?.map(row => <div className="flex flex-wrap items-center gap-2 break-all" key={row.delivery_id}><span>{labels[row.state]} · {row.run_id} · 发送登记 {row.attempts} 次</span>{["sending", "unknown"].includes(row.state) && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void reconcile(row.delivery_id)}>只查询原回执</Button>}{row.error_code && <span className="text-muted-foreground">{row.error_code}</span>}</div>)}{receipts?.length === 0 && <p>尚无本人摘要外部投递。</p>}</div></details>{error && <p role="alert" className="text-destructive">{error}</p>}</section>;
}

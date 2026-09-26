"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { WorkspaceShell } from "@/components/workspace-shell";
import { isRecord, requestIdentity, responseBody } from "@/components/workspace-api";
import type { WorkspaceIdentity } from "@/components/workspace-types";

type Person = { id: string; display_name: string; username: string; is_active: boolean };
type Binding = { id: string; version: number; status: string; app_id: string; sdk_id: string; external_user_id: string; external_display_name: string; actor_name: string; evidence: string; created_at: string };
type Data = { current: Binding | null; person: Person; is_self: boolean; can_manage: boolean; configured: boolean; enabled: boolean; app_id: string | null; sdk_id: string | null; items: Binding[]; next_before_version: number | null; users: Person[]; more_users: boolean };
type Command = { request_id: string; user_id: string; expected_binding_id: string | null; action: "register" | "confirm" | "revoke"; external_user_id: string | null; external_display_name: string | null; evidence: string; identity_checked: true };
const labels: Record<string, string> = { pending: "待本人确认", active: "本人已确认", revoked: "已撤销" };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
class RequestError extends Error { constructor(message: string, readonly status: number) { super(message); } }
async function request(query = "", body?: object) {
  const response = await fetch(`/api/integrations/tencent-meeting/bindings${query ? `?${query}` : ""}`, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const value: unknown = await responseBody(response);
  if (!response.ok) throw new RequestError(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "账号映射读取或保存失败", response.status);
  if (!isRecord(value)) throw new Error("尚未收到完整回执，请按原请求重试");
  return value;
}
function dataValue(value: Record<string, unknown>): Data {
  if (!isRecord(value.person) || !Array.isArray(value.items) || !Array.isArray(value.users) || typeof value.can_manage !== "boolean") throw new Error("账号映射资料未完整载入");
  return value as Data;
}
export function TencentMeetingIntegration() {
  const router = useRouter();
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null), [data, setData] = useState<Data | null>(null), [busy, setBusy] = useState(false), [loggingOut, setLoggingOut] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [search, setSearch] = useState(""), [externalId, setExternalId] = useState(""), [externalName, setExternalName] = useState(""), [evidence, setEvidence] = useState(""), [ack, setAck] = useState(false);
  const [command, setCommand] = useState<Command | null>(null), [pending, setPending] = useState(false);
  useEffect(() => {
    let active = true;
    requestIdentity().then(async who => { if (!active) return; if (!who) { router.replace("/login"); return; } setIdentity(who); const next = dataValue(await request()); if (active) { setData(next); setExternalId(next.current?.external_user_id ?? ""); setExternalName(next.current?.external_display_name ?? ""); } }).catch(error => { if (active) setError(error instanceof Error ? error.message : "读取失败"); });
    return () => { active = false; };
  }, [router]);
  async function load(user = data?.person.id, before?: number) {
    setBusy(true); setError("");
    const query = new URLSearchParams(); if (user) query.set("user_id", user); if (search) query.set("q", search); if (before) query.set("before_version", String(before));
    try { const next = dataValue(await request(query.toString())); setData(old => before && old ? { ...next, items: [...old.items, ...next.items] } : next); if (!before) { setExternalId(next.current?.external_user_id ?? ""); setExternalName(next.current?.external_display_name ?? ""); setEvidence(""); setAck(false); } }
    catch (error) { setError(error instanceof Error ? error.message : "读取失败"); } finally { setBusy(false); }
  }
  function preview(action: Command["action"]) {
    if (!data) return;
    setNotice(""); setCommand({ request_id: crypto.randomUUID(), user_id: data.person.id, expected_binding_id: data.current?.id ?? null, action, external_user_id: action === "register" ? externalId.trim() : null, external_display_name: action === "register" ? externalName.trim() : null, evidence, identity_checked: true });
  }
  async function save() {
    if (!command) return;
    setBusy(true); setPending(true); setError("");
    try { const value = await request("", command); if (value.id !== command.request_id || typeof value.version !== "number") throw new Error("未收到完整回执，请重试原请求"); setPending(false); setCommand(null); setNotice(`账号映射 v${value.version} 已保存；${labels[String(value.status)] ?? value.status}。`); await load(); }
    catch (error) { setError(error instanceof Error ? error.message : "结果待确认"); if (error instanceof RequestError && [400, 401, 403, 404, 409, 422].includes(error.status)) { setPending(false); setCommand(null); } } finally { setBusy(false); }
  }
  async function logout() { setLoggingOut(true); try { await fetch("/api/session/logout", { method: "POST" }); } finally { router.replace("/login"); } }
  const frozen = busy || !!command || pending;
  const content = <div className="mx-auto max-w-3xl space-y-5 py-5"><header><h1 className="text-xl font-semibold">腾讯会议企业账号</h1><p className="mt-2 text-sm text-muted-foreground">管理员核对企业通讯录后登记，员工本人确认自己的账号。预约操作在项目会议页面单独预览并提交。</p></header>
    {error && <p role="alert" className="text-destructive">{error}</p>}{notice && <p role="status">{notice}</p>}<div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" disabled={frozen} onClick={() => void load()}>刷新账号资料</Button>{identity && <Button variant="ghost" size="sm" disabled={frozen} onClick={() => void load(identity.user.id)}>查看本人映射</Button>}</div>
    {data && <><p className="text-sm">{data.configured ? `企业应用 ${data.app_id}${data.sdk_id ? ` · ${data.sdk_id}` : ""} 已配置` : "当前租户的企业应用尚未配置，请由管理员配置服务端凭据。"} · {data.enabled ? "预约队列已启用" : "预约队列关闭"}</p>
      {data.can_manage && <fieldset disabled={frozen} className="space-y-3 rounded-lg border p-4"><legend className="px-1 text-sm font-medium">选择需要登记的内部人员</legend><div className="flex items-end gap-2"><label className="flex-1 text-sm">搜索姓名或账号<input className={field} maxLength={100} value={search} onChange={e => setSearch(e.target.value)}/></label><Button variant="outline" size="sm" onClick={() => void load()}>搜索</Button></div><label className="block text-sm">人员<select className={field} value={data.person.id} onChange={e => void load(e.target.value)}>{!data.users.some(u => u.id === data.person.id) && <option value={data.person.id}>{data.person.display_name} · {data.person.username}</option>}{data.users.map(user => <option key={user.id} value={user.id}>{user.display_name} · {user.username}{!user.is_active ? "（已停用）" : ""}</option>)}</select></label>{data.more_users && <p className="text-xs">仅列出前50项，请缩小姓名或账号搜索范围。</p>}</fieldset>}
      <section className="space-y-3 rounded-lg border p-4"><h2 className="font-medium">{data.person.display_name} · {data.person.username}</h2>{data.current ? <div className="space-y-1 text-sm"><p>v{data.current.version} · {labels[data.current.status]}</p><p>腾讯企业用户：{data.current.external_display_name} · {data.current.external_user_id}</p><p>原企业应用：{data.current.app_id} · {data.current.sdk_id || "无子应用"}</p><p>{data.current.actor_name} · {new Date(data.current.created_at).toLocaleString("zh-CN")}</p><p>{data.current.evidence}</p></div> : <p className="text-sm">尚未登记腾讯会议企业账号。</p>}
        <fieldset disabled={frozen} className="space-y-3 text-sm">{data.can_manage && data.person.is_active && <><label className="block">已核对的企业用户 ID<input className={field} value={externalId} maxLength={256} onChange={e => setExternalId(e.target.value)}/></label><label className="block">企业通讯录中的姓名<input className={field} value={externalName} maxLength={256} onChange={e => setExternalName(e.target.value)}/></label></>}
          <label className="block">本次核对或撤销依据<textarea className={field} value={evidence} maxLength={2048} onChange={e => setEvidence(e.target.value)}/></label><label className="flex items-start gap-2"><input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)}/>我已核对所选人员、企业应用、用户ID及本次操作。</label>
          <div className="flex flex-wrap gap-2">{data.can_manage && data.person.is_active && <Button size="sm" disabled={!data.configured || !ack || !evidence.trim() || !externalId.trim() || !externalName.trim()} onClick={() => preview("register")}>预览登记新版本</Button>}{data.is_self && data.current?.status === "pending" && <Button size="sm" disabled={!data.configured || !ack || !evidence.trim()} onClick={() => preview("confirm")}>预览确认本人账号</Button>}{data.current && data.current.status !== "revoked" && <Button variant="outline" size="sm" disabled={!ack || !evidence.trim()} onClick={() => preview("revoke")}>预览撤销映射</Button>}</div>
        </fieldset>
      </section>
      {command && <section className="space-y-3 rounded-lg border border-primary p-4 text-sm"><h2 className="font-medium">{command.action === "register" ? "登记新映射，等待本人确认" : command.action === "confirm" ? "确认这是本人的腾讯企业账号" : "撤销当前映射"}</h2><p>内部人员：{data.person.display_name} · {data.person.username}</p>{command.action === "register" ? <><p>原映射：{data.current ? `${data.current.external_display_name} · ${data.current.external_user_id}（${data.current.app_id}）` : "无"}</p><p>新映射：{command.external_display_name} · {command.external_user_id} · 企业应用 {data.app_id}</p></> : <p>账号：{data.current?.external_display_name} · {data.current?.external_user_id} · 企业应用 {data.current?.app_id}</p>}<p>{command.evidence}</p><p>{command.action === "register" ? "保存后需要该员工本人确认。" : command.action === "revoke" ? "后续请求将重新检查账号映射，已有外部会议及回执保留。" : "确认后可以在项目会议中以本人身份提交预约操作。"}</p><Button size="sm" disabled={busy} onClick={() => void save()}>{pending ? "按原请求核对回执" : "确认保存"}</Button>{!pending && <Button variant="ghost" size="sm" disabled={busy} onClick={() => setCommand(null)}>返回修改</Button>}</section>}
      <details className="rounded-lg border p-4"><summary className="cursor-pointer font-medium">账号映射历史</summary>{data.items.map(item => <article key={item.id} className="mt-3 border-t pt-3 text-sm"><p>v{item.version} · {labels[item.status]} · {item.actor_name} · {new Date(item.created_at).toLocaleString("zh-CN")}</p><p>{item.external_display_name} · {item.external_user_id} · 企业应用 {item.app_id}</p><p>{item.evidence}</p></article>)}{data.next_before_version && <Button variant="outline" size="sm" className="mt-3" disabled={frozen} onClick={() => void load(data.person.id, data.next_before_version ?? undefined)}>更早版本</Button>}</details>
    </>}
  </div>;
  return identity ? <WorkspaceShell active="tencent-meeting-integration" identity={identity} loggingOut={loggingOut} onLogout={() => void logout()}>{content}</WorkspaceShell> : <main className="p-6">{error || "正在读取账号资料…"}</main>;
}

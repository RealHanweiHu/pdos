"use client";
import { RetirementFeedback } from "./retirement-feedback";
import { WorkResponsibility } from "./work-responsibility";

import { useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { command, request, type Evidence, type ProductCatalog, type ProductNode, type Workspace } from "./product-work-api";

const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const levels: Record<string, string> = { line: "产品线", family: "产品族", platform: "平台", series: "系列", model: "型号", variant: "变体" };
const life: Record<string, string> = { proposed: "拟议", developing: "开发中", available: "在售 / 可供应", retired: "已退役" };
const nextLevel: Record<string, string> = { line: "family", family: "platform", platform: "series", series: "model", model: "variant" };
const accessLabels: Record<string, string> = { viewer: "只读", contributor: "协作", manager: "管理" };
const lines = (value: FormDataEntryValue | null) => String(value ?? "").split("\n").map((item) => item.trim()).filter(Boolean);
type Act = (work: () => Promise<unknown>) => Promise<void>;

export function ProductTree({ catalog, workspace, base, busy, act, refresh, onResponsibilityLock, evidence = [] }: { evidence?: Evidence[]; catalog: ProductCatalog; workspace: Workspace; base: string; busy: boolean; act: Act; refresh: () => Promise<void>; onResponsibilityLock: (value: boolean) => void }) {
  const [ownerLock, setOwnerLock] = useState<string | null>(null);
  const working = busy || !!ownerLock;
  const [createParent, setCreateParent] = useState<ProductNode | "root" | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const creation = useRef({ body: "", id: "" });
  const managedLines = catalog.nodes.filter((node) => node.level === "line" && catalog.line_access[node.id]?.can_manage);
  const ownerMembers = (lineId: string | null) => workspace.members.filter((member) => member.access !== "viewer" && (!lineId || catalog.members.some((grant) => grant.product_line_id === lineId && grant.user_id === member.id && grant.access !== "viewer")));
  const selectedNode = catalog.nodes.find((node) => node.id === editing);
  const renderBranch = (parentId: string | null): ReactNode => {
    const children = catalog.nodes.filter((node) => node.parent_id === parentId);
    return children.length ? <ul className={parentId ? "ml-3 space-y-2 border-l pl-3 sm:ml-5" : "space-y-3"}>{children.map((node) => <li key={node.id} className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3"><div><p className="font-medium">{node.name} <span className="text-xs text-muted-foreground">{node.code}</span></p><p className="text-xs text-muted-foreground">{levels[node.level]} · {life[node.lifecycle]} · {workspace.members.find((member) => member.id === node.owner_user_id)?.display_name ?? "负责人当前不可用"} · v{node.version}</p>{(node.regions.length > 0 || node.channels.length > 0) && <p className="text-xs">地区：{node.regions.join("、") || "待定义"} · 渠道：{node.channels.join("、") || "待定义"}</p>}</div>
        {catalog.line_access[node.product_line_id]?.can_manage && <div className="flex gap-2"><Button size="sm" variant="outline" disabled={working} onClick={() => setEditing(editing === node.id ? null : node.id)}>编辑</Button>{nextLevel[node.level] && node.lifecycle !== "retired" && <Button size="sm" variant="outline" disabled={working} onClick={() => setCreateParent(node)}>新增{levels[nextLevel[node.level]]}</Button>}</div>}
      </div><WorkResponsibility spaceId={workspace.space.id} kind="node" recordId={node.id} disabled={busy || !!editing || !!createParent || (!!ownerLock && ownerLock !== node.id)} onLock={value => { setOwnerLock(value ? node.id : null); onResponsibilityLock(value); }} onChanged={refresh}/><RetirementFeedback base={base} productId={node.id} evidence={evidence} disabled={working}/>{renderBranch(node.id)}
    </li>)}</ul> : null;
  };
  return <section className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">产品层级</h3>{catalog.can_create_line && <Button size="sm" disabled={working} onClick={() => setCreateParent("root")}>新建产品线</Button>}</div>
    <p className="text-sm text-muted-foreground">产品线 → 产品族 → 平台 → 系列 → 型号 → 变体。产品编号保持稳定；产品线内的研究与专业工作按成员权限分配。</p>
    {catalog.nodes.length === 0 ? <p className="text-sm text-muted-foreground">当前没有可访问的产品线。</p> : renderBranch(null)}
    {createParent && <form key={createParent === "root" ? "root" : createParent.id} className="grid gap-3 rounded-lg border p-4 sm:grid-cols-2" onSubmit={(event) => {
      event.preventDefault(); const form = new FormData(event.currentTarget); const parent = createParent === "root" ? null : createParent;
      const body = { code: String(form.get("code")).trim(), name: String(form.get("name")).trim(), level: parent ? nextLevel[parent.level] : "line", parent_id: parent?.id ?? null, owner_user_id: form.get("owner"), regions: lines(form.get("regions")), channels: lines(form.get("channels")) };
      const serialized = JSON.stringify(body); if (creation.current.body !== serialized) creation.current = { body: serialized, id: crypto.randomUUID() };
      void act(async () => { await request(`${base}/products`, "POST", { ...body, request_id: creation.current.id }); setCreateParent(null); });
    }}>
      <h4 className="font-medium sm:col-span-2">{createParent === "root" ? "新建产品线" : `为 ${createParent.name} 新增${levels[nextLevel[createParent.level]]}`}</h4>
      <label className="text-sm">产品编号<input name="code" required maxLength={128} pattern="[a-zA-Z0-9_.:-]+" className={field} /></label><label className="text-sm">名称<input name="name" required maxLength={2048} className={field} /></label>
      <label className="text-sm">负责人<select name="owner" required className={field} defaultValue={workspace.current_user_id}><option value="">请选择</option>{ownerMembers(createParent === "root" ? null : createParent.product_line_id).map((member) => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label>
      <p className="self-center text-xs text-muted-foreground">新产品线会为创建者和负责人登记管理权限。其余成员需另行加入产品线。</p>
      <label className="text-sm">地区代码（每行一项，如 CN）<textarea name="regions" className={field} /></label><label className="text-sm">渠道代码（每行一项，如 retail）<textarea name="channels" className={field} /></label>
      <div className="flex gap-2"><Button disabled={working}>创建</Button><Button type="button" variant="outline" onClick={() => setCreateParent(null)}>取消</Button></div>
    </form>}
    {selectedNode && <form key={`${selectedNode.id}:${selectedNode.version}`} className="grid gap-3 rounded-lg border p-4 sm:grid-cols-2" onSubmit={(event) => {
      event.preventDefault(); const form = new FormData(event.currentTarget);
      void act(async () => { await request(`${base}/products/${selectedNode.id}/changes`, "POST", { ...command(selectedNode), name: String(form.get("name")).trim(), owner_user_id: form.get("owner"), lifecycle: form.get("lifecycle"), regions: lines(form.get("regions")), channels: lines(form.get("channels")), reason: String(form.get("reason")).trim() }); setEditing(null); });
    }}>
      <h4 className="font-medium sm:col-span-2">编辑 {selectedNode.code}</h4><label className="text-sm">名称<input name="name" required maxLength={2048} defaultValue={selectedNode.name} className={field} /></label>
      <label className="text-sm">生命周期<select name="lifecycle" defaultValue={selectedNode.lifecycle} className={field}>{Object.entries(life).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label className="text-sm">负责人<select name="owner" defaultValue={selectedNode.owner_user_id} className={field}>{ownerMembers(selectedNode.product_line_id).filter((member) => selectedNode.level !== "line" || catalog.members.some((grant) => grant.product_line_id === selectedNode.id && grant.user_id === member.id && grant.access === "manager")).map((member) => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label>
      <label className="text-sm">变更原因<textarea name="reason" required maxLength={2048} className={field} /></label>
      <label className="text-sm">地区代码<textarea name="regions" defaultValue={selectedNode.regions.join("\n")} className={field} /></label><label className="text-sm">渠道代码<textarea name="channels" defaultValue={selectedNode.channels.join("\n")} className={field} /></label>
      <div className="flex gap-2"><Button disabled={working}>保存新版本</Button><Button type="button" variant="outline" onClick={() => setEditing(null)}>取消</Button></div>
    </form>}
    <fieldset disabled={working}>{managedLines.map((line) => <details key={line.id} className="rounded-lg border p-4"><summary className="cursor-pointer font-medium">{line.name} · 产品线成员</summary><p className="mt-2 text-xs text-muted-foreground">访问同时受市场空间、产品线和岗位权限限制。</p><ul className="mt-3 space-y-2 text-sm">{catalog.members.filter((member) => member.product_line_id === line.id).map((member) => <li key={member.user_id} className="flex flex-wrap items-center gap-2"><span>{member.display_name} · {accessLabels[member.access]}</span>{member.user_id !== line.owner_user_id && <Button size="sm" variant="outline" disabled={working} onClick={() => void act(() => request(`${base}/products/${line.id}/members`, "POST", { ...command(line), user_id: member.user_id, access: null }))}>移除产品线权限</Button>}</li>)}</ul>
      <form className="mt-3 flex flex-wrap items-end gap-2" onSubmit={(event) => { event.preventDefault(); const form = new FormData(event.currentTarget); void act(() => request(`${base}/products/${line.id}/members`, "POST", { ...command(line), user_id: form.get("member"), access: form.get("access") })); }}><label className="text-sm">空间成员<select name="member" required className={field}><option value="">请选择</option>{workspace.members.map((member) => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label><label className="text-sm">产品线权限<select name="access" className={field}>{Object.entries(accessLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><Button size="sm" disabled={working}>保存权限</Button></form>
    </details>)}</fieldset>
    <p className="text-sm text-muted-foreground">此处维护产品身份和层级；上方矩阵与路线图复用当前产品归属，工程资源比较在组合管理入口办理。</p>
  </section>;
}

export function SpaceSettings({ workspace, base, busy, act }: { workspace: Workspace; base: string; busy: boolean; act: Act }) {
  const [open, setOpen] = useState(false);
  const space = workspace.space;
  return <details className="rounded-lg border p-4" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}><summary className="cursor-pointer font-medium">空间资料与生命周期 · {space.lifecycle === "archived" ? "已归档" : space.lifecycle === "active" ? "使用中" : "草稿"}</summary>
    {workspace.can_manage && <form key={`edit:${space.version}`} className="mt-3 grid gap-3 sm:grid-cols-2" onSubmit={(event) => {
      event.preventDefault(); const form = new FormData(event.currentTarget);
      void act(() => request(`${base}/changes`, "POST", { ...command(space), title: String(form.get("title")).trim(), user_groups: lines(form.get("user_groups")), regions: lines(form.get("regions")), use_scenarios: lines(form.get("use_scenarios")), research_questions: lines(form.get("research_questions")), reason: String(form.get("reason")).trim() }));
    }}><label className="text-sm">空间名称<input name="title" required defaultValue={space.title} maxLength={512} className={field} /></label><label className="text-sm">修改原因<input name="reason" required maxLength={2048} className={field} /></label>{([['user_groups', '用户群'], ['regions', '地域 / 市场'], ['use_scenarios', '使用场景'], ['research_questions', '待研究问题']] as const).map(([key, label]) => <label key={key} className="text-sm">{label}（每行一项）<textarea name={key} required defaultValue={space[key].join("\n")} className={field} /></label>)}<Button disabled={busy} className="justify-self-start">保存空间资料</Button></form>}
    {workspace.can_restore && <form className="mt-4 flex flex-wrap items-end gap-2 border-t pt-3" onSubmit={(event) => { event.preventDefault(); const form = new FormData(event.currentTarget); void act(() => request(`${base}/lifecycle`, "POST", { ...command(space), lifecycle: form.get("lifecycle"), reason: String(form.get("reason")).trim() })); }}><label className="text-sm">状态<select name="lifecycle" className={field}>{space.lifecycle !== "active" && <option value="active">{space.lifecycle === "archived" ? "恢复使用" : "启用市场空间"}</option>}{space.lifecycle !== "archived" && <option value="archived">归档市场空间</option>}</select></label><label className="text-sm">处置原因<input name="reason" required maxLength={2048} className={field} /></label><Button variant="outline" disabled={busy}>更新状态</Button><p className="w-full text-xs text-muted-foreground">归档前须完成或取消未结束工作。归档后资料只读，恢复会保留原记录和版本历史。</p></form>}
  </details>;
}

"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { skillTitle, type SkillReading } from "@/lib/agent-skills";
import { localDatetime, matchMcpReceipt, mcpPendingKey, mcpStates, parseMcpPending, type McpCommand, type McpDetail, type McpGrant, type McpHistory, type McpIndex, type McpPreview, type McpReceipt, type McpTool } from "@/lib/mcp-management";
import { proofClockCurrent } from "@/lib/proof-clock";
import type { WorkspaceTransport } from "@/lib/workspace-api";

const field = "w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2 text-sm";
const emptySchema = '{"type":"object","properties":{}}';
export function ConnectedMcpManagement({ api, principalId, categoryId }: { api: WorkspaceTransport; principalId: string; categoryId: string }) {
  const epoch = useRef(0), locked = useRef(false), proofFocus = useRef<HTMLElement>(null);
  const storageKey = mcpPendingKey(principalId, categoryId);
  const toolForm = useRef<HTMLDetailsElement>(null), grantForm = useRef<HTMLFieldSetElement>(null);
  const [toolOpen, setToolOpen] = useState(true);
  const [index, setIndex] = useState<McpIndex | null>(null), [selected, setSelected] = useState<McpDetail | null>(null), [skills, setSkills] = useState<SkillReading | null>(null), [history, setHistory] = useState<McpHistory | null>(null);
  const [preview, setPreview] = useState<McpPreview | null>(null), [pending, setPending] = useState<McpCommand | null>(null);
  const [busy, setBusy] = useState(true), [broken, setBroken] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [connectorKey, setConnectorKey] = useState(""), [endpoint, setEndpoint] = useState(""), [credentialRef, setCredentialRef] = useState(""), [active, setActive] = useState(true), [reason, setReason] = useState("");
  const [toolName, setToolName] = useState(""), [description, setDescription] = useState(""), [toolKind, setToolKind] = useState<"read" | "write">("read"), [inputSchema, setInputSchema] = useState(emptySchema), [outputSchema, setOutputSchema] = useState(""), [removed, setRemoved] = useState<string[]>([]);
  const [editingGrant, setEditingGrant] = useState<McpGrant | null>(null), [grantTool, setGrantTool] = useState(""), [grantSkill, setGrantSkill] = useState(""), [grantExpiry, setGrantExpiry] = useState(""), [externalWrite, setExternalWrite] = useState(false);
  useEffect(() => { if (preview || pending) proofFocus.current?.focus(); }, [preview, pending]);

  function clearTool() { setToolName(""); setDescription(""); setToolKind("read"); setInputSchema(emptySchema); setOutputSchema(""); setRemoved([]); }
  function clearGrant() { setEditingGrant(null); setGrantTool(""); setGrantSkill(""); setGrantExpiry(""); setExternalWrite(false); }
  function configure(value: McpDetail | null) {
    setSelected(value); setHistory(null); setConnectorKey(value?.connector.key ?? ""); setEndpoint(value?.connector.endpoint ?? ""); setCredentialRef(""); setActive(value?.connector.active ?? true); setReason(""); setToolOpen(!value); clearTool(); clearGrant();
  }
  async function loadIndex(current: number, cursor?: string) {
    const result = await api<McpIndex>(`v1/agent-mcp?page_size=20${cursor ? `&cursor=${cursor}` : ""}`);
    if (epoch.current === current) setIndex(previous => cursor && previous ? { ...result, items: [...previous.items, ...result.items.filter(item => !previous.items.some(old => old.id === item.id))] } : result);
    return result;
  }
  async function loadDetail(identity: string, current: number, suffix = "", merge = false) {
    const result = await api<McpDetail>(`v1/agent-mcp/${identity}${suffix}`);
    if (merge && selected && selected.connector.revision !== result.connector.revision) throw new Error("连接器登记已变化，请刷新后继续分页。");
    if (epoch.current === current) setSelected(previous => merge && previous?.connector.id === identity ? { ...result, tools: [...previous.tools, ...result.tools.filter(item => !previous.tools.some(old => old.name === item.name))], grants: [...previous.grants.filter(item => !result.grants.some(next => next.id === item.id)), ...result.grants], next_tool_cursor: suffix.includes("tool_cursor=") ? result.next_tool_cursor : previous.next_tool_cursor, next_grant_cursor: suffix.includes("grant_cursor=") ? result.next_grant_cursor : previous.next_grant_cursor } : result);
    return result;
  }
  async function loadSkills(current: number) {
    const result = await api<SkillReading>("v1/agent-skills"); if (epoch.current === current) setSkills(result);
  }
  function accept(original: McpCommand, receipt: McpReceipt, current: number) {
    if (!matchMcpReceipt(receipt, original, principalId, categoryId)) throw new Error("回执与原 MCP 请求不一致，请保留原请求继续核对。");
    if (epoch.current !== current) return;
    setPending(null); setPreview(null); clearGrant();
    if (original.operation === "mcp.connector.allow") { setCredentialRef(""); setReason(""); clearTool(); }
    setNotice(`${original.operation === "mcp.connector.allow" ? `连接器${original.payload.active ? "准入" : "停用"}` : `工具授权${original.payload.active ? "已确认" : "已撤销"}`} · 第 ${receipt.subject_revision} 版 · 回执 ${receipt.id}`);
    try { localStorage.removeItem(storageKey); } catch { setError("已取得原回执，本地恢复记录未清除，重开时将再次只读核对。"); }
  }
  useEffect(() => {
    const current = ++epoch.current; locked.current = true;
    async function open() {
      try {
        const currentIndex = await loadIndex(current), raw = localStorage.getItem(storageKey);
        if (!raw) return;
        let original: McpCommand;
        try { original = parseMcpPending(raw, categoryId); } catch (failure) { setBroken(true); throw failure; }
        if (epoch.current !== current) return;
        setPending(original);
        const result = await api<{ receipt: McpReceipt | null }>("v1/agent-mcp/recover", original);
        if (result.receipt) {
          accept(original, result.receipt, current);
          if (currentIndex.can_edit) { const value = await loadDetail(original.operation === "mcp.connector.allow" ? result.receipt.subject_id : original.payload.connector_id, current); if (epoch.current === current) configure(value); await loadSkills(current); }
        }
      } catch (failure) { if (epoch.current === current) setError((failure as Error).message); }
      finally { if (epoch.current === current) { locked.current = false; setBusy(false); } }
    }
    void open();
    return () => { epoch.current = current + 1; };
    // Scope-owned component remounts when the current person/category changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, categoryId, storageKey]);
  async function run(action: (current: number) => Promise<void>) {
    if (locked.current) return;
    const current = epoch.current; locked.current = true; setBusy(true); setError("");
    try { await action(current); } catch (failure) { if (epoch.current === current) setError((failure as Error).message); }
    finally { if (epoch.current === current) { locked.current = false; setBusy(false); } }
  }
  async function refreshAfter(original: McpCommand, receipt: McpReceipt, current: number) {
    const value = await loadIndex(current);
    if (value.can_edit) { const detail = await loadDetail(original.operation === "mcp.connector.allow" ? receipt.subject_id : original.payload.connector_id, current); if (epoch.current === current) { if (original.operation === "mcp.connector.allow") configure(detail); else setHistory(null); } await loadSkills(current); }
  }
  async function save(original: McpCommand, current: number) {
    localStorage.setItem(storageKey, JSON.stringify(original));
    if (epoch.current === current) { setPending(original); setPreview(null); }
    let receipt: McpReceipt;
    try { receipt = await api<McpReceipt>("v1/commands", original); }
    catch (failure) { const status = (failure as { status?: number }).status; if (epoch.current === current && status !== undefined && status >= 400 && status < 500) { localStorage.removeItem(storageKey); setPending(null); } throw failure; }
    accept(original, receipt, current); await refreshAfter(original, receipt, current);
  }
  function envelope(operation: McpCommand["operation"], revision: number, payload: unknown) { return { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), category_id: categoryId, product_id: null, operation, expected_revision: revision, source_read_set: [], payload }; }
  function prepareConnector() {
    void run(async current => {
      const actual = await loadIndex(current); if (!actual.can_edit) throw new Error("当前已无连接器管理权限。");
      const tools: McpTool[] = toolName.trim() ? [{ name: toolName.trim(), description: description.trim(), kind: toolKind, input_schema: JSON.parse(inputSchema), ...(outputSchema.trim() ? { output_schema: JSON.parse(outputSchema) } : {}) }] : [];
      const payload = { key: connectorKey.trim(), expected_revision: selected?.connector.revision ?? 0, endpoint: endpoint.trim() || null, secret_ref: credentialRef.trim() || null, tools, remove_tools: removed, active, decision: "批准", reason };
      const result = await api<McpPreview>("v1/commands/preview", envelope("mcp.connector.allow", actual.category_revision, payload));
      if (epoch.current === current) { setPreview(result); setNotice(""); }
    });
  }
  function prepareGrant(enabled: boolean) {
    if (!selected) return;
    void run(async current => {
      const actual = await loadDetail(selected.connector.id, current);
      // The selected row may come from any page. The server locks and rechecks its revision.
      const stored = editingGrant;
      const target = editingGrant?.tool ?? grantTool;
      const contract = actual.tools.find(item => item.name === target) ?? selected.tools.find(item => item.name === target);
      const payload = { connector_id: actual.connector.id, grant_id: editingGrant?.id ?? crypto.randomUUID(), expected_revision: stored?.revision ?? 0,
        connector_digest: contract?.binding_digest ?? null, tool: target, skill_key: editingGrant?.skill_key ?? grantSkill,
        active: enabled, expires_at: enabled ? new Date(grantExpiry).toISOString() : stored?.expires_at, allow_external_write: enabled ? externalWrite : stored?.allow_external_write ?? false };
      const result = await api<McpPreview>("v1/commands/preview", envelope("mcp.tool.grant", actual.category_revision, payload));
      if (epoch.current === current) { setPreview(result); setNotice(""); }
    });
  }
  const frozen = busy || !!preview || !!pending || broken, canEdit = !!index?.can_edit && !frozen;
  function editTool(item: McpTool) { setToolName(item.name); setDescription(item.description); setToolKind(item.kind); setInputSchema(JSON.stringify(item.input_schema, null, 2)); setOutputSchema(item.output_schema ? JSON.stringify(item.output_schema, null, 2) : ""); setRemoved(old => old.filter(name => name !== item.name)); setToolOpen(true); toolForm.current?.focus(); }
  function editGrant(item: McpGrant) { setEditingGrant(item); setGrantTool(item.tool); setGrantSkill(item.skill_key ?? ""); setGrantExpiry(localDatetime(item.expires_at)); setExternalWrite(item.allow_external_write && selected?.tools.find(tool => tool.name === item.tool)?.kind === "write"); grantForm.current?.focus(); }
  return <section aria-label="MCP 连接器与工具授权" className="space-y-4 rounded-lg border border-border p-4 sm:p-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-semibold">MCP 连接器与工具授权</h2><Button variant="outline" disabled={frozen} onClick={() => void run(async current => { await loadIndex(current); if (selected) { const value = await loadDetail(selected.connector.id, current); if (epoch.current === current) configure(value); } })}>刷新 MCP 登记</Button></div>
    <p className="text-sm text-muted-foreground">管理员先具名登记允许的服务和工具，再按技能逐项确认授权。这里保存配置，不连接服务、不发送业务资料；凭据只使用服务器引用，不填写密钥。</p>
    {error && <p role="alert" className="break-words text-sm text-destructive">{error}</p>}{notice && <p role="status" className="break-all text-sm">{notice}</p>}{busy && <p role="status" className="text-sm">正在核对 MCP 登记、授权和原回执…</p>}
    {index && !index.can_edit && <p className="text-sm text-muted-foreground">当前仅可查看租户登记摘要。准入与授权由有当前品类写入权限的租户管理员办理。</p>}
    {index && <ul className="space-y-2">{index.items.map(item => <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border p-3 text-sm"><p className="min-w-0 break-all">{item.key} · {item.active ? "已准入" : "已停用"} · {item.tool_count} 项工具 · 第 {item.revision} 版</p>{index.can_edit && <Button variant="outline" disabled={frozen} onClick={() => void run(async current => { const value = await loadDetail(item.id, current); if (epoch.current === current) configure(value); await loadSkills(current); })}>管理 {item.key}</Button>}</li>)}</ul>}
    {index && !index.items.length && <p className="text-sm text-muted-foreground">尚无 MCP 连接器登记。</p>}
    {index?.next_cursor && <Button variant="outline" disabled={frozen} onClick={() => void run(current => loadIndex(current, index.next_cursor!).then(() => undefined))}>读取更多连接器</Button>}
    {index?.can_edit && <>
      {selected && <Button variant="outline" disabled={frozen} onClick={() => { configure(null); setNotice(""); }}>登记另一个连接器</Button>}
      <fieldset disabled={!canEdit} className="space-y-3 rounded-lg border border-border p-3"><legend className="px-1 font-medium">{selected ? `变更 ${selected.connector.key}` : "登记新连接器"}</legend>
        <div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1 text-sm"><span>MCP 服务商标识</span><input className={field} value={connectorKey} disabled={!!selected} maxLength={160} onChange={event => setConnectorKey(event.target.value)} /></label><label className="space-y-1 text-sm"><span>MCP 服务地址</span><input className={field} value={endpoint} maxLength={1000} onChange={event => setEndpoint(event.target.value)} placeholder="https://…/mcp" /></label></div>
        <label className="block space-y-1 text-sm"><span>服务器凭据引用（非密钥）</span><input className={field} value={credentialRef} maxLength={200} autoComplete="off" onChange={event => setCredentialRef(event.target.value)} placeholder={selected ? "留空沿用已登记引用" : "服务器已有的凭据引用"} /></label>
        <p className="text-xs text-muted-foreground">凭据可用性尚未核对。登记不会证明连接成功；服务商数据协议仍在实际调用前逐次核对。</p>
        <details ref={toolForm} tabIndex={-1} className="space-y-3" open={toolOpen} onToggle={event => setToolOpen(event.currentTarget.open)}><summary className="cursor-pointer text-sm font-medium">本批新增或更新一个工具</summary><div className="mt-3 grid gap-3 sm:grid-cols-2"><label className="space-y-1 text-sm"><span>MCP 工具名称</span><input className={field} value={toolName} maxLength={160} onChange={event => setToolName(event.target.value)} placeholder="留空则只变更连接器登记" /></label><label className="space-y-1 text-sm"><span>MCP 工具类型</span><select className={field} value={toolKind} onChange={event => setToolKind(event.target.value as "read" | "write")}><option value="read">只读</option><option value="write">向外写入或发送</option></select></label></div>
          <label className="block space-y-1 text-sm"><span>MCP 工具说明</span><textarea className={field} rows={2} value={description} maxLength={2000} onChange={event => setDescription(event.target.value)} /></label>
          <label className="block space-y-1 text-sm"><span>参数结构（JSON Schema）</span><textarea className={`${field} font-mono text-xs`} rows={4} value={inputSchema} onChange={event => setInputSchema(event.target.value)} /></label><label className="block space-y-1 text-sm"><span>结构化结果说明（可选 JSON Schema）</span><textarea className={`${field} font-mono text-xs`} rows={3} value={outputSchema} onChange={event => setOutputSchema(event.target.value)} /></label><Button variant="outline" onClick={clearTool}>清空本批工具变更</Button>
        </details>
        {removed.length > 0 && <p className="break-all text-sm">本批将移除：{removed.join("、")}</p>}
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={active} onChange={event => setActive(event.target.checked)} /><span>准入此连接器（取消勾选以停用）</span></label>
        <label className="block space-y-1 text-sm"><span>MCP 准入决定理由</span><textarea className={field} rows={2} maxLength={4000} value={reason} onChange={event => setReason(event.target.value)} /></label>
        <Button disabled={!canEdit || !connectorKey.trim() || !endpoint.trim() || !selected && !credentialRef.trim() || !reason.trim() || !!toolName.trim() && !description.trim()} onClick={prepareConnector}>预览具名{active ? "准入或变更" : "停用"}连接器</Button>
      </fieldset>
      {selected && <>
        <section aria-label="当前 MCP 工具" className="space-y-3 text-sm"><h3 className="font-medium">当前工具 · {selected.connector.tool_count} 项</h3><p className="text-xs text-muted-foreground">读取于 {new Date(selected.as_of).toLocaleString()}</p>{selected.tools.map(item => <div key={item.name} className="space-y-2 rounded-lg border border-border p-3"><p className="break-all font-medium">{item.name} · {item.kind === "read" ? "只读" : "向外写入或发送"}</p><p className="break-words">{item.description}</p><div className="flex flex-wrap gap-2"><Button variant="outline" disabled={!canEdit} onClick={() => editTool(item)}>编辑 {item.name} 的登记</Button><label className="flex items-center gap-2"><input type="checkbox" checked={removed.includes(item.name)} disabled={!canEdit || item.name === toolName} onChange={event => setRemoved(old => event.target.checked ? [...old, item.name] : old.filter(name => name !== item.name))} />移除 {item.name}</label></div></div>)}{selected.next_tool_cursor && <Button variant="outline" disabled={frozen} onClick={() => void run(current => loadDetail(selected.connector.id, current, `?tool_cursor=${encodeURIComponent(selected.next_tool_cursor!)}`, true).then(() => undefined))}>读取更多工具</Button>}</section>
        <fieldset ref={grantForm} tabIndex={-1} disabled={!canEdit} className="space-y-3 rounded-lg border border-border p-3"><legend className="px-1 font-medium">{editingGrant ? "变更已有逐项授权" : "按技能新建逐项授权"}</legend><p className="text-xs text-muted-foreground">本项授权不会自动启用技能。实际运行还须核对已加载技能和资料出站政策。</p>
          {editingGrant && <p className="break-all text-sm">原授权第 {editingGrant.revision} 版 · {mcpStates[editingGrant.state]}。范围保持原样；改换范围请新建授权。</p>}
          <div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1 text-sm"><span>授权的 MCP 工具</span><select className={field} value={grantTool} disabled={!!editingGrant} onChange={event => { setGrantTool(event.target.value); setExternalWrite(false); }}><option value="">请选择工具</option>{selected.tools.map(item => <option key={item.name} value={item.name}>{item.name} · {item.kind === "read" ? "只读" : "外部写入"}</option>)}{editingGrant && !selected.tools.some(item => item.name === editingGrant.tool) && <option value={editingGrant.tool}>{editingGrant.tool}（已移除，仅可撤销）</option>}</select></label>
            <label className="space-y-1 text-sm"><span>获授权技能</span><select className={field} value={grantSkill} disabled={!!editingGrant} onChange={event => setGrantSkill(event.target.value)}><option value="">请选择技能</option>{skills?.items.map(item => <option key={item.skill_key} value={item.skill_key}>{skillTitle(item.skill_key)}</option>)}{editingGrant?.skill_key && !skills?.items.some(item => item.skill_key === editingGrant.skill_key) && <option value={editingGrant.skill_key}>{skillTitle(editingGrant.skill_key)}</option>}</select></label></div>
          <label className="block space-y-1 text-sm"><span>MCP 授权到期时间（本地时区）</span><input type="datetime-local" className={field} value={grantExpiry} onChange={event => setGrantExpiry(event.target.value)} /></label>
          <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={externalWrite} disabled={!canEdit || selected.tools.find(item => item.name === grantTool)?.kind !== "write"} onChange={event => setExternalWrite(event.target.checked)} /><span>我明确允许这一技能通过所选工具向此连接器写入或发送资料。未勾选时不授权外部写入。</span></label>
          <div className="flex flex-wrap gap-2"><Button disabled={!canEdit || !selected.connector.active || !grantTool || !grantSkill || !grantExpiry || !selected.tools.some(item => item.name === grantTool)} onClick={() => prepareGrant(true)}>预览确认逐项授权</Button>{editingGrant && <Button variant="outline" disabled={!canEdit} onClick={() => prepareGrant(false)}>预览撤销此项授权</Button>}{editingGrant && <Button variant="outline" onClick={clearGrant}>改为新建授权</Button>}</div>
        </fieldset>
        <section aria-label="已登记 MCP 授权" className="space-y-3 text-sm"><h3 className="font-medium">已登记授权</h3>{!selected.grants.length && <p className="text-muted-foreground">尚未授权任何工具。</p>}{selected.grants.map(item => <div key={item.id} className="space-y-2 rounded-lg border border-border p-3"><p className="break-all font-medium">{item.tool} · {item.skill_key ? skillTitle(item.skill_key) : "自动化规则授权"}</p><p>{mcpStates[item.state]} · 第 {item.revision} 版</p><p className="break-words">到期 {new Date(item.expires_at).toLocaleString()} · {item.allow_external_write ? "已明确授权外部写入" : "未授权外部写入"}</p><p className="break-all text-muted-foreground">确认人：{item.authorized_by_name ?? "原记录人员"} · 回执 {item.receipt_id ?? "原记录尚无办理回执"}</p>{item.skill_key && !item.automation_rule_id && <Button variant="outline" disabled={!canEdit} onClick={() => editGrant(item)}>管理此项授权 {item.id.slice(0, 8)}</Button>}</div>)}{selected.next_grant_cursor && <Button variant="outline" disabled={frozen} onClick={() => void run(current => loadDetail(selected.connector.id, current, `?grant_cursor=${selected.next_grant_cursor}`, true).then(() => undefined))}>读取更多授权</Button>}</section>
        <section className="space-y-3 text-sm"><Button variant="outline" disabled={frozen} onClick={() => void run(async current => { const result = await api<McpHistory>(`v1/agent-mcp/${selected.connector.id}/history?page_size=20`); if (epoch.current === current) setHistory(result); })}>读取准入与授权变更历史</Button>{history && <ul className="space-y-2">{history.items.map(item => <li key={item.id} className="break-words rounded-lg border border-border p-3"><p>{item.operation === "mcp.connector.allow" ? "具名连接器决定" : "工具授权确认"} · 第 {item.revision} 版 · {item.decided_by_name ?? "原记录人员"}</p><p>{item.reason}</p><p className="break-all text-muted-foreground">{new Date(item.created_at).toLocaleString()} · 回执 {item.receipt_id}</p></li>)}</ul>}{history?.next_cursor && <Button variant="outline" disabled={frozen} onClick={() => void run(async current => { const result = await api<McpHistory>(`v1/agent-mcp/${selected.connector.id}/history?cursor=${history.next_cursor}&page_size=20`); if (epoch.current === current) setHistory(old => ({ ...result, items: [...(old?.items ?? []), ...result.items] })); })}>读取更早变更历史</Button>}</section>
      </>}
    </>}
    {preview && <section ref={proofFocus} tabIndex={-1} aria-label="确认 MCP 准入或授权" className="space-y-3 rounded-lg border border-primary/40 p-3 text-sm"><h3 className="break-all font-medium">{preview.command.operation === "mcp.connector.allow" ? "具名核对连接器" : "一次确认工具授权"} · {preview.review.key}</h3><p>状态第 {preview.review.next_revision} 版 · {preview.review.active ? "启用本项" : "停用或撤销本项"}</p>{preview.review.endpoint && <p className="break-all">服务地址：{preview.review.endpoint}</p>}{preview.review.credential_reference && <p>凭据引用：{preview.review.credential_reference}，可用性尚未核对。</p>}{preview.review.binding_changed && <p>目标变更影响此连接器授权；工具结构变更只影响对应工具授权。</p>}{preview.review.tool && <p className="break-all">工具 {preview.review.tool} · 技能 {skillTitle(preview.review.skill_key ?? "")} · {preview.review.allow_external_write ? "已明确授权外部写入" : "未授权外部写入"}</p>}{preview.review.expires_at && <p>到期 {new Date(preview.review.expires_at).toLocaleString()}</p>}{preview.review.upsert_tools?.map(item => <p key={item.name} className="break-all">本批登记：{item.name}（{item.kind === "read" ? "只读" : "向外写入或发送"}）</p>)}{!!preview.review.remove_tools?.length && <p className="break-all">本批移除：{preview.review.remove_tools.join("、")}</p>}{preview.review.reason && <p className="break-words">理由：{preview.review.reason}</p>}<p>{preview.review.effect}</p><div className="flex flex-wrap gap-2"><Button disabled={busy || !index?.can_edit || !proofClockCurrent(preview.write_tier ?? "T1", preview.expires_at)} onClick={() => void run(current => save(preview.command, current))}>{preview.command.operation === "mcp.connector.allow" ? preview.review.active ? "本人具名准入或变更" : "本人具名停用" : preview.review.active ? "确认逐项授权" : "确认撤销授权"}</Button><Button variant="outline" disabled={busy} onClick={() => setPreview(null)}>返回</Button></div></section>}
    {pending && <section ref={proofFocus} tabIndex={-1} aria-label="恢复原 MCP 请求" className="space-y-3 rounded-lg border border-primary/40 p-3 text-sm"><p>原 MCP 登记或授权结果待核对。重新打开先只读查询原回执；只有本人点击才沿用原请求重试。</p><Button disabled={busy} onClick={() => void run(async current => { const result = await api<{ receipt: McpReceipt | null }>("v1/agent-mcp/recover", pending); if (result.receipt) { accept(pending, result.receipt, current); await refreshAfter(pending, result.receipt, current); } else { const value = await loadIndex(current); if (!value.can_edit) throw new Error("当前已无办理权限，请保留原请求核对现有回执。"); await save(pending, current); } })}>核对并重试原 MCP 请求</Button></section>}
    {broken && <Button variant="outline" disabled={busy || !index} onClick={() => { localStorage.removeItem(storageKey); setBroken(false); setError(""); }}>已核对当前状态，清除损坏的本地记录</Button>}
  </section>;
}

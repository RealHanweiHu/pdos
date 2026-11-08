"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ArrowClockwise, MagnifyingGlass, PencilSimple, UserPlus } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { DetailSheet } from "@/components/ui/detail-sheet";
import type { browserApi } from "@/lib/browser-api";
import { categoryTransport } from "@/lib/category-transport";
import {
  formatJoined, grantLabel, leadHolder, needsGrant, pendingText, roleChanges, roleName, selectableRoles, teamPath,
  teamRequest, teamStorageKey, type MemberChange, type RoleChoice, type TeamMember, type TeamRequest, type TeamView,
} from "@/lib/project-team";
import s from "../shell/organization.module.css";
import t from "./project-team.module.css";

type Props = { api: typeof browserApi; categoryId: string; productId: string; projectId: string; principalId: string; readVersion?: number };
type Failure = Error & { status?: number; code?: string };

export function ProjectTeam(props: Props) {
  return <Team key={`${props.principalId}:${props.categoryId}:${props.projectId}:${props.readVersion ?? 0}`} {...props}/>;
}

function Team({ api, categoryId, productId, projectId, principalId }: Props) {
  const scoped = useMemo(() => categoryTransport(categoryId, api), [categoryId, api]);
  const path = teamPath(productId, projectId), storage = teamStorageKey(principalId, projectId);
  const [view, setView] = useState<TeamView | null>(null), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [pending, setPending] = useState<TeamRequest | null>(null), [busy, setBusy] = useState(false);
  const [picking, setPicking] = useState(false), [checked, setChecked] = useState<string[]>([]), [search, setSearch] = useState("");
  const [editing, setEditing] = useState<TeamMember | null>(null), [draft, setDraft] = useState<RoleChoice[]>([]), [removing, setRemoving] = useState(false);
  const alive = useRef(false), lock = useRef(false), generation = useRef(0);
  const load = useCallback(async () => {
    const seq = ++generation.current;
    try { const value = await scoped<TeamView>(path); if (alive.current && seq === generation.current) { setView(value); setError(""); } }
    catch (e) { if (alive.current && seq === generation.current) { setView(null); setError((e as Error).message); } }
  }, [scoped, path]);
  useEffect(() => {
    const counter = generation; alive.current = true;
    void Promise.resolve().then(() => {
      try { const saved = JSON.parse(localStorage.getItem(storage) ?? "null"); if (saved?.request_key && Array.isArray(saved.changes)) setPending(saved); } catch { /* Nothing retained. */ }
      void load();
    });
    return () => { alive.current = false; ++counter.current; };
  }, [storage, load]);

  async function execute(request: TeamRequest, done: string) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(""); setNotice("");
    try {
      try { localStorage.setItem(storage, JSON.stringify(request)); } catch { /* Retry stays available while this page is open. */ }
      setPending(request);
      const result = await scoped<TeamView>(path, request);
      if (!alive.current) return;
      try { localStorage.removeItem(storage); } catch { /* Ignore. */ }
      setPending(null); setView(result); setEditing(null); setRemoving(false); setPicking(false); setChecked([]); setNotice(done);
    } catch (e) {
      if (!alive.current) return;
      const failure = e as Failure;
      setError(failure.message);
      // A refusal is final; an unknown outcome keeps the same request for an exact retry.
      if (failure.status && failure.status >= 400 && failure.status < 500) {
        try { localStorage.removeItem(storage); } catch { /* Ignore. */ }
        setPending(null);
        if (failure.code === "VERSION_CONFLICT") { setEditing(null); setRemoving(false); await load(); }
      }
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  function submit(changes: MemberChange[], done: string) {
    if (view) void execute(teamRequest(view, changes, crypto.randomUUID()), done);
  }
  function edit(member: TeamMember) {
    setEditing(member); setRemoving(false); setDraft(member.roles.map(role => ({ key: role.key, lead: role.lead })));
  }
  function toggleRole(key: string, on: boolean) {
    setDraft(current => on ? [...current, { key, lead: false }] : current.filter(role => role.key !== key));
  }
  function toggleLead(key: string) {
    setDraft(current => current.map(role => role.key === key ? { ...role, lead: !role.lead } : role));
  }

  const disabled = busy || !!pending;
  if (!view) return <section className={t.team} aria-label="项目团队">
    <Heading/>
    {error ? <div className={s.empty} role="alert"><p>{error}</p><Button size="xs" variant="outline" onClick={() => void load()}>重新读取团队</Button></div> : <div className={s.empty} role="status">正在读取项目团队…</div>}
  </section>;

  const candidates = (view.candidates ?? []).filter(item => item.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const chosen = candidates.filter(item => checked.includes(item.principal_id));
  const names = (keys: string[]) => keys.map(key => roleName(view, key)).join("、");
  const visibility = view.membership_controls_visibility
    ? "私有项目：团队成员即项目受众，加入后可见，移出后不可见（有未交接事项的，交接完成后再完全移出）；已有记录保留署名。"
    : "品类共享项目：成员表示参与和职责，不改变可见范围。";

  return <section className={t.team} aria-label="项目团队">
    <Heading actions={<div className={s.actions}>
      <Button size="icon-xs" variant="ghost" aria-label="刷新团队" disabled={disabled} onClick={() => { setNotice(""); void load(); }}><ArrowClockwise/></Button>
      {view.can_manage && <Button size="xs" variant="outline" disabled={disabled} aria-expanded={picking} onClick={() => { setPicking(!picking); setChecked([]); setSearch(""); }}><UserPlus/>添加成员</Button>}
    </div>}/>
    <p className={t.footnote}>{visibility}{view.can_manage ? "" : ` 团队由项目负责人 ${view.project.owner_name} 维护。`}</p>
    {error && <p className={`${s.notice} ${t.warn}`} role="alert">{error}</p>}
    {notice && <p className={s.notice} role="status">{notice}</p>}
    {pending && !busy && <div className={s.notice} role="status">保存结果待确认，重试会使用同一个请求，不会重复修改。<Button size="xs" variant="outline" disabled={busy} onClick={() => void execute(pending, "团队已更新。")}>重试原请求</Button></div>}

    {view.can_manage && picking && <div className={s.picker}>
      <div className={s.filters}><label className={s.search}><MagnifyingGlass size={14}/><input type="search" aria-label="搜索可添加的同事" placeholder="搜索同事…" value={search} onChange={e => setSearch(e.target.value)} onKeyDown={e => { if (e.key === "Escape") setSearch(""); }}/></label></div>
      <div className={s.pickerList}>
        {candidates.map(item => {
          const blocked = needsGrant(item.grant);
          return <label key={item.principal_id} aria-disabled={blocked || undefined} title={blocked ? "由管理员授予品类权限；项目负责人不能代为授权。" : undefined}>
            <input type="checkbox" disabled={disabled || blocked} checked={checked.includes(item.principal_id)} onChange={e => setChecked(ids => e.target.checked ? [...ids, item.principal_id] : ids.filter(id => id !== item.principal_id))}/>
            {item.name}
            <span className={t.candidateHint} data-blocked={blocked}>{grantLabel(item.grant)}</span>
          </label>;
        })}
        {!candidates.length && <p className={s.notice}>{search ? "没有匹配的同事。" : "组织内没有可添加的同事。"}</p>}
      </div>
      <div className={s.actions}>
        <span className={s.muted}>需要品类授权的同事由管理员处理后才能加入；加入后再设置角色。</span>
        <Button size="xs" variant="ghost" onClick={() => setPicking(false)}>取消</Button>
        <Button size="xs" disabled={disabled || !chosen.length} onClick={() => submit(chosen.map(item => ({ action: "add", principal_id: item.principal_id, roles: [] })), `已加入 ${chosen.map(item => item.name).join("、")}。`)}>加入团队{chosen.length ? `（${chosen.length}）` : ""}</Button>
      </div>
    </div>}

    <div className={t.summary}>
      <span><strong>{view.members.length}</strong> 名成员</span>
      <span>空缺角色：{view.vacant_roles.length ? names(view.vacant_roles) : "无"}</span>
      {view.roles_without_lead.length > 0 && <span>未定主责：{names(view.roles_without_lead)}</span>}
    </div>
    <div className={s.scroll}><table className={s.table}>
      <thead><tr><th>成员</th><th>角色</th><th className={t.hideNarrow}>加入</th><th>品类授权</th>{view.can_manage && <th aria-label="操作"/>}</tr></thead>
      <tbody>{view.members.map(member => <tr key={member.member_id}>
        <td><span className={s.titleLink}>{member.name}{member.is_owner && <span className={t.owner}>负责人</span>}</span>{!member.active_person && <small className={t.warn}>账号已停用</small>}{(member.needs_model_access ?? []).map(gap => <small key={gap.object} className={t.warn}>需要{gap.object}资料可见，请联系 {gap.owner_name}</small>)}</td>
        <td>{member.roles.length ? <span className={t.chips}>{member.roles.map(role => <span key={role.key} className={t.chip} data-lead={role.lead} title={role.lead ? `${role.name}主责人` : role.name}>{role.name}{role.lead ? " · 主责" : ""}</span>)}</span> : <span className={t.none}>未设角色</span>}</td>
        <td className={t.hideNarrow}>{formatJoined(member.joined_at)}<small>由 {member.added_by_name} 添加</small></td>
        <td><span className={needsGrant(member.grant) ? t.warn : undefined} title={needsGrant(member.grant) ? "由管理员处理；项目负责人不能代为授权。" : undefined}>{grantLabel(member.grant)}</span></td>
        {view.can_manage && <td><Button size="xs" variant="ghost" disabled={disabled} aria-label={`编辑 ${member.name} 的角色`} onClick={() => edit(member)}><PencilSimple/>编辑</Button></td>}
      </tr>)}</tbody>
    </table></div>
    <p className={t.footnote}>小Pai 不是项目成员，不担任角色，也不当任务负责人。每个角色最多一名主责人。</p>

    {view.departed.length > 0 && <details className={t.departed} open={view.departed.some(member => member.handover_pending) || undefined}>
      <summary>已离开的成员（{view.departed.length}）{view.departed.some(member => member.handover_pending) ? ` · ${view.departed.filter(member => member.handover_pending).length} 人待交接` : ""}</summary>
      <div className={s.scroll}><table className={s.table}><thead><tr><th>成员</th><th>离开时角色</th><th>在项目期间</th><th className={t.hideNarrow}>移出人</th>{view.can_manage && <th aria-label="操作"/>}</tr></thead>
        <tbody>{view.departed.map(member => <tr key={member.member_id}>
          <td>{member.name}{member.handover_pending && <span className={t.owner}>待交接</span>}{member.handover_pending && <small>{pendingText(member.pending) ? `未交接：${pendingText(member.pending)}；交接完成前仍可看到本项目` : "已无未交接事项，可以完成移出"}</small>}</td>
          <td>{member.roles.length ? names(member.roles.map(role => role.key)) : <span className={t.none}>未设角色</span>}</td>
          <td>{formatJoined(member.joined_at)} — {formatJoined(member.left_at)}</td>
          <td className={t.hideNarrow}>{member.removed_by_name}</td>
          {view.can_manage && <td>{member.handover_pending && <Button size="xs" variant="ghost" disabled={disabled || !!pendingText(member.pending)} title={pendingText(member.pending) ? "交接完成后才能完全移出" : undefined} onClick={() => submit([{ action: "complete", principal_id: member.principal_id }], `${member.name} 已完全移出，不再能看到本项目。`)}>完成移出</Button>}</td>}
        </tr>)}</tbody></table></div>
    </details>}

    {editing && <DetailSheet title={`${editing.name} 的角色`} onClose={() => { if (!busy) { setEditing(null); setRemoving(false); } }}>
      <form className={t.form} onSubmit={event => { event.preventDefault(); submit(roleChanges(view, editing.principal_id, draft), `已更新 ${editing.name} 的角色。`); }}>
        <fieldset disabled={disabled} className={t.form}>
          <h3>角色（可多选）</h3>
          <div className={t.roleList}>{selectableRoles(view, editing.roles).map(role => {
            const selected = draft.find(item => item.key === role.key), holder = leadHolder(view, editing.principal_id, role.key);
            return <div className={t.roleRow} key={role.key}>
              <label><input type="checkbox" checked={!!selected} onChange={e => toggleRole(role.key, e.target.checked)}/><span>{role.name}{!role.active && <small>已停用，保留现有担任</small>}{selected?.lead && holder && <small>保存后主责从 {holder.name} 改为 {editing.name}</small>}</span></label>
              {selected && <Button type="button" size="xs" variant="ghost" className={t.leadToggle} data-on={selected.lead} aria-pressed={selected.lead} onClick={() => toggleLead(role.key)}>{selected.lead ? "主责人" : "设为主责"}</Button>}
            </div>;
          })}</div>
          <div className={t.sheetActions}>
            {!editing.is_owner && <Button type="button" size="xs" variant="ghost" className={t.warn} onClick={() => setRemoving(true)}>移出项目</Button>}
            <div><Button type="button" size="xs" variant="ghost" onClick={() => setEditing(null)}>取消</Button><Button type="submit" size="xs">保存角色</Button></div>
          </div>
          {removing && <div className={t.consequence} role="alert">
            <p>{!view.membership_controls_visibility ? `移出后 ${editing.name} 仍按品类授权查看本项目，只是不再属于团队；担任的角色一并解除，历史记录保留署名。`
              : pendingText(editing.pending) ? `${editing.name} 还有未交接事项（${pendingText(editing.pending)}）。移出后成员资格和角色立即结束；交接完成前仍可看到本项目，列为“待交接”，交接完成后由你完成移出。`
              : `移出后 ${editing.name} 立即看不到本项目，随本项目加上的型号与定义查看权一并撤回；担任的角色一并解除，历史记录保留署名。`}</p>
            <div className={t.sheetActions}><div><Button type="button" size="xs" variant="ghost" onClick={() => setRemoving(false)}>保留成员</Button><Button type="button" size="xs" variant="destructive" onClick={() => submit([{ action: "remove", principal_id: editing.principal_id }], `${editing.name} 已移出团队。`)}>确认移出</Button></div></div>
          </div>}
        </fieldset>
      </form>
    </DetailSheet>}
  </section>;
}

function Heading({ actions }: { actions?: ReactNode }) {
  return <header className={t.heading}><div><h2>团队</h2><p>项目成员、角色与主责人。成员资格不授予权限，须先有当前品类授权。</p></div>{actions}</header>;
}

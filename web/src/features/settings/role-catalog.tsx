"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { DetailSheet } from "@/components/ui/detail-sheet";
import { browserApi } from "@/lib/browser-api";
import styles from "./platform-settings.module.css";

type Role = { key?: string; name: string; active: boolean };
type Catalog = { revision: number; can_publish: boolean; roles: Role[] };
type Request = { expected_revision: number; request_key: string; roles: Role[] };
const path = "v1/role-catalog";

export function RoleCatalogSettings() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [draft, setDraft] = useState<Role[] | null>(null);
  const [request, setRequest] = useState<Request | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const active = useRef(false);
  const writing = useRef(false);

  useEffect(() => {
    active.current = true;
    let current = true;
    void browserApi<Catalog>(path).then(value => {
      if (current) { setCatalog(value); setError(""); }
    }).catch(failure => {
      if (current) { setError((failure as Error).message); setCatalog(null); }
    });
    return () => { current = false; active.current = false; };
  }, [attempt]);

  function edit(index: number, values: Partial<Role>) {
    setDraft(rows => rows?.map((row, position) => index === position ? {...row, ...values} : row) ?? null);
  }
  async function publish() {
    if (!request || writing.current) return;
    writing.current = true;
    setBusy(true);
    setError("");
    try {
      const saved = await browserApi<Catalog>(path, request);
      if (active.current) {
        setCatalog(saved); setDraft(null); setRequest(null);
        setNotice(`已发布角色目录 v${saved.revision}`);
      }
    } catch (failure) {
      if (active.current) {
        setError((failure as Error).message);
        const status = (failure as Error & { status?: number }).status;
        if (status === 403) { setCatalog(null); setDraft(null); }
        if (status && status >= 400 && status < 500) setRequest(null);
      }
    } finally {
      writing.current = false;
      if (active.current) setBusy(false);
    }
  }

  return <section className="space-y-4 pt-4" aria-label="项目角色目录">
    <header className="flex flex-wrap items-center justify-between gap-2">
      <div><h2 className="font-semibold">项目角色目录</h2>{catalog && <p className={styles.note}>{catalog.revision ? `已发布 v${catalog.revision}` : "租户默认目录"}</p>}</div>
      <div className="flex gap-2">
        <Button size="sm" variant="ghost" disabled={busy || !!request} onClick={() => {setDraft(null); setAttempt(value => value + 1);}}>刷新目录</Button>
        {catalog?.can_publish && !draft && <Button size="sm" variant="outline" onClick={() => setDraft(catalog.roles.map(row => ({...row})))}>编辑角色</Button>}
      </div>
    </header>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {!catalog && !error && <p role="status">正在读取角色目录…</p>}
    {catalog && <div className={styles.tableScroll}><table className={styles.table}>
      <thead><tr><th>角色名称</th><th>状态</th>{draft && <th>操作</th>}</tr></thead>
      <tbody>{(draft ?? catalog.roles).map((role, index) => <tr key={role.key ?? `new-${index}`}>
        <td>{draft ? <input aria-label={`角色 ${index + 1} 名称`} value={role.name} maxLength={40} disabled={!!request} onChange={event => edit(index, {name: event.target.value})}/> : role.name}</td>
        <td>{draft ? <label className="flex items-center gap-2"><input type="checkbox" checked={role.active} disabled={!!request} onChange={event => edit(index, {active: event.target.checked})}/>启用</label> : role.active ? "启用" : "已停用"}</td>
        {draft && <td><Button type="button" size="sm" variant="ghost" disabled={!!request} onClick={() => setDraft(draft.filter((_, position) => index !== position))}>删除</Button></td>}
      </tr>)}</tbody>
    </table></div>}
    {draft && catalog && <div className="flex flex-wrap gap-2">
      <Button size="sm" variant="outline" disabled={!!request || draft.length >= 100} onClick={() => setDraft([...draft, {name:"", active:true}])}>添加角色</Button>
      <Button size="sm" disabled={!!request || !draft.length || draft.some(row => !row.name.trim())}
        onClick={() => setRequest({expected_revision: catalog.revision, request_key: crypto.randomUUID(), roles: draft})}>核对并发布</Button>
    </div>}
    {request && <DetailSheet title="确认发布角色目录" onClose={() => {if (!busy) setRequest(null);}}>
      <div className="space-y-4">
        <p>将发布 v{request.expected_revision + 1}。停用的角色不再用于新分派，现有历史保留。</p>
        <ul>{request.roles.map((role, index) => <li key={role.key ?? index}>{role.name} · {role.active ? "启用" : "停用"}</li>)}</ul>
        {error && <p role="alert">{error}</p>}
        <Button size="sm" disabled={busy} onClick={() => void publish()}>确认发布</Button>
      </div>
    </DetailSheet>}
  </section>;
}

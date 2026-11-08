"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Copy, UserPlus } from "@phosphor-icons/react";
import { browserApi } from "@/lib/browser-api";
import { Button } from "@/components/ui/button";
import styles from "./accounts.module.css";

export type Account = {
  principal_id: string; name: string; login_name: string | null;
  status: "active" | "invited" | "link_expired" | "deactivated" | "no_sign_in";
  active: boolean; administrator: boolean; self: boolean; password_set: boolean;
  pending_link: { purpose: "invite" | "reset"; expires_at: string } | null;
  active_sessions: number; last_sign_in_at: string | null;
};
type Link = { token: string; purpose: "invite" | "reset"; expires_at: string };
type Result = { account: Account; link?: Link; sessions_revoked?: number };
type Api = <T>(path: string, body?: unknown) => Promise<T>;
type Action = "invitation" | "password-reset" | "deactivate" | "reactivate" | "sessions/revoke" | "administrator";

export const statusLabel: Record<Account["status"], string> = { active: "启用", invited: "待设置密码", link_expired: "链接已过期", deactivated: "已停用", no_sign_in: "无登录账户" };
const time = (value: string | null) => value ? new Date(value).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
const confirmText: Partial<Record<Action, string>> = {
  deactivate: "停用后，此账户的全部会话和未用链接立即失效。",
  "password-reset": "旧密码和此账户的全部会话立即失效，并生成新的重设链接。",
  "sessions/revoke": "此账户在所有设备上立即下线。",
};

/** Settings → 账户与邀请 for tenant administrators (D214/D86/D192). Rules are enforced by the API. */
export function AccountManagement({ api = browserApi }: { api?: Api }) {
  const [items, setItems] = useState<Account[] | null>(null);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [link, setLink] = useState<{ name: string; url: string; purpose: string; expires: string } | null>(null);
  const [busy, setBusy] = useState(""), [confirming, setConfirming] = useState<{ id: string; action: Action } | null>(null);
  const [form, setForm] = useState({ display_name: "", login_name: "" });
  const linkInput = useRef<HTMLInputElement>(null);
  const read = useCallback(async () => {
    try { setItems((await api<{ items: Account[] }>("v1/accounts")).items); setError(""); }
    catch (failure) { setError((failure as Error).message); }
  }, [api]);
  useEffect(() => { void Promise.resolve().then(read); }, [read]);
  function merge(account: Account) { setItems(old => old && (old.some(item => item.principal_id === account.principal_id) ? old.map(item => item.principal_id === account.principal_id ? account : item) : [...old, account])); }
  function showLink(account: Account, value: Link) {
    // The token is shown once; the server keeps only its hash.
    setLink({ name: account.name, url: `${window.location.origin}/invite#${value.token}`, purpose: value.purpose === "reset" ? "重设密码链接" : "邀请链接", expires: time(value.expires_at) });
    requestAnimationFrame(() => linkInput.current?.select());
  }
  async function create(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy("create"); setError(""); setNotice(""); setLink(null);
    try {
      const result = await api<Result>("v1/accounts", { display_name: form.display_name.trim(), login_name: form.login_name.trim() });
      merge(result.account); if (result.link) showLink(result.account, result.link);
      setForm({ display_name: "", login_name: "" });
    } catch (failure) { setError((failure as Error).message); }
    finally { setBusy(""); }
  }
  async function act(account: Account, action: Action, body: unknown = {}) {
    if (busy) return;
    setBusy(account.principal_id); setError(""); setNotice(""); setConfirming(null);
    if (action !== "invitation" && action !== "password-reset") setLink(null);
    try {
      const result = await api<Result>(`v1/accounts/${account.principal_id}/${action}`, body);
      merge(result.account);
      if (result.link) showLink(result.account, result.link);
      if (typeof result.sessions_revoked === "number" && action !== "password-reset") setNotice(`${result.account.name}：已结束 ${result.sessions_revoked} 个会话。`);
    } catch (failure) { setError((failure as Error).message); void read(); }
    finally { setBusy(""); }
  }
  function ask(account: Account, action: Action) { if (confirmText[action]) setConfirming({ id: account.principal_id, action }); else void act(account, action); }
  async function copy() {
    if (!link) return;
    try { await navigator.clipboard.writeText(link.url); setNotice("链接已复制。请通过钉钉或当面发给本人，不要发到群里。"); }
    catch { linkInput.current?.select(); setNotice("无法自动复制，请手动复制已选中的链接。"); }
  }
  return <section className={styles.section} aria-label="账户与邀请">
    <div className={styles.head}><div><h2>账户与邀请</h2><p>账户只由管理员开通。邀请和重设链接 72 小时内有效、只能使用一次；停用账户或重置密码会立即结束它的全部会话。任何人都不能停用自己或更改自己的管理员身份，租户至少保留一位启用的管理员。</p></div></div>
    <form className={styles.create} onSubmit={create} aria-label="新建账户">
      <label>姓名<input required maxLength={160} value={form.display_name} onChange={event => setForm(old => ({ ...old, display_name: event.target.value }))} placeholder="例如：王工"/></label>
      <label>登录名<input required maxLength={64} autoCapitalize="none" spellCheck={false} value={form.login_name} onChange={event => setForm(old => ({ ...old, login_name: event.target.value }))} placeholder="小写字母、数字或 . _ -"/></label>
      <Button type="submit" disabled={Boolean(busy) || !form.display_name.trim() || !form.login_name.trim()}><UserPlus/>{busy === "create" ? "正在创建…" : "新建并生成邀请"}</Button>
    </form>
    {link && <div className={styles.link} role="status">
      <p>已为 <strong>{link.name}</strong> 生成{link.purpose}，有效至 {link.expires}，只能使用一次。链接只显示这一次。</p>
      <div className={styles.linkRow}><input ref={linkInput} readOnly value={link.url} aria-label={link.purpose} data-account-link onFocus={event => event.currentTarget.select()}/><Button type="button" variant="outline" onClick={() => void copy()}><Copy/>复制</Button><Button type="button" variant="ghost" onClick={() => setLink(null)}>关闭</Button></div>
    </div>}
    {error && <p role="alert" className={styles.alert}>{error}</p>}
    {notice && <p role="status" className={styles.notice}>{notice}</p>}
    {!items ? !error && <p role="status" className={styles.notice}>正在读取账户…</p> : <div className={styles.tableWrap}><table className={styles.table}>
      <thead><tr><th>成员</th><th>登录名</th><th>状态</th><th>角色</th><th>在线会话</th><th>最近登录</th><th><span className="sr-only">操作</span></th></tr></thead>
      <tbody>{items.map(account => {
        const open = confirming?.id === account.principal_id ? confirming.action : null;
        const working = busy === account.principal_id;
        return <tr key={account.principal_id} data-account={account.login_name ?? account.principal_id}>
          <td><span className={styles.name}>{account.name}</span>{account.self && <span className={styles.you}>（你）</span>}</td>
          <td className={styles.login}>{account.login_name ?? "—"}</td>
          <td><span className={styles.badge} data-status={account.status}>{statusLabel[account.status]}</span>{account.pending_link && <span className={styles.you}>链接至 {time(account.pending_link.expires_at)}</span>}</td>
          <td>{account.administrator ? "管理员" : "成员"}</td>
          <td>{account.active_sessions}</td>
          <td>{time(account.last_sign_in_at)}</td>
          <td>{open ? <div className={styles.confirm}><span>{confirmText[open]}</span><Button size="sm" variant="destructive" disabled={working} onClick={() => void act(account, open)}>确认</Button><Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>取消</Button></div>
            : <div className={styles.actions}>
              {account.login_name && account.active && !account.password_set && <Button size="sm" variant="ghost" disabled={working} onClick={() => ask(account, "invitation")}>重发邀请</Button>}
              {account.login_name && account.active && account.password_set && <Button size="sm" variant="ghost" disabled={working} onClick={() => ask(account, "password-reset")}>重置密码</Button>}
              {account.active_sessions > 0 && <Button size="sm" variant="ghost" disabled={working} onClick={() => ask(account, "sessions/revoke")}>强制下线</Button>}
              {!account.self && account.active && <Button size="sm" variant="ghost" disabled={working} onClick={() => void act(account, "administrator", { administrator: !account.administrator })}>{account.administrator ? "取消管理员" : "设为管理员"}</Button>}
              {!account.self && (account.active ? <Button size="sm" variant="ghost" className="text-destructive" disabled={working} onClick={() => ask(account, "deactivate")}>停用</Button> : <Button size="sm" variant="ghost" disabled={working} onClick={() => ask(account, "reactivate")}>启用</Button>)}
            </div>}</td>
        </tr>;
      })}</tbody>
    </table></div>}
  </section>;
}

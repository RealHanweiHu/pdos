"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { AccountFrame, accountStyles as styles, postJson } from "./account-frame";

type Invitation = { purpose: "invite" | "reset"; display_name: string; login_name: string; expires_at: string };
const MIN = 10;
const time = (value: string) => new Date(value).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });

/** Invitation or reset link. The token travels in the URL fragment, so it never reaches a server log. */
export function InvitationPage() {
  const token = useRef("");
  const [state, setState] = useState<{ phase: "loading" | "ready" | "failed"; invitation?: Invitation; message?: string }>({ phase: "loading" });
  const [password, setPassword] = useState(""), [again, setAgain] = useState("");
  const [error, setError] = useState(""), [busy, setBusy] = useState(false);
  useEffect(() => {
    // Read the fragment once (effects may run twice in development), then drop the
    // secret from the address bar and history; it stays only in memory.
    if (!token.current) token.current = window.location.hash.slice(1);
    if (window.location.hash) window.history.replaceState(null, "", window.location.pathname);
    if (!token.current) { void Promise.resolve().then(() => setState({ phase: "failed", message: "链接不完整。请从管理员发送的消息里重新打开完整链接。" })); return; }
    let active = true;
    postJson<Invitation>("/api/auth/invitation", { token: token.current })
      .then(invitation => { if (active) setState({ phase: "ready", invitation }); })
      .catch(failure => { if (active) setState({ phase: "failed", message: (failure as Error).message }); });
    return () => { active = false; };
  }, []);
  const invitation = state.invitation;
  const reset = invitation?.purpose === "reset";
  const problem = password && password.length < MIN ? `密码至少 ${MIN} 个字符。` : again && again !== password ? "两次输入的密码不一致。" : "";
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || problem || !password || password !== again) return;
    setBusy(true); setError("");
    try {
      await postJson("/api/auth/invitation/accept", { token: token.current, password });
      token.current = "";
      window.location.replace("/");
    } catch (failure) {
      const reason = (failure as { reason?: string }).reason;
      if (reason && reason.startsWith("INVITATION_")) setState({ phase: "failed", message: (failure as Error).message });
      else setError((failure as Error).message);
      setBusy(false);
    }
  }
  if (state.phase === "loading") return <AccountFrame title="正在核对链接"><p role="status" className={styles.status}>正在核对链接是否有效…</p></AccountFrame>;
  if (state.phase === "failed" || !invitation) return <AccountFrame title="链接不可用" lead={state.message}>
    <p className={styles.footnote}>每个链接只能使用一次，72 小时内有效。已有账户可以直接<a href="/login">登录</a>。</p>
  </AccountFrame>;
  return <AccountFrame title={reset ? "重新设置密码" : "设置密码，开始使用 PDOS"} lead={reset ? "管理员已重置你的密码，旧密码和原有登录都已失效。设好新密码后会直接进入工作区。" : "管理员已为你开通账户。设好密码后会直接进入工作区。"}>
    <dl className={styles.facts}>
      <dt>姓名</dt><dd>{invitation.display_name}</dd>
      <dt>登录名</dt><dd>{invitation.login_name}</dd>
      <dt>链接有效至</dt><dd>{time(invitation.expires_at)} · 只能使用一次</dd>
    </dl>
    {error && <p role="alert" className={styles.alert}>{error}</p>}
    <form className={styles.form} onSubmit={submit} noValidate>
      <input type="text" name="username" autoComplete="username" value={invitation.login_name} readOnly hidden/>
      <label>新密码<input name="new-password" type="password" autoComplete="new-password" required minLength={MIN} maxLength={128} value={password} onChange={event => setPassword(event.target.value)} aria-describedby="password-rule" autoFocus/></label>
      <p id="password-rule" className={styles.hint}>至少 {MIN} 个字符，不能与登录名相同。</p>
      <label>再次输入<input name="confirm-password" type="password" autoComplete="new-password" required maxLength={128} value={again} onChange={event => setAgain(event.target.value)} aria-invalid={Boolean(again && again !== password)}/></label>
      {problem && <p role="status" className={styles.hint}>{problem}</p>}
      <Button type="submit" className={styles.submit} disabled={busy || Boolean(problem) || !password || password !== again}>{busy ? "正在保存…" : reset ? "保存新密码并登录" : "设置密码并登录"}</Button>
    </form>
  </AccountFrame>;
}

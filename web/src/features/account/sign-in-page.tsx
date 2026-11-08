"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { AccountFrame, accountStyles as styles, postJson, safeNext } from "./account-frame";

export function SignInPage() {
  const [loginName, setLoginName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    const reason = new URLSearchParams(window.location.search).get("reason");
    const text = reason === "expired" ? "会话已结束，请重新登录。" : reason === "signed_out" ? "你已退出登录。" : "";
    if (text) void Promise.resolve().then(() => setNotice(text));
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await postJson("/api/auth/sign-in", { login_name: loginName.trim(), password });
      window.location.replace(safeNext(new URLSearchParams(window.location.search).get("next")));
    } catch (failure) {
      setPassword("");
      setError((failure as Error).message);
      setBusy(false);
    }
  }
  return <AccountFrame title="登录 PDOS" lead="使用管理员为你开通的登录名和密码。">
    {notice && <p role="status" className={`${styles.status} mb-4`}>{notice}</p>}
    {error && <p role="alert" className={styles.alert}>{error}</p>}
    <form className={styles.form} onSubmit={submit} noValidate>
      <label>登录名<input name="username" autoComplete="username" autoCapitalize="none" spellCheck={false} required maxLength={64} value={loginName} onChange={event => setLoginName(event.target.value)} autoFocus/></label>
      <label>密码<input name="password" type="password" autoComplete="current-password" required maxLength={128} value={password} onChange={event => setPassword(event.target.value)}/></label>
      <Button type="submit" className={styles.submit} disabled={busy || !loginName.trim() || !password}>{busy ? "正在登录…" : "登录"}</Button>
    </form>
    <p className={styles.footnote}>账户只由租户管理员开通。忘记密码时，请联系管理员重置，你会收到一个 72 小时内有效、只能使用一次的链接。</p>
  </AccountFrame>;
}

"use client";

import type { ReactNode } from "react";
import { useTheme } from "next-themes";
import { Moon, Sun } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import styles from "./account.module.css";

/** Shared public frame for sign-in and link pages: brand, theme toggle, one narrow column. */
export function AccountFrame({ title, lead, children }: { title: string; lead?: ReactNode; children: ReactNode }) {
  const { resolvedTheme, setTheme } = useTheme();
  return <div className={styles.page}>
    <header className={styles.header}>
      <span className={styles.brandMark} aria-hidden="true">P</span><span className={styles.brand}>PDOS</span>
      <Button className={styles.theme} size="icon" variant="ghost" aria-label="切换明暗主题" title="切换明暗主题" onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}>{/* Both icons render; CSS picks one, so server and client markup match. */}<Sun className="hidden dark:block"/><Moon className="block dark:hidden"/></Button>
    </header>
    <main className={styles.main}><div className={styles.column}>
      <h1 className={styles.title}>{title}</h1>
      {lead ? <p className={styles.lead}>{lead}</p> : <div className="h-7"/>}
      {children}
    </div></main>
  </div>;
}

export const accountStyles = styles;

/** A same-origin path to continue to after sign-in; anything else returns to the workspace. */
export function safeNext(value: string | null): string {
  return value && value.startsWith("/") && !value.startsWith("//") && !value.startsWith("/\\") && !value.startsWith("/api/") ? value : "/";
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), cache: "no-store" });
  const value = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(value.message ?? "服务暂不可用，请稍后重试。"), { status: response.status, reason: value.detail?.reason });
  return value as T;
}

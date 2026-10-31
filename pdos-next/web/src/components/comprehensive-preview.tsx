"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { ArrowRight, Compass, Moon, Sun } from "@phosphor-icons/react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/browser-api";
import type { PreviewCatalog } from "@/lib/local-preview-types";

export function ComprehensivePreview({ catalog, initialRoleId, progress }: { catalog: PreviewCatalog; initialRoleId?: string; progress: ReactNode }) {
  const initialRole = catalog.roles.find(role => role.id === initialRoleId);
  const [caseId, setCaseId] = useState(initialRole?.caseId ?? catalog.cases[0].id);
  const [roleId, setRoleId] = useState(initialRole?.id ?? catalog.cases[0].roleIds[0]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const { resolvedTheme, setTheme } = useTheme();
  const selected = catalog.cases.find(item => item.id === caseId)!;
  const roles = catalog.roles.filter(item => selected.roleIds.includes(item.id));
  async function enter(entryId: string) {
    setBusy(entryId); setError("");
    try {
      const result = await browserApi<{ href: string }>("preview-session", { caseId, roleId, entryId });
      window.location.assign(result.href);
    } catch (failure) { setError((failure as Error).message); setBusy(""); }
  }
  return <>
    <header className="workspace-public-header"><Compass size={20} className="text-primary"/><strong>PDOS</strong><span className="subtle">综合预览</span><div className="ml-auto flex items-center gap-3"><Link href="/plan" className="text-sm hover:text-primary">功能进展</Link><Button size="icon" variant="ghost" aria-label="切换明暗主题" onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}><Sun className="hidden dark:block"/><Moon className="dark:hidden"/></Button></div></header>
    <main className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-8">
      <section className="border-b border-border pb-5"><p className="text-xs font-medium text-primary">9 个业务场景 · 实际保存的数据 · 可切换演示身份</p><h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">走进目前的研发工作区</h1><p className="mt-3 max-w-3xl text-sm leading-6 text-[var(--text-subtle)]">从提案到现场反馈，选择一个有数据的案例亲手体验。各案例来自已验证的合成流程，使用独立预览副本；修改会保留在本地，不影响你已确认的 S1 演示。</p></section>
      <div className="grid items-start gap-6 lg:grid-cols-[290px_1fr]">
        <nav aria-label="选择业务场景" className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-1">{catalog.cases.map(item => <button key={item.id} disabled={!!busy} aria-current={caseId === item.id ? "true" : undefined} className={`rounded-lg border px-4 py-3 text-left text-sm transition-colors ${caseId === item.id ? "border-primary bg-primary/5 text-primary" : "border-border hover:bg-muted"}`} onClick={() => { setCaseId(item.id); setRoleId(item.roleIds[0]); setError(""); }}><span className="font-medium">{item.title}</span></button>)}</nav>
        <section aria-labelledby="scenario-title" className="panel min-w-0 !p-6 sm:!p-8">
          <p className="text-xs text-[var(--text-subtle)]">本地合成案例</p><h2 id="scenario-title" className="mt-2 text-xl font-semibold">{selected.title.slice(5)}</h2><p className="mt-3 text-sm leading-7">{selected.summary}</p>
          <div className="my-5 flex flex-wrap gap-x-6 gap-y-3 border-y border-border py-4">{selected.counts.length ? selected.counts.map(item => <p key={item.label} className="text-sm"><strong className="mr-1 font-mono text-lg">{item.value}</strong><span className="text-[var(--text-subtle)]">{item.label}</span></p>) : <p className="text-sm">本人已确认提案 · 已批准 G0 · 2 项承接事项</p>}</div>
          <p className="text-xs text-[var(--text-subtle)]">数量来自预览准备时的数据库记录；进入页面可查看和刷新当前状态。</p>
          <label className="mt-6 block text-sm font-medium" htmlFor="preview-role">以谁的身份体验</label><select id="preview-role" className="mt-2 max-w-xl" value={roleId} disabled={!!busy} onChange={event => setRoleId(event.target.value)}>{roles.map(role => <option key={role.id} value={role.id}>{role.label} · {role.name}</option>)}</select>
          <p className="mt-2 text-xs leading-6 text-[var(--text-subtle)]">仅切换本案例的列名演示账号。专业资格、权限和具名决定仍由实际页面核对。</p>
          <div className="mt-6 flex flex-wrap gap-3">{selected.entries.map((entry, index) => <Button key={entry.id} variant={index === 0 ? "default" : "outline"} disabled={!!busy} onClick={() => void enter(entry.id)}>{busy === entry.id ? "正在进入…" : entry.label}<ArrowRight size={16}/></Button>)}</div>
          {error && <p role="alert" className="mt-4 text-sm text-destructive">{error}</p>}
          <p className="mt-6 border-l-2 border-primary pl-3 text-sm leading-6 text-[var(--text-subtle)]">{selected.limit}</p>
        </section>
      </div>
      <section className="grid gap-6 border-y border-border py-6 md:grid-cols-2"><div><h2 className="font-semibold">小Pai 现在能体验什么</h2><p className="mt-2 text-sm leading-7 text-[var(--text-subtle)]">场景 01 可回看真实模型起草、本人确认和保存结果。各工作区保留小Pai入口；这份综合预览未开启新模型调用，全岗位自动接续仍在建设中。</p></div><div><h2 className="font-semibold">哪些仍未接齐</h2><p className="mt-2 text-sm leading-7 text-[var(--text-subtle)]">组合与资源、完整阶段门禁、部分驾驶舱汇总及跨场景的小Pai接续仍有缺口。页面会展示实际空态或限制，下面的进度直接读取当前建设清单。</p></div></section>
      {progress}
      <footer className="border-t border-border pt-4 text-xs leading-6 text-[var(--text-subtle)]">演示账号有效至 {catalog.expires_at.slice(0, 10)}。专业事实的原有效期不延长；合成批准和外部回执不代表真实签核或对外发送。</footer>
    </main>
  </>;
}

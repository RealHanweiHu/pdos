"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { ArrowClockwise, ArrowRight, ArrowSquareOut, Circle, Compass, Moon, Sun } from "@phosphor-icons/react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/browser-api";
import { readPortfolio, type Portfolio } from "@/lib/portfolio-reads";

type Snapshot = { name: string; portfolio: Portfolio };

export function PreviewGuide({ progress }: { progress: ReactNode }) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [signedOut, setSignedOut] = useState(false);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [projectId, setProjectId] = useState("");
  const { resolvedTheme, setTheme } = useTheme();

  useEffect(() => {
    let active = true;
    async function read() {
      try {
        const who = await browserApi<{ name: string }>("v1/session");
        const portfolio = await readPortfolio(browserApi);
        if (active) { setSnapshot({ name: who.name, portfolio }); setError(""); setSignedOut(false); }
      } catch (failure) {
        if (active) { setSnapshot(null); setSignedOut((failure as { status?: number }).status === 401); setError((failure as Error).message); }
      }
    }
    void read();
    return () => { active = false; };
  }, [revision]);

  async function signIn() {
    setBusy(true); setError("");
    try { await browserApi("local-session", {}); setRevision(value => value + 1); }
    catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }

  const projects = snapshot?.portfolio.projects ?? [];
  const selected = projects.find(item => item.project.id === projectId) ?? projects[0];
  const cockpit = selected ? `/?${new URLSearchParams({ area: "cockpit", category: selected.category.id, project: selected.project.id })}` : "/?area=projects";
  const proposals = selected ? `/?${new URLSearchParams({ area: "category", category: selected.category.id, focus: "proposals" })}` : "/?area=category";
  const bench = (view: string, task?: string) => selected ? `/?${new URLSearchParams({ area: "category", category: selected.category.id, product: selected.product.id, project: selected.project.id, bench: "projects", view, ...(task ? { task } : {}) })}` : "/?area=projects";
  const steps = [
    { number: "01", title: "从我的工作开始", body: "看本人待办、项目与需要继续的工作，再从事项进入办理。", href: "/?area=work", action: "打开我的工作" },
    { number: "02", title: "走进项目驾驶舱", body: "核对固定定义、负责人、G0 承接事项与项目动态。未知日期和健康度保留为未知。", href: cockpit, action: "进入项目驾驶舱" },
    { number: "03", title: "回看提案与小Pai", body: "从提案进入文档，查看 AI 起草条目、本人确认和 G0 决定；小Pai 工作记录可回看实际运行。", href: proposals, action: "查看立项提案" },
    { number: "04", title: "体验工作与计划", body: "查看任务、计划候选与确认入口。本次项目尚未填入的内容，需要你按页面提示继续办理。", href: bench("plan"), action: "打开工作与计划" },
  ];

  return <>
    <header className="workspace-public-header"><Compass size={20} className="text-primary" aria-hidden="true"/><strong>PDOS</strong><span className="subtle">本地预览</span><div className="ml-auto flex items-center gap-3"><Link className="text-sm hover:text-primary" href="/plan">进展详情</Link><Button size="icon" variant="ghost" aria-label="切换明暗主题" onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}><Sun className="hidden dark:block"/><Moon className="dark:hidden"/></Button></div></header>
    <main className="mx-auto max-w-6xl space-y-10 px-4 py-8 sm:px-8 sm:py-10">
      <section className="border-b border-border pb-8">
        <p className="mb-3 text-xs font-medium text-primary">实际应用 · 本机合成演练</p>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">看进展，也亲手走一遍。</h1>
        <p className="mt-4 max-w-2xl text-sm leading-7 text-[var(--text-subtle)]">从下面的入口进入当前应用。已保存的提案、项目和回执会保留；专业工作台中的空态和未接入项也按实际情况展示。</p>
        <div className="mt-5 flex flex-wrap gap-3"><Button asChild><Link href="/?area=work">进入工作区<ArrowRight/></Link></Button><Button variant="outline" asChild><a href="#current-progress-heading">查看当前进展</a></Button></div>
      </section>

      <section aria-labelledby="preview-project" className="panel">
        <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 id="preview-project" className="font-semibold">本次体验的数据</h2><p className="subtle mt-1">{snapshot ? `${snapshot.name} · 按当前账号读取` : "正在核对本地会话与项目"}</p></div><Button size="sm" variant="outline" onClick={() => { setSnapshot(null); setError(""); setRevision(value => value + 1); }}><ArrowClockwise/>刷新</Button></div>
        {error && <p role="alert" className="mt-4 text-sm text-destructive">{error}</p>}
        {signedOut && <Button disabled={busy} className="mt-4" onClick={() => void signIn()}>进入本地合成环境</Button>}
        {snapshot?.portfolio.readErrors.map(item => <p key={item.path} role="status" className="mt-3 text-sm">{item.message}</p>)}
        {selected && <div className="mt-5 grid gap-5 md:grid-cols-2"><div>
          {projects.length > 1 ? <label>选择体验项目<select value={selected.project.id} onChange={event => setProjectId(event.target.value)}>{projects.map(item => <option key={item.project.id} value={item.project.id}>{item.project.name}</option>)}</select></label> : <h3 className="text-lg font-medium">{selected.project.name}</h3>}
          <p className="subtle mt-2">{selected.category.name} · {selected.product.name}</p><p className="mt-2 text-sm">{selected.project.plan_state === "unavailable" ? "计划暂不可读" : selected.project.plan ? "已有项目计划，可进入继续办理" : "尚未建立项目计划"}</p>
        </div><div><p className="mb-2 text-sm font-medium">当前项目承接事项</p>{selected.openItemsError ? <p role="status">{selected.openItemsError}</p> : selected.openItems.length ? <ul className="space-y-2">{selected.openItems.map(item => <li key={item.id} className="flex items-start gap-2 text-sm"><Circle size={16} className="mt-0.5 shrink-0 text-primary" aria-hidden="true"/><span>{item.title}<span className="subtle ml-2">{item.due_date ?? "日期未定"}</span></span></li>)}</ul> : <p className="subtle">暂无承接事项。</p>}</div></div>}
        {snapshot && !selected && <p role="status" className="mt-4">当前账号没有可见项目，可先从品类与提案入口开始。</p>}
      </section>

      <section aria-labelledby="experience-heading"><h2 id="experience-heading" className="mb-5 text-lg font-semibold">建议按这个顺序体验</h2><div className="grid gap-x-8 gap-y-6 md:grid-cols-2">{steps.map(step => <article key={step.number} className="border-t border-border pt-4"><p className="font-mono text-xs text-primary">{step.number}</p><h3 className="mt-2 font-semibold">{step.title}</h3><p className="mt-2 text-sm leading-6 text-[var(--text-subtle)]">{step.body}</p><Link className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-primary hover:underline" href={step.href}>{step.action}<ArrowRight size={16}/></Link></article>)}</div></section>

      <section aria-labelledby="more-experience" className="panel"><h2 id="more-experience" className="font-semibold">继续探索专业工作台</h2><p className="subtle mt-2">这些模块已有不同程度的实现与合成验证。本次项目尚无完整试制、测试、变更和交付案例，进入后需按实际前置继续办理；入口可见不代表阶段已验收。</p><div className="mt-4 flex flex-wrap gap-2">{[{ label: "试制与配置", href: bench("builds", "prepare") }, { label: "测试与交接", href: bench("verification", "handoff") }, { label: "问题与变更", href: bench("issues") }, { label: "现场反馈", href: bench("field") }, { label: "知识", href: "/?area=knowledge" }, { label: "模型与设置", href: "/?area=settings" }].map(item => <Button key={item.label} variant="outline" size="sm" asChild><Link href={item.href}>{item.label}<ArrowSquareOut/></Link></Button>)}</div></section>

      <section className="border-l-2 border-primary pl-4" aria-labelledby="pai-state"><h2 id="pai-state" className="font-semibold">小Pai 当前体验边界</h2><p className="mt-2 text-sm leading-7 text-[var(--text-subtle)]">本次演示已验证提案真实起草和本人确认保存，启用范围为起草与查漏。个人入口仍偏向建立品类，项目与专业技能尚未全部接续。可先回看已保存运行；发起新工作仍受当前技能配置和调用额度限制。</p><p className="subtle mt-2">打开导览、浏览记录不会发起模型调用；不会自动扩充额度或启用更多技能。</p></section>
      {progress}
      <footer className="border-t border-border pt-5 text-xs text-[var(--text-subtle)]">预览使用本机合成环境。实际保存走现有确认与具名决定流程；尚未完成的功能不会用演示结果代替。</footer>
    </main>
  </>;
}

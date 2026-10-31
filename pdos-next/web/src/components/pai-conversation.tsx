import { useEffect, useRef, type ReactNode, type RefObject } from "react";
import { ArrowUpRight, CaretDown, Check, DotsThree, FileText, Folder, Minus, SidebarSimple, Plus, Sparkle, X } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { usedSkillName } from "@/lib/run-process";
import { AnswerSources } from "./pai/answer-sources";
import styles from "./pai-conversation.module.css";

export type LoadedSkill = { key: string; version?: string };

/** Follow new replies, while leaving someone reading earlier messages in place. */
export function usePaiScroll(panel: RefObject<HTMLElement | null>, turnKey?: string) {
  const follow = useRef(true);
  useEffect(() => {
    if (typeof MutationObserver === "undefined") return;
    const thread = panel.current?.querySelector<HTMLDivElement>('[aria-label="小Pai 对话线程"]');
    if (!thread) return;
    const scroll = () => { follow.current = thread.scrollHeight - thread.clientHeight - thread.scrollTop < 64; };
    const observer = new MutationObserver(() => { if (follow.current) thread.scrollTop = thread.scrollHeight; });
    observer.observe(thread, { childList: true, subtree: true, characterData: true });
    thread.addEventListener("scroll", scroll, { passive: true });
    return () => { observer.disconnect(); thread.removeEventListener("scroll", scroll); };
  }, [panel]);
  useEffect(() => {
    follow.current = true;
    if (typeof MutationObserver === "undefined") return;
    const thread = panel.current?.querySelector<HTMLDivElement>('[aria-label="小Pai 对话线程"]');
    if (thread) thread.scrollTop = thread.scrollHeight;
  }, [panel, turnKey]);
}

/** Skill chips describe persisted load events, never a client-side capability grant. */
export function loadedSkillFacts(events: { event: { type: string; key?: string; version?: string } }[]): LoadedSkill[] {
  return [...new Map(events.flatMap(({ event }) => event.type === "skill_loaded" && event.key
    ? [[`${event.key}:${event.version ?? ""}`, { key: event.key, version: event.version }] as const] : [])).values()];
}

export function PaiScope({ scope, skills, hasRun, title, historyOpen, onHistoryToggle, onNewConversation, onBackground, disabled, actions }: {
  actions?: ReactNode;
  onBackground?: () => void;
  scope: string; skills: LoadedSkill[]; hasRun: boolean; title?: string; historyOpen?: boolean; onHistoryToggle?: () => void; onNewConversation?: () => void; disabled?: boolean;
}) {
  return <div className={styles.scopeBar}>
    {onHistoryToggle && <Button size="sm" variant="ghost" className={styles.historyToggle} aria-label={historyOpen ? "返回对话" : "工作记录"} title={historyOpen ? "返回对话" : "会话记录"} aria-expanded={!!historyOpen} onClick={onHistoryToggle}><SidebarSimple size={16} aria-hidden="true" /></Button>}
    <span className={styles.conversationTitle} title={title || "小Pai"}>{title?.split("\n")[0] || "小Pai"}</span>
    {onNewConversation && <Button size="sm" variant="ghost" className={styles.toolbarButton} aria-label="新建对话" title="新建对话" disabled={disabled} onClick={onNewConversation}><Plus size={16} aria-hidden="true" /></Button>}
    <details className={styles.conversationInfo} onKeyDown={event => { if (event.key === "Escape") { event.currentTarget.open = false; event.currentTarget.querySelector("summary")?.focus(); } }}><summary aria-label="会话信息" title="更多"><DotsThree size={18} aria-hidden="true"/></summary><div>
      {onBackground && <button type="button" className={styles.backgroundAction} aria-label="后台继续" disabled={disabled} title="收起对话，继续在后台处理" onClick={event => { event.currentTarget.closest("details")?.removeAttribute("open"); onBackground(); }}><Minus size={15} aria-hidden="true"/>后台继续</button>}
      <p>范围：{scope}</p>
      {hasRun && <><p>已使用的技能</p>{skills.map(skill => <span key={`${skill.key}:${skill.version ?? ""}`} className={styles.skillChip}><Check size={11} aria-hidden="true" />{usedSkillName(skill.key)}{skill.version ? ` · ${skill.version}` : ""}</span>)}{!skills.length && <p>尚无加载记录</p>}</>}
      <PaiPolicy />
    </div></details>{actions}
  </div>;
}

export function PaiMessage({ from, children }: { from: "user" | "pai"; children: ReactNode }) {
  return <article className={`${styles.message}${from === "user" ? ` ${styles.user}` : ""}`} aria-label={from === "user" ? "你委派的目标" : "小Pai 的实际结果"}>
    {from === "pai" && <p className={styles.who}><span className={styles.agentTag}><Sparkle size={14} aria-hidden="true" />小Pai</span></p>}
    <div className={from === "user" ? styles.bubble : styles.messageBody}>{children}</div>
  </article>;
}

/** A presentation record has no original Run status, creation clock or actions. */
export function PaiHiddenResponse({ run }: { run: { hidden_message: string; recorded_at: string } }) {
  return <div role="status"><p className={styles.response}>{run.hidden_message}</p><p className="text-xs text-muted-foreground">记录时间：<time dateTime={run.recorded_at} title={run.recorded_at}>{new Date(run.recorded_at).toLocaleString()}</time></p></div>;
}

/** The conversation shows the answer; execution diagnostics stay in its disclosure. */
export function PaiResponse({ run, collapsedCitationIds }: { collapsedCitationIds?: string[]; run: { status: string; reverted: boolean; error_code?: string | null; result?: { summary?: string; result?: { assistant?: { lookup?: string; notice?: string | null; sources?: unknown; unknowns?: unknown } } | null } | null } }) {
  const summary = run.result?.summary;
  const notLooked = run.status === "completed" && run.result?.result?.assistant?.lookup === "not_run";
  const fallback = run.reverted ? "这次结果已撤回。可以新建对话继续。"
    : run.error_code || run.status === "failed" ? "这次没能完成回复。具体原因可在运行记录中查看。"
    : run.status === "queued" ? "正在准备回复…"
    : run.status === "running" ? "正在处理…"
    : run.status === "waiting_input" ? "还需要你补充以下信息。"
    : run.status === "cancelled" ? "已停止。你可以继续补充想法。"
    : "这次回复没有返回正文，可以继续告诉我需要完善的内容。";
  const split = summary && summary.length > 400 ? summary.indexOf("\n\n") : -1;
  const evidence = !run.reverted && ["completed", "partial"].includes(run.status) ? <AnswerSources answer={run.result?.result?.assistant} collapsedCitationIds={collapsedCitationIds} /> : null;
  if (summary && split > 0) return <><p className={styles.response}>{summary.slice(0, split)}</p><details className={styles.runDetails}><summary>展开完整回复</summary><p className={styles.response}>{summary.slice(split + 2)}</p></details>{notLooked && <p className={styles.lookupNote}>未查公司资料</p>}{evidence}</>;
  return <><p className={styles.response} role={run.error_code || run.status === "failed" ? "status" : undefined}>{summary || fallback}</p>{notLooked && <p className={styles.lookupNote}>未查公司资料</p>}{evidence}</>;
}

export function PaiUnfinished({ items }: { items?: string[] }) {
  if (!items?.length) return null;
  return <details className={styles.runDetails}><summary>待完善 · {items.length} 项</summary><ul className="list-disc space-y-1 pl-4">{items.map((item, index) => <li key={index}>{item}</li>)}</ul></details>;
}

/** Reply context is separate from operational controls and diagnostic records. */
export function PaiReplyDetails({ scope, skills = [], contextHref, children }: {
  scope: string; skills?: LoadedSkill[]; contextHref?: string; children: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const names = [...new Set(skills.map(skill => usedSkillName(skill.key)))];
  return <>
    <details className={styles.replyDetails}>
      <summary>对话详情<CaretDown size={10} aria-hidden="true" /></summary>
      <p>上下文：{scope}。</p>
      {names.length > 0 && <p>已加载技能：{names.join("、")}。</p>}
      <div className={styles.replyLinks}>
        {contextHref && <a href={contextHref}>查看关联页面<ArrowUpRight size={12} aria-hidden="true" /></a>}
        <button type="button" onClick={() => dialog.current?.showModal()}>查看运行记录<ArrowUpRight size={12} aria-hidden="true" /></button>
      </div>
    </details>
    <dialog ref={dialog} className={styles.recordDialog} aria-label="运行记录">
      <header><h2>运行记录</h2><Button size="sm" variant="ghost" aria-label="关闭运行记录" onClick={() => dialog.current?.close()}><X size={16} aria-hidden="true" /></Button></header>
      <div className={styles.recordDialogBody}>{children}</div>
    </dialog>
  </>;
}

export function PaiMobileWorkspaceSwitch({ view, onClick }: { view: "chat" | "editor"; onClick: () => void }) {
  const label = view === "chat" ? "继续对话" : "返回编辑";
  return <Button type="button" size="sm" variant="ghost" className={styles.mobileWorkspaceSwitch} aria-label={label} title={label} onClick={onClick}>
    {view === "chat" ? <Sparkle size={14} aria-hidden="true" /> : <FileText size={14} aria-hidden="true" />}{label}
  </Button>;
}

export function PaiDocumentCard({ title, metadata, action, onOpen, disabled, children }: {
  title: string; metadata: string; action: string; onOpen: () => void; disabled?: boolean; children?: ReactNode;
}) {
  return <article className={styles.documentCard}>
    <button type="button" className={styles.documentOpen} aria-label={`${action}：${title}`} disabled={disabled} onClick={onOpen}>
      <span className={styles.documentIdentity}><FileText size={19} aria-hidden="true"/><span><strong>{title}</strong><small>{metadata}</small></span></span>
      <span className={styles.documentAction}>{action}<ArrowUpRight size={14} aria-hidden="true"/></span>
    </button>{children}
  </article>;
}

export function PaiCarry({ scope, objects }: { scope: string; objects: string[] }) {
  return <details className={styles.carry} aria-label="本次发送携带什么">
    <summary aria-label="查看携带上下文" title={`携带：${scope}${objects.length ? ` · ${objects.length} 个对象` : ""}`}><Folder size={13}/>{objects.length > 0 && <span>{objects.length}</span>}</summary>
    <div><p>本次发送携带什么</p><p>范围：{scope}</p>
      <p>对象：{objects.length ? objects.join("；") : "未附加对象或原件"}</p>
      <p>技能：发送后由服务器按本次目标加载，以运行中的实际记录为准。</p>
    </div>
  </details>;
}

export function PaiPolicy() {
  return <details className={styles.policy}><summary>办理方式：自动 / 一次确认 / 具名决定</summary>
    <p>自动须具备当前资格和授权；一次确认先核对候选再保存；具名决定由有权人员在正式入口办理。</p>
  </details>;
}

/** Page context remains available without turning the chat bubble into a form dump. */
export function PaiGoal({ value }: { value: string }) {
  const marker = "\n\n当前页面资料（";
  const split = value.indexOf(marker);
  return <><p className="whitespace-pre-wrap break-words text-sm">{split < 0 ? value : value.slice(0,split)}</p>{split >= 0 && <details className="mt-2 text-xs text-muted-foreground"><summary className="cursor-pointer">附带的页面资料</summary><p className="mt-2 whitespace-pre-wrap break-words">{value.slice(split + 2)}</p></details>}</>;
}

export function PaiContextBar({ scope, control }: { scope: string; control?: ReactNode }) {
  return <div className={styles.contextBar}><Folder size={13} aria-hidden="true"/><span title={scope}>{scope}</span>{control}<small>仅你可见</small></div>;
}

export function PaiWelcome({ scope, onSuggest }: { scope?: string; onSuggest: (text: string) => void }) {
  return <div className={styles.empty}><Sparkle size={25} aria-hidden="true"/><h1>{scope ? "一起完善当前工作" : "有什么想一起解决的？"}</h1><p>{scope ? `已带入${scope}，从一个问题或一份资料开始。` : "从一个问题、一个想法，或一份资料开始。"}</p><div className={styles.suggestions}>{(scope ? ["帮我梳理当前资料", "有哪些需要补充的内容", "帮我准备下一步工作"] : ["帮我梳理一个想法", "起草一份工作方案", "比较两个方案"]).map(text => <button key={text} type="button" onClick={() => onSuggest(text)}>{text}<ArrowUpRight size={12}/></button>)}</div></div>;
}

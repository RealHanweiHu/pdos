"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { PaiContextBar, PaiMessage, PaiScope } from "@/components/pai-conversation";
import { RunContinuation } from "@/components/pai/run-continuation";
import styles from "@/components/pai-conversation.module.css";

// Uses the production controls with local state only. No transport or model calls.
const previewApi = async <T,>(path: string): Promise<T> => {
  if (!path.endsWith("/continuation")) throw new Error("此预览不发送消息。");
  return { run_id: "controls-preview", owner_id: "local-preview", can_continue: false, existing: null } as T;
};

export function PaiControlsPreview() {
  const [status, setStatus] = useState("running");
  const [background, setBackground] = useState(false);
  return <main className="mx-auto flex h-dvh max-w-[980px] flex-col gap-3 p-4">
    <header className="flex items-center justify-between gap-3 text-xs text-muted-foreground"><p>运行控件预览 · 本地演示，不调用模型</p><Button size="sm" variant="ghost" onClick={() => { setStatus("running"); setBackground(false); }}>重新演示</Button></header>
    <section className={`${styles.workspace} rounded-lg border border-border`} aria-label="小Pai控件预览">
      {background ? <div className="m-auto flex flex-col items-center gap-4 p-6 text-sm"><p>对话已收起，小Pai继续在后台处理。</p><Button variant="outline" onClick={() => setBackground(false)}>返回对话</Button></div> : <div className={`${styles.conversation} flex-1`}>
        <PaiScope scope="汽车充气泵" skills={[]} hasRun title="整理品类资料" onBackground={status === "running" ? () => setBackground(true) : undefined} />
        <PaiContextBar scope="汽车充气泵" />
        <div className={styles.thread} aria-label="小Pai 对话线程"><PaiMessage from="user">帮我整理当前品类的资料。</PaiMessage><PaiMessage from="pai"><p className={styles.response}>{status === "running" ? "正在整理当前资料…" : "已停止，已有内容保留。"}</p></PaiMessage></div>
        <div className={styles.composer}><RunContinuation presentation="composer" api={previewApi} root="preview" run={{run_id:"controls-preview", session_id:"controls-preview-session", status, reverted:false}} onOpen={async () => {}} onStop={status === "running" ? () => setStatus("cancelled") : undefined} /></div>
      </div>}
    </section>
  </main>;
}

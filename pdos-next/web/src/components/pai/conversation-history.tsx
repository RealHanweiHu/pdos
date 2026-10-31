"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { PaiMessage, PaiUnfinished, PaiResponse, PaiReplyDetails, PaiGoal, PaiHiddenResponse } from "@/components/pai-conversation";
import { ResearchResult } from "./research-result";
import { RunProcess } from "./run-process";
import type { RunProcessData } from "@/lib/run-process";
import { assertHiddenRun, type PaiHiddenRun, type PaiSessionApi, type PaiRunStatus } from "@/lib/pai-sessions";

export type Message = PaiHiddenRun | ReadableMessage;
type ReadableMessage = {
  run_id: string;
  session_id: string;
  goal?: string;
  status: Exclude<PaiRunStatus, "hidden">;
  history_hidden?: false;
  error_code?: string | null;
  reverted: boolean;
  process?: RunProcessData;
  conversation?: { previous_run_id: string | null };
  result?: {
    summary?: string;
    unfinished?: string[];
    result?: Record<string, unknown>;
  };
};
type Props = {
  api: PaiSessionApi;
  root: string;
  sessionId: string;
  previousRunId: string | null;
  onOpen: (id: string) => void;
  onUnavailable: () => void;
  renderMaterials?: (run: ReadableMessage) => ReactNode;
  scope?: string;
  contextHref?: string;
};

/** Read earlier turns from the server-owned chain. Never infer, continue or adopt. */
export function ConversationHistory(props: Props) {
  return (
    <History
      key={`${props.root}:${props.sessionId}:${props.previousRunId}`}
      {...props}
    />
  );
}

function History({
  api,
  root,
  sessionId,
  previousRunId,
  onOpen,
  onUnavailable,
  renderMaterials,
  scope = "通用对话",
  contextHref,
}: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [cursor, setCursor] = useState(previousRunId);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const callbacks = useRef({ onUnavailable });
  useEffect(() => {
    callbacks.current = { onUnavailable };
  }, [onUnavailable]);
  const load = useCallback(
    async (start: string | null, previous: Message[] = []) => {
      if (!start) return;
      const own = ++generation.current;
      setLoading(true);
      setError("");
      try {
        const page: Message[] = [],
          seen = new Set(previous.map((item) => item.run_id));
        let next: string | null = start;
        while (next && page.length < 10) {
          if (seen.has(next))
            throw new Error("会话记录衔接异常，请重新打开会话。");
          const value: Message = await api(`${root}/${next}`);
          if (generation.current !== own) return;
          if (value.status === "hidden") assertHiddenRun(value);
          if (
            value.run_id !== next ||
            value.session_id !== sessionId ||
            !value.conversation
          )
            throw new Error("历史消息与当前会话不一致，请重新打开。");
          seen.add(next);
          page.push(value);
          next = value.conversation.previous_run_id;
        }
        setMessages([...previous, ...page]);
        setCursor(next);
      } catch (failure) {
        if (generation.current !== own) return;
        setError(
          failure instanceof Error
            ? failure.message
            : "历史消息读取失败，可重试。",
        );
        if (
          [401, 403, 404].includes((failure as { status?: number }).status ?? 0)
        ) {
          setMessages([]);
          setCursor(null);
          callbacks.current.onUnavailable();
        }
      } finally {
        if (generation.current === own) setLoading(false);
      }
    },
    [api, root, sessionId],
  );
  useEffect(() => {
    let live = true;
    const counter = generation;
    void Promise.resolve().then(() => {
      if (live) return load(previousRunId);
    });
    return () => {
      live = false;
      counter.current++;
    };
  }, [load, previousRunId]);
  return (
    <>
      {cursor && (
        <Button
          size="sm"
          variant="ghost"
          disabled={loading}
          onClick={() => void load(cursor, messages)}
        >
          {loading ? "正在读取历史消息…" : "查看更早消息"}
        </Button>
      )}
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
      {[...messages].reverse().map((item) => (
        <div className="contents" key={item.run_id}>
          {item.goal && (
            <PaiMessage from="user">
              <PaiGoal value={item.goal}/>
            </PaiMessage>
          )}
          <PaiMessage from="pai">
            {item.status === "hidden" ? <PaiHiddenResponse run={item} /> : <>
            {item.reverted && (
              <p className="text-xs text-muted-foreground">此轮结果已撤回</p>
            )}
            <RunProcess key={`progress:${item.run_id}`} value={item.process} api={api} root={root} presentation="conversation" onUnavailable={onUnavailable} />
            <PaiResponse run={item} />
            <ResearchResult value={item.result?.result?.research} />
            {renderMaterials?.(item)}
            <PaiUnfinished items={item.result?.unfinished} />
            <PaiReplyDetails scope={scope} contextHref={contextHref} skills={item.process?.steps.flatMap(step => step.kind === "skill_loaded" && step.skill ? [{ key: step.skill, version: step.version ?? undefined }] : [])}>
              <p className="break-all">运行 {item.run_id}</p>
              {item.error_code && <p>错误代码：{item.error_code}</p>}
              {item.process && <RunProcess value={item.process} api={api} root={root} />}
              <Button
              size="xs"
              variant="ghost"
              onClick={() => onOpen(item.run_id)}
            >
              查看本轮成果与记录
            </Button></PaiReplyDetails></>}
          </PaiMessage>
        </div>
      ))}
    </>
  );
}

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { PaiMobileWorkspaceSwitch } from "@/components/pai-conversation";
import type { MaterialContext } from "@/components/category-material-editor";
import { ProposalDocument } from "@/components/preproject/proposal-document";
import { ProposalSpecEditor } from "@/components/preproject/proposal-spec-editor";
import { ProposalItemTable } from "@/components/preproject/proposal-item-table";
import { browserApi } from "@/lib/browser-api";
import {
  boundCandidateCommand,
  sameCandidateCommand,
  type DomainCandidate,
  type DomainCommand,
  type CandidatePreview,
  type CandidateReceipt,
} from "@/lib/domain-candidate";
import {
  candidateRows,
  reviseCandidateRows,
  candidateHumanEdits,
} from "@/lib/proposal-candidate-editor";
import type {
  ProposalPatch,
  ProposalRowDraft,
} from "@/lib/proposal-spec-editor";
import { proofClockCurrent } from "@/lib/proof-clock";
import styles from "./proposal-workspace.module.css";

type Props = {
  candidate: DomainCandidate;
  categoryId: string;
  principalId: string;
  open: boolean;
  onClose: () => void;
  onMobileChat?: () => void;
  onContextChange: (id: string, context: MaterialContext | undefined) => void;
  onSaved: () => void;
  onUnavailable: () => void;
};
const sections: Record<string, string> = {
  worth_it: "立项价值",
  summary: "提案摘要",
  target_customer_market_channel: "用户与市场",
  features_in_out: "功能范围",
  certification_regions: "认证与地区",
  launch_window: "上市窗口",
};

/** The original conversation owns this document; saving never navigates away. */
export function PaiProposalWorkspace({
  candidate,
  categoryId,
  principalId,
  open,
  onClose,
  onMobileChat,
  onContextChange,
  onSaved,
  onUnavailable,
}: Props) {
  const original = candidate.command;
  const [rows, setRows] = useState(() =>
    original ? candidateRows(original) : [],
  );
  const [title, setTitle] = useState(
    String(original?.payload.title ?? "提案修订"),
  );
  const [brief, setBrief] = useState(String(original?.payload.brief ?? ""));
  const [drafts, setDrafts] = useState<Record<string, ProposalRowDraft>>({});
  const [preview, setPreview] = useState<CandidatePreview | null>(null);
  const [pending, setPending] = useState<DomainCommand | null>(null);
  const [saved, setSaved] = useState(
    candidate.state === "adopted"
      ? (candidate.receipt?.subject_id ?? null)
      : null,
  );
  const [savedMeta, setSavedMeta] = useState<{ title: string; version?: number } | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [people, setPeople] = useState<{ id: string; name: string }[]>([]);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [ready, setReady] = useState(false);
  const [, tick] = useState(0);
  const dialog = useRef<HTMLDialogElement>(null),
    live = useRef(true),
    lock = useRef(false);
  const key = `pdos-next:proposal-candidate:${principalId}:${categoryId}:${candidate.event_id}`;
  const runId = String(original?.payload.prepared_by_run_id ?? "");
  const publishContext = useCallback(
    (context: MaterialContext | undefined) => onContextChange(candidate.event_id, context),
    [candidate.event_id, onContextChange],
  );
  const updateContext = useCallback(
    (context: MaterialContext | undefined) => {
      setSavedMeta(context ? { title: context.title, version: context.version } : null);
      publishContext(context);
    },
    [publishContext],
  );
  useEffect(() => {
    if (open) dialog.current?.show();
    else dialog.current?.close();
  }, [open]);
  useEffect(() => {
    live.current = true;
    let active = true;
    void Promise.resolve().then(() => {
      if (!active) return;
      try {
        const stored = JSON.parse(sessionStorage.getItem(key) ?? "null");
        if (
          original &&
          stored &&
          boundCandidateCommand(stored, categoryId, runId) &&
          stored.payload.candidate_digest ===
            original.payload.candidate_digest &&
          stored.operation === original.operation &&
          sameCandidateCommand(stored, {
            ...original,
            command_id: stored.command_id,
            idempotency_key: stored.idempotency_key,
            payload: {
              ...original.payload,
              human_edits: stored.payload.human_edits,
            },
          })
        ) {
          const edits = stored.payload.human_edits as
            | Record<string, unknown>
            | undefined;
          setPending(stored);
          if (edits) {
            setRows(
              candidateRows({
                ...original,
                payload: { ...original.payload, ...edits },
              }),
            );
            setTitle(
              String(edits.title ?? original.payload.title ?? "提案修订"),
            );
            setBrief(String(edits.brief ?? original.payload.brief ?? ""));
          }
        }
      } catch {
        /* In-memory recovery remains available. */
      }
      setReady(true);
    });
    void browserApi<{ items: { id: string; name: string }[] }>(
      `v1/categories/${categoryId}/participants`,
    )
      .then((value) => {
        if (active) setPeople(value.items);
      })
      .catch((failure) => {
        if (active) {
          setError(failure.message);
          if ([401, 403, 404].includes(failure.status)) {
            setUnavailable(true);
            updateContext(undefined);
            onUnavailable();
          }
        }
      });
    return () => {
      active = false;
      live.current = false;
    };
  }, [key, categoryId, original, runId, onUnavailable, updateContext]);
  useEffect(() => {
    if (!preview) return;
    const timer = setInterval(() => tick((value) => value + 1), 1000);
    return () => clearInterval(timer);
  }, [preview]);
  useEffect(() => {
    if (!original || saved || unavailable) return;
    publishContext({
      kind: "proposal",
      title,
      id: String(original.payload.proposal_id ?? candidate.event_id),
      draft: { title, brief, items: rows, unsaved_items: drafts },
    });
  }, [
    original,
    saved,
    unavailable,
    title,
    brief,
    rows,
    drafts,
    candidate.event_id,
    publishContext,
  ]);
  const frozen = unavailable || busy || !!pending || !!preview || !ready;
  function remember(value: DomainCommand | null) {
    try {
      if (value) sessionStorage.setItem(key, JSON.stringify(value));
      else sessionStorage.removeItem(key);
    } catch {
      if (value)
        throw new Error("本机存储失败，尚未发送保存请求。请恢复存储后重试。");
    }
  }
  function failed(failure: unknown) {
    const status = (failure as { status?: number }).status;
    setError(failure instanceof Error ? failure.message : "保存失败，请重试。");
    if ([401, 403, 404].includes(status ?? 0)) {
      setUnavailable(true);
      remember(null);
      setPending(null);
      setPreview(null);
      setRows([]);
      setDrafts({});
      setTitle("");
      setBrief("");
      updateContext(undefined);
      onUnavailable();
    }
    return status;
  }
  async function prepare() {
    if (!original || frozen || lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      const request: DomainCommand = {
        ...original,
        command_id: crypto.randomUUID(),
        idempotency_key: crypto.randomUUID(),
        payload: {
          ...original.payload,
          human_edits: candidateHumanEdits(
            original,
            rows,
            drafts,
            title,
            brief,
          ),
        },
      };
      const result = await browserApi<CandidatePreview>(
        `v1/categories/${categoryId}/commands/preview`,
        request,
      );
      if (
        !sameCandidateCommand(result.command, request) ||
        !result.command.payload.confirmation_token ||
        !proofClockCurrent("T1", result.expires_at)
      )
        throw new Error("保存预览无法核对，请重新准备。");
      if (live.current) setPreview(result);
    } catch (failure) {
      if (live.current) failed(failure);
    } finally {
      lock.current = false;
      if (live.current) setBusy(false);
    }
  }
  async function save(request: DomainCommand) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      remember(request);
      setPending(request);
      const result = await browserApi<CandidateReceipt>(
        `v1/categories/${categoryId}/commands`,
        request,
      );
      if (
        !result.id ||
        result.subject_type !== "proposal" ||
        result.operation !== request.operation ||
        !result.subject_id ||
        (request.payload.proposal_id &&
          result.subject_id !== request.payload.proposal_id)
      )
        throw new Error("保存结果尚未核对，请重试原请求。");
      if (!live.current) return;
      remember(null);
      setPending(null);
      setPreview(null);
      setSaved(result.subject_id);
      setSavedMeta({ title, version: Number(result.result.revision) || undefined });
      setDrafts({});
      onSaved();
      window.dispatchEvent(
        new CustomEvent("pdos:proposal-saved", { detail: { categoryId } }),
      );
    } catch (failure) {
      if (!live.current) return;
      const status = failed(failure);
      if (
        status &&
        status >= 400 &&
        status < 500 &&
        ![408, 429].includes(status)
      ) {
        remember(null);
        setPending(null);
        setPreview(null);
      }
    } finally {
      lock.current = false;
      if (live.current) setBusy(false);
    }
  }
  async function mutate(ops: ProposalPatch[]) {
    if (frozen) return false;
    try {
      setRows(reviseCandidateRows(rows, ops));
      return true;
    } catch (failure) {
      failed(failure);
      return false;
    }
  }
  const onDraft = (id: string, value: ProposalRowDraft | null) =>
    setDrafts((previous) => {
      const next = { ...previous };
      if (value) next[id] = value;
      else delete next[id];
      return next;
    });
  const expired = !!preview && !proofClockCurrent("T1", preview.expires_at);
  return (
    <dialog
      ref={dialog}
      className="candidate-editor material-workspace"
      aria-label="立项提案编辑区"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <header className="candidate-editor-heading">
        <div>
          <h3>{saved ? savedMeta?.title ?? "立项提案" : title || "编辑提案"}</h3>
          <p className="subtle">
            {saved
              ? "已保存，继续修改或与小Pai讨论"
              : "小Pai起草 · 人工修改会一并保留"}
          </p>
        </div>
        <PaiMobileWorkspaceSwitch view="chat" onClick={onMobileChat ?? onClose} />
        <Button size="sm" variant="ghost" onClick={onClose}>
          收起编辑区
        </Button>
      </header>
      <div className={`candidate-editor-body ${styles.body}`}>
        {error && <p role="alert">{error}</p>}
        {unavailable ? (
          <p role="alert">当前资料不可访问，请核对权限后重新打开。</p>
        ) : saved ? (
          <ProposalDocument
            categoryId={categoryId}
            proposalId={saved}
            embedded
            onContextChange={updateContext}
          />
        ) : (
          original && (
            <>
              {original.operation === "proposal.create" && (
                <div className={styles.summary}>
                  <label>
                    提案名称
                    <input
                      aria-label="提案名称"
                      value={title}
                      disabled={frozen}
                      onChange={(event) => setTitle(event.target.value)}
                    />
                  </label>
                  <label>
                    摘要
                    <textarea
                      aria-label="提案摘要"
                      rows={3}
                      value={brief}
                      disabled={frozen}
                      onChange={(event) => setBrief(event.target.value)}
                    />
                  </label>
                </div>
              )}
              {rows
                .filter((row) => row.kind === "section")
                .map((row) => (
                  <label className={styles.section} key={row.item_id}>
                    {sections[String(row.content.key)] ?? "说明"}
                    <textarea
                      rows={3}
                      value={String(row.content.text ?? "")}
                      disabled={frozen}
                      onChange={(event) =>
                        setRows((previous) =>
                          previous.map((item) =>
                            item.item_id === row.item_id
                              ? {
                                  ...item,
                                  content: {
                                    ...item.content,
                                    text: event.target.value,
                                  },
                                }
                              : item,
                          ),
                        )
                      }
                    />
                  </label>
                ))}
              <section className={styles.group}>
                <ProposalItemTable
                  kind="option"
                  items={rows.filter((row) => row.kind === "option")}
                  people={people}
                  editable={!frozen}
                  busy={busy}
                  mutate={mutate}
                  drafts={drafts}
                  onDraft={onDraft}
                />
              </section>
              <section className={styles.group}>
                <ProposalSpecEditor
                  categoryId={categoryId}
                  items={rows.filter((row) => row.kind === "spec")}
                  editable={!frozen}
                  busy={busy}
                  mutate={mutate}
                  drafts={drafts}
                  onDraft={onDraft}
                />
              </section>
              <section className={styles.group}>
                <ProposalItemTable
                  kind="question"
                  items={rows.filter((row) => row.kind === "question")}
                  people={people}
                  editable={!frozen}
                  busy={busy}
                  mutate={mutate}
                  drafts={drafts}
                  onDraft={onDraft}
                  onAssignQuestion={(item, content) => {
                    void mutate([
                      {
                        op: "upsert",
                        item_id: item.item_id,
                        base_version: item.version,
                        kind: item.kind,
                        content,
                        source_refs: item.source_refs,
                      },
                    ]).then((ok) => {
                      if (ok) onDraft(item.item_id, null);
                    });
                  }}
                />
              </section>
              {rows
                .filter(
                  (row) =>
                    !["section", "option", "spec", "question"].includes(
                      row.kind,
                    ),
                )
                .map((row) => (
                  <details key={row.item_id} className={styles.extra}>
                    <summary>
                      {(
                        {
                          risk: "风险",
                          assumption: "假设",
                          difference: "差异",
                          commercial_target: "商业目标",
                          decision_note: "决策记录",
                        } as Record<string, string>
                      )[row.kind] ?? "其他条目"}
                    </summary>
                    {Object.entries(row.content).map(([field, value]) => (
                      <p key={field}>
                        {typeof value === "string"
                          ? value
                          : JSON.stringify(value)}
                      </p>
                    ))}
                  </details>
                ))}
            </>
          )
        )}
      </div>
      {!saved && (
        <footer className="candidate-editor-footer">
          {pending ? (
            <>
              <span role="status">{busy ? "正在保存…" : "保存结果待核对，原请求已保留。"}</span>
              <Button
                size="sm"
                disabled={busy || !ready}
                onClick={() => void save(pending)}
              >
                核对原请求
              </Button>
            </>
          ) : !unavailable && preview ? (
            <>
              <span>
                {expired
                  ? "确认已过期，请重新准备。"
                  : "确认将当前修订保存到提案，小Pai会留在旁边。"}
              </span>
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => setPreview(null)}
              >
                继续修改
              </Button>
              <Button
                size="sm"
                disabled={busy || expired}
                onClick={() => void save(preview.command)}
              >
                确认保存
              </Button>
            </>
          ) : (
            <>
              <span className="subtle">
                行内编辑先记入当前草稿，统一确认保存。
              </span>
              <Button
                size="sm"
                disabled={frozen || !original}
                onClick={() => void prepare()}
              >
                保存提案
              </Button>
            </>
          )}
        </footer>
      )}
    </dialog>
  );
}

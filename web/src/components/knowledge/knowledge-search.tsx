"use client";

import {
  ArchiveIcon,
  ArrowClockwiseIcon,
  BookOpenTextIcon,
  CheckCircleIcon,
  MagnifyingGlassIcon,
  PencilSimpleIcon,
  PlusIcon,
  ShieldCheckIcon,
} from "@phosphor-icons/react";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { requestProjects } from "@/components/projects/project-api";
import type { Project } from "@/components/projects/project-types";
import { Button } from "@/components/ui/button";
import { WorkspaceShell } from "@/components/workspace-shell";
import type { WorkspaceIdentity } from "@/components/workspace-types";
import { cn } from "@/lib/utils";

import { SourcePicker, type SourceSelection } from "./source-picker";
import { MemorySources } from "./memory-sources";
import { CorrectionForm, KnowledgeCorrections } from "./knowledge-corrections";
import { KnowledgeLearning } from "./knowledge-learning";
import { KNOWLEDGE_KINDS, KnowledgeKindSelect, knowledgeKindLabel, type KnowledgeKind } from "./knowledge-kind";

import {
  createMemory,
  editMemory,
  requestMemories,
  searchKnowledge,
  transitionMemory,
} from "./memory-api";
import type {
  KnowledgeSearchItem,
  MemoryDraftInput,
  MemoryRecord,
} from "./memory-types";

type LoadState = "loading" | "ready" | "forbidden" | "error" | "redirecting";

const internalRoles = new Set(["owner", "admin", "project_manager", "engineer", "quality"]);
const verificationRoles = new Set(["owner", "admin", "project_manager", "quality"]);
const statusLabels = { draft: "草稿", verified: "已验证", archived: "已归档" } as const;
const emptyDraft: MemoryDraftInput = {
  title: "",
  content: "",
  applicability: null,
  tags: [],
};

function messageFrom(error: unknown) {
  return error instanceof Error ? error.message : "操作失败，请稍后重试。";
}

function projectLabel(project: Project) {
  return `${project.code} · ${project.name}`;
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function sourceLabel(memory: MemoryRecord) {
  if (memory.source_ncr_id) return "CAPA / NCR";
  if (memory.source_finding_id) return "Knowledge Finding";
  return "人工整理";
}

function StatusBadge({ memory }: { memory: MemoryRecord }) {
  return (
    <span
      className={cn(
        "rounded-full border px-2 py-0.5 text-[10px] font-semibold",
        memory.status === "draft" && "border-pending/30 bg-pending/10 text-pending",
        memory.status === "verified" && "border-success/30 bg-success/10 text-success",
        memory.status === "archived" && "border-muted-foreground/20 text-muted-foreground",
      )}
    >
      {statusLabels[memory.status]}
    </span>
  );
}

export function KnowledgeSearch() {
  const { replace } = useRouter();
  const [editingDigest, setEditingDigest] = useState<string | null>(null);
  const [replaceDraftSources, setReplaceDraftSources] = useState(false);
  const [sourceSelections, setSourceSelections] = useState<SourceSelection[]>([]);
  const [correctionRevision, setCorrectionRevision] = useState(0);
  const [state, setState] = useState<LoadState>("loading");
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [query, setQuery] = useState("");
  const [knowledgeKind, setKnowledgeKind] = useState<KnowledgeKind | "unclassified" | null>(null);
  const [results, setResults] = useState<KnowledgeSearchItem[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [busyMemoryId, setBusyMemoryId] = useState<string | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<MemoryDraftInput>(emptyDraft);
  const [showEditor, setShowEditor] = useState(false);
  const [selectedMemoryId, setSelectedMemoryId] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    requestProjects().then(
      async (loaded) => {
        if (!active) return;
        if (loaded === null) {
          setState("redirecting");
          replace("/login");
          return;
        }
        setIdentity(loaded.identity);
        if (!internalRoles.has(loaded.identity.user.role)) {
          setState("forbidden");
          return;
        }
        const requested = new URLSearchParams(window.location.search).get("project");
        setSelectedMemoryId(new URLSearchParams(window.location.search).get("memory"));
        const selected = loaded.projects.find((project) => project.id === requested)
          ?? loaded.projects[0];
        setProjects(loaded.projects);
        setProjectId(selected?.id ?? "");
        try {
          setMemories(selected ? await requestMemories(selected.id) : []);
          if (active) setState("ready");
        } catch (loadError) {
          if (!active) return;
          setError(messageFrom(loadError));
          setState("error");
        }
      },
      (loadError) => {
        if (!active) return;
        setError(messageFrom(loadError));
        setState("error");
      },
    );
    return () => {
      active = false;
    };
  }, [replace]);

  async function switchProject(nextProjectId: string) {
    setProjectId(nextProjectId);
    setResults(null);
    setError(null);
    setStatus(null);
    setShowEditor(false);
    setSelectedMemoryId(null);
    const url = new URL(window.location.href);
    url.searchParams.set("project", nextProjectId);
    url.searchParams.delete("memory");
    window.history.replaceState(null, "", url);
    try {
      setMemories(await requestMemories(nextProjectId));
    } catch (loadError) {
      setError(messageFrom(loadError));
    }
  }

  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId || !query.trim()) return;
    setSearching(true);
    setError(null);
    setStatus(null);
    try {
      setResults(await searchKnowledge(projectId, query, knowledgeKind));
    } catch (searchError) {
      setResults(null);
      setError(messageFrom(searchError));
    } finally {
      setSearching(false);
    }
  }

  function beginCreate() {
    setEditingDigest(null);
    setReplaceDraftSources(false);
    setSourceSelections([]);
    setEditingId(null);
    setDraft(emptyDraft);
    setShowEditor(true);
    setError(null);
  }

  function beginEdit(memory: MemoryRecord) {
    setEditingDigest(memory.review_digest ?? null);
    setReplaceDraftSources(false);
    setSourceSelections([]);
    setEditingId(memory.id);
    setDraft({
      title: memory.title,
      content: memory.content,
      applicability: memory.applicability,
      tags: memory.tags,
      knowledge_kind: memory.knowledge_kind ?? null,
    });
    setShowEditor(true);
    setError(null);
  }

  async function saveDraft(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId) return;
    setBusyMemoryId(editingId ?? "new");
    setError(null);
    setStatus(null);
    try {
      const saved = editingId
        ? await editMemory(projectId, editingId, { ...draft, expected_review_digest: editingDigest ?? "", source_selections: replaceDraftSources ? sourceSelections : null })
        : await createMemory(projectId, { ...draft, source_selections: sourceSelections });
      setMemories((current) =>
        editingId
          ? current.map((memory) => (memory.id === saved.id ? saved : memory))
          : [saved, ...current],
      );
      setShowEditor(false);
      setEditingId(null);
      setDraft(emptyDraft);
      setStatus(editingId ? "Memory 草稿已更新" : "Memory 草稿已创建，尚未进入检索");
    } catch (saveError) {
      setError(messageFrom(saveError));
    } finally {
      setBusyMemoryId(null);
    }
  }

  async function transition(memory: MemoryRecord, action: "verify" | "archive" | "reembed") {
    setBusyMemoryId(memory.id);
    setError(null);
    setStatus(null);
    try {
      const updated = await transitionMemory(projectId, memory.id, action, memory.review_digest);
      setMemories((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setStatus(
        action === "verify"
          ? "Memory 已通过四眼验证并进入语义检索"
          : action === "archive"
            ? "Memory 已归档并退出所有检索入口"
            : "Memory 已按当前模型重新嵌入",
      );
      if (action === "archive") {
        setResults((current) =>
          current?.filter((item) => item.memory.id !== memory.id) ?? null,
        );
      }
    } catch (transitionError) {
      setError(messageFrom(transitionError));
    } finally {
      setBusyMemoryId(null);
    }
  }

  async function logout() {
    setLoggingOut(true);
    try {
      await fetch("/api/session/logout", { method: "POST", credentials: "same-origin" });
    } finally {
      replace("/login");
    }
  }

  if (state === "redirecting") return null;
  if (state === "loading") {
    return (
      <main aria-busy="true" className="mx-auto max-w-6xl px-4 py-10 text-sm text-muted-foreground">
        正在加载 Knowledge Search…
      </main>
    );
  }
  if (state === "forbidden") {
    return (
      <main className="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center px-6 text-center">
        <h1 className="text-lg font-semibold">知识库仅供内部成员</h1>
        <p className="mt-1 text-sm text-muted-foreground">外部角色不能读取 Memory 或推断其存在性。</p>
      </main>
    );
  }
  if (state === "error" || identity === null) {
    return (
      <main className="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center px-6 text-center">
        <h1 className="text-lg font-semibold">Knowledge Search 暂不可用</h1>
        <p className="mt-1 text-sm text-muted-foreground">{error ?? "无法读取 Memory。"}</p>
        <Button className="mt-4 h-11" onClick={() => window.location.reload()}>重新加载</Button>
      </main>
    );
  }

  const canVerify = verificationRoles.has(identity.user.role);
  return (
    <WorkspaceShell
      active="knowledge"
      identity={identity}
      loggingOut={loggingOut}
      onLogout={() => void logout()}
    >
      <header className="flex flex-wrap items-end justify-between gap-4 border-b pb-5">
        <div>
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">
            Verified organizational memory
          </p>
          <h1 className="mt-1 text-lg font-semibold">Knowledge Search</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            只检索经另一位成员验证的项目 Memory；草稿与归档内容不会进入 AI 上下文。
          </p>
        </div>
        <label className="grid min-w-64 gap-1 text-xs font-medium" htmlFor="knowledge-project">
          项目范围
          <select
            className="h-11 rounded-lg border bg-background px-3 text-sm"
            id="knowledge-project"
            onChange={(event) => void switchProject(event.target.value)}
            value={projectId}
          >
            {projects.map((project) => (
              <option key={project.id} value={project.id}>{projectLabel(project)}</option>
            ))}
          </select>
        </label>
      </header>

      {error ? <p className="mt-4 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-3 text-sm text-destructive" role="alert">{error}</p> : null}
      {status ? <p className="mt-4 rounded-lg border border-success/30 bg-success/5 px-3 py-3 text-sm text-success" role="status">{status}</p> : null}

      {projects.length === 0 ? (
        <section className="mt-6 rounded-lg border border-dashed px-4 py-12 text-center">
          <BookOpenTextIcon aria-hidden="true" className="mx-auto size-7 text-muted-foreground" />
          <h2 className="mt-3 font-semibold">还没有可用项目</h2>
          <p className="mt-1 text-sm text-muted-foreground">Memory 必须绑定项目后才能创建和验证。</p>
        </section>
      ) : (
        <>
          <form className="mt-6 rounded-lg border bg-card p-4 sm:p-5" onSubmit={search}>
            <label className="text-sm font-medium" htmlFor="knowledge-query">语义检索</label>
            <div className="mt-2 flex flex-col gap-2 sm:flex-row">
              <div className="relative min-w-0 flex-1">
                <MagnifyingGlassIcon aria-hidden="true" className="absolute left-3 top-3.5 size-4 text-muted-foreground" />
                <input
                  className="h-11 w-full rounded-lg border bg-background pl-9 pr-3 text-sm"
                  id="knowledge-query"
                  maxLength={500}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="例如：DVT 前如何验证连接器？"
                  required
                  value={query}
                />
              </div>
              <label className="text-xs">分类<select className="mt-1 block h-8 rounded-lg border bg-background px-2 text-sm" disabled={searching} value={knowledgeKind ?? ""} onChange={event => { setKnowledgeKind((event.target.value || null) as KnowledgeKind | "unclassified" | null); setResults(null); }}><option value="">全部分类</option>{Object.entries(KNOWLEDGE_KINDS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}<option value="unclassified">历史未分类</option></select></label>
              <Button className="h-11" disabled={searching || !query.trim()} type="submit">
                {searching ? "正在检索…" : "搜索已验证 Memory"}
              </Button>
            </div>
          </form>

          <div className="mt-5 grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
            <section aria-label="Knowledge Search 结果" className="min-w-0 overflow-hidden rounded-lg border bg-card">
              <div className="flex items-center justify-between border-b px-4 py-3 sm:px-5">
                <h2 className="font-semibold">检索结果</h2>
                <span className="font-mono text-[10px] text-muted-foreground">verified only</span>
              </div>
              {results === null ? (
                <div className="px-4 py-14 text-center text-sm text-muted-foreground">
                  输入问题后，系统将按当前 embedding 模型检索本项目的已验证记忆。
                </div>
              ) : results.length === 0 ? (
                <div className="px-4 py-14 text-center">
                  <h3 className="font-medium">没有匹配的已验证 Memory</h3>
                  <p className="mt-1 text-sm text-muted-foreground">这不包含草稿或归档内容。</p>
                </div>
              ) : (
                <ol className="divide-y">
                  {results.map((item, index) => (
                    <li className="px-4 py-4 sm:px-5" key={item.memory.id}>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-[10px] text-muted-foreground">#{index + 1}</span>
                        <StatusBadge memory={item.memory} />
                        <span className="text-xs">{knowledgeKindLabel(item.memory.knowledge_kind)}</span>
                        <span className="text-[10px] text-muted-foreground">相似度 {(item.similarity * 100).toFixed(1)}%</span>
                      </div>
                      <h3 className="mt-2 font-semibold">{item.memory.title}</h3>
                      <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-muted-foreground">{item.memory.content}</p>
                      {item.memory.applicability ? <p className="mt-2 text-xs"><span className="font-medium">适用范围：</span>{item.memory.applicability}</p> : null}
                      <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
                        {item.memory.tags.map((tag) => <span className="rounded-full bg-muted px-2 py-1" key={tag}>{tag}</span>)}
                        <span className="ml-auto font-mono">{item.embedding_provider} / {item.embedding_model}</span>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </section>

            <aside aria-label="Memory 登记册" className="self-start overflow-hidden rounded-lg border bg-card">
              <div className="flex items-center justify-between border-b px-4 py-3">
                <div>
                  <h2 className="font-semibold">Memory 登记册</h2>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">{memories.length} 条含历史记录</p>
                </div>
                <Button aria-label="创建 Memory 草稿" className="size-11" onClick={beginCreate} size="icon" variant="outline">
                  <PlusIcon aria-hidden="true" />
                </Button>
              </div>
              {memories.length === 0 ? (
                <div className="px-4 py-10 text-center text-sm text-muted-foreground">本项目还没有 Memory。</div>
              ) : (
                <ol className="max-h-[680px] divide-y overflow-y-auto">
                  {memories.map((memory) => {
                    const ownDraft = memory.created_by_user_id === identity.user.id || memory.last_edited_by_user_id === identity.user.id;
                    return (
                      <li
                        className={cn("px-4 py-4", selectedMemoryId === memory.id && "bg-primary/5 shadow-[inset_2px_0_0_var(--primary)]")}
                        key={memory.id}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <StatusBadge memory={memory} />
                          <span className="text-[10px] text-muted-foreground">{sourceLabel(memory)}</span>
                        </div>
                        <h3 className="mt-2 text-sm font-semibold">{memory.title}</h3>
                        <p className="mt-1 text-xs text-muted-foreground">{knowledgeKindLabel(memory.knowledge_kind)}{!memory.knowledge_kind && memory.status === "verified" ? " · 保留原审核历史，可通过修正补齐" : ""}</p>
                        <MemorySources key={`${memory.id}:${memory.updated_at}`} projectId={memory.project_id} memoryId={memory.id} />
                        {memory.status === "draft" && !memory.knowledge_kind && <p className="text-xs text-muted-foreground">请先编辑草稿确认分类，再由另一位有权限的成员审核。</p>}
                        {memory.status === "verified" && <CorrectionForm key={`${memory.id}:${memory.content_sha256}`} memory={memory} onSubmitted={() => setCorrectionRevision(value => value + 1)} />}
                        <p className="mt-1 line-clamp-3 text-xs leading-5 text-muted-foreground">{memory.content}</p>
                        <p className="mt-2 font-mono text-[10px] text-muted-foreground">更新 {formatTime(memory.updated_at)}</p>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {memory.status === "draft" ? (
                            <Button className="h-9" disabled={busyMemoryId !== null || !memory.review_digest} onClick={() => beginEdit(memory)} size="sm" variant="outline">
                              <PencilSimpleIcon aria-hidden="true" />编辑
                            </Button>
                          ) : null}
                          {memory.status === "draft" && canVerify && !ownDraft ? (
                            <Button className="h-9" disabled={busyMemoryId !== null || !memory.review_digest || !memory.knowledge_kind} onClick={() => void transition(memory, "verify")} size="sm">
                              <ShieldCheckIcon aria-hidden="true" />{busyMemoryId === memory.id ? "验证中…" : "验证"}
                            </Button>
                          ) : null}
                          {memory.status === "draft" && canVerify && ownDraft ? (
                            <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground"><ShieldCheckIcon aria-hidden="true" />需另一位成员验证</span>
                          ) : null}
                          {memory.status === "verified" && canVerify ? (
                            <>
                              <Button className="h-9" disabled={busyMemoryId !== null} onClick={() => void transition(memory, "reembed")} size="sm" variant="outline">
                                <ArrowClockwiseIcon aria-hidden="true" />重新嵌入
                              </Button>
                              <Button className="h-9" disabled={busyMemoryId !== null} onClick={() => void transition(memory, "archive")} size="sm" variant="outline">
                                <ArchiveIcon aria-hidden="true" />归档
                              </Button>
                            </>
                          ) : null}
                        </div>
                      </li>
                    );
                  })}
                </ol>
              )}
            </aside>
          </div>

          <KnowledgeLearning key={projectId} projectId={projectId} onChanged={() => {
            requestMemories(projectId).then(setMemories).catch(error => setError(messageFrom(error)));
          }} />
          <KnowledgeCorrections key={`${projectId}:${correctionRevision}`} projectId={projectId} canReview={canVerify} userId={identity.user.id} onChanged={() => {
            setResults(null);
            requestMemories(projectId).then(setMemories).catch(error => setError(messageFrom(error)));
          }} />

          {showEditor ? (
            <form className="mt-5 rounded-lg border bg-card p-4 sm:p-5" onSubmit={saveDraft}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-primary">Unverified draft</p>
                  <h2 className="mt-1 font-semibold">{editingId ? "编辑 Memory 草稿" : "创建 Memory 草稿"}</h2>
                  <p className="mt-1 text-xs text-muted-foreground">保存后仍不进入检索；必须由另一位具权限成员验证。</p>
                </div>
                <Button className="h-9" onClick={() => setShowEditor(false)} size="sm" type="button" variant="ghost">取消</Button>
              </div>
              <div className="mt-4"><KnowledgeKindSelect value={draft.knowledge_kind} onChange={knowledge_kind => setDraft({ ...draft, knowledge_kind })} /></div>
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <label className="grid gap-1.5 text-xs font-medium">标题
                  <input className="h-11 rounded-lg border bg-background px-3 text-sm font-normal" maxLength={512} onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))} required value={draft.title} />
                </label>
                <label className="grid gap-1.5 text-xs font-medium">标签（逗号分隔）
                  <input className="h-11 rounded-lg border bg-background px-3 text-sm font-normal" onChange={(event) => setDraft((current) => ({ ...current, tags: event.target.value.split(",").map((tag) => tag.trim()).filter(Boolean) }))} value={draft.tags.join(", ")} />
                </label>
                <label className="grid gap-1.5 text-xs font-medium sm:col-span-2">记忆内容
                  <textarea className="min-h-32 rounded-lg border bg-background px-3 py-2 text-sm font-normal" maxLength={20_000} onChange={(event) => setDraft((current) => ({ ...current, content: event.target.value }))} required value={draft.content} />
                </label>
                <label className="grid gap-1.5 text-xs font-medium sm:col-span-2">适用范围
                  <textarea className="min-h-20 rounded-lg border bg-background px-3 py-2 text-sm font-normal" maxLength={5_000} onChange={(event) => setDraft((current) => ({ ...current, applicability: event.target.value || null }))} value={draft.applicability ?? ""} />
                </label>
              </div>
              {editingId && <label className="mt-3 flex items-center gap-2 text-xs"><input type="checkbox" checked={replaceDraftSources} onChange={event => setReplaceDraftSources(event.target.checked)} />修订草稿的文档、规格或快照依据（原始业务出处继续保留）</label>}
              {(!editingId || replaceDraftSources) && <SourcePicker key={projectId} projectId={projectId} value={sourceSelections} onChange={setSourceSelections} />}
              {editingId && !editingDigest && <p className="mt-2 text-xs text-destructive">缺少当前审核版本，请刷新后重新编辑。</p>}
              <Button className="mt-4 h-11" disabled={busyMemoryId !== null || Boolean(editingId && (!editingDigest || (replaceDraftSources && !sourceSelections.length)))} type="submit">
                <CheckCircleIcon aria-hidden="true" />{busyMemoryId ? "正在保存…" : "保存未验证草稿"}
              </Button>
            </form>
          ) : null}
        </>
      )}
    </WorkspaceShell>
  );
}

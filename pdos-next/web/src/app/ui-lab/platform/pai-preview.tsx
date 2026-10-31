"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArrowDownLeft,
  ArrowLeft,
  ArrowUp,
  ArrowUpRight,
  ArrowsOutSimple,
  CaretDown,
  Check,
  Circle,
  Clock,
  DotsThree,
  FileText,
  FolderSimple,
  MagnifyingGlass,
  Paperclip,
  PencilSimple,
  Plus,
  SidebarSimple,
  Sparkle,
  Stop,
  Table,
  X,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { screenNames, type Role } from "./design-data";
import {
  generalScope,
  skillCatalog,
  type PaiArtifact,
  type PaiController,
  type PaiScope,
} from "./pai-preview-state";
import s from "./pai-preview.module.css";
import { CategoryPaiPreview } from "./category-pai-preview";
import { ProposalPaiPreview } from "./proposal-pai-preview";
import type { ProposalDraft } from "./proposal-pai-draft";
import { CatalogPaiPreview } from "./catalog-pai-preview";
import type { CatalogDraft } from "./catalog-pai-draft";
import { catalogLabels, catalogTabs } from "./catalog-fields";
import { PaiSavedDocument } from "./pai-saved-document";

function ArtifactBody({ artifact }: { artifact: PaiArtifact }) {
  if (artifact.kind === "table") {
    const [header, ...rows] = artifact.body
      .split("\n")
      .map((line) => line.split("|"));
    return (
      <div className={s.tableScroll}>
        <table>
          <thead>
            <tr>
              {header.map((cell, i) => (
                <th key={i}>{cell}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <td key={j}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return (
    <div className={s.document}>
      {artifact.body
        .split("\n")
        .map((line, i) =>
          line.startsWith("# ") ? (
            <h2 key={i}>{line.slice(2)}</h2>
          ) : line.startsWith("## ") ? (
            <h3 key={i}>{line.slice(3)}</h3>
          ) : line ? (
            <p key={i}>{line}</p>
          ) : null,
        )}
    </div>
  );
}

function ArtifactPane({
  artifact,
  save,
  close,
  openSource,
}: {
  artifact: PaiArtifact;
  save: (body: string) => void;
  close: () => void;
  openSource?: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(artifact.body);
  const [saved, setSaved] = useState(false);
  return (
    <section className={s.artifactPane} aria-label="成果内容区">
      <header>
        <span>
          <FileText size={16} />
          {artifact.kind === "table" ? "方案比较" : "文档"}
          <small>草稿 · v{artifact.version}</small>
        </span>
        <button aria-label="收起成果，返回对话" onClick={close}>
          <X size={17} />
        </button>
      </header>
      <div className={s.artifactToolbar}>
        <span>{saved ? "修改已保留在本次预览" : "可继续修改"}</span>
        {editing ? (
          <>
            <button
              onClick={() => {
                setText(artifact.body);
                setEditing(false);
              }}
            >
              取消
            </button>
            <Button
              size="sm"
              onClick={() => {
                save(text);
                setSaved(true);
                setEditing(false);
              }}
            >
              <Check size={14} />
              保存修改
            </Button>
          </>
        ) : (
          <button
            onClick={() => {
              setText(artifact.body);
              setEditing(true);
            }}
          >
            <PencilSimple size={14} />
            编辑
          </button>
        )}
      </div>
      <div className={s.artifactContent}>
        {editing ? (
          <textarea
            aria-label="编辑成果内容"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        ) : (
          <>
            <h1 className={s.artifactTitle}>{artifact.title}</h1>
            <ArtifactBody artifact={artifact} />
          </>
        )}
      </div>
      <footer>
        <span>仅你可见 · 未发布到项目</span>
        {openSource && (
          <button onClick={openSource}>
            查看关联页面
            <ArrowUpRight size={13} />
          </button>
        )}
      </footer>
    </section>
  );
}

export function PaiPreview({
  controller: c,
  full,
  role,
  state,
  onExpand,
  onDock,
  onClose,
  onOpenScope,
  onRestore,
  onCreateCategory,
  onSaveCatalog,
  onOpenCatalog,
  onSaveProposal,
  onOpenProposal,
  getProposalParameters,
}: {
  controller: PaiController;
  full: boolean;
  role: Role;
  state: string;
  onExpand: () => void;
  onDock: () => void;
  onClose: () => void;
  onOpenScope: (scope: PaiScope) => void;
  onRestore: () => void;
  onCreateCategory: (
    name: string,
    description: string,
  ) => { id?: string; error?: string };
  onSaveCatalog: (draft: CatalogDraft) => {
    record?: import("./category-preview-state").CatalogRecord;
    id?: string;
    version?: number;
    error?: string;
  };
  onOpenCatalog: (draft: CatalogDraft) => void;
  onSaveProposal: (draft: ProposalDraft) => {
    proposal?: import("./product-preview-state").Proposal;
    id?: string;
    version?: number;
    error?: string;
  };
  onOpenProposal: (id: string) => void;
  getProposalParameters: (categoryId: string) => import("./category-preview-state").CatalogRecord[];
}) {
  const current = c.current;
  const [history, setHistory] = useState<"auto" | "open" | "closed">("auto");
  const historyRef = useRef<HTMLElement>(null);
  const [query, setQuery] = useState("");
  const [archived, setArchived] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState("");
  const [artifactId, setArtifactId] = useState<string | null>(null);
  const [editor, setEditor] = useState<{
    sessionId: string;
    messageId: string;
    kind: "categoryDraft" | "catalogDraft" | "proposalDraft";
  } | null>(null);
  const [editorView, setEditorView] = useState<"editor" | "chat">("editor");
  const editorHeading = useRef<HTMLHeadingElement>(null);
  const editTrigger = useRef<HTMLElement | null>(null);
  const [notice, setNotice] = useState("");
  const transcript = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const files = useRef<HTMLInputElement>(null);
  const artifact =
    artifactId === "latest"
      ? current.artifacts.at(-1)
      : current.artifacts.find((a) => a.id === artifactId);
  const selectedMessage =
    editor?.sessionId === current.id && full
      ? current.messages.find((message) => message.id === editor.messageId)
      : undefined;
  const resolvedEditorMessage =
    selectedMessage && editor
      ? (current.messages.findLast(
          (message, index) =>
            index >= current.messages.indexOf(selectedMessage) &&
            ["ready", "saved", "created"].includes(message[editor.kind]?.status ?? ""),
        ) ?? selectedMessage)
      : undefined;
  const editorMessage =
    resolvedEditorMessage &&
    editor &&
    ["ready", "saved", "created"].includes(
      resolvedEditorMessage[editor.kind]?.status ?? "",
    )
      ? resolvedEditorMessage
      : undefined;
  const editorDraft =
    editorMessage && editor ? editorMessage[editor.kind] : undefined;
  const editorSaved =
    editorDraft?.status === "saved" || editorDraft?.status === "created";
  const editorVersion =
    editorMessage?.proposalDraft?.savedVersion ??
    editorMessage?.catalogDraft?.savedVersion;
  const editorTitle =
    editorMessage?.proposalDraft?.values.title ||
    editorMessage?.catalogDraft?.values.name ||
    editorMessage?.categoryDraft?.name ||
    "未命名草稿";
  const editorLabel = editorMessage?.proposalDraft
    ? "立项提案"
    : editorMessage?.catalogDraft
      ? catalogLabels[editorMessage.catalogDraft.kind]
      : "品类";
  const scope = full ? current.scope : c.pageScope;
  const availableSkills = skillCatalog.filter(
    (skill) => !skill.roles || skill.roles.includes(role),
  );
  const readOnly = state === "权限失效";
  const unavailable = readOnly || ["离线", "读取失败"].includes(state);
  const sessions = c.mine
    .filter(
      (session) =>
        session.messages.length &&
        session.archived === archived &&
        `${session.title} ${session.scope.label}`
          .toLowerCase()
          .includes(query.toLowerCase()),
    )
    .sort(
      (a, b) =>
        Number(b.pinned) - Number(a.pinned) || b.updatedAt - a.updatedAt,
    );
  useEffect(() => {
    transcript.current?.scrollTo({ top: transcript.current.scrollHeight });
  }, [current.id, current.messages.length, current.status]);
  useEffect(() => {
    input.current?.focus();
  }, [current.id]);
  const activeEditorId = editorMessage ? editor?.messageId : undefined;
  useEffect(() => {
    if (!activeEditorId) return;
    if (editorView === "editor") editorHeading.current?.focus();
    else input.current?.focus();
  }, [activeEditorId, editorView]);
  const savedEditorKey = editorSaved ? editorMessage?.id : undefined;
  useEffect(() => {
    if (savedEditorKey) editorHeading.current?.focus();
  }, [savedEditorKey]);
  function closeEditor() {
    setEditor(null);
    requestAnimationFrame(() => editTrigger.current?.focus());
  }
  function switchSession(id: string) {
    setEditor(null);
    c.select(id);
    setHistory("auto");
    setArtifactId(null);
    setNotice("");
  }
  const proposalContext =
    scope.proposalContext ??
    (current.scope.id === scope.id ? current.scope.proposalContext : undefined);
  const suggestions =
    proposalContext &&
    (current.scope.proposalIntent || scope.id.startsWith("proposal:"))
      ? proposalContext.base && proposalContext.base.status !== "草稿"
        ? ["梳理这份提案的依据", "查看立项后的待决问题", "解释方案取舍"]
        : [
            proposalContext.base
              ? "帮我完善当前提案，补齐规格缺项"
              : "帮我起草一份立项提案",
            "完善提案的方案对比",
            "补充提案的待决问题",
          ]
      : scope.catalogKind
        ? [
            `帮我新增${catalogLabels[scope.catalogKind]}`,
            "梳理当前资料的缺失项",
            "比较已有资料的差异",
          ]
        : scope.projectId
          ? [
              "起草当前项目的工作方案",
              "比较两种推进方案",
              "持续跟进当前项目的关键事项",
            ]
          : [
              scope.id === "page:category" &&
              (role === "product" || role === "management")
                ? "帮我新建一个品类"
                : "帮我梳理一个想法",
              "起草一份工作方案",
              "比较两个方案",
            ];
  function openEditor(
    messageId: string,
    kind: "categoryDraft" | "catalogDraft" | "proposalDraft",
  ) {
    editTrigger.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    setEditor({ sessionId: current.id, messageId, kind });
    setEditorView("editor");
    requestAnimationFrame(() => editorHeading.current?.focus());
    setArtifactId(null);
    setHistory("closed");
    if (!full) {
      c.activateCurrent();
      onExpand();
    }
  }
  function renderCandidate(
    message: (typeof current.messages)[number],
    editing = false,
  ) {
    const saved =
      message.proposalDraft?.status === "saved" ||
      message.catalogDraft?.status === "saved" ||
      message.categoryDraft?.status === "created";
    if (editing && saved)
      return (
        <PaiSavedDocument
          proposal={message.proposalDraft}
          catalog={message.catalogDraft}
          category={message.categoryDraft}
          disabled={
            unavailable ||
            state === "版本冲突" ||
            current.archived ||
            current.status === "running"
          }
          open={() => {
            if (message.proposalDraft?.savedId)
              onOpenProposal(message.proposalDraft.savedId);
            else if (message.catalogDraft) onOpenCatalog(message.catalogDraft);
            else if (message.categoryDraft?.categoryId)
              onOpenScope({
                id: `category:${message.categoryDraft.categoryId}`,
                label: message.categoryDraft.name,
                screen: "category",
              });
          }}
          continueEditing={() => {
            const id = c.reviseSavedDraft(message.id);
            if (id)
              openEditor(
                id,
                message.proposalDraft ? "proposalDraft" : "catalogDraft",
              );
          }}
        />
      );
    return (
      <>
        {message.proposalDraft && (
          <ProposalPaiPreview
            key={message.id}
            editing={editing}
            active={editorMessage?.id === message.id}
            onEdit={() => openEditor(message.id, "proposalDraft")}
            draft={message.proposalDraft}
            parameters={getProposalParameters(message.proposalDraft.context.category.id)}
            disabled={
              unavailable ||
              state === "版本冲突" ||
              current.archived ||
              current.status === "running" ||
              (role !== "product" && role !== "management")
            }
            update={(value) => c.updateProposalDraft(message.id, value)}
            save={onSaveProposal}
            open={() => openEditor(message.id, "proposalDraft")}
          />
        )}
        {message.catalogDraft && (
          <CatalogPaiPreview
            key={message.id}
            editing={editing}
            active={editorMessage?.id === message.id}
            onEdit={() => openEditor(message.id, "catalogDraft")}
            draft={message.catalogDraft}
            disabled={
              unavailable ||
              state === "版本冲突" ||
              current.archived ||
              current.status === "running" ||
              (role !== "product" && role !== "management")
            }
            update={(value) => c.updateCatalogDraft(message.id, value)}
            save={onSaveCatalog}
            open={() => openEditor(message.id, "catalogDraft")}
          />
        )}
        {message.categoryDraft && (
          <CategoryPaiPreview
            key={message.id}
            editing={editing}
            active={editorMessage?.id === message.id}
            onEdit={() => openEditor(message.id, "categoryDraft")}
            draft={message.categoryDraft}
            disabled={
              unavailable ||
              state === "版本冲突" ||
              current.archived ||
              current.status === "running" ||
              (role !== "product" && role !== "management")
            }
            update={(value) => c.updateCategoryDraft(message.id, value)}
            create={onCreateCategory}
            open={(id) =>
              onOpenScope({
                id: `category:${id}`,
                label: message.categoryDraft!.name,
                screen: "category",
              })
            }
          />
        )}
      </>
    );
  }
  return (
    <section
      className={s.experience}
      data-full={full}
      data-artifact={!!artifact}
      data-editor={!!editorMessage}
      data-editor-view={editorView}
      data-history={history}
      aria-label={full ? "小Pai工作区" : "小Pai页内面板"}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          const disclosure = event.currentTarget.querySelector("details[open]");
          if (disclosure) {
            disclosure.removeAttribute("open");
            return;
          }
          if (history === "open") setHistory("closed");
          else if (editorMessage) closeEditor();
          else if (artifact) setArtifactId(null);
          else if (!full) onClose();
        }
      }}
    >
      {readOnly ? (
        <div className={s.unavailable}>
          <FolderSimple size={24} />
          <h2>当前范围已不可访问</h2>
          <p>会话与携带内容已收起。核对授权后可以继续。</p>
          <Button variant="outline" onClick={onRestore}>
            核对授权（预览）
          </Button>
          <button onClick={onClose}>返回页面</button>
        </div>
      ) : (
        <>
          <aside
            ref={historyRef}
            className={s.history}
            aria-label="小Pai会话列表"
          >
            <header>
              <strong>会话</strong>
              <button
                aria-label="关闭会话列表"
                onClick={() => setHistory("closed")}
              >
                <X size={16} />
              </button>
            </header>
            <button
              className={s.newChat}
              onClick={() => {
                setEditor(null);
                c.newChat(generalScope);
                setHistory("auto");
                setArtifactId(null);
              }}
            >
              <Plus size={16} />
              新对话
            </button>
            <label className={s.search}>
              <MagnifyingGlass size={14} />
              <input
                aria-label="搜索会话"
                placeholder="搜索会话"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
            <div className={s.historyTabs}>
              <button
                aria-pressed={!archived}
                onClick={() => setArchived(false)}
              >
                最近
              </button>
              <button aria-pressed={archived} onClick={() => setArchived(true)}>
                已归档
              </button>
            </div>
            <div className={s.sessions}>
              {sessions.length ? (
                sessions.map((session) => (
                  <button
                    key={session.id}
                    title={session.title}
                    aria-current={
                      session.id === current.id ? "true" : undefined
                    }
                    onClick={() => switchSession(session.id)}
                  >
                    <span>
                      {session.pinned && <span title="已置顶">· </span>}
                      {session.title}
                    </span>
                  </button>
                ))
              ) : (
                <p className={s.noSessions}>
                  {query
                    ? "没有匹配的会话"
                    : archived
                      ? "没有已归档会话"
                      : "聊过的内容会保留在这里。"}
                </p>
              )}
            </div>
            <footer>私人会话 · 仅你可见</footer>
          </aside>
          {editorMessage && (
            <section className={s.candidatePane} aria-label="草稿编辑区">
              <header>
                <span>
                  <FileText size={16} />
                  {editorLabel}
                  <small role="status">
                    {editorSaved
                      ? `已保存${editorVersion ? ` · v${editorVersion}` : ""}`
                      : "未保存"}
                  </small>
                </span>
                <div>
                  <button
                    className={s.editorChatToggle}
                    onClick={() => {
                      setEditorView("chat");
                      input.current?.focus();
                    }}
                  >
                    <Sparkle size={14} />
                    继续对话
                  </button>
                  <button
                    aria-label="收起编辑区"
                    title="收起编辑区，草稿保留在会话中"
                    onClick={closeEditor}
                  >
                    <X size={17} />
                  </button>
                </div>
              </header>
              <div
                className={s.candidateContent}
                key={`${editorMessage.id}-${editorSaved}`}
              >
                <div className={s.candidateDocument}>
                  <p className={s.candidateScope}>
                    {editorMessage.proposalDraft?.context.category.name ||
                      editorMessage.catalogDraft?.categoryName ||
                      "品类资料"}
                  </p>
                  <h1 ref={editorHeading} tabIndex={-1}>
                    {editorTitle}
                  </h1>
                  {renderCandidate(editorMessage, true)}
                </div>
              </div>
            </section>
          )}
          <div className={s.chat}>
            <header className={s.chatHeader}>
              <button
                aria-label="查看会话列表"
                aria-expanded={
                  history === "open"
                    ? true
                    : history === "closed"
                      ? false
                      : undefined
                }
                onClick={() => {
                  if (!full) {
                    c.activateCurrent();
                    onExpand();
                  }
                  setHistory(
                    historyRef.current?.offsetWidth ? "closed" : "open",
                  );
                }}
              >
                <SidebarSimple size={17} />
              </button>
              <strong>
                {full && !editorMessage && current.messages.length
                  ? current.title
                  : "小Pai"}
              </strong>
              <div>
                <button
                  aria-label="新建对话"
                  onClick={() => {
                    setEditor(null);
                    c.newChat(full ? generalScope : scope);
                    setArtifactId(null);
                    setNotice("");
                  }}
                >
                  <Plus size={17} />
                </button>
                <details className={s.menu} key={current.id}>
                  <summary aria-label="会话更多操作">
                    <DotsThree size={21} />
                  </summary>
                  <div>
                    <button
                      onClick={(event) => {
                        setRenaming(true);
                        setTitle(current.title);
                        event.currentTarget
                          .closest("details")
                          ?.removeAttribute("open");
                      }}
                    >
                      重命名
                    </button>
                    <button
                      onClick={(event) => {
                        c.patch({ pinned: !current.pinned });
                        event.currentTarget
                          .closest("details")
                          ?.removeAttribute("open");
                      }}
                    >
                      {current.pinned ? "取消置顶" : "置顶会话"}
                    </button>
                    {current.archived ? (
                      <button
                        onClick={() => {
                          c.patch({ archived: false });
                          setArchived(false);
                        }}
                      >
                        恢复会话
                      </button>
                    ) : (
                      <button
                        disabled={["running", "waiting"].includes(
                          current.status,
                        )}
                        onClick={() => {
                          setEditor(null);
                          c.archive();
                          setArtifactId(null);
                        }}
                      >
                        归档会话
                      </button>
                    )}
                  </div>
                </details>
                <button
                  aria-label={full ? "回到页内面板" : "展开小Pai工作区"}
                  onClick={() => {
                    c.activateCurrent();
                    if (full) {
                      setEditor(null);
                      onDock();
                    } else onExpand();
                  }}
                >
                  {full ? (
                    <ArrowDownLeft size={17} />
                  ) : (
                    <ArrowsOutSimple size={17} />
                  )}
                </button>
                {!full && (
                  <button aria-label="关闭小Pai" onClick={onClose}>
                    <X size={17} />
                  </button>
                )}
              </div>
            </header>
            {editorMessage && (
              <button
                className={s.editorReturn}
                onClick={() => setEditorView("editor")}
              >
                <FileText size={14} />
                <span>返回编辑 · {editorTitle}</span>
                <ArrowUpRight size={13} />
              </button>
            )}
            {renaming && (
              <form
                className={s.rename}
                onSubmit={(e) => {
                  e.preventDefault();
                  if (title.trim()) {
                    c.patch({ title: title.trim() });
                    setRenaming(false);
                  }
                }}
              >
                <input
                  aria-label="会话名称"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  autoFocus
                />
                <button type="submit" disabled={!title.trim()}>
                  保存
                </button>
                <button type="button" onClick={() => setRenaming(false)}>
                  取消
                </button>
              </form>
            )}
            <div className={s.context}>
              <details key={`${current.id}-${scope.id}`}>
                <summary>
                  <FolderSimple size={13} />
                  <span>
                    {scope.proposalContext?.category.name ??
                      current.scope.proposalContext?.category.name ??
                      scope.label}
                  </span>
                  {scope.screen && (
                    <small>{full ? "会话上下文" : "当前页面"}</small>
                  )}
                  <CaretDown size={11} />
                </summary>
                <div>
                  <strong>本次对话的上下文</strong>
                  <p>
                    {scope.proposalContext?.category.name ??
                      current.scope.proposalContext?.category.name ??
                      scope.label}
                    {scope.screen
                      ? ` · ${screenNames[scope.screen]}`
                      : " · 可直接讨论任何问题"}
                  </p>
                  <p>
                    使用当前账号有权访问的内容。运行中的工作保留发起时的范围。
                  </p>
                  {scope.screen && (
                    <button onClick={() => onOpenScope(scope)}>
                      打开关联页面
                      <ArrowUpRight size={12} />
                    </button>
                  )}
                </div>
              </details>
              <span>仅你可见</span>
            </div>
            <div className={s.transcript} ref={transcript}>
              {!current.messages.length ? (
                <div className={s.welcome}>
                  <Sparkle size={23} weight="light" />
                  <h1>有什么想一起解决的？</h1>
                  <p>
                    {proposalContext &&
                    (current.scope.proposalIntent ||
                      scope.id.startsWith("proposal:"))
                      ? `已带入${proposalContext.category.name}的资料${proposalContext.base ? "与当前提案" : ""}。`
                      : scope.catalogKind
                        ? `已带入${scope.label}的${catalogTabs[scope.catalogKind]}。`
                        : scope.projectId
                          ? `已带入${scope.label}的上下文。`
                          : "从一个问题、一个想法，或一份资料开始。"}
                  </p>
                  <div>
                    {suggestions.map((text) => (
                      <button
                        key={text}
                        onClick={() => {
                          c.patch({ draft: text });
                          input.current?.focus();
                        }}
                      >
                        {text}
                        <ArrowUpRight size={13} />
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className={s.messages}>
                  {current.messages.map((message) => (
                    <article
                      key={message.id}
                      className={s.message}
                      data-author={message.author}
                    >
                      <div className={s.author}>
                        {message.author === "pai" ? (
                          <>
                            <Sparkle size={14} />
                            <strong>小Pai</strong>
                          </>
                        ) : (
                          <strong>你</strong>
                        )}
                      </div>
                      <p>{message.text}</p>
                      {renderCandidate(message)}
                      {message.artifactId &&
                        (() => {
                          const item = current.artifacts.find(
                            (a) => a.id === message.artifactId,
                          );
                          return (
                            item && (
                              <button
                                className={s.artifactLink}
                                onClick={() => {
                                  setEditor(null);
                                  setArtifactId(
                                    current.artifacts.at(-1)?.id === item.id
                                      ? "latest"
                                      : item.id,
                                  );
                                  setHistory("closed");
                                  if (!full) {
                                    c.activateCurrent();
                                    onExpand();
                                  }
                                }}
                              >
                                {item.kind === "table" ? (
                                  <Table size={20} />
                                ) : (
                                  <FileText size={20} />
                                )}
                                <span>
                                  <strong>{item.title}</strong>
                                  <small>
                                    {item.kind === "table" ? "表格" : "文档"} ·
                                    草稿 v{item.version} · 打开编辑
                                  </small>
                                </span>
                                <ArrowUpRight size={16} />
                              </button>
                            )
                          );
                        })()}
                      {message.author === "pai" && message.skill && (
                        <details className={s.evidence}>
                          <summary>
                            {message.skill === "通用对话"
                              ? "对话详情"
                              : `使用了${message.skill}`}
                            <CaretDown size={10} />
                          </summary>
                          <p>
                            上下文：{message.scope?.label}
                            。本条为合成示例，未调用模型、读取真实材料或修改业务对象。
                          </p>
                          {message.scope?.screen && (
                            <button onClick={() => onOpenScope(message.scope!)}>
                              查看关联页面
                              <ArrowUpRight size={12} />
                            </button>
                          )}
                        </details>
                      )}
                    </article>
                  ))}
                </div>
              )}
              {current.status === "running" && (
                <div className={s.runState} role="status">
                  <Clock size={15} />
                  <span>
                    正在{current.task?.follow ? "梳理跟进要点" : "整理内容"}…
                    <small>可以离开，结果会留在这段对话。</small>
                  </span>
                  <button onClick={c.stop}>
                    <Stop size={13} />
                    停止
                  </button>
                </div>
              )}
              {current.status === "waiting" &&
                !current.messages.some(
                  (m) =>
                    m.proposalDraft?.status === "ready" ||
                    m.categoryDraft?.status === "ready" ||
                    m.catalogDraft?.status === "ready",
                ) && (
                  <div className={s.followUp}>
                    <span>
                      <Circle size={8} weight="fill" />
                      需要你处理
                    </span>
                    <p>本轮最重要的完成判据是什么？</p>
                    <button
                      onClick={() => {
                        c.patch({
                          draft: "先明确每项工作的负责人和完成判据，整理成方案",
                        });
                        input.current?.focus();
                      }}
                    >
                      补充要求
                      <ArrowUpRight size={13} />
                    </button>
                    <button
                      onClick={() => {
                        c.patch({ status: "done" });
                        setNotice("已结束本次跟进，已有内容保留。 ");
                      }}
                    >
                      结束本次跟进
                    </button>
                  </div>
                )}
              {current.status === "stopped" && (
                <div className={s.runState}>
                  <Stop size={15} />
                  <span>已停止，已有内容保留。</span>
                  <button onClick={c.resume}>继续原工作</button>
                </div>
              )}
              {notice && (
                <p role="status" className={s.localNotice}>
                  {notice}
                </p>
              )}
            </div>
            <div className={s.composerWrap}>
              {unavailable && (
                <p role="status" className={s.error}>
                  {state === "离线"
                    ? "当前离线，输入已保留。恢复后可以继续。"
                    : "小Pai暂时无法连接，输入已保留。"}
                  <button onClick={onRestore}>
                    {state === "离线" ? "恢复连接" : "重试连接"}
                  </button>
                </p>
              )}
              {current.archived ? (
                <div className={s.archived}>
                  会话已归档。
                  <button
                    onClick={() => {
                      c.patch({ archived: false });
                      setArchived(false);
                    }}
                  >
                    恢复并继续
                  </button>
                </div>
              ) : (
                <form
                  className={s.composer}
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (!unavailable) {
                      c.send();
                      setNotice("");
                    }
                  }}
                >
                  {current.files.length > 0 && (
                    <div className={s.attachments}>
                      {current.files.map((file, i) => (
                        <span key={`${file}-${i}`}>
                          <Paperclip size={12} />
                          {file}
                          <button
                            type="button"
                            aria-label={`移除附件 ${file}`}
                            onClick={() =>
                              c.patch({
                                files: current.files.filter(
                                  (_, index) => index !== i,
                                ),
                              })
                            }
                          >
                            <X size={12} />
                          </button>
                        </span>
                      ))}
                      <small>仅展示文件名，预览不上传或读取内容。</small>
                    </div>
                  )}
                  <textarea
                    ref={input}
                    aria-label="发消息给小Pai"
                    value={current.draft}
                    onChange={(event) => c.patch({ draft: event.target.value })}
                    placeholder={
                      scope.projectId
                        ? "聊聊这个项目，或交给我一件事…"
                        : "发消息给小Pai…"
                    }
                    rows={2}
                    onKeyDown={(event) => {
                      if (
                        event.key === "Enter" &&
                        !event.shiftKey &&
                        !event.nativeEvent.isComposing
                      ) {
                        event.preventDefault();
                        if (!unavailable) {
                          c.send();
                          setNotice("");
                        }
                      }
                    }}
                  />
                  <div className={s.composerTools}>
                    <input
                      ref={files}
                      type="file"
                      multiple
                      hidden
                      onChange={(event) => {
                        c.patch({
                          files: [
                            ...current.files,
                            ...Array.from(event.target.files ?? []).map(
                              (file) => file.name,
                            ),
                          ],
                        });
                        event.target.value = "";
                      }}
                    />
                    <button
                      type="button"
                      aria-label="添加附件"
                      onClick={() => files.current?.click()}
                    >
                      <Paperclip size={17} />
                    </button>
                    <details className={s.skills}>
                      <summary>
                        <Sparkle size={14} />
                        <span>{current.skill || "自动选择技能"}</span>
                        <CaretDown size={10} />
                      </summary>
                      <div>
                        <strong>当前可用技能</strong>
                        <button
                          type="button"
                          onClick={(event) => {
                            c.patch({ skill: "" });
                            event.currentTarget
                              .closest("details")
                              ?.removeAttribute("open");
                          }}
                        >
                          <span>
                            自动选择<small>根据对话使用适合的能力</small>
                          </span>
                          {!current.skill && <Check size={14} />}
                        </button>
                        {availableSkills.map((skill) => (
                          <button
                            type="button"
                            key={skill.name}
                            onClick={(event) => {
                              c.patch({ skill: skill.name });
                              event.currentTarget
                                .closest("details")
                                ?.removeAttribute("open");
                            }}
                          >
                            <span>
                              {skill.name}
                              <small>{skill.description}</small>
                            </span>
                            {current.skill === skill.name && (
                              <Check size={14} />
                            )}
                          </button>
                        ))}
                      </div>
                    </details>
                    <Button
                      type="submit"
                      size="icon"
                      aria-label="发送消息"
                      disabled={
                        !current.draft.trim() ||
                        current.status === "running" ||
                        unavailable
                      }
                    >
                      <ArrowUp size={17} />
                    </Button>
                  </div>
                </form>
              )}
              <p className={s.composerHint}>Enter 发送 · Shift Enter 换行</p>
            </div>
          </div>
          {artifact && (
            <ArtifactPane
              key={artifact.id}
              artifact={artifact}
              save={(body) => c.saveArtifact(artifact.id, body)}
              close={() => setArtifactId(null)}
              openSource={
                current.scope.screen
                  ? () => onOpenScope(current.scope)
                  : undefined
              }
            />
          )}
          {artifact && (
            <button
              className={s.mobileBack}
              onClick={() => setArtifactId(null)}
            >
              <ArrowLeft size={15} />
              返回对话
            </button>
          )}
        </>
      )}
    </section>
  );
}

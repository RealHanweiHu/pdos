"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Archive,
  ArrowClockwise,
  ArrowLeft,
  ChatCircle,
  Check,
  EnvelopeSimple,
  Plus,
  Sparkle,
  MagnifyingGlass,
  X,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { readRunActivity, type ActivityRun } from "@/lib/portfolio-reads";
import type { browserApi } from "@/lib/browser-api";
import {
  inboxRoot,
  isUnread,
  restoreInboxPending,
  visibleInbox,
  type InboxConversation,
  type InboxKind,
  type InboxPending,
  type InboxState,
  type MessagePage,
} from "@/lib/inbox";
import styles from "./inbox.module.css";
import { InboxFollowing } from "./inbox-following";

type Props = {
  api: typeof browserApi;
  principalId: string;
  onOpenRun: (id: string, categoryId: string) => void;
  onOpenProject?: (categoryId: string, id: string) => void;
};
const labels: Record<string, string> = {
  queued: "等待执行",
  running: "进行中",
  waiting_input: "需要你处理",
  completed: "已完成",
  partial: "部分完成",
  cancelled: "已取消",
  failed: "未完成",
};
type Reading = {
  runs: ActivityRun[];
  conversations: InboxConversation[];
  cursor: string | null;
  states: InboxState[];
  categories: { id: string; name: string }[];
};
const time = (value: string) =>
  new Date(value).toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
export function Inbox(props: Props) {
  return <ScopedInbox key={props.principalId} {...props} />;
}
function ScopedInbox({ api, principalId, onOpenRun, onOpenProject }: Props) {
  const [tab, setTab] = useState<"activity" | "messages" | "followed">("activity"),
    [filter, setFilter] = useState<"all" | "unread" | "archived" | "followed">(
      "all",
    );
  const [query, setQuery] = useState("");
  const [notificationId, setNotificationId] = useState("");
  const [data, setData] = useState<Reading | null>(null),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [selected, setSelected] = useState(""),
    [messages, setMessages] = useState<MessagePage | null>(null),
    [reply, setReply] = useState("");
  const [creating, setCreating] = useState(false),
    [category, setCategory] = useState(""),
    [title, setTitle] = useState(""),
    [body, setBody] = useState("");
  const [members, setMembers] = useState<{ id: string; name: string }[]>([]),
    [recipients, setRecipients] = useState<string[]>([]),
    [memberQuery, setMemberQuery] = useState("");
  const [pending, setPending] = useState<InboxPending | null>(null),
    [busy, setBusy] = useState(false),
    [ready, setReady] = useState(false);
  const alive = useRef(false),
    locked = useRef(false),
    selectedRef = useRef(selected),
    generation = useRef(0),
    readGeneration = useRef(0),
    dialog = useRef<HTMLDialogElement>(null);
  const drafts = useRef<Record<string,string>>({});
  const storageKey = `pdos:inbox:${principalId}:pending:v1`;
  const clearPrivate = useCallback(() => {
    setData(null);
    setSelected("");
    setNotificationId("");
    selectedRef.current = "";
    setMessages(null);
    setMembers([]);
    setRecipients([]);
    setReply("");
    drafts.current = {};
    setTitle("");
    setBody("");
    setCreating(false);
    setPending(null);
    try {
      localStorage.removeItem(storageKey);
    } catch {
      /* Private values stay hidden. */
    }
  }, [storageKey]);
  const load = useCallback(async () => {
    const request = ++readGeneration.current;
    try {
      const [waiting, recent, conversations, states, categories] =
        await Promise.all([
          readRunActivity(api, true),
          readRunActivity(api),
          api<{ items: InboxConversation[]; next_cursor: string | null }>(
            `${inboxRoot}/conversations`,
          ),
          api<{ items: InboxState[] }>(`${inboxRoot}/states`),
          api<Reading["categories"]>("v1/categories"),
        ]);
      if (!alive.current || request !== readGeneration.current) return;
      setData({
        runs: [
          ...new Map(
            [...waiting, ...recent.filter(run => ["failed", "partial"].includes(run.status))].map((run) => [run.run_id, run]),
          ).values(),
        ],
        conversations: conversations.items,
        cursor: conversations.next_cursor,
        states: states.items,
        categories,
      });
    } catch (failure) {
      if (alive.current && request === readGeneration.current) {
        setData(null);
        setMessages(null);
        setError((failure as Error).message);
        if (
          [401, 403, 404].includes(
            (failure as Error & { status?: number }).status ?? 0,
          )
        )
          clearPrivate();
      }
    }
  }, [api, clearPrivate]);
  useEffect(() => {
    alive.current = true;
    const messageCounter = generation,
      readCounter = readGeneration;
    void Promise.resolve().then(() => {
      if (!alive.current) return;
      try {
        setPending(restoreInboxPending(localStorage.getItem(storageKey)));
        setReady(true);
      } catch {
        setError("无法保存原发送请求，请恢复本机存储后重试。");
      }
    });
    void Promise.resolve().then(load);
    return () => {
      alive.current = false;
      ++messageCounter.current;
      ++readCounter.current;
    };
  }, [load, storageKey]);
  useEffect(() => {
    if (creating && !dialog.current?.open) dialog.current?.showModal();
    if (!creating && dialog.current?.open) dialog.current.close();
  }, [creating]);
  useEffect(() => {
    let active = true;
    if (category)
      void api<{ items: { id: string; name: string }[] }>(
        `v1/categories/${category}/participants`,
      )
        .then((value) => {
          if (active)
            setMembers(value.items.filter((row) => row.id !== principalId));
        })
        .catch((failure) => {
          if (active) {
            setMembers([]);
            setError((failure as Error).message);
          }
        });
    return () => {
      active = false;
    };
  }, [api, category, principalId]);
  async function openConversation(id: string) {
    if (busy) return;
    const turn = ++generation.current;
    setSelected(id);
    selectedRef.current = id;
    setMessages(null);
    setReply(drafts.current[id] ?? "");
    setError("");
    try {
      const value = await api<MessagePage>(
        `${inboxRoot}/conversations/${id}/messages`,
      );
      if (
        alive.current &&
        generation.current === turn &&
        value.conversation_id === id
      ) {
        setMessages(value);
        const latest = value.items.at(-1)?.sequence;
        if (latest && isUnread(stateFor("conversation",id),String(latest))) changeState("conversation",id,String(latest),"read");
      }
    } catch (failure) {
      if (alive.current && generation.current === turn) {
        setError((failure as Error).message);
        if (
          [401, 403, 404].includes(
            (failure as Error & { status?: number }).status ?? 0,
          )
        )
          clearPrivate();
      }
    }
  }
  async function execute(command: InboxPending) {
    if (locked.current || !ready) return;
    locked.current = true;
    setBusy(true);
    setError("");
    let saved = false;
    try {
      localStorage.setItem(storageKey, JSON.stringify(command));
      setPending(command);
      const value = await api<Record<string, unknown>>(
        command.path,
        command.body,
      );
      saved = true;
      if (!alive.current) return;
      // Keep the same request if local cleanup fails; its replay is idempotent.
      localStorage.removeItem(storageKey);
      setPending(null);
      setNotice(command.kind === "state" ? "" : "消息已发送");
      if (command.kind === "create") {
        setCreating(false);
        setTitle("");
        setBody("");
        setRecipients([]);
        setTab("messages");
        const id = String(value.conversation_id);
        setSelected(id);
        selectedRef.current = id;
        setMessages(null);
      }
      if (command.kind === "message") { setReply(""); delete drafts.current[selectedRef.current]; }
      await load();
      const id = selectedRef.current;
      if (id && command.kind !== "state") {
        const page = await api<MessagePage>(
          `${inboxRoot}/conversations/${id}/messages`,
        );
        if (alive.current && selectedRef.current === id) setMessages(page);
      }
    } catch (failure) {
      if (!alive.current) return;
      const status = (failure as Error & { status?: number }).status;
      if ([401, 403, 404].includes(status ?? 0)) clearPrivate();
      else if (status && status >= 400 && status < 500) {
        localStorage.removeItem(storageKey);
        setPending(null);
        await load();
      }
      setError((failure as Error).message);
      setNotice(
        saved
          ? "已保存，最新内容暂未读回。请刷新查看。"
          : status && status < 500
            ? "内容已保留，请核对后再发送。"
            : "结果待核实。请用原请求重试，避免重复发送。",
      );
    } finally {
      locked.current = false;
      if (alive.current) setBusy(false);
    }
  }
  function stateFor(kind: InboxKind, id: string) {
    return data?.states.find(
      (row) => row.kind === kind && row.target_id === id,
    );
  }
  function changeState(
    kind: InboxKind,
    id: string,
    token: string,
    action: "read" | "archive" | "follow",
  ) {
    if (pending || busy) return;
    const state = stateFor(kind, id),
      unread = isUnread(state, token);
    void execute({
      kind: "state",
      path: `${inboxRoot}/states`,
      body: {
        kind,
        target_id: id,
        expected_revision: state?.revision ?? 0,
        observed_token: token,
        mark_read:
          action === "read" ? unread : action === "archive" ? true : !unread,
        archived:
          action === "archive" ? !state?.archived : (state?.archived ?? false),
        followed:
          action === "follow" ? !state?.followed : (state?.followed ?? false),
        request_key: crypto.randomUUID(),
      },
    });
  }
  function actions(kind: InboxKind, id: string, token: string) {
    const state = stateFor(kind, id),
      unread = isUnread(state, token);
    return (
      <div className={styles.actions}>
        <Button
          size="icon-xs"
          variant="ghost"
          disabled={busy || !!pending || !token}
          title={unread ? "标为已读" : "标为未读"}
          aria-label={unread ? "标为已读" : "标为未读"}
          onClick={() => changeState(kind, id, token, "read")}
        >
          {unread ? <Check /> : <EnvelopeSimple />}
        </Button>
        <Button
          size="icon-xs"
          variant="ghost"
          disabled={busy || !!pending || !token}
          title={state?.archived ? "移回收件箱" : "归档"}
          aria-label={state?.archived ? "移回收件箱" : "归档"}
          onClick={() => changeState(kind, id, token, "archive")}
        >
          <Archive />
        </Button>
      </div>
    );
  }
  const conversation = data?.conversations.find((row) => row.id === selected);
  const conversations =
    data?.conversations.filter((row) =>
      `${row.title} ${row.latest?.body ?? ""}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()) && visibleInbox(
        stateFor("conversation", row.id),
        String(row.latest?.sequence ?? 0),
        filter,
      ),
    ) ?? [];
  const runs =
    data?.runs.filter((row) =>
      row.goal.toLocaleLowerCase().includes(query.toLocaleLowerCase()) && visibleInbox(
        stateFor("run", row.run_id),
        row.reading_token ?? "",
        filter,
      ),
    ) ?? [];
  const notification = data?.runs.find(run => run.run_id === notificationId);
  async function markAllRead() {
    if (locked.current || pending || !ready) return;
    locked.current = true; setBusy(true); setError("");
    const items = tab === "messages" ? conversations.map(row => ({ kind: "conversation" as const, id: row.id, token: String(row.latest?.sequence ?? 0) })) : runs.map(row => ({ kind: "run" as const, id: row.run_id, token: row.reading_token ?? "" }));
    try { for (const item of items) { const state = stateFor(item.kind,item.id); if (!item.token || !isUnread(state,item.token)) continue; const command: InboxPending = { kind: "state", path: `${inboxRoot}/states`, body: { kind: item.kind, target_id: item.id, expected_revision: state?.revision ?? 0, observed_token: item.token, mark_read: true, archived: state?.archived ?? false, followed: state?.followed ?? false, request_key: crypto.randomUUID() } }; localStorage.setItem(storageKey,JSON.stringify(command)); setPending(command); await api(command.path,command.body); localStorage.removeItem(storageKey); if (!alive.current) return; setPending(null); } setNotice("当前列表已全部标为已读。"); await load(); }
    catch (e) { if (alive.current) { setError((e as Error).message); await load(); } }
    finally { locked.current = false; if (alive.current) setBusy(false); }
  }
  const disabled = busy || !!pending || !ready;
  return (
    <section className={styles.page}>
      <div className="workspace-page-heading">
        <div><h1>收件箱</h1><p>接收工作消息，与同事保持沟通。</p></div>
        <div className={styles.actions}>
          <Button
            size="xs"
            variant="ghost"
            aria-label="刷新收件箱"
            disabled={busy}
            onClick={() => {
              setError("");
              void load();
              if (selected) void openConversation(selected);
            }}
          >
            <ArrowClockwise />
          </Button>
          <Button
            size="xs"
            variant="outline"
            disabled={disabled}
            onClick={() => {
              setCreating(true);
              setCategory(data?.categories[0]?.id ?? "");
            }}
          >
            <Plus />
            发起聊天
          </Button>
        </div>
      </div>
      <div className={styles.toolbar}>
        <nav className="workspace-view-tabs" aria-label="收件箱视图">
          <button
            aria-pressed={tab === "activity"}
            onClick={() => setTab("activity")}
          >
            通知
          </button>
          <button
            aria-pressed={tab === "messages"}
            onClick={() => setTab("messages")}
          >
            聊天
          </button>
          <button aria-pressed={tab === "followed"} onClick={() => setTab("followed")}>关注动态</button>
        </nav>
      </div>
      <div className={styles.listTools}><label className={styles.search}><MagnifyingGlass size={14}/><input type="search" aria-label={tab === "messages" ? "搜索聊天" : tab === "followed" ? "搜索项目动态" : "搜索通知"} placeholder={tab === "messages" ? "搜索聊天…" : tab === "followed" ? "搜索项目动态…" : "搜索通知…"} value={query} onChange={event => setQuery(event.target.value)}/></label>
        {tab !== "followed" && <select
          aria-label="筛选收件箱"
          value={filter}
          onChange={(event) => setFilter(event.target.value as typeof filter)}
        >
          <option value="all">收件箱</option>
          <option value="unread">未读</option>
          
          <option value="archived">已归档</option>
        </select>}
        {tab !== "followed" && <Button size="xs" variant="ghost" disabled={disabled} onClick={() => void markAllRead()}><Check/>全部已读</Button>}
      </div>
      {error && (
        <p role="alert" className={styles.feedback}>
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className={styles.feedback}>
          {notice}
        </p>
      )}
      {pending && (
        <div className={styles.recovery}>
          <span>有一条原请求尚未核实</span>
          <Button
            size="xs"
            variant="outline"
            disabled={busy}
            onClick={() => void execute(pending)}
          >
            按原请求重试
          </Button>
        </div>
      )}
      {!data ? (
        <div className={styles.empty}>
          {error ? (
            <Button variant="outline" size="sm" onClick={() => void load()}>
              重新读取
            </Button>
          ) : (
            "正在读取收件箱…"
          )}
        </div>
      ) : tab === "followed" ? <InboxFollowing api={api} states={data.states} query={query} disabled={disabled} onChange={(id,token,action) => changeState("project",id,token,action)} onOpenProject={onOpenProject}/> : tab === "activity" ? (
        <div className={styles.split} data-selected={!!notification}>
          <div className={styles.conversations}><ul className={styles.list}>{runs.map(run => <li key={run.run_id} className={styles.item} data-selected={notificationId === run.run_id} data-unread={isUnread(stateFor("run",run.run_id),run.reading_token ?? "")}><button className={styles.row} onClick={() => { setNotificationId(run.run_id); if (isUnread(stateFor("run",run.run_id),run.reading_token ?? "")) changeState("run",run.run_id,run.reading_token ?? "","read"); }}><span className={styles.itemIcon}><Sparkle size={16}/></span><span className={styles.rowBody}><strong className={styles.title}>{run.status === "waiting_input" ? "小Pai需要你处理" : "小Pai执行未完成"}</strong><span>{run.goal.split("\n")[0]}</span><small>{run.categoryName || "个人工作"} · <time dateTime={run.created_at}>{time(run.created_at)}</time></small></span><span className={styles.dot}/></button></li>)}</ul>{!runs.length && <p className={styles.empty}>这里暂时没有通知</p>}<p className={styles.caption}>需要处理的小Pai请求与近期异常</p></div>
          <section className={styles.detail} aria-label="通知内容">{notification ? <><header className={styles.detailHead}><Button className={styles.back} size="icon-xs" variant="ghost" aria-label="返回通知列表" onClick={() => setNotificationId("")}><ArrowLeft/></Button><div><h2>{notification.goal.split("\n")[0]}</h2><p>{notification.categoryName || "个人工作"} · {time(notification.created_at)}</p></div>{actions("run",notification.run_id,notification.reading_token ?? "")}</header><div className={styles.notificationBody}><p>{notification.goal.split("\n\n当前页面资料（")[0]}</p><p className={styles.caption}>{labels[notification.status] ?? notification.status}</p><Button size="sm" variant="outline" onClick={() => onOpenRun(notification.run_id, notification.categoryId)}>打开小Pai对话</Button></div></> : <div className={styles.detailEmpty}><Check size={24}/><p>选择一条通知，查看上下文。</p></div>}</section>
        </div>
      ) : (
        <div className={styles.split} data-selected={!!selected}>
          <div className={styles.conversations}>
            <ul className={styles.list}>
              {conversations.map((row) => (
                <li
                  className={styles.item}
                  key={row.id}
                  data-selected={selected === row.id}
                  data-unread={isUnread(
                    stateFor("conversation", row.id),
                    String(row.latest?.sequence ?? 0),
                  )}
                >
                  <button
                    className={styles.row}
                    aria-label={row.title}
                    onClick={() => void openConversation(row.id)}
                  >
                    <span className={styles.itemIcon}><ChatCircle size={16}/></span><span className={styles.rowBody}><strong className={styles.title}>{row.title}</strong><span>{row.latest?.body ?? "尚无消息"}</span><small>{row.category_name} · {time(row.latest?.created_at ?? row.created_at)}</small></span><span className={styles.dot}/>
                  </button>
                </li>
              ))}
            </ul>
            {!conversations.length && <p className={styles.empty}>暂无会话</p>}
            {data.cursor && (
              <Button
                size="xs"
                variant="ghost"
                onClick={async () => {
                  try {
                    const page = await api<{
                      items: InboxConversation[];
                      next_cursor: string | null;
                    }>(`${inboxRoot}/conversations?cursor=${data.cursor}`);
                    if (alive.current)
                      setData((current) =>
                        current
                          ? {
                              ...current,
                              conversations: [
                                ...new Map(
                                  [...current.conversations, ...page.items].map(
                                    (row) => [row.id, row],
                                  ),
                                ).values(),
                              ],
                              cursor: page.next_cursor,
                            }
                          : null,
                      );
                  } catch (failure) {
                    setError((failure as Error).message);
                  }
                }}
              >
                更多会话
              </Button>
            )}
          </div>
          <div className={styles.detail}>
            {!conversation ? (
              <div className={styles.detailEmpty}><ChatCircle size={24}/><p>选择一个会话，继续交流。</p></div>
            ) : (
              <>
                <header className={styles.detailHead}>
                  <Button
                    className={styles.back}
                    size="icon-xs"
                    variant="ghost"
                    aria-label="返回会话列表"
                    onClick={() => {
                      selectedRef.current = "";
                      setSelected("");
                      ++generation.current;
                    }}
                  >
                    <ArrowLeft />
                  </Button>
                  <div>
                    <h2>{conversation.title}</h2>
                    <p>
                      {conversation.category_name} ·{" "}
                      {conversation.members
                        .map((person) => person.name)
                        .join("、")}
                    </p>
                  </div>
                  {actions(
                    "conversation",
                    conversation.id,
                    String(conversation.latest?.sequence ?? 0),
                  )}
                </header>
                <div className={styles.messages} aria-label="消息记录">
                  {messages?.next_before && (
                    <Button
                      size="xs"
                      variant="ghost"
                      onClick={async () => {
                        const id = selected;
                        try {
                          const page = await api<MessagePage>(
                            `${inboxRoot}/conversations/${id}/messages?before=${messages.next_before}`,
                          );
                          if (alive.current && selectedRef.current === id)
                            setMessages((current) =>
                              current
                                ? {
                                    ...page,
                                    items: [...page.items, ...current.items],
                                  }
                                : page,
                            );
                        } catch (failure) {
                          setError((failure as Error).message);
                        }
                      }}
                    >
                      较早消息
                    </Button>
                  )}
                  {!messages ? (
                    <p>正在读取消息…</p>
                  ) : (
                    messages.items.map((message) => (
                      <article
                        key={message.id}
                        className={styles.message}
                        data-own={message.sender_id === principalId}
                      >
                        <header>
                          <strong>{message.sender_name}</strong>
                          <time dateTime={message.created_at}>
                            {time(message.created_at)}
                          </time>
                        </header>
                        <p>{message.body}</p>
                      </article>
                    ))
                  )}
                </div>
                <form
                  className={styles.composer}
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (!disabled && reply.trim())
                      void execute({
                        kind: "message",
                        path: `${inboxRoot}/conversations/${selected}/messages`,
                        body: { body: reply, request_key: crypto.randomUUID() },
                      });
                  }}
                >
                  <textarea
                    aria-label="回复消息"
                    placeholder="回复…"
                    rows={2}
                    maxLength={8000}
                    disabled={disabled}
                    value={reply}
                    onChange={(event) => { setReply(event.target.value); drafts.current[selected] = event.target.value; }}
                  />
                  <Button size="xs" disabled={disabled || !reply.trim()}>
                    发送
                  </Button>
                </form>
              </>
            )}
          </div>
        </div>
      )}
      <dialog
        ref={dialog}
        className={styles.dialog}
        onCancel={(event) => {
          if (disabled) event.preventDefault();
          else setCreating(false);
        }}
      >
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!disabled && recipients.length)
              void execute({
                kind: "create",
                path: `${inboxRoot}/conversations`,
                body: {
                  category_id: category,
                  title,
                  body,
                  recipients,
                  request_key: crypto.randomUUID(),
                },
              });
          }}
        >
          <header>
            <h2>新消息</h2>
            <Button
              type="button"
              size="icon-xs"
              variant="ghost"
              aria-label="关闭新消息"
              disabled={disabled}
              onClick={() => setCreating(false)}
            >
              <X />
            </Button>
          </header>
          <label>
            所属品类
            <select
              value={category}
              disabled={disabled}
              onChange={(event) => {
                setCategory(event.target.value);
                setRecipients([]);
                setMembers([]);
              }}
            >
              {data?.categories.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            收件人
            <input
              placeholder="搜索成员"
              value={memberQuery}
              disabled={disabled}
              onChange={(event) => setMemberQuery(event.target.value)}
            />
          </label>
          <div className={styles.recipients}>
            {members
              .filter((row) =>
                row.name
                  .toLocaleLowerCase()
                  .includes(memberQuery.toLocaleLowerCase()),
              )
              .map((row) => (
                <label key={row.id}>
                  <input
                    type="checkbox"
                    checked={recipients.includes(row.id)}
                    disabled={
                      disabled ||
                      (!recipients.includes(row.id) && recipients.length >= 19)
                    }
                    onChange={(event) =>
                      setRecipients((current) =>
                        event.target.checked
                          ? [...current, row.id]
                          : current.filter((id) => id !== row.id),
                      )
                    }
                  />
                  {row.name}
                </label>
              ))}
            {!members.length && <p>当前没有可选择的其他成员</p>}
          </div>
          <label>
            标题
            <input
              required
              maxLength={160}
              value={title}
              disabled={disabled}
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          <label>
            消息
            <textarea
              required
              rows={4}
              maxLength={8000}
              value={body}
              disabled={disabled}
              onChange={(event) => setBody(event.target.value)}
            />
          </label>
          <footer>
            <span>
              {recipients.length
                ? `已选 ${recipients.length} 位成员`
                : "仅所选成员可见"}
            </span>
            <Button
              size="sm"
              disabled={
                disabled || !title.trim() || !body.trim() || !recipients.length
              }
            >
              发送消息
            </Button>
          </footer>
        </form>
      </dialog>
    </section>
  );
}

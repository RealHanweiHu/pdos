"use client";
/* THESIS: 把要做的事、收到的信息和项目归类分清，让用户知道下一步去哪。
OWN-WORLD: 扩展既有 Linear 简洁方向；Geist、Phosphor、8px、主题橙与中性列表。
STORY: 浏览未读 → 看上下文 → 回复或回到业务对象；项目集只组织项目。
FIRST VIEWPORT: 简短标题与三类消息切换；左侧列表，右侧内容，窄屏逐层返回。
FORM: 用户指定的现有世界扩展，项目集独立侧栏入口，资源需求融入项目计划。 */
import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  Archive,
  Bell,
  Check,
  ChatCircle,
  FolderSimple,
  Plus,
  Sparkle,
  Users,
  X,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { projects, roles, type Role, type Screen } from "./design-data";
import type { PaiController } from "./pai-preview-state";
import {
  attentionKey,
  commitments,
  type OrganizationController,
} from "./organization-state";
import s from "./platform.module.css";
import o from "./organization.module.css";

type Jump = (id: string, screen?: Screen) => void;
function ChoiceTabs({
  values,
  value,
  onChange,
}: {
  values: string[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className={s.tabs}>
      {values.map((v) => (
        <button key={v} aria-pressed={value === v} onClick={() => onChange(v)}>
          {v}
        </button>
      ))}
    </div>
  );
}
function Blank({ children }: { children: React.ReactNode }) {
  return (
    <div className={o.blank}>
      <Check size={22} />
      <p>{children}</p>
    </div>
  );
}
function ProjectLink({
  id,
  onProject,
  screen,
}: {
  id: string;
  onProject: Jump;
  screen?: Screen;
}) {
  const project = projects.find((p) => p.id === id);
  if (!project) return null;
  return (
    <button className={o.projectLink} onClick={() => onProject(id, screen)}>
      <FolderSimple size={14} />
      {project.name}
      <ArrowUpRight size={13} />
    </button>
  );
}
export function ProjectMembershipSelect({
  controller: c,
  id,
  disabled,
}: {
  controller: OrganizationController;
  id: string;
  disabled: boolean;
}) {
  const current = c.sets.find((set) => set.projects.includes(id));
  return (
    <select
      className={o.membershipSelect}
      aria-label={`移动${projects.find((p) => p.id === id)?.name}到项目集`}
      value={current?.id ?? ""}
      disabled={disabled}
      onChange={(e) => c.moveProjects([id], e.target.value || null)}
    >
      <option value="">未归类</option>
      {c.sets.map((set) => (
        <option key={set.id} value={set.id}>
          {set.name}
        </option>
      ))}
    </select>
  );
}
export function ProjectSets({
  controller: c,
  go,
  onProject,
  disabled,
}: {
  controller: OrganizationController;
  go: (screen: Screen) => void;
  onProject: Jump;
  disabled: boolean;
}) {
  const editing = c.setEditor;
  const setEditing = c.setSetEditor;
  const selected = c.sets.find((set) => set.id === c.selectedSetId);
  const [view, setView] = useState("列表");
  const [addingTo, setAddingTo] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const duplicate =
    !!editing &&
    c.sets.some((x) => x.id !== editing.id && x.name === editing.name.trim());
  const available = projects.filter((p) => !selected?.projects.includes(p.id));
  const entries = c.sets.map((set) => {
    const members = projects.filter((p) => set.projects.includes(p.id));
    const attention = members.filter((p) => p.health !== "正常").length;
    return {
      ...set,
      members,
      attention,
      group: !members.length ? "暂无项目" : attention ? "需关注" : "进展正常",
    };
  });
  function openSet(id: string) {
    c.setSelectedSetId(id);
    setEditing(null);
    c.setSetNotice("");
  }
  function beginAdd() {
    if (!selected) return;
    setEditing(null);
    setAddingTo(selected.id);
    setPicked([]);
    c.setSetNotice("");
  }
  return (
    <div className={s.page}>
      {selected && (
        <button
          className={o.backToSets}
          onClick={() => {
            c.setSelectedSetId(null);
            setAddingTo(null);
            setEditing(null);
          }}
        >
          <ArrowLeft size={15} />
          全部项目集
        </button>
      )}
      <header className={s.heading}>
        <div>
          <h1>{selected?.name ?? "项目集"}</h1>
          <p>
            {selected
              ? selected.description || "把相关项目放在一起推进。"
              : "创建项目集，把相关项目归到一起。"}
          </p>
        </div>
        <div className={o.headingActions}>
          {selected ? (
            <>
              <Button
                variant="ghost"
                disabled={disabled}
                onClick={() => {
                  setEditing({ ...selected, projects: [...selected.projects] });
                  setAddingTo(null);
                  c.setSetNotice("");
                }}
              >
                编辑
              </Button>
              <Button
                variant="outline"
                disabled={disabled || !available.length}
                onClick={beginAdd}
              >
                <Plus size={16} />
                移入项目
              </Button>
            </>
          ) : (
            <Button
              variant="outline"
              disabled={disabled}
              onClick={() => {
                setEditing({ id: "", name: "", description: "", projects: [] });
                c.setSetNotice("");
              }}
            >
              <Plus size={16} />
              新建项目集
            </Button>
          )}
        </div>
      </header>
      {!selected && (
        <ChoiceTabs values={["列表", "看板"]} value={view} onChange={setView} />
      )}
      {c.setNotice && (
        <p role="status" className={o.notice}>
          {c.setNotice}
        </p>
      )}
      {editing && (
        <form
          className={o.editor}
          onSubmit={(e) => {
            e.preventDefault();
            if (disabled || !editing.name.trim() || duplicate) return;
            c.saveSet({ ...editing, name: editing.name.trim() });
            setEditing(null);
            setAddingTo(null);
          }}
        >
          <div className={o.editorHeading}>
            <h2>{editing.id ? "编辑项目集" : "新建项目集"}</h2>
            <button
              type="button"
              aria-label="取消编辑项目集"
              onClick={() => setEditing(null)}
            >
              <X size={17} />
            </button>
          </div>
          <label>
            名称
            <input
              autoFocus
              maxLength={60}
              value={editing.name}
              onChange={(e) => setEditing({ ...editing, name: e.target.value })}
              placeholder="例如：2027 年便携产品"
            />
          </label>
          <label>
            说明（选填）
            <input
              maxLength={180}
              value={editing.description}
              onChange={(e) =>
                setEditing({ ...editing, description: e.target.value })
              }
              placeholder="这些项目为什么放在一起？"
            />
          </label>
          <fieldset>
            <legend>移入项目（选填）</legend>
            {projects.map((p) => {
              const origin = c.sets.find((set) => set.projects.includes(p.id));
              return (
                <label key={p.id} className={o.checkbox}>
                  <input
                    type="checkbox"
                    checked={editing.projects.includes(p.id)}
                    onChange={(e) =>
                      setEditing({
                        ...editing,
                        projects: e.target.checked
                          ? [...editing.projects, p.id]
                          : editing.projects.filter((id) => id !== p.id),
                      })
                    }
                  />
                  {p.name}
                  <small>
                    {origin?.id === editing.id
                      ? "当前项目集"
                      : origin
                        ? `来自：${origin.name}`
                        : "未归类"}
                  </small>
                </label>
              );
            })}
          </fieldset>
          <p className={s.footnote}>
            移入后会离开原项目集；取消勾选则移至未归类。
          </p>
          {duplicate && <p role="alert">已有同名项目集，请换一个名称。</p>}
          <div className={o.actions}>
            <Button
              type="submit"
              disabled={disabled || !editing.name.trim() || duplicate}
            >
              保存项目集
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => setEditing(null)}
            >
              取消
            </Button>
          </div>
        </form>
      )}
      {selected ? (
        <>
          {addingTo === selected.id && (
            <form
              className={o.editor}
              onSubmit={(e) => {
                e.preventDefault();
                if (disabled || !picked.length) return;
                c.moveProjects(picked, selected.id);
                setAddingTo(null);
                setPicked([]);
              }}
            >
              <div className={o.editorHeading}>
                <h2>移入“{selected.name}”</h2>
                <button
                  type="button"
                  aria-label="取消移入项目"
                  onClick={() => setAddingTo(null)}
                >
                  <X size={17} />
                </button>
              </div>
              <fieldset>
                <legend>选择已有项目</legend>
                {available.map((p) => (
                  <label className={o.checkbox} key={p.id}>
                    <input
                      type="checkbox"
                      checked={picked.includes(p.id)}
                      onChange={(e) =>
                        setPicked(
                          e.target.checked
                            ? [...picked, p.id]
                            : picked.filter((id) => id !== p.id),
                        )
                      }
                    />
                    {p.name}
                    <small>
                      {c.sets.find((set) => set.projects.includes(p.id))
                        ?.name ?? "未归类"}
                    </small>
                  </label>
                ))}
              </fieldset>
              <p className={s.footnote}>
                项目会离开原项目集，计划、负责人和权限保持不变。
              </p>
              <div className={o.actions}>
                <Button type="submit" disabled={disabled || !picked.length}>
                  移入所选项目{picked.length > 0 && `（${picked.length}）`}
                </Button>
                <Button
                  variant="ghost"
                  type="button"
                  onClick={() => setAddingTo(null)}
                >
                  取消
                </Button>
              </div>
            </form>
          )}
          <div className={o.setDetailHeading}>
            <h2>项目</h2>
            <span>{selected.projects.length} 个</span>
          </div>
          {selected.projects.length ? (
            <div className={o.collectionProjects}>
              {projects
                .filter((p) => selected.projects.includes(p.id))
                .map((p) => (
                  <div key={p.id} className={o.collectionProject}>
                    <button onClick={() => onProject(p.id)}>
                      <FolderSimple size={17} />
                      <span>
                        <strong>{p.name}</strong>
                        <small>
                          {p.phase} · {p.lead} · {p.health}
                        </small>
                      </span>
                      <ArrowUpRight size={14} />
                    </button>
                    <ProjectMembershipSelect
                      controller={c}
                      id={p.id}
                      disabled={disabled}
                    />
                  </div>
                ))}
            </div>
          ) : (
            <div className={o.blank}>
              <FolderSimple size={24} />
              <h2>这个项目集还没有项目</h2>
              <p>从已有项目中选择，移入后就能在这里查看。</p>
              <Button variant="outline" disabled={disabled} onClick={beginAdd}>
                选择要移入的项目
              </Button>
            </div>
          )}
        </>
      ) : view === "列表" ? (
        <div className={`${s.tableWrap} ${o.setTable}`}>
          <table>
            <thead>
              <tr>
                <th>项目集</th>
                <th>包含项目</th>
                <th>项目进展</th>
                <th>
                  <span className={o.visuallyHidden}>操作</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {entries.map((set) => (
                <tr key={set.id}>
                  <td>
                    <button onClick={() => openSet(set.id)}>
                      {set.name}
                      <ArrowUpRight size={13} />
                    </button>
                    <p>{set.description || "尚未添加说明"}</p>
                  </td>
                  <td>
                    <span>{set.projects.length} 个项目</span>
                    <small>
                      {set.members.map((p) => p.id).join(" · ") || "还没有项目"}
                    </small>
                  </td>
                  <td>
                    {!set.members.length
                      ? "—"
                      : set.attention
                        ? `${set.attention} 个需关注`
                        : "全部正常"}
                  </td>
                  <td>
                    <button
                      disabled={disabled}
                      aria-label={`编辑${set.name}`}
                      onClick={() => {
                        setEditing({ ...set, projects: [...set.projects] });
                        c.setSetNotice("");
                      }}
                    >
                      编辑
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className={`${s.board} ${o.setBoard}`}>
          {["需关注", "进展正常", "暂无项目"].map((group) => (
            <section key={group}>
              <div className={o.boardHeading}>
                <h2>{group}</h2>
                <span>
                  {entries.filter((set) => set.group === group).length}
                </span>
              </div>
              {entries
                .filter((set) => set.group === group)
                .map((set) => (
                  <button key={set.id} onClick={() => openSet(set.id)}>
                    <h2>{set.name}</h2>
                    <p>{set.description || "尚未添加说明"}</p>
                    <div>
                      <small>{set.projects.length} 个项目</small>
                      <small>
                        {set.members.map((p) => p.id).join(" · ") || "待移入"}
                      </small>
                    </div>
                  </button>
                ))}
              {!entries.some((set) => set.group === group) && (
                <p className={o.boardEmpty}>暂无项目集</p>
              )}
            </section>
          ))}
        </div>
      )}
      <div className={o.setFooter}>
        <p className={s.footnote}>每个项目归属一个项目集，也可以保留未归类。</p>
        <button className={s.textLink} onClick={() => go("projects")}>
          查看全部项目
          <ArrowUpRight size={13} />
        </button>
      </div>
    </div>
  );
}

export function Commitments({
  role,
  person,
  onProject,
}: {
  role: Role;
  person: string;
  onProject: Jump;
}) {
  const [direction, setDirection] = useState("我承诺的");
  const data = commitments.filter((item) =>
    direction === "我承诺的" ? item.from === person : item.to === person,
  );
  if (role === "external")
    return <Blank>当前没有单独登记的承诺，可从待办继续核对收到的交付。</Blank>;
  return (
    <section>
      <div className={o.subToolbar}>
        <div className={o.segment}>
          {["我承诺的", "别人承诺给我的"].map((v) => (
            <button
              aria-pressed={direction === v}
              key={v}
              onClick={() => setDirection(v)}
            >
              {v}
            </button>
          ))}
        </div>
        <span>对谁 · 交付什么 · 何时兑现</span>
      </div>
      <div className={o.commitments}>
        {!data.length && <Blank>暂无对应的承诺记录</Blank>}
        {data.map((item) => (
          <button
            key={item.id}
            className={o.commitment}
            onClick={() => onProject(item.project, item.screen)}
          >
            <div>
              <strong>{item.title}</strong>
              <span>
                {item.from} → {item.to} ·{" "}
                {projects.find((p) => p.id === item.project)?.name}
              </span>
            </div>
            <dl>
              <div>
                <dt>承诺日期</dt>
                <dd>{item.due}</dd>
              </div>
              <div>
                <dt>最新预计</dt>
                <dd>{item.forecast}</dd>
              </div>
            </dl>
            <span className={o.commitStatus}>
              {item.status}
              <ArrowUpRight size={14} />
            </span>
          </button>
        ))}
      </div>
      <p className={s.footnote}>
        打开原事项核对进展。预计日期变化时，原承诺仍然保留；聊天回复不代表承诺已履行。
      </p>
    </section>
  );
}

export function Inbox({
  controller: c,
  pai,
  person,
  openPai,
  onProject,
  disabled,
  empty,
}: {
  controller: OrganizationController;
  pai: PaiController;
  person: string;
  openPai: (id: string) => void;
  onProject: Jump;
  disabled: boolean;
  empty: boolean;
}) {
  const [tab, setTab] = useState("通知");
  const [filter, setFilter] = useState("收件箱");
  const [selected, setSelected] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [newChat, setNewChat] = useState(false);
  const [members, setMembers] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [project, setProject] = useState("");
  const [sent, setSent] = useState(false);
  const notice = empty
    ? undefined
    : c.mine.notices.find((n) => n.id === selected);
  const chat = empty
    ? undefined
    : c.mine.chats.find((x) => x.id === c.mine.selectedChat);
  const notices = empty
    ? []
    : c.mine.notices.filter(
        (n) =>
          (filter === "已归档"
            ? n.archived
            : !n.archived && (filter !== "未读" || !n.read)) &&
          `${n.title}${n.body}`.includes(search),
      );
  const attention =
    empty || filter === "已归档"
      ? []
      : pai.needsAttention.filter(
          (x) =>
            (filter !== "未读" || !c.mine.paiRead.includes(attentionKey(x))) &&
            x.title.includes(search),
        );
  const chats = empty
    ? []
    : c.mine.chats.filter((x) =>
        `${x.title}${x.messages.map((m) => m.text).join("")}`.includes(search),
      );
  const messagesRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    messagesRef.current?.scrollTo({ top: messagesRef.current.scrollHeight });
  }, [chat?.id, chat?.messages.length, tab, newChat]);
  const teammates = roles.filter(
    (r) => r.id !== "external" && r.person !== person,
  );
  const openConversation = (id: string) => {
    c.selectChat(id);
    setNewChat(false);
    setSent(false);
  };
  return (
    <div className={`${s.page} ${o.inboxPage}`}>
      <header className={s.heading}>
        <div>
          <h1>收件箱</h1>
          <p>接收工作消息，与同事保持沟通。</p>
        </div>
        <Button
          variant="outline"
          disabled={disabled}
          onClick={() => {
            setTab("聊天");
            setNewChat(true);
            setSearch("");
            setMembers([]);
            setName("");
            setProject("");
          }}
        >
          <Plus size={16} />
          发起聊天
        </Button>
      </header>
      <ChoiceTabs
        values={["通知", "聊天", "关注动态"]}
        value={tab}
        onChange={(v) => {
          setTab(v);
          setSearch("");
          setSelected(null);
          setNewChat(false);
          c.selectChat(null);
        }}
      />
      {tab === "关注动态" ? (
        <Following controller={c} onProject={onProject} empty={empty} />
      ) : (
        <>
          <div className={o.inboxTools}>
            <input
              aria-label={tab === "通知" ? "搜索通知" : "搜索聊天"}
              placeholder={
                tab === "通知" ? "搜索通知…" : "搜索同事、群聊或消息…"
              }
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {tab === "通知" && (
              <>
                <select
                  aria-label="通知筛选"
                  value={filter}
                  onChange={(e) => {
                    setFilter(e.target.value);
                    setSelected(null);
                  }}
                >
                  {["收件箱", "未读", "已归档"].map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
                <button
                  className={o.readAll}
                  onClick={() => {
                    c.readAll();
                    pai.needsAttention.forEach((x) =>
                      c.readPai(attentionKey(x)),
                    );
                  }}
                >
                  <Check size={15} />
                  全部已读
                </button>
              </>
            )}
          </div>
          <div
            className={o.split}
            data-open={tab === "通知" ? !!notice : !!chat || newChat}
          >
            <div
              className={o.messageList}
              aria-label={tab === "通知" ? "通知列表" : "会话列表"}
            >
              {tab === "通知" ? (
                <>
                  {attention.map((session) => (
                    <button
                      key={session.id}
                      className={o.messageRow}
                      onClick={() => {
                        c.readPai(attentionKey(session));
                        openPai(session.id);
                      }}
                    >
                      <span className={o.avatar}>
                        <Sparkle size={17} />
                      </span>
                      <span>
                        <strong>小Pai需要你处理</strong>
                        <p>{session.title}</p>
                        <small>{session.scope.label} · 等待补充</small>
                      </span>
                      {!c.mine.paiRead.includes(attentionKey(session)) && (
                        <i aria-label="未读" />
                      )}
                    </button>
                  ))}
                  {notices.map((n) => (
                    <button
                      key={n.id}
                      className={o.messageRow}
                      aria-pressed={selected === n.id}
                      onClick={() => {
                        setSelected(n.id);
                        c.patchNotice(n.id, { read: true });
                      }}
                    >
                      <span className={o.avatar}>
                        {n.kind === "提及" ? "@" : <Bell size={16} />}
                      </span>
                      <span>
                        <strong>{n.title}</strong>
                        <p>{n.body}</p>
                        <small>
                          {n.project} · {n.kind} · {n.time}
                        </small>
                      </span>
                      {!n.read && <i aria-label="未读" />}
                    </button>
                  ))}
                  {!notices.length && !attention.length && (
                    <Blank>
                      {search
                        ? "没有匹配的通知"
                        : filter === "已归档"
                          ? "暂时没有归档通知"
                          : "没有待阅读的通知"}
                    </Blank>
                  )}
                </>
              ) : (
                <>
                  {chats.map((x) => (
                    <button
                      key={x.id}
                      className={o.messageRow}
                      aria-pressed={chat?.id === x.id && !newChat}
                      onClick={() => openConversation(x.id)}
                    >
                      <span className={o.avatar}>
                        {x.members.length > 2 ? (
                          <Users size={17} />
                        ) : (
                          x.title[0]
                        )}
                      </span>
                      <span>
                        <strong>{x.title}</strong>
                        <p>
                          {x.draft
                            ? `草稿：${x.draft}`
                            : x.messages.at(-1)?.text || "还没有消息"}
                        </p>
                        <small>
                          {x.members.length > 2
                            ? `${x.members.length} 人群聊`
                            : "私聊"}
                          {x.project && ` · ${x.project}`}
                        </small>
                      </span>
                      {x.unread && <i aria-label="未读" />}
                    </button>
                  ))}
                  {!chats.length && (
                    <Blank>
                      {search ? "没有匹配的会话" : "还没有会话，发起一次聊天。"}
                    </Blank>
                  )}
                </>
              )}
            </div>
            <section
              className={o.messageDetail}
              aria-label={tab === "通知" ? "通知内容" : "聊天内容"}
            >
              {tab === "通知" ? (
                notice ? (
                  <>
                    <header className={o.detailTop}>
                      <button
                        className={o.back}
                        aria-label="返回通知列表"
                        onClick={() => setSelected(null)}
                      >
                        <ArrowLeft size={17} />
                      </button>
                      <span>{notice.kind}</span>
                      <div>
                        <button
                          aria-label="标为未读"
                          onClick={() => {
                            c.patchNotice(notice.id, { read: false });
                            setSelected(null);
                          }}
                        >
                          <Bell size={16} />
                        </button>
                        <button
                          aria-label={
                            notice.archived ? "移回收件箱" : "归档通知"
                          }
                          onClick={() => {
                            c.patchNotice(notice.id, {
                              archived: !notice.archived,
                            });
                            setSelected(null);
                          }}
                        >
                          <Archive size={16} />
                          {notice.archived ? "移回收件箱" : "归档"}
                        </button>
                      </div>
                    </header>
                    <article className={o.noticeBody}>
                      <h2>{notice.title}</h2>
                      <p className={o.meta}>
                        {notice.from} · {notice.time}
                      </p>
                      <p>{notice.body}</p>
                      <ProjectLink
                        id={notice.project}
                        screen={notice.screen}
                        onProject={onProject}
                      />
                      <div className={o.actions}>
                        <Button
                          variant="outline"
                          disabled={disabled || notice.from === person}
                          onClick={() => {
                            c.createChat(
                              [notice.from],
                              notice.from,
                              notice.project,
                            );
                            setTab("聊天");
                            setSearch("");
                            setSent(false);
                            setNewChat(false);
                          }}
                        >
                          <ChatCircle size={15} />与{notice.from}沟通
                        </Button>
                      </div>
                    </article>
                    <p className={o.detailFoot}>
                      已读与归档只整理消息，相关工作仍在“我的工作”办理。
                    </p>
                  </>
                ) : (
                  <Blank>选择一条通知，查看上下文。</Blank>
                )
              ) : newChat ? (
                <form
                  className={o.newChat}
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (
                      !members.length ||
                      disabled ||
                      (members.length > 1 && !name.trim())
                    )
                      return;
                    c.createChat(
                      members,
                      members.length > 1 ? name : members[0],
                      project,
                    );
                    setNewChat(false);
                    setSent(false);
                  }}
                >
                  <div className={o.editorHeading}>
                    <h2>发起聊天</h2>
                    <button
                      type="button"
                      aria-label="取消发起聊天"
                      onClick={() => setNewChat(false)}
                    >
                      <X size={17} />
                    </button>
                  </div>
                  <fieldset>
                    <legend>选择同事 · 多选即创建群聊</legend>
                    {teammates.map((r) => (
                      <label className={o.checkbox} key={r.id}>
                        <input
                          type="checkbox"
                          checked={members.includes(r.person)}
                          onChange={(e) =>
                            setMembers(
                              e.target.checked
                                ? [...members, r.person]
                                : members.filter((m) => m !== r.person),
                            )
                          }
                        />
                        {r.person}
                        <small>{r.name}</small>
                      </label>
                    ))}
                  </fieldset>
                  {members.length > 1 && (
                    <label>
                      群聊名称
                      <input
                        value={name}
                        maxLength={60}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="例如：P1 试制协作"
                        required
                      />
                    </label>
                  )}
                  <label>
                    关联项目（选填）
                    <select
                      value={project}
                      onChange={(e) => setProject(e.target.value)}
                    >
                      <option value="">不关联项目</option>
                      {projects.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <Button
                    disabled={
                      !members.length ||
                      disabled ||
                      (members.length > 1 && !name.trim())
                    }
                  >
                    开始{members.length > 1 ? "群聊" : "私聊"}
                  </Button>
                  <small>仅创建本地演示会话，不会通知同事。</small>
                </form>
              ) : chat ? (
                <>
                  <header className={o.detailTop}>
                    <button
                      className={o.back}
                      aria-label="返回会话列表"
                      onClick={() => c.selectChat(null)}
                    >
                      <ArrowLeft size={17} />
                    </button>
                    <div className={o.chatTitle}>
                      <h2>{chat.title}</h2>
                      <details>
                        <summary>
                          {chat.members.length > 2
                            ? `${chat.members.length} 位成员`
                            : "私聊成员"}
                        </summary>
                        <p>{chat.members.join("、")}</p>
                      </details>
                    </div>
                  </header>
                  {chat.project && (
                    <div className={o.chatProject}>
                      <ProjectLink id={chat.project} onProject={onProject} />
                    </div>
                  )}
                  <div
                    ref={messagesRef}
                    className={o.chatMessages}
                    role="log"
                    aria-label="聊天消息"
                  >
                    {chat.messages.length ? (
                      chat.messages.map((m) => (
                        <article key={m.id}>
                          <span className={o.avatar}>{m.author[0]}</span>
                          <div>
                            <header>
                              <strong>
                                {m.author === person ? "我" : m.author}
                              </strong>
                              <time>{m.time}</time>
                            </header>
                            <p>{m.text}</p>
                          </div>
                        </article>
                      ))
                    ) : (
                      <Blank>会话已准备好，写下第一条消息。</Blank>
                    )}
                  </div>
                  <form
                    className={o.composer}
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (disabled || !chat.draft.trim()) return;
                      c.sendChat(chat.id);
                      setSent(true);
                    }}
                  >
                    <textarea
                      aria-label="聊天消息输入"
                      value={chat.draft}
                      maxLength={4000}
                      onChange={(e) => {
                        c.patchChat(chat.id, { draft: e.target.value });
                        setSent(false);
                      }}
                      placeholder={`发消息给${chat.title}…`}
                    />
                    <div>
                      <span role="status">
                        {disabled
                          ? "离线时保留草稿，恢复后可发送"
                          : sent
                            ? "已加入当前预览，未发送给真实成员"
                            : "本地预览 · 消息不会发送给真实成员"}
                      </span>
                      <Button
                        disabled={disabled || !chat.draft.trim()}
                        type="submit"
                      >
                        发送
                      </Button>
                    </div>
                  </form>
                </>
              ) : (
                <Blank>选择一段聊天，或发起新的对话。</Blank>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}

function Following({
  controller: c,
  onProject,
  empty,
}: {
  controller: OrganizationController;
  onProject: Jump;
  empty: boolean;
}) {
  const [filter, setFilter] = useState("all");
  const feed = [
    {
      id: "P1",
      person: "周宁",
      title: "更新了项目进展",
      body: "噪声复测等待资源协调，验证评审仍按原承诺跟进。",
      time: "今天 09:40",
      screen: "now" as Screen,
    },
    {
      id: "P1",
      person: "吴敏",
      title: "交付了首批样件",
      body: "Lot A · 4 件 · E-06 / M-04，另 2 件待交付。",
      time: "今天 09:18",
      screen: "builds" as Screen,
    },
    {
      id: "S2",
      person: "林悦",
      title: "补充了接口差异说明",
      body: "继续核对规格冻结资料。",
      time: "昨天 16:30",
      screen: "now" as Screen,
    },
    {
      id: "D3",
      person: "高远",
      title: "更新了制造准备",
      body: "制造接收结论待提供，完成预测仍未知。",
      time: "昨天 15:10",
      screen: "now" as Screen,
    },
  ].filter(
    (x) =>
      !empty &&
      c.mine.followed.includes(x.id) &&
      (filter === "all" || x.id === filter),
  );
  return (
    <>
      <div className={o.subToolbar}>
        <label className={o.filter}>
          范围
          <select
            aria-label="动态项目范围"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="all">我关注的项目</option>
            {projects
              .filter((p) => c.mine.followed.includes(p.id))
              .map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
          </select>
        </label>
        <details className={o.followMenu}>
          <summary>管理关注</summary>
          <div>
            {projects.map((p) => (
              <label key={p.id} className={o.checkbox}>
                <input
                  type="checkbox"
                  checked={c.mine.followed.includes(p.id)}
                  onChange={(e) => {
                    c.follow(p.id, e.target.checked);
                    if (!e.target.checked && filter === p.id) setFilter("all");
                  }}
                />
                {p.name}
              </label>
            ))}
          </div>
        </details>
      </div>
      <p className={o.feedHint}>
        了解项目发生了什么。需要你处理的事项会进入待办，@你的消息会进入通知。
      </p>
      <div className={o.feed}>
        {feed.map((x) => (
          <article key={`${x.id}-${x.title}`}>
            <span className={o.avatar}>{x.person[0]}</span>
            <div>
              <p>
                <strong>{x.person}</strong> {x.title}
              </p>
              <p>{x.body}</p>
              <ProjectLink id={x.id} onProject={onProject} screen={x.screen} />
            </div>
            <time>{x.time}</time>
          </article>
        ))}
        {!feed.length && (
          <Blank>暂无关注动态，可在“管理关注”中选择项目。</Blank>
        )}
      </div>
    </>
  );
}

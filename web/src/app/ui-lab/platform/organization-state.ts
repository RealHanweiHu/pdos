"use client";
import { useRef, useState } from "react";
import type { Conversation } from "./pai-preview-state";
import { roles, type Role, type Screen } from "./design-data";

export type InboxNotice = {
  id: string;
  title: string;
  body: string;
  from: string;
  time: string;
  project: string;
  screen: Screen;
  kind: "提及" | "工作通知";
  read: boolean;
  archived: boolean;
};
export type TeamChat = {
  id: string;
  title: string;
  members: string[];
  project: string;
  unread: boolean;
  draft: string;
  messages: { id: string; author: string; text: string; time: string }[];
};
export type ProjectSet = {
  id: string;
  name: string;
  description: string;
  projects: string[];
};
type PersonalState = {
  notices: InboxNotice[];
  chats: TeamChat[];
  selectedChat: string | null;
  followed: string[];
  paiRead: string[];
};
function initialPersonal(role: Role): PersonalState {
  const person = roles.find((r) => r.id === role)!.person;
  const colleague = person === "林悦" ? "周宁" : "林悦";
  if (role === "external")
    return {
      notices: [],
      chats: [],
      selectedChat: null,
      followed: [],
      paiRead: [],
    };
  return {
    notices: [
      {
        id: "mention",
        title: `${colleague} 在评审准备中提到了你`,
        body: `@${person} 请一起核对评审资料，重点看噪声复测的结论和未完成项。讨论后仍需在项目中正式提交。`,
        from: colleague,
        time: "今天 09:42",
        project: "P1",
        screen: "release",
        kind: "提及",
        read: false,
        archived: false,
      },
      {
        id: "sample",
        title: "首批 4 件样件已交付",
        body: "吴敏已交付 Lot A 首批 4 件样件，工程配置 E-06 / 制造配置 M-04。另 2 件待交付，品质接收仍需由负责人办理。",
        from: "吴敏",
        time: "今天 09:18",
        project: "P1",
        screen: "builds",
        kind: "工作通知",
        read: false,
        archived: false,
      },
      {
        id: "definition",
        title: "S2 的接口差异说明已更新",
        body: "林悦补充了 S2 派生项目的接口差异说明，下一步核对规格冻结所需资料。",
        from: "林悦",
        time: "昨天 16:30",
        project: "S2",
        screen: "now",
        kind: "工作通知",
        read: true,
        archived: false,
      },
    ],
    chats: [
      {
        id: "review-team",
        title: "P1 · 验证评审",
        members: Array.from(new Set([person, "林悦", "许澄", "陈舟"])),
        project: "P1",
        unread: true,
        draft: "",
        messages: [
          {
            id: "m1",
            author: "林悦",
            text: "这个群用于对齐 P1 的验证评审准备。相关结论和正式决定仍在项目里记录。",
            time: "昨天 16:20",
          },
          {
            id: "m2",
            author: "许澄",
            text: "首批 4 件样件已交付，复测还在等消音室时段。我会在确认后更新预计完成时间。",
            time: "今天 09:35",
          },
        ],
      },
      {
        id: "direct",
        title: colleague,
        members: [person, colleague],
        project: "",
        unread: false,
        draft: "",
        messages: [
          {
            id: "d1",
            author: colleague,
            text: "评审资料里请保留当前承诺和最新预测，方便大家看清差异。",
            time: "昨天 15:10",
          },
        ],
      },
    ],
    selectedChat: null,
    followed: ["P1", "S2"],
    paiRead: [],
  };
}
export function attentionKey(session: Conversation) {
  return `${session.id}:${session.messages.at(-1)?.id ?? "waiting"}`;
}

export const commitments: {
  id: string;
  title: string;
  from: string;
  to: string;
  due: string;
  forecast: string;
  status: string;
  project: string;
  screen: Screen;
}[] = [
  {
    id: "COM-01",
    title: "提交验证评审资料",
    from: "周宁",
    to: "林悦",
    due: "11月06日",
    forecast: "11月09日",
    status: "预计晚于承诺",
    project: "P1",
    screen: "plan",
  },
  {
    id: "COM-02",
    title: "提交噪声复测结论",
    from: "许澄",
    to: "周宁",
    due: "11月04日",
    forecast: "时段待确认",
    status: "等待资源确认",
    project: "P1",
    screen: "builds",
  },
  {
    id: "COM-03",
    title: "确认第二批电机到料",
    from: "沈禾",
    to: "周宁",
    due: "11月02日",
    forecast: "未提供",
    status: "等待进展",
    project: "P1",
    screen: "plan",
  },
  {
    id: "COM-04",
    title: "提交规格差异说明",
    from: "林悦",
    to: "陈舟",
    due: "11月02日",
    forecast: "11月02日",
    status: "进行中",
    project: "S2",
    screen: "now",
  },
  {
    id: "COM-05",
    title: "完成接口图修订",
    from: "陈舟",
    to: "高远",
    due: "11月03日",
    forecast: "11月03日",
    status: "进行中",
    project: "P1",
    screen: "engineering",
  },
  {
    id: "COM-06",
    title: "补齐制造准备记录",
    from: "高远",
    to: "吴敏",
    due: "11月05日",
    forecast: "未提供",
    status: "等待进展",
    project: "D3",
    screen: "now",
  },
  {
    id: "COM-07",
    title: "交付剩余 2 件样件",
    from: "吴敏",
    to: "许澄",
    due: "11月03日",
    forecast: "11月03日",
    status: "进行中",
    project: "P1",
    screen: "builds",
  },
  {
    id: "COM-08",
    title: "给出资源协调意见",
    from: "郑言",
    to: "周宁",
    due: "10月30日",
    forecast: "10月30日",
    status: "待决定",
    project: "P1",
    screen: "plan",
  },
];
export function useOrganizationPreview(role: Role) {
  const seq = useRef(0);
  const [people, setPeople] = useState<Record<Role, PersonalState>>(
    () =>
      Object.fromEntries(
        roles.map((r) => [r.id, initialPersonal(r.id)]),
      ) as Record<Role, PersonalState>,
  );
  const [sets, setSets] = useState<ProjectSet[]>([
    {
      id: "portable",
      name: "便携充气产品",
      description: "一起查看面向便携使用场景的研发项目。",
      projects: ["P1", "S2"],
    },
    {
      id: "manufacturing",
      name: "本期制造导入",
      description: "集中关注即将交给制造团队的项目。",
      projects: ["D3"],
    },
  ]);
  const [selectedSetId, setSelectedSetId] = useState<string | null>(null);
  const [setEditor, setSetEditor] = useState<ProjectSet | null>(null);
  const [setNotice, setSetNotice] = useState("");
  const mine = people[role];
  function update(fn: (value: PersonalState) => PersonalState) {
    setPeople((prev) => ({ ...prev, [role]: fn(prev[role]) }));
  }
  function patchNotice(
    id: string,
    patch: Partial<Pick<InboxNotice, "read" | "archived">>,
  ) {
    update((p) => ({
      ...p,
      notices: p.notices.map((n) => (n.id === id ? { ...n, ...patch } : n)),
    }));
  }
  function selectChat(id: string | null) {
    update((p) => ({
      ...p,
      selectedChat: id,
      chats: p.chats.map((c) => (c.id === id ? { ...c, unread: false } : c)),
    }));
  }
  function patchChat(
    id: string,
    patch: Partial<Pick<TeamChat, "draft" | "project">>,
  ) {
    update((p) => ({
      ...p,
      chats: p.chats.map((c) => (c.id === id ? { ...c, ...patch } : c)),
    }));
  }
  function createChat(members: string[], title: string, project: string) {
    const person = roles.find((r) => r.id === role)!.person;
    const existing =
      members.length === 1
        ? mine.chats.find(
            (c) =>
              c.members.length === 2 &&
              c.members.includes(members[0]) &&
              c.project === project,
          )
        : undefined;
    if (existing) {
      selectChat(existing.id);
      return existing.id;
    }
    const id = `chat-${++seq.current}`;
    update((p) => ({
      ...p,
      selectedChat: id,
      chats: [
        {
          id,
          title: title.trim() || members.join("、"),
          members: [person, ...members],
          project,
          unread: false,
          draft: "",
          messages: [],
        },
        ...p.chats,
      ],
    }));
    return id;
  }
  function sendChat(id: string) {
    const messageId = `local-${++seq.current}`;
    const person = roles.find((r) => r.id === role)!.person;
    update((p) => ({
      ...p,
      chats: p.chats.map((c) =>
        c.id === id && c.draft.trim()
          ? {
              ...c,
              draft: "",
              messages: [
                ...c.messages,
                {
                  id: messageId,
                  author: person,
                  text: c.draft.trim(),
                  time: "刚刚 · 仅本地预览",
                },
              ],
            }
          : c,
      ),
    }));
  }
  function saveSet(value: ProjectSet) {
    const saved = { ...value, id: value.id || `set-${++seq.current}` };
    setSets((prev) => {
      const next = prev
        .filter((x) => x.id !== saved.id)
        .map((x) => ({
          ...x,
          projects: x.projects.filter((id) => !saved.projects.includes(id)),
        }));
      const index = prev.findIndex((x) => x.id === saved.id);
      next.splice(index < 0 ? next.length : index, 0, saved);
      return next;
    });
    setSelectedSetId(saved.id);
    setSetNotice(`已保存“${saved.name}”`);
  }
  function moveProjects(ids: string[], target: string | null) {
    const destination = sets.find((set) => set.id === target);
    if (target && !destination) return;
    setSets((prev) =>
      prev.map((set) => ({
        ...set,
        projects:
          set.id === target
            ? [...new Set([...set.projects, ...ids])]
            : set.projects.filter((id) => !ids.includes(id)),
      })),
    );
    setSetNotice(
      `${ids.length} 个项目已${destination ? `移入“${destination.name}”` : "移至未归类"}`,
    );
  }
  return {
    mine,
    sets,
    selectedSetId,
    setSelectedSetId,
    setEditor,
    setSetEditor,
    setNotice,
    setSetNotice,
    moveProjects,
    patchNotice,
    selectChat,
    patchChat,
    createChat,
    sendChat,
    saveSet,
    readAll: () =>
      update((p) => ({
        ...p,
        notices: p.notices.map((n) => ({ ...n, read: true })),
      })),
    readPai: (id: string) =>
      update((p) => ({ ...p, paiRead: [...new Set([...p.paiRead, id])] })),
    follow: (id: string, yes: boolean) =>
      update((p) => ({
        ...p,
        followed: yes
          ? [...new Set([...p.followed, id])]
          : p.followed.filter((x) => x !== id),
      })),
    unread:
      mine.notices.filter((n) => !n.read && !n.archived).length +
      mine.chats.filter((c) => c.unread).length,
  };
}
export type OrganizationController = ReturnType<typeof useOrganizationPreview>;

/**
 * Project discussions and object comments (P34-2/3). Presentation only: who may
 * read, write or be mentioned is decided by the server on every request.
 */

export type MentionKind = "person" | "role" | "all" | "task" | "agent";
export type Mention = { kind: "person"; id: string } | { kind: "role"; key: string; member_ids: string[] } | { kind: "all"; member_ids: string[] } | { kind: "task"; id: string } | { kind: "agent" };

/** The run card under a human message that @-mentioned 小Pai (P34-4). Status only for others. */
export type AgentCard = {
  request_id: string; requester_name: string; own: boolean; state: string; label: string;
  delivery: "pending" | "public" | "private" | "none"; reason: string | null; reason_label: string | null;
  private_only: boolean; reply_message_id: string | null; share_mode: "body" | "link" | null; can_open_link: boolean;
  run_id?: string; error_code?: string | null; can_share?: boolean; customer_derived?: boolean;
};
/** How a message written by 小Pai came to the thread (P54). */
export type AgentMessage = { request_id: string; kind: "reply" | "notice" | "share"; requested_by: string; share_mode: "body" | "link" | null; can_retract: boolean };
export type AgentReply = {
  request_id: string; body: string; delivery: string; run_id?: string; share_mode?: "body" | "link" | null; can_share?: boolean;
  share_modes?: ("link" | "body")[]; customer_derived?: boolean; uncovered_source_kinds?: string[]; reason_label?: string | null; body_warning?: string | null;
};

export type DiscussionMessage = {
  id: string; sequence: number; author_id: string; author_name: string;
  state: "posted" | "edited" | "retracted"; retracted: boolean; body: string; placeholder: string | null;
  mentions: Mention[]; revision: number; edited: boolean; subject_revision: number | null;
  created_at: string; updated_at: string; change_seq: number; own: boolean; can_edit: boolean;
  author_kind?: "human" | "agent"; agent?: AgentMessage | null; agent_request?: AgentCard | null; can_retract?: boolean;
};
export type DiscussionSubject = { type: "work_task" | "artifact"; type_label: string; id: string; title: string; revision: number; visibility?: string };
export type ThreadView = {
  thread: null | { id: string; project_id: string; subject_type: string; subject_id: string; title: string | null; author_id: string; author_name: string; created_at: string; following: boolean; token?: string };
  subject: DiscussionSubject | null;
  messages: DiscussionMessage[];
  people: Record<string, string>;
  next_before: number | null;
  can_post: boolean;
  full_project: boolean;
  note: string;
};
export type TopicSummary = { id: string; title: string; author_name: string; created_at: string; messages: number; token: string; latest: DiscussionMessage | null; following: boolean };
export type TopicList = { project_id: string; items: TopicSummary[]; note: string };
export type MentionCandidate = { principal_id: string; name: string; is_member: boolean; roles: string[]; can_see: boolean; is_self: boolean };
export type Mentionable = { people: MentionCandidate[]; roles: { key: string; name: string; members: number }[]; can_mention_all: boolean; can_invite: boolean; agent: { available: boolean; note: string } };
export type DiscussionScope = { categoryId: string; productId: string; projectId: string };

/** Category-scoped paths; the server re-derives every scope from them. */
const base = ({ categoryId, productId, projectId }: DiscussionScope) => `v1/categories/${categoryId}/products/${productId}/projects/${projectId}`;
export const topicsPath = (scope: DiscussionScope) => `${base(scope)}/discussions`;
export const threadPath = (scope: DiscussionScope, threadId: string) => `${base(scope)}/discussions/${threadId}`;
export const commentsPath = (scope: DiscussionScope, subjectType: "work_task" | "artifact", subjectId: string) => `${base(scope)}/comments/${subjectType}/${subjectId}`;
export const mentionablePath = (scope: DiscussionScope, subjectType = "project", subjectId?: string) =>
  `${base(scope)}/mentionable${subjectType === "project" ? "" : `?subject_type=${subjectType}&subject_id=${subjectId}`}`;
export const messagePath = (scope: DiscussionScope, threadId: string, messageId: string, action: "edit" | "retract") => `${threadPath(scope, threadId)}/messages/${messageId}/${action}`;
export const agentReplyPath = (scope: DiscussionScope, threadId: string, requestId: string) => `${threadPath(scope, threadId)}/agent-requests/${requestId}/reply`;
export const agentSharePath = (scope: DiscussionScope, threadId: string, requestId: string) => `${threadPath(scope, threadId)}/agent-requests/${requestId}/share`;

const TOKEN = /@\[([^\]\n]{1,80})\]\((person|role|all|task|agent)(?::([A-Za-z0-9_-]{1,64}))?\)/g;

export type Segment = { kind: "text"; text: string } | { kind: "mention"; mention: MentionKind; label: string; ref: string | null };

/** Split a message body into text and @ tokens; labels show current names when known. */
export function segments(body: string, people: Record<string, string> = {}): Segment[] {
  const result: Segment[] = [];
  let last = 0;
  for (const match of body.matchAll(TOKEN)) {
    if (match.index > last) result.push({ kind: "text", text: body.slice(last, match.index) });
    const [, label, kind, ref] = match;
    const name = kind === "person" && ref && people[ref] ? people[ref] : label;
    result.push({ kind: "mention", mention: kind as MentionKind, label: name, ref: ref ?? null });
    last = match.index + match[0].length;
  }
  if (last < body.length) result.push({ kind: "text", text: body.slice(last) });
  return result;
}

export function mentionToken(kind: "person" | "role" | "all" | "task" | "agent", label: string, ref?: string) {
  const clean = label.replace(/[\]\n]/g, "").slice(0, 80) || "成员";
  return kind === "all" || kind === "agent" ? `@[${clean}](${kind})` : `@[${clean}](${kind}:${ref})`;
}

/** True when the text @-mentions 小Pai, i.e. sending it starts a 小Pai run. */
export function hasAgentMention(text: string) {
  return [...text.matchAll(TOKEN)].some(match => match[2] === "agent");
}

/** The "@query" being typed at the caret, if any. */
export function activeQuery(text: string, caret: number): { start: number; query: string } | null {
  const before = text.slice(0, caret);
  const at = before.lastIndexOf("@");
  if (at < 0) return null;
  const query = before.slice(at + 1);
  if (/[\s\]()[]/.test(query) || query.length > 20) return null;
  if (at > 0 && !/[\s，。、,.:：(（]/.test(before[at - 1])) return null;
  return { start: at, query };
}

export function insertMention(text: string, caret: number, token: string) {
  const active = activeQuery(text, caret);
  const start = active ? active.start : caret;
  const next = `${text.slice(0, start)}${token} ${text.slice(caret)}`;
  return { text: next, caret: start + token.length + 1 };
}

export type Choice = { key: string; kind: "person" | "role" | "all" | "agent"; label: string; detail: string; token: string; disabled: boolean; reason?: string };

/** Mention choices for a query: people who cannot see the object are listed, greyed (§7.2). */
export function mentionChoices(options: Mentionable | null, query: string): Choice[] {
  if (!options) return [];
  const q = query.trim().toLowerCase();
  const match = (value: string) => !q || value.toLowerCase().includes(q);
  const people: Choice[] = options.people.filter(person => !person.is_self && (match(person.name) || person.roles.some(match))).map(person => ({
    key: `person:${person.principal_id}`, kind: "person", label: person.name,
    detail: person.can_see ? person.roles.join("、") || (person.is_member ? "项目成员" : "可查看") : "不在本项目受众中",
    token: mentionToken("person", person.name, person.principal_id), disabled: !person.can_see,
    reason: person.can_see ? undefined : options.can_invite ? "提及不授予访问权；可先在团队页邀请加入。" : "提及不授予访问权。",
  }));
  people.sort((a, b) => Number(a.disabled) - Number(b.disabled));
  const roles: Choice[] = options.roles.filter(role => match(role.name)).map(role => ({
    key: `role:${role.key}`, kind: "role", label: role.name, detail: `本项目 ${role.members} 人`, token: mentionToken("role", role.name, role.key), disabled: false,
  }));
  const all: Choice[] = options.can_mention_all && match("全体") ? [{ key: "all", kind: "all", label: "全体", detail: "本项目全部成员", token: mentionToken("all", "全体"), disabled: false }] : [];
  // 小Pai is offered first when available; it is never a person or a recipient.
  const agent: Choice[] = (match("小Pai") || match("xiaopai") || match("pai")) ? [{
    key: "agent", kind: "agent", label: "小Pai", detail: options.agent.available ? "按你的权限发起一次运行" : "当前不可用",
    token: mentionToken("agent", "小Pai"), disabled: !options.agent.available, reason: options.agent.note || undefined,
  }] : [];
  return [...agent, ...people, ...roles, ...all].slice(0, 12);
}

export function anchorLabel(message: DiscussionMessage, subject: DiscussionSubject | null) {
  if (!subject || message.subject_revision === null) return null;
  return message.subject_revision === subject.revision ? `评论于 v${message.subject_revision}` : `评论于 v${message.subject_revision} · 当前 v${subject.revision}`;
}

const RUNNING = new Set(["queued", "running", "waiting_input"]);

/** True while a card can still change: the run works, waits, or its sources are being checked. */
export function cardInProgress(card: AgentCard | null | undefined) {
  return !!card && (card.delivery === "pending" || RUNNING.has(card.state));
}

/** Tone for the card's status chip. */
export function cardTone(card: AgentCard): "running" | "waiting" | "done" | "partial" | "failed" {
  if (card.state === "waiting_input") return "waiting";
  if (cardInProgress(card)) return "running";
  if (card.state === "partial") return "partial";
  if (card.state === "completed") return "done";
  return "failed";
}

/** One line under the status: where the reply went, without naming any hidden source. */
export function cardNote(card: AgentCard): string | null {
  if (card.delivery === "public") return card.own ? "回复已贴在下方，串里的人都能看到。" : null;
  if (card.delivery === "private") {
    const who = card.own ? "你" : card.requester_name;
    if (card.share_mode === "body") return `${who}已把回复正文分享到串里。`;
    if (card.share_mode === "link") return card.own ? "你已分享回复链接；成员打开时按各自权限核对全部来源。" : `${who}分享了回复链接；打开前按你的权限核对全部来源。`;
    return `回复只给${who}看${card.reason_label ? `：${card.reason_label}` : ""}。`;
  }
  if (card.delivery === "none") return card.reason_label ? `${card.reason_label}。` : "这次没有回复。";
  if (card.state === "waiting_input") return card.own ? "小Pai 需要你补充信息，请在小Pai 工作栏里回答。" : null;
  return null;
}

export function mentionError(error: unknown): string | null {
  const value = error as { detail?: { reason?: string; blocked?: { name: string }[] }; message?: string } | null;
  if (value?.detail?.reason === "mention_not_visible") return `不在本项目受众中：${(value.detail.blocked ?? []).map(item => item.name).join("、")}。提及不授予访问权。`;
  if (value?.detail?.reason === "agent_mention_edit") return "编辑不会发起小Pai，请另发一条消息 @小Pai。";
  return null;
}

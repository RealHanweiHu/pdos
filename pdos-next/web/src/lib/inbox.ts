export type InboxKind = "conversation" | "run" | "project";
export type InboxState = {
  kind: InboxKind;
  target_id: string;
  revision: number;
  read_through: string;
  archived: boolean;
  followed: boolean;
};
export type InboxMessage = {
  id: string;
  sequence: number;
  sender_id: string;
  sender_name: string;
  body: string;
  created_at: string;
};
export type InboxConversation = {
  id: string;
  title: string;
  category_id: string;
  category_name: string;
  members: { id: string; name: string }[];
  created_at: string;
  latest: InboxMessage | null;
};
export type MessagePage = {
  conversation_id: string;
  items: InboxMessage[];
  next_before: number | null;
};
export type InboxPending = {
  path: string;
  body: Record<string, unknown>;
  kind: "create" | "message" | "state";
};
export const inboxRoot = "v1/personal/inbox";
export const isUnread = (state: InboxState | undefined, token: string) =>
  !state || state.read_through !== token;
export function visibleInbox(
  state: InboxState | undefined,
  token: string,
  filter: "all" | "unread" | "archived" | "followed",
) {
  const unread = isUnread(state, token);
  if (filter === "archived") return !!state?.archived && !unread;
  if (filter === "followed") return !!state?.followed;
  return (!state?.archived || unread) && (filter !== "unread" || unread);
}
export function restoreInboxPending(raw: string | null): InboxPending | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw);
    if (
      !["create", "message", "state"].includes(value.kind) ||
      typeof value.body?.request_key !== "string"
    )
      return null;
    const valid =
      value.kind === "create"
        ? value.path === `${inboxRoot}/conversations`
        : value.kind === "state"
          ? value.path === `${inboxRoot}/states`
          : /^v1\/personal\/inbox\/conversations\/[a-f0-9-]{36}\/messages$/i.test(
              value.path,
            );
    return valid ? value : null;
  } catch {
    return null;
  }
}

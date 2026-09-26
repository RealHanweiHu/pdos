export type NotificationMode = "none" | "in_app" | "dingtalk";
export type NotificationScope = {
  mode: Exclude<NotificationMode, "none">;
  channel: { corp_id: string } | null;
  recipients: { id: string; display_name: string; participation: string; binding_id?: string | null; corp_id?: string | null }[];
};
export type AutomaticNotice = { status: "waiting_conference" | "registered" | "needs_review"; batch_id?: string; mode?: string; message?: string };
export const notificationModes: Record<NotificationMode, string> = { none: "逐场人工确认通知", in_app: "自动登记站内通知", dingtalk: "自动登记站内通知及钉钉个人消息" };

export function NotificationScopeSummary({ scope }: { scope: NotificationScope | null | undefined }) {
  if (!scope) return <p>参会通知：逐场人工确认。</p>;
  return <div className="space-y-1"><p>新场次：{notificationModes[scope.mode]}。有外部预约时，等待预约成功绑定后通知；已有场次不补发。</p><details><summary>已确认的 {scope.recipients.length} 位收件人</summary>{scope.recipients.map(p => <p key={p.id}>{p.display_name} · {p.participation === "organizer" ? "组织者" : p.participation === "required" ? "必需参会" : "可选参会"}{scope.mode === "dingtalk" ? p.binding_id && p.corp_id === scope.channel?.corp_id ? " · 站内及钉钉" : " · 未绑定当前企业钉钉，仅站内通知" : " · 站内通知"}</p>)}</details><p className="text-xs text-muted-foreground">名单、账号或授权变化后须重新核对。暂停后不再新增自动通知，原批次中尚未投递的钉钉消息派发前也会复核授权；已登记的站内通知及实际投递回执保留。</p></div>;
}

export function AutomaticNoticeSummary({ value }: { value: AutomaticNotice }) {
  return <p>参会通知：{value.status === "waiting_conference" ? "等待外部预约成功绑定" : value.status === "registered" ? "已登记，实际送达请查看本场逐人回执" : "待人工核对，本次未自动通知"}{value.batch_id && ` · 批次 ${value.batch_id}`}{value.message && ` · ${value.message}`}</p>;
}

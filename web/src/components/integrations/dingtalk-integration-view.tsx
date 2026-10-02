import {
  CheckCircleIcon,
  ClockCounterClockwiseIcon,
  LinkSimpleIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react/ssr";

import { Button } from "@/components/ui/button";
import { SettingsNav } from "@/components/settings/settings-nav";
import { WorkspaceShell } from "@/components/workspace-shell";
import type { WorkspaceIdentity } from "@/components/workspace-types";

import type { DingTalkBootstrap } from "./dingtalk-types";

const OPERATION_LABELS: Record<string, string> = {
  group_markdown: "项目群通知",
  gate_approval_create: "Gate 外部审批",
  interactive_card_create: "交互卡片",
  interactive_card_update: "卡片更新",
};

export function DingTalkIntegrationView({
  data,
  identity,
  linking,
  linkError,
  loggingOut,
  onLink,
  onLogout,
}: {
  data: DingTalkBootstrap;
  identity: WorkspaceIdentity;
  linking: boolean;
  linkError: string | null;
  loggingOut: boolean;
  onLink: () => void;
  onLogout: () => void;
}) {
  const healthy = data.status.configured && data.status.binding_status === "active";
  return (
    <WorkspaceShell
      active="settings"
      identity={identity}
      loggingOut={loggingOut}
      onLogout={onLogout}
    >
      <SettingsNav current="dingtalk-integration" identity={identity}>
      <div className="border-b pb-4">
        <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">
          Integration
        </p>
        <h1 className="mt-1 text-lg font-semibold">钉钉集成</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          查看独立应用、身份绑定和可靠投递状态。远端审批结果只作为外部证据。
        </p>
      </div>

      <section className="mt-5 grid gap-4 sm:grid-cols-3" aria-label="钉钉集成状态">
        <StatusCard
          label="应用"
          value={healthy ? "已启用" : data.status.configured ? "已停用" : "未配置"}
          ok={healthy}
        />
        <StatusCard
          label="当前身份"
          value={data.status.linked ? "已绑定" : "未绑定"}
          ok={data.status.linked}
        />
        <StatusCard
          label="外发模式"
          value={data.status.delivery_enabled ? "自动投递" : "人工降级"}
          ok={data.status.delivery_enabled}
        />
      </section>

      <section className="mt-5 rounded-lg border bg-card p-5" aria-labelledby="identity-title">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="font-medium" id="identity-title">身份绑定</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              绑定只作用于当前登录用户，不按手机号、姓名或邮箱自动匹配。
            </p>
          </div>
          <Button
            className="h-11"
            disabled={linking || data.status.linked || !healthy}
            onClick={onLink}
            variant={data.status.linked ? "outline" : "default"}
          >
            <LinkSimpleIcon aria-hidden="true" />
            {data.status.linked ? "当前身份已绑定" : linking ? "正在前往钉钉…" : "显式绑定当前身份"}
          </Button>
        </div>
        {linkError ? (
          <p className="mt-4 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
            {linkError}
          </p>
        ) : null}
      </section>

      {data.outbox !== null ? (
        <section className="mt-5 overflow-hidden rounded-lg border bg-card" aria-labelledby="outbox-title">
          <div className="border-b px-5 py-4">
            <h2 className="font-medium" id="outbox-title">最近投递</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              uncertain 必须先人工对账，不能直接重放。
            </p>
          </div>
          {data.outbox.length === 0 ? (
            <div className="px-5 py-10 text-center text-sm text-muted-foreground">
              <ClockCounterClockwiseIcon aria-hidden="true" className="mx-auto mb-2 size-7" />
              暂无钉钉投递记录
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[680px] text-left text-sm">
                <thead className="bg-muted/50 text-xs text-muted-foreground">
                  <tr>
                    <th className="px-5 py-3 font-medium" scope="col">类型</th>
                    <th className="px-5 py-3 font-medium" scope="col">状态</th>
                    <th className="px-5 py-3 font-medium" scope="col">尝试</th>
                    <th className="px-5 py-3 font-medium" scope="col">错误码 / 远端引用</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {data.outbox.map((item) => (
                    <tr key={item.id}>
                      <td className="px-5 py-3 font-medium">
                        {OPERATION_LABELS[item.operation] ?? item.operation}
                      </td>
                      <td className="px-5 py-3"><StatusPill status={item.status} /></td>
                      <td className="px-5 py-3 font-mono text-xs">{item.attempt_count}</td>
                      <td className="max-w-sm truncate px-5 py-3 font-mono text-xs text-muted-foreground">
                        {item.last_error_code ?? item.remote_reference ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}
      </SettingsNav>
    </WorkspaceShell>
  );
}

function StatusCard({ label, ok, value }: { label: string; ok: boolean; value: string }) {
  const Icon = ok ? CheckCircleIcon : WarningCircleIcon;
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-2 flex items-center gap-2 font-medium">
        <Icon aria-hidden="true" className={ok ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400"} />
        {value}
      </p>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  return (
    <span className="inline-flex rounded-full bg-muted px-2.5 py-1 font-mono text-[11px] font-medium">
      {status}
    </span>
  );
}

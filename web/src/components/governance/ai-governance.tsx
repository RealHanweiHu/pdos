"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  requestAiUsage,
  requestCapabilities,
  requestTouchpoints,
} from "@/components/ai/ai-api";
import type { AiCapability, AiTouchpoint, AiUsage } from "@/components/ai/ai-types";
import { requestProjects } from "@/components/projects/project-api";
import { SettingsNav } from "@/components/settings/settings-nav";
import { WorkspaceShell } from "@/components/workspace-shell";
import type { WorkspaceIdentity } from "@/components/workspace-types";
import { cn } from "@/lib/utils";
import { AiWritePolicy } from "./ai-write-policy";

type LoadState = "loading" | "ready" | "forbidden" | "error" | "redirecting";

const zoneLabels = { free: "自由区", confirm: "确认区", hard_gate: "硬闸区" } as const;
const stateLabels = { enabled: "可用", degraded: "降级", disabled: "失能" } as const;

export function AiGovernance() {
  const { replace } = useRouter();
  const [state, setState] = useState<LoadState>("loading");
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [usage, setUsage] = useState<AiUsage | null>(null);
  const [capabilities, setCapabilities] = useState<AiCapability[]>([]);
  const [touchpoints, setTouchpoints] = useState<AiTouchpoint[]>([]);
  const [loggingOut, setLoggingOut] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const loaded = await requestProjects();
        if (!active) return;
        if (loaded === null) {
          setState("redirecting");
          replace("/login");
          return;
        }
        setIdentity(loaded.identity);
        if (!["owner", "admin"].includes(loaded.identity.user.role)) {
          setState("forbidden");
          return;
        }
        const [nextUsage, nextCapabilities, nextTouchpoints] = await Promise.all([
          requestAiUsage(),
          requestCapabilities(),
          requestTouchpoints(),
        ]);
        if (!active) return;
        setUsage(nextUsage);
        setCapabilities(nextCapabilities);
        setTouchpoints(nextTouchpoints);
        setState("ready");
      } catch (loadError) {
        if (!active) return;
        setError(loadError instanceof Error ? loadError.message : "AI 治理数据暂不可用");
        setState("error");
      }
    })();
    return () => {
      active = false;
    };
  }, [replace]);

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
        正在加载 AI 治理看板…
      </main>
    );
  }
  if (state === "forbidden") {
    return (
      <main className="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center px-6 text-center">
        <h1 className="text-lg font-semibold">仅管理员可查看 AI 治理</h1>
      </main>
    );
  }
  if (state === "error" || identity === null) {
    return (
      <main className="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center px-6 text-center">
        <h1 className="text-lg font-semibold">AI 治理暂不可用</h1>
        <p className="mt-1 text-sm text-muted-foreground">{error ?? "无法读取治理数据。"}</p>
      </main>
    );
  }

  return (
    <WorkspaceShell active="settings" identity={identity} loggingOut={loggingOut} onLogout={() => void logout()}>
      <SettingsNav current="ai-governance" identity={identity}>
      <div className="border-b pb-4">
        <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">
          Admin Workspace
        </p>
        <h1 className="mt-1 text-lg font-semibold">AI 治理看板</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          租户级 AI 用量、能力合同与触点失能态；预算耗尽或模型不可用时每个触点给出人工替代路径。
        </p>
      </div>

      <AiWritePolicy />

      <section aria-label="用量与预算" className="mt-5 rounded-lg border bg-card p-4">
        <h2 className="text-sm font-semibold">用量与预算</h2>
        {usage ? (
          <>
            <dl className="mt-3 flex flex-wrap overflow-hidden rounded-lg border text-center">
              {[
                ["日预算 tokens", usage.daily_token_budget],
                ["今日已用", usage.used_tokens_today],
                ["今日剩余", usage.remaining_tokens_today],
              ].map(([label, value], index) => (
                <div className={cn("min-w-32 px-3 py-2", index > 0 && "border-l")} key={String(label)}>
                  <dt className="text-[10px] text-muted-foreground">{label}</dt>
                  <dd className="mt-0.5 font-mono text-base font-semibold">
                    {value === null ? "—" : Number(value).toLocaleString()}
                  </dd>
                </div>
              ))}
              <div className="min-w-32 border-l px-3 py-2">
                <dt className="text-[10px] text-muted-foreground">预算熔断</dt>
                <dd
                  className={cn(
                    "mt-0.5 font-mono text-base font-semibold",
                    usage.budget_exhausted ? "text-destructive" : "text-success",
                  )}
                >
                  {usage.budget_exhausted ? "已触发" : "未触发"}
                </dd>
              </div>
            </dl>
            {usage.rows.length > 0 ? (
              <div className="mt-3 overflow-x-auto">
                <table className="w-full min-w-[560px] text-left text-xs">
                  <thead>
                    <tr className="border-b text-muted-foreground">
                      <th className="py-1.5 pr-3 font-medium">Agent</th>
                      <th className="py-1.5 pr-3 font-medium">Prompt 版本</th>
                      <th className="py-1.5 pr-3 font-medium">调用</th>
                      <th className="py-1.5 pr-3 font-medium">成功</th>
                      <th className="py-1.5 font-medium">tokens</th>
                    </tr>
                  </thead>
                  <tbody>
                    {usage.rows.map((row) => (
                      <tr className="border-b last:border-b-0" key={`${row.agent_key}:${row.prompt_version}`}>
                        <td className="py-1.5 pr-3 font-medium">{row.agent_key}</td>
                        <td className="py-1.5 pr-3 font-mono">{row.prompt_version}</td>
                        <td className="py-1.5 pr-3 font-mono">{row.invocation_count}</td>
                        <td className="py-1.5 pr-3 font-mono">{row.succeeded_count}</td>
                        <td className="py-1.5 font-mono">{row.total_tokens.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="mt-3 text-xs text-muted-foreground">还没有模型调用记录。</p>
            )}
          </>
        ) : null}
      </section>

      <section aria-label="触点失能态" className="mt-5 rounded-lg border bg-card p-4">
        <h2 className="text-sm font-semibold">AI 触点失能态清单</h2>
        <ul className="mt-3 space-y-2" role="list">
          {touchpoints.map((touchpoint) => (
            <li className="flex flex-wrap items-start gap-3 rounded-lg border px-3 py-2" key={touchpoint.key}>
              <span
                className={cn(
                  "mt-0.5 rounded-full border px-2 py-0.5 text-[10px] font-semibold",
                  touchpoint.state === "enabled" && "border-success/30 bg-success/10 text-success",
                  touchpoint.state === "degraded" && "border-pending/30 bg-pending/10 text-pending",
                  touchpoint.state === "disabled" &&
                    "border-destructive/30 bg-destructive/10 text-destructive",
                )}
              >
                {stateLabels[touchpoint.state]}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">
                  {touchpoint.label}
                  {touchpoint.reason_code ? (
                    <span className="ml-2 font-mono text-[10px] text-muted-foreground">
                      {touchpoint.reason_code}
                    </span>
                  ) : null}
                </p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  人工替代：{touchpoint.manual_alternative}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section aria-label="能力合同" className="mt-5 rounded-lg border bg-card p-4">
        <h2 className="text-sm font-semibold">能力合同（capability_key）</h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-xs">
            <thead>
              <tr className="border-b text-muted-foreground">
                <th className="py-1.5 pr-3 font-medium">Capability</th>
                <th className="py-1.5 pr-3 font-medium">授权区</th>
                <th className="py-1.5 pr-3 font-medium">灰度</th>
                <th className="py-1.5 pr-3 font-medium">Prompt 版本</th>
                <th className="py-1.5 font-medium">质量控制</th>
              </tr>
            </thead>
            <tbody>
              {capabilities.map((capability) => {
                const narrowed = capability.controls.some((control) => control.status === "narrowed");
                return (
                  <tr className="border-b last:border-b-0" key={capability.capability_key}>
                    <td className="py-1.5 pr-3 font-mono">{capability.capability_key}</td>
                    <td className="py-1.5 pr-3">{capability.write_tier ? `${capability.write_tier.toUpperCase()} · ${capability.write_tier === "t0" ? "可撤回写入" : capability.write_tier === "t1" ? "预填确认" : "人工裁决"}` : zoneLabels[capability.zone]}</td>
                    <td className="py-1.5 pr-3">
                      <span
                        className={cn(
                          "rounded-full border px-2 py-0.5 text-[10px] font-semibold",
                          capability.rollout === "live"
                            ? "border-success/30 bg-success/10 text-success"
                            : "border-pending/30 bg-pending/10 text-pending",
                        )}
                      >
                        {capability.rollout === "live" ? "已上线" : "Shadow"}
                      </span>
                    </td>
                    <td className="py-1.5 pr-3 font-mono">{capability.prompt_version}</td>
                    <td className="py-1.5">
                      {narrowed ? (
                        <span className="text-destructive">已熔断（narrowed）</span>
                      ) : (
                        capability.quality_control
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
      </SettingsNav>
    </WorkspaceShell>
  );
}

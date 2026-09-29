import { CheckCircleIcon, ShieldCheckIcon, WarningCircleIcon } from "@phosphor-icons/react/ssr";
import { type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { SettingsNav } from "@/components/settings/settings-nav";
import { WorkspaceShell } from "@/components/workspace-shell";
import type { WorkspaceIdentity } from "@/components/workspace-types";

import type {
  EligibleModel,
  ModelGovernanceSnapshot,
  ModelGovernanceUpdate,
} from "./model-governance-types";

const PROVIDER_LABELS: Record<EligibleModel["provider"], string> = {
  minimax: "MiniMax",
  deepseek: "DeepSeek",
  glm: "GLM",
  openai: "OpenAI",
  anthropic: "Anthropic",
  openrouter: "OpenRouter",
  opencode_go: "OpenCode Go",
};

const MODEL_KEY_SEPARATOR = "::";

function modelKey(model: Pick<EligibleModel, "provider" | "model">) {
  return `${model.provider}${MODEL_KEY_SEPARATOR}${model.model}`;
}

function parseModelKey(value: string, models: EligibleModel[]) {
  return models.find((model) => modelKey(model) === value) ?? null;
}

function formatCount(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
}

function BudgetMeter({ snapshot }: { snapshot: ModelGovernanceSnapshot }) {
  const budget = snapshot.budget;
  const usedRatio = Math.min(100, Math.round((budget.used_tokens_today / budget.daily_token_budget) * 100));
  return (
    <section className="rounded-lg border bg-card p-5" aria-labelledby="budget-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium text-muted-foreground">今日剩余</p>
          <p className="mt-1 font-mono text-2xl font-semibold tracking-tight">
            {formatCount(budget.remaining_tokens_today)}
          </p>
        </div>
        <span
          className={
            budget.exhausted
              ? "rounded-full bg-destructive/10 px-2.5 py-1 text-xs font-medium text-destructive"
              : "rounded-full bg-accent px-2.5 py-1 text-xs font-medium text-accent-foreground"
          }
        >
          {budget.exhausted ? "预算已耗尽" : "预算正常"}
        </span>
      </div>
      <h2 className="sr-only" id="budget-title">今日 Token 用量</h2>
      <div
        aria-label="今日 Token 用量"
        aria-valuemax={budget.daily_token_budget}
        aria-valuemin={0}
        aria-valuenow={Math.min(budget.used_tokens_today, budget.daily_token_budget)}
        className="mt-5 h-2 overflow-hidden rounded-full bg-muted"
        role="progressbar"
      >
        <div className="h-full rounded-full bg-primary" style={{ width: `${usedRatio}%` }} />
      </div>
      <div className="mt-2 flex justify-between gap-4 text-xs text-muted-foreground">
        <span>已用 {formatCount(budget.used_tokens_today)}</span>
        <span>上限 {formatCount(budget.daily_token_budget)}</span>
      </div>
    </section>
  );
}

export function ModelGovernanceView({
  identity,
  loggingOut,
  onLogout,
  onSave,
  saveError,
  saved,
  saving,
  snapshot,
}: {
  identity: WorkspaceIdentity;
  loggingOut: boolean;
  onLogout: () => void;
  onSave: (update: ModelGovernanceUpdate) => void;
  saveError: string | null;
  saved: boolean;
  saving: boolean;
  snapshot: ModelGovernanceSnapshot;
}) {
  const selected = snapshot.selection?.available
    ? modelKey(snapshot.selection)
    : snapshot.eligible_models[0]
      ? modelKey(snapshot.eligible_models[0])
      : "";

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const model = parseModelKey(String(form.get("model") ?? ""), snapshot.eligible_models);
    const budget = Number(form.get("daily_token_budget"));
    if (!model || !Number.isSafeInteger(budget) || budget < 1 || budget > 1_000_000_000) return;
    onSave({ provider: model.provider, model: model.model, daily_token_budget: budget });
  }

  return (
    <WorkspaceShell
      active="settings"
      identity={identity}
      loggingOut={loggingOut}
      onLogout={onLogout}
    >
      <SettingsNav current="model-governance" identity={identity}>
      <div className="border-b pb-4">
        <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">
          Governance
        </p>
        <h1 className="mt-1 text-lg font-semibold">模型与预算</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          为当前租户选择已通过资格门禁的模型，并设置每日 Token 上限。
        </p>
      </div>

      <div className="mt-5 grid items-start gap-5 lg:grid-cols-[minmax(0,1.45fr)_minmax(280px,0.75fr)]">
        <form className="rounded-lg border bg-card p-5" onSubmit={submit}>
          <div className="flex items-start gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <ShieldCheckIcon aria-hidden="true" className="size-5" />
            </span>
            <div>
              <h2 className="font-medium">发布设置</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                候选池同时满足运行凭据配置和 golden-case 评测。
              </p>
            </div>
          </div>

          {snapshot.eligible_models.length === 0 ? (
            <div className="mt-5 rounded-lg border border-dashed p-5 text-center">
              <WarningCircleIcon aria-hidden="true" className="mx-auto size-7 text-muted-foreground" />
              <p className="mt-2 font-medium">当前没有可发布模型</p>
              <p className="mt-1 text-xs text-muted-foreground">
                配置运行凭据并通过 golden-case 后，模型才会出现在这里。
              </p>
            </div>
          ) : (
            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <label className="grid gap-1.5 text-xs font-medium">
                模型
                <select
                  className="h-11 w-full rounded-lg border bg-background px-3 text-sm"
                  defaultValue={selected}
                  key={selected}
                  name="model"
                >
                  {snapshot.eligible_models.map((model) => (
                    <option key={modelKey(model)} value={modelKey(model)}>
                      {PROVIDER_LABELS[model.provider]} · {model.model}
                    </option>
                  ))}
                </select>
              </label>
              <label className="grid gap-1.5 text-xs font-medium">
                每日 Token 预算
                <input
                  className="h-11 w-full rounded-lg border bg-background px-3 font-mono text-sm"
                  defaultValue={snapshot.budget.daily_token_budget}
                  inputMode="numeric"
                  max={1_000_000_000}
                  min={1}
                  name="daily_token_budget"
                  required
                  type="number"
                />
              </label>
            </div>
          )}

          <p className="mt-4 text-xs text-muted-foreground">
            连接凭据由服务端运行环境保管，不会进入浏览器或租户设置记录。
          </p>
          {saveError ? (
            <p className="mt-4 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
              {saveError}
            </p>
          ) : null}
          {saved ? (
            <p className="mt-4 flex items-center gap-2 text-sm text-emerald-700 dark:text-emerald-400" role="status">
              <CheckCircleIcon aria-hidden="true" />
              模型与预算已保存
            </p>
          ) : null}
          <div className="mt-5 flex justify-end">
            <Button
              className="h-11"
              disabled={saving || snapshot.eligible_models.length === 0}
              type="submit"
            >
              {saving ? "正在保存…" : "保存模型设置"}
            </Button>
          </div>
        </form>

        <BudgetMeter snapshot={snapshot} />
      </div>
      </SettingsNav>
    </WorkspaceShell>
  );
}

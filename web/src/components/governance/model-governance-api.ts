import { isRecord, requestIdentity, responseBody } from "@/components/workspace-api";
import type { WorkspaceIdentity } from "@/components/workspace-types";

import { MODEL_PROVIDERS } from "./model-governance-types";
import type {
  EligibleModel,
  ModelBudget,
  ModelGovernanceSnapshot,
  ModelGovernanceUpdate,
  ModelProvider,
  ModelSelection,
} from "./model-governance-types";

const ADMIN_ROLES = new Set(["owner", "admin"]);

function isProvider(value: unknown): value is ModelProvider {
  return typeof value === "string" && MODEL_PROVIDERS.includes(value as ModelProvider);
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function parseEligibleModel(value: unknown): EligibleModel {
  if (
    !isRecord(value) ||
    !isProvider(value.provider) ||
    typeof value.model !== "string" ||
    value.model.length === 0 ||
    (value.protocol !== "openai-compatible" && value.protocol !== "anthropic-native")
  ) {
    throw new Error("invalid eligible model");
  }
  return {
    provider: value.provider,
    model: value.model,
    protocol: value.protocol,
  };
}

function parseSelection(value: unknown): ModelSelection | null {
  if (value === null) return null;
  if (
    !isRecord(value) ||
    !isProvider(value.provider) ||
    typeof value.model !== "string" ||
    value.model.length === 0 ||
    typeof value.available !== "boolean"
  ) {
    throw new Error("invalid model selection");
  }
  return { provider: value.provider, model: value.model, available: value.available };
}

function parseBudget(value: unknown): ModelBudget {
  if (
    !isRecord(value) ||
    !isNonNegativeInteger(value.daily_token_budget) ||
    value.daily_token_budget < 1 ||
    !isNonNegativeInteger(value.used_tokens_today) ||
    !isNonNegativeInteger(value.remaining_tokens_today) ||
    typeof value.exhausted !== "boolean"
  ) {
    throw new Error("invalid model budget");
  }
  return {
    daily_token_budget: value.daily_token_budget,
    used_tokens_today: value.used_tokens_today,
    remaining_tokens_today: value.remaining_tokens_today,
    exhausted: value.exhausted,
  };
}

function parseSnapshot(value: unknown): ModelGovernanceSnapshot {
  if (!isRecord(value) || !Array.isArray(value.eligible_models) || !("selection" in value)) {
    throw new Error("invalid model governance response");
  }
  return {
    eligible_models: value.eligible_models.map(parseEligibleModel),
    selection: parseSelection(value.selection),
    budget: parseBudget(value.budget),
  };
}

async function governanceResponse(response: Response): Promise<ModelGovernanceSnapshot | null> {
  if (response.status === 401) return null;
  if (!response.ok) throw new Error("model governance unavailable");
  return parseSnapshot(await responseBody(response));
}

export type ModelGovernanceBootstrap =
  | { kind: "forbidden"; identity: WorkspaceIdentity }
  | { kind: "ready"; identity: WorkspaceIdentity; snapshot: ModelGovernanceSnapshot };

export async function requestModelGovernanceBootstrap(): Promise<ModelGovernanceBootstrap | null> {
  const identity = await requestIdentity();
  if (identity === null) return null;
  if (!ADMIN_ROLES.has(identity.user.role)) return { kind: "forbidden", identity };
  const snapshot = await governanceResponse(
    await fetch("/api/ai/governance/model", {
      cache: "no-store",
      credentials: "same-origin",
    }),
  );
  return snapshot === null ? null : { kind: "ready", identity, snapshot };
}

export async function updateModelGovernance(
  update: ModelGovernanceUpdate,
): Promise<ModelGovernanceSnapshot | null> {
  return governanceResponse(
    await fetch("/api/ai/governance/model", {
      method: "PATCH",
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update),
    }),
  );
}

export const MODEL_PROVIDERS = ["minimax", "deepseek", "glm", "openai", "anthropic"] as const;

export type ModelProvider = (typeof MODEL_PROVIDERS)[number];
export type ModelProtocol = "openai-compatible" | "anthropic-native";

export type EligibleModel = {
  provider: ModelProvider;
  model: string;
  protocol: ModelProtocol;
};

export type ModelSelection = {
  provider: ModelProvider;
  model: string;
  available: boolean;
};

export type ModelBudget = {
  daily_token_budget: number;
  used_tokens_today: number;
  remaining_tokens_today: number;
  exhausted: boolean;
};

export type ModelGovernanceSnapshot = {
  eligible_models: EligibleModel[];
  selection: ModelSelection | null;
  budget: ModelBudget;
};

export type ModelGovernanceUpdate = {
  provider: ModelProvider;
  model: string;
  daily_token_budget: number;
};

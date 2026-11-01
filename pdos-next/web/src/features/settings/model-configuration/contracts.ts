export type ProtocolKind = "openai-compatible" | "anthropic-native";
export interface ModelMetadata {
  protocol: ProtocolKind;
  base_url: string;
  model: string;
  model_version: string;
  max_output_tokens: number;
  context_window_tokens?: number | null;
  openai_output_parameter: "max_tokens" | "max_completion_tokens";
  openai_response_mode?: "auto" | "tools" | "json_schema" | "json_object" | "text";
  streaming?: boolean;
  connection_id?: string | null;
  timeout_seconds: number;
  response_bytes: number;
}
export interface ModelConnection {
  id: string | null;
  name: string;
  metadata: ModelMetadata;
  provider: string;
  credential_display: string;
  pricing_configured: boolean;
}
export interface SaveConfiguration {
  expected_revision: number;
  metadata: ModelMetadata;
  enabled: boolean;
}
export interface ConfigurationReading {
  revision: number;
  version_id: string;
  provider_version: string;
  metadata: ModelMetadata;
  enabled: boolean;
  credential_status: "bound" | "missing" | "changed" | "unavailable";
  credential_display: "已绑定 ••••" | "未绑定" | "需重新绑定" | "暂不可核对";
  created_at: string;
  requires_requalification: true;
}
export type ReadinessCode =
  | "MODEL_RUNTIME_PORTS_MISSING" | "MODEL_UNAVAILABLE"
  | "MODEL_NOT_CONFIGURED" | "MODEL_DISABLED" | "MODEL_SECRET_MISSING"
  | "MODEL_SECRET_CHANGED" | "MODEL_SECRET_UNAVAILABLE" | "MODEL_SECRET_INVALID"
  | "MODEL_CONFIGURATION_CHANGED" | "MODEL_PERMISSION_DENIED"
  | "MODEL_QUALIFICATION_REQUIRED" | "MODEL_EGRESS_REQUIRED"
  | "MODEL_BUDGET_REQUIRED" | "MODEL_CANCELLED" | "MODEL_POLICY_EXPIRED"
  | "MODEL_AUTHORIZER_CHECK_REQUIRED";
export interface ReadinessReading {
  state: "unavailable" | "authorizer_check";
  code: ReadinessCode | string;
}
export interface ModelConfigurationProps {
  reading: ConfigurationReading | null;
  canEdit: boolean;
  readiness: ReadinessReading | null;
  // Parent uses the existing controlled-command preview/confirmation/receipt shell.
  // This component neither confirms nor saves, and never consumes a confirmation token.
  onPreview?: (request: SaveConfiguration) => Promise<void>;
  pending?: boolean;
}

export function readinessText(reading: ReadinessReading | null): string {
  if (!reading) return "当前调用检查接口待接入";
  if (reading.code === "MODEL_AUTHORIZER_CHECK_REQUIRED" && reading.state === "authorizer_check") {
    return "基础条件已核对，仍须取得本次材料和调用授权";
  }
  const text: Record<string, string> = {
    RUN_CHECK_REQUIRED: "每次调用前会核对当前配置、授权、资格和预算。",
    MODEL_RUNTIME_PORTS_MISSING: "模型配置与当前授权尚未就绪，仍可手动办理",
    MODEL_UNAVAILABLE: "当前模型不可用",
    MODEL_NOT_CONFIGURED: "尚未配置模型", MODEL_DISABLED: "模型已停用",
    MODEL_SECRET_MISSING: "模型密钥尚未绑定或不可用", MODEL_SECRET_CHANGED: "密钥已变化，需重新绑定并核对资格",
    MODEL_SECRET_UNAVAILABLE: "暂无法核对密钥", MODEL_SECRET_INVALID: "服务端密钥不符合要求",
    MODEL_CONFIGURATION_CHANGED: "配置已变化，需重新选择", MODEL_PERMISSION_DENIED: "当前运行没有模型使用权限",
    MODEL_QUALIFICATION_REQUIRED: "当前用途和版本缺少真实资格", MODEL_EGRESS_REQUIRED: "本次材料缺少出站授权",
    MODEL_BUDGET_REQUIRED: "当前运行缺少可用预算", MODEL_CANCELLED: "当前运行已取消",
    MODEL_POLICY_EXPIRED: "本次调用条件已过期，需重新核对",
  };
  return text[reading.code] ?? "当前调用条件或接口尚不齐全";
}

export function validateRequest(request: SaveConfiguration): string | null {
  const m = request.metadata;
  if (!Number.isInteger(request.expected_revision) || request.expected_revision < 0) return "配置版本无效，请刷新。";
  if (!m.model.trim() || !m.model_version.trim() || !m.base_url.trim()) return "请填写端点、模型和模型版本。";
  if (!Number.isInteger(m.max_output_tokens) || m.max_output_tokens < 1 || m.max_output_tokens > 32768) return "输出上限须为 1–32768 的整数。";
  if (m.context_window_tokens != null && (!Number.isInteger(m.context_window_tokens) || m.context_window_tokens < 1024 || m.context_window_tokens > 10000000)) return "上下文窗口须为 1024–10,000,000 的整数，或留空。";
  if (!Number.isFinite(m.timeout_seconds) || m.timeout_seconds < 1 || m.timeout_seconds > 90) return "超时须在 1–90 秒内。";
  if (!Number.isInteger(m.response_bytes) || m.response_bytes < 1024 || m.response_bytes > 2097152) return "响应上限须在 1024–2097152 字节内。";
  return null; // Endpoint policy, tenant, permissions and eligibility are checked on server.
}

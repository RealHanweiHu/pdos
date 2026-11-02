import { canonical } from "./competitor-segments";
import {
  boundCandidateCommand,
  sameCandidateCommand,
  type DomainCommand,
  type DomainCandidate,
} from "./domain-candidate";

export function editableMaterial(
  candidate: DomainCandidate,
): MaterialKind | null {
  if (
    candidate.state === "adopted" &&
    candidate.receipt &&
    candidate.material_binding
  )
    return candidate.material_binding.kind;
  if (
    candidate.state !== "pending" ||
    !candidate.command ||
    candidate.command.product_id
  )
    return null;
  const { operation, payload } = candidate.command;
  if (operation === "category.parameter.publish") return "parameter";
  return operation === "category.knowledge.add" &&
    (payload.kind === "competitor" || payload.kind === "voice")
    ? payload.kind
    : null;
}

export type MaterialKind = "competitor" | "voice" | "parameter";
export type MaterialRef = {
  type: string;
  id: string;
  version: number;
  line?: number | null;
  quote?: string | null;
  statement?: string | null;
};
export type CategoryKnowledge = {
  id?: string;
  lineage_id?: string;
  version?: number;
  kind: string;
  content: Record<string, unknown> | null;
  origin: string;
  status: string;
  regions?: string[];
  source_refs?: MaterialRef[];
  direct_source_refs?: MaterialRef[];
  source_changes?: unknown[];
};
export type CategoryParameter = {
  parameter_id: string;
  version: number;
  key: string;
  name: string;
  unit: string | null;
  value_type: string;
  direction?: string;
  enum_values?: string[] | null;
  standard_condition?: string | null;
  method?: string | null;
  acceptance_criterion?: string | null;
  change_note?: string;
};
export type MaterialCommand = {
  command_id: string;
  idempotency_key: string;
  category_id: string;
  product_id: null;
  operation:
    | "category.knowledge.add"
    | "category.knowledge.withdraw"
    | "category.knowledge.promote"
    | "category.parameter.publish";
  expected_revision: number;
  source_read_set: unknown[];
  payload: Record<string, unknown>;
};
export type MaterialPreview = {
  command: MaterialCommand;
  expires_at: string | null;
  confirmation_token?: string | null;
  review: Record<string, unknown>;
};
export type MaterialReceipt = {
  id: string;
  category_id: string;
  operation: string;
  subject_type: string;
  subject_id: string;
  subject_revision: number;
  result: {
    entry_id?: string;
    lineage_id?: string;
    parameter_id?: string;
    version: number;
  };
};
export const materialRecord = (
  value: unknown,
): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);
const uuid = (value: unknown): value is string =>
  typeof value === "string" &&
  /^[a-f\d]{8}(?:-[a-f\d]{4}){3}-[a-f\d]{12}$/i.test(value);
export function materialReferences(refs: MaterialRef[] = []): MaterialRef[] {
  return refs.map(
    (ref) =>
      Object.fromEntries(
        Object.entries(ref).filter(([key]) =>
          ["type", "id", "version", "line", "quote", "statement"].includes(key),
        ),
      ) as MaterialRef,
  );
}
/** The read projection appends nested references. Remove that suffix before a
 * replacement, otherwise each edit would duplicate the same source locations. */
export function materialSources(item: CategoryKnowledge): MaterialRef[] {
  if (!item.content || item.source_changes?.length)
    throw new Error("原资料或来源需要重新核对，暂不能沿用保存。");
  const direct = materialReferences(
    item.direct_source_refs ?? item.source_refs,
  );
  const content = item.content;
  const nested =
    item.kind === "voice"
      ? materialReferences((content.representative_refs as MaterialRef[]) ?? [])
      : ["metrics", "features", "prices"].flatMap((key) =>
          ((content[key] as Record<string, unknown>[]) ?? []).flatMap((row) =>
            row.source_ref
              ? materialReferences([row.source_ref as MaterialRef])
              : [],
          ),
        );
  if (!nested.length || !direct.length) return direct;
  const normalize = (refs: MaterialRef[]) =>
    refs.map((ref) => ({ line: null, quote: null, statement: null, ...ref }));
  if (
    direct.length < nested.length ||
    canonical(normalize(direct.slice(-nested.length))) !==
      canonical(normalize(nested))
  )
    throw new Error("原资料的固定来源无法核对，请先刷新资料。");
  return direct.slice(0, -nested.length);
}
export function materialCommand(
  categoryId: string,
  categoryRevision: number,
  kind: MaterialKind,
  fields: Record<string, unknown>,
  original: CategoryKnowledge | CategoryParameter | null,
  statement: string,
  principalId: string,
): MaterialCommand {
  let payload: Record<string, unknown>;
  if (kind === "parameter") {
    const parameter = original as CategoryParameter | null;
    payload = {
      parameter_id: parameter?.parameter_id ?? null,
      expected_current_version: parameter?.version ?? 0,
      key: fields.key,
      name: fields.name,
      value_type: fields.value_type,
      enum_values:
        fields.value_type === "enum" ? (fields.enum_values ?? []) : null,
      unit: fields.unit || null,
      direction: fields.direction,
      standard_condition: fields.standard_condition || null,
      method: fields.method || null,
      acceptance_criterion: fields.acceptance_criterion || null,
      change_note: fields.change_note,
    };
    if (
      !String(fields.key ?? "").trim() ||
      !String(fields.name ?? "").trim() ||
      !String(fields.change_note ?? "").trim()
    )
      throw new Error("请填写参数键、名称与修订说明。");
  } else {
    const knowledge = original as CategoryKnowledge | null;
    const content = structuredClone(fields);
    delete content.sample_size;
    if (
      (kind === "competitor" &&
        (!String(content.brand ?? "").trim() ||
          !String(content.model ?? "").trim())) ||
      (kind === "voice" && !String(content.label ?? "").trim())
    )
      throw new Error("请填写资料名称与必要内容。");
    const source_refs = knowledge ? materialSources(knowledge) : [];
    if (statement.trim())
      source_refs.push({
        type: "human",
        id: principalId,
        version: 1,
        statement: statement.trim(),
      });
    payload = {
      kind,
      content,
      regions: knowledge?.regions ?? [],
      source_refs,
      supersedes: knowledge
        ? {
            lineage_id: knowledge.lineage_id,
            expected_version: knowledge.version,
          }
        : null,
    };
  }
  return {
    command_id: crypto.randomUUID(),
    idempotency_key: crypto.randomUUID(),
    category_id: categoryId,
    product_id: null,
    operation:
      kind === "parameter"
        ? "category.parameter.publish"
        : "category.knowledge.add",
    expected_revision: original?.version ?? categoryRevision,
    source_read_set: [],
    payload,
  };
}
export function materialWithdraw(
  categoryId: string,
  item: CategoryKnowledge,
  reason: string,
): MaterialCommand {
  if (!item.lineage_id || !item.version || !reason.trim())
    throw new Error("请填写撤回理由。");
  return {
    command_id: crypto.randomUUID(),
    idempotency_key: crypto.randomUUID(),
    category_id: categoryId,
    product_id: null,
    operation: "category.knowledge.withdraw",
    expected_revision: item.version,
    source_read_set: [],
    payload: {
      lineage_id: item.lineage_id,
      expected_version: item.version,
      reason: reason.trim(),
    },
  };
}
export function validMaterialPreview(
  value: unknown,
  original: MaterialCommand,
): value is MaterialPreview {
  if (
    !materialRecord(value) ||
    !materialRecord(value.command) ||
    !materialRecord(value.command.payload) ||
    !materialRecord(value.review)
  )
    return false;
  const { confirmation_token, ...payload } = value.command.payload;
  const originalPayload = { ...original.payload };
  delete originalPayload.confirmation_token;
  return (
    canonical({ ...value.command, payload }) ===
      canonical({ ...original, payload: originalPayload }) &&
    value.review.operation === original.operation &&
    (original.operation === "category.knowledge.add" ||
      (typeof confirmation_token === "string" &&
        confirmation_token.length >= 20)) &&
    (confirmation_token == null ||
      value.confirmation_token === confirmation_token) &&
    (value.expires_at === null ||
      (typeof value.expires_at === "string" &&
        Date.parse(value.expires_at) > Date.now()))
  );
}
export function validMaterialReceipt(
  value: unknown,
  command: MaterialCommand,
): value is MaterialReceipt {
  if (
    !materialRecord(value) ||
    !uuid(value.id) ||
    value.category_id !== command.category_id ||
    value.operation !== command.operation ||
    !uuid(value.subject_id) ||
    !materialRecord(value.result)
  )
    return false;
  const parameter = command.operation === "category.parameter.publish",
    supersedes = command.payload.supersedes as {
      lineage_id: string;
      expected_version: number;
    } | null;
  const identity = parameter
    ? command.payload.parameter_id
    : command.operation === "category.knowledge.withdraw"
      ? command.payload.lineage_id
      : supersedes?.lineage_id;
  const version =
    Number(
      parameter
        ? command.payload.expected_current_version
        : command.operation === "category.knowledge.withdraw"
          ? command.payload.expected_version
          : (supersedes?.expected_version ?? 0),
    ) + 1;
  return (
    value.subject_type === (parameter ? "parameter" : "category_knowledge") &&
    (!identity || value.subject_id === identity) &&
    value.subject_revision === version &&
    value.result.version === version &&
    value.result[parameter ? "parameter_id" : "lineage_id"] ===
      value.subject_id &&
    (parameter || uuid(value.result.entry_id))
  );
}
export const materialJournalKey = (
  principal: string,
  category: string,
  target: string,
) => `pdos:category-material:v1:${principal}:${category}:${target}`;
export function clearMaterialJournals(principal: string, category: string) {
  try {
    const prefix = `pdos:category-material:v1:${principal}:${category}:`;
    for (let i = sessionStorage.length - 1; i >= 0; i--) {
      const key = sessionStorage.key(i);
      if (key?.startsWith(prefix)) sessionStorage.removeItem(key);
    }
  } catch { /* The inaccessible editor and contexts are cleared regardless. */ }
}
export function restoreMaterialCommand(
  raw: string,
  category: string,
  target: string,
  candidate?: DomainCommand,
): MaterialCommand {
  const value: unknown = JSON.parse(raw);
  if (
    !materialRecord(value) ||
    !uuid(value.command_id) ||
    !uuid(value.idempotency_key) ||
    value.category_id !== category ||
    value.product_id !== null ||
    ![
      "category.knowledge.add",
      "category.knowledge.withdraw",
      "category.parameter.publish",
    ].includes(String(value.operation)) ||
    !Number.isSafeInteger(value.expected_revision) ||
    Number(value.expected_revision) < 1 ||
    !Array.isArray(value.source_read_set) ||
    (!candidate && value.source_read_set.length > 0) ||
    !materialRecord(value.payload)
  )
    throw new Error("原保存请求不完整，请保留记录并核对。");
  const p = value.payload,
    supersedes = materialRecord(p.supersedes) ? p.supersedes : null;
  const identity =
    value.operation === "category.parameter.publish"
      ? (p.parameter_id ?? "new:parameter")
      : value.operation === "category.knowledge.withdraw"
        ? p.lineage_id
        : (supersedes?.lineage_id ?? `new:${p.kind}`);
  if (
    identity !== target ||
    (!candidate && (p.prepared_by_run_id || p.candidate_digest)) ||
    (candidate &&
      !sameMaterialCandidate(value as unknown as DomainCommand, candidate)) ||
    (value.operation !== "category.knowledge.add" &&
      (typeof p.confirmation_token !== "string" ||
        p.confirmation_token.length < 20))
  )
    throw new Error("原请求与当前资料不一致，已停止保存。");
  return value as MaterialCommand;
}

export function sameMaterialCandidate(
  command: DomainCommand,
  original: DomainCommand,
) {
  const { human_edits: edits, ...payload } = command.payload;
  return (
    boundCandidateCommand(
      command,
      original.category_id,
      String(original.payload.prepared_by_run_id),
    ) &&
    materialRecord(edits) &&
    sameCandidateCommand(
      {
        ...command,
        command_id: original.command_id,
        idempotency_key: original.idempotency_key,
        payload,
      },
      original,
    )
  );
}

/** Keep the model payload sealed. The server validates and records human edits separately. */
export function materialCandidateCommand(
  original: DomainCommand,
  kind: MaterialKind,
  fields: Record<string, unknown>,
): MaterialCommand {
  const content = structuredClone(fields);
  delete content.sample_size;
  const edits =
    kind === "parameter"
      ? Object.fromEntries(
          [
            "name",
            "value_type",
            "enum_values",
            "unit",
            "direction",
            "standard_condition",
            "method",
            "acceptance_criterion",
            "change_note",
            ...(!original.payload.parameter_id ? ["key"] : []),
          ].map((key) => [
            key,
            key === "enum_values" && fields.value_type !== "enum"
              ? null
              : (fields[key] ?? null),
          ]),
        )
      : { content };
  return {
    ...original,
    command_id: crypto.randomUUID(),
    idempotency_key: crypto.randomUUID(),
    payload: { ...original.payload, human_edits: edits },
  } as MaterialCommand;
}
export async function materialPages<T>(
  api: <T>(path: string) => Promise<T>,
  root: string,
): Promise<T[]> {
  const result: T[] = [],
    seen = new Set<string>();
  let cursor: string | null = null;
  do {
    const page: { items: T[]; next_cursor?: string | null } = await api(
      `${root}${root.includes("?") ? "&" : "?"}page_size=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
    );
    result.push(...page.items);
    cursor = page.next_cursor ?? null;
    if (cursor && seen.has(cursor)) throw new Error("资料分页未推进，请重试。");
    if (cursor) seen.add(cursor);
  } while (cursor);
  return result;
}

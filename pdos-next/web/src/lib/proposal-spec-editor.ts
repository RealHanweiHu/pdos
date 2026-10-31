export type ProposalEditableItem = {
  item_id: string;
  version: number;
  kind: string;
  content: Record<string, unknown>;
  source_refs: unknown[];
  origin: string;
};
export type DictionaryParameter = {
  parameter_id: string;
  version: number;
  key: string;
  name: string;
  value_type: "number" | "range" | "text" | "boolean" | "enum";
  unit: string | null;
  standard_condition?: string | null;
  method?: string | null;
  acceptance_criterion?: string | null;
};
export type ProposalPatch = {
  op: "upsert" | "remove";
  item_id?: string;
  base_version?: number;
  kind: string;
  content: Record<string, unknown>;
  source_refs: unknown[];
};

/** Selected dictionary versions are retained exactly; existing references never migrate implicitly. */
export function newSpecPatches(
  parameters: DictionaryParameter[],
  items: ProposalEditableItem[],
): ProposalPatch[] {
  const used = new Set(
    items
      .filter((item) => item.kind === "spec")
      .map((item) => item.content.parameter_id),
  );
  const patches: ProposalPatch[] = [];
  for (const parameter of parameters) {
    if (used.has(parameter.parameter_id)) continue;
    used.add(parameter.parameter_id);
    patches.push({
      op: "upsert",
      kind: "spec",
      source_refs: [],
      content: {
        key: parameter.key,
        parameter: parameter.name,
        parameter_id: parameter.parameter_id,
        parameter_version: parameter.version,
        value_type: parameter.value_type,
        unit: parameter.unit,
        condition_note: parameter.standard_condition ?? null,
        verification_method: parameter.method ?? null,
        acceptance_criterion: parameter.acceptance_criterion ?? null,
        value: null,
        lower: null,
        upper: null,
        text_value: null,
        availability: "unknown",
        item_status: "unknown",
      },
    });
  }
  return patches;
}

export function editedSpecContent(
  content: Record<string, unknown>,
  first: string,
  second: string,
  condition: string,
): Record<string, unknown> {
  const type = content.value_type;
  const bounds = specUsesBounds(content);
  const initialFirst = String(
    content.value ?? content.lower ?? content.text_value ?? "",
  );
  const initialSecond = String(content.upper ?? "");
  // Editing a condition must not change unknown/not-applicable or the exact numeric shape.
  if (first === initialFirst && second === initialSecond)
    return { ...content, condition_note: condition.trim() || null };
  const known = bounds
    ? Boolean(first.trim() || second.trim())
    : Boolean(first.trim());
  return {
    ...content,
    value: type === "number" && !bounds && known ? first.trim() : null,
    lower: bounds && first.trim() ? first.trim() : null,
    upper: bounds && second.trim() ? second.trim() : null,
    text_value:
      !["number", "range"].includes(String(type)) && known
        ? first.trim()
        : null,
    condition_note: condition.trim() || null,
    availability: known ? "known" : "unknown",
    item_status:
      !known && content.item_status === "confirmed"
        ? "unknown"
        : content.item_status,
  };
}

export type ProposalRowDraft = {
  item: ProposalEditableItem;
  values: Record<string, string>;
};
export type ProposalDrafts = {
  drafts?: Record<string, ProposalRowDraft>;
  onDraft?: (id: string, draft: ProposalRowDraft | null) => void;
};
export function specUsesBounds(content: Record<string, unknown>) {
  return (
    content.value_type === "range" ||
    (content.value_type === "number" &&
      (content.lower != null || content.upper != null))
  );
}

/** One atomic patch for ordinary draft edits. Responsibility changes use their T1 command. */
export function proposalDraftPatches(
  drafts: Record<string, ProposalRowDraft>,
  current: ProposalEditableItem[],
): ProposalPatch[] {
  return Object.entries(drafts).flatMap(([id, entry]) => {
    const item = entry.item,
      values = entry.values;
    if (!Object.keys(values).length) return [];
    if (current.find((row) => row.item_id === id)?.version !== item.version)
      throw new Error("部分条目已更新，草稿已保留，请核对后再保存。");
    let content: Record<string, unknown>;
    if (item.kind === "spec")
      content = editedSpecContent(
        item.content,
        values.first ??
          String(
            item.content.value ??
              item.content.lower ??
              item.content.text_value ??
              "",
          ),
        values.second ?? String(item.content.upper ?? ""),
        values.condition ?? String(item.content.condition_note ?? ""),
      );
    else if (item.kind === "section")
      content = { ...item.content, text: values.text ?? item.content.text };
    else content = { ...item.content, ...values };
    if (
      item.kind === "question" &&
      ["question", "owner_id", "due_date"].some(
        (key) => content[key] !== item.content[key],
      )
    )
      throw new Error(
        "问题的内容、负责人或期限有变化，请先点击该行保存并确认责任安排。",
      );
    return [
      {
        op: "upsert",
        item_id: id,
        base_version: item.version,
        kind: item.kind,
        content,
        source_refs: item.source_refs,
      },
    ];
  });
}

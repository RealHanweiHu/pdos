import type { DomainCommand } from "./domain-candidate";
import {
  editedSpecContent,
  type ProposalEditableItem,
  type ProposalPatch,
  type ProposalRowDraft,
} from "./proposal-spec-editor";

export type CandidateRow = ProposalEditableItem & {
  original?: Record<string, unknown>;
  questionGroup?: boolean;
};
/** Local row identities never become new domain item identities. */
export function candidateRows(command: DomainCommand): CandidateRow[] {
  const groups = command.payload.groups as
    | {
        items?: Record<string, unknown>[];
        questions?: Record<string, unknown>[];
      }
    | undefined;
  const values: {
    original: Record<string, unknown>;
    questionGroup: boolean;
  }[] =
    command.operation === "proposal.create"
      ? [
          ...(groups?.items ?? []).map((original) => ({
            original,
            questionGroup: false,
          })),
          ...(groups?.questions ?? []).map((content) => ({
            original: { kind: "question", content },
            questionGroup: true,
          })),
        ]
      : ((command.payload.ops ?? []) as Record<string, unknown>[])
          .filter((row) => row.op !== "remove")
          .map((original) => ({ original, questionGroup: false }));
  return values.map(({ original, questionGroup }, index) => ({
    item_id: String(original.item_id ?? `local-${index}`),
    version: Number(original.base_version ?? 1),
    kind: String(original.kind),
    content: structuredClone(original.content as Record<string, unknown>),
    source_refs: structuredClone((original.source_refs as unknown[]) ?? []),
    origin: "ai_draft",
    original,
    questionGroup,
  }));
}
export function reviseCandidateRows(
  rows: CandidateRow[],
  patches: ProposalPatch[],
): CandidateRow[] {
  let next = [...rows];
  for (const patch of patches) {
    const existing = next.find((row) => row.item_id === patch.item_id);
    if (patch.item_id && (!existing || existing.version !== patch.base_version))
      throw new Error("条目已变化，请重新核对。");
    if (patch.op === "remove") next = next.filter((row) => row !== existing);
    else if (existing)
      next = next.map((row) =>
        row === existing
          ? { ...row, content: patch.content, source_refs: patch.source_refs }
          : row,
      );
    else
      next.push({
        item_id: `local-${crypto.randomUUID()}`,
        version: 1,
        kind: patch.kind,
        content: patch.content,
        source_refs: patch.source_refs,
        origin: "human",
      });
  }
  return next;
}
export function candidateHumanEdits(
  command: DomainCommand,
  rows: CandidateRow[],
  drafts: Record<string, ProposalRowDraft>,
  title: string,
  brief: string,
): Record<string, unknown> {
  const resolved = rows.map((row) => {
    const values = drafts[row.item_id]?.values;
    if (!values) return row;
    if (drafts[row.item_id].item.version !== row.version)
      throw new Error("条目已变化，请核对草稿。");
    return {
      ...row,
      content:
        row.kind === "spec"
          ? editedSpecContent(
              row.content,
              values.first ??
                String(
                  row.content.value ??
                    row.content.lower ??
                    row.content.text_value ??
                    "",
                ),
              values.second ?? String(row.content.upper ?? ""),
              values.condition ?? String(row.content.condition_note ?? ""),
            )
          : { ...row.content, ...values },
    };
  });
  const item = (row: CandidateRow) => ({
    ...row.original,
    kind: row.kind,
    content: row.content,
    source_refs: row.source_refs,
  });
  if (command.operation === "proposal.create") {
    if (!title.trim()) throw new Error("请填写提案名称。");
    return {
      title: title.trim(),
      brief,
      groups: {
        items: resolved.filter((row) => !row.questionGroup).map(item),
        questions: resolved
          .filter((row) => row.questionGroup)
          .map((row) => row.content),
      },
    };
  }
  const original = (command.payload.ops ?? []) as Record<string, unknown>[];
  const ids = new Set(resolved.map((row) => row.item_id));
  const removed = original
    .filter(
      (row) =>
        row.op === "remove" || (row.item_id && !ids.has(String(row.item_id))),
    )
    .map((row) => ({ ...row, op: "remove" }));
  return {
    ops: [
      ...resolved.map((row) => ({ ...item(row), op: "upsert" })),
      ...removed,
    ],
  };
}

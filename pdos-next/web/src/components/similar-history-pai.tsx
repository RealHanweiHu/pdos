"use client";

import { createContext } from "react";
import type { MaterialContext } from "./category-material-editor";
import type { SimilarHistoryCard, SimilarHistoryView } from "@/lib/similar-history";

export type SimilarHistorySelection = { anchor: SimilarHistoryView["anchor"]; candidate: SimilarHistoryCard };
export const SimilarHistoryPaiContext = createContext<((selection: SimilarHistorySelection) => void) | null>(null);
export function similarHistoryMaterial(selection: SimilarHistorySelection, requestId: string): MaterialContext {
  const { anchor, candidate } = selection;
  const change = anchor.kind === "change";
  const identity = change ? anchor.change_id : anchor.issue_id;
  return {
    kind: change ? "change_request" : "quality_issue", title: anchor.title, id: identity, version: anchor.revision,
    request: { id: requestId, prompt: `请用案例表比较“${anchor.title}”（v${anchor.revision}）和“${candidate.title}”（v${candidate.source_revision}），列出相同点、差异、可参考措施和还缺少的信息。` },
    draft: {
      selection_kind: "unverified_object_metadata", current: { kind: change ? "change" : "issue", object_id: identity, version_id: anchor.version_id, revision: anchor.revision },
      candidate: { kind: candidate.kind, object_id: candidate.object_id, version_id: candidate.source_id, revision: candidate.source_revision },
    },
  };
}

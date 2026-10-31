"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CategoryMaterialEditor,
  type MaterialContext,
} from "@/components/category-material-editor";
import { Button } from "@/components/ui/button";
import { PaiMobileWorkspaceSwitch } from "@/components/pai-conversation";
import { browserApi } from "@/lib/browser-api";
import {
  editableMaterial,
  materialJournalKey,
  materialPages,
  type CategoryKnowledge,
  type CategoryParameter,
} from "@/lib/category-materials";
import type { DomainCandidate } from "@/lib/domain-candidate";

/** Kept mounted when folded and across continuation runs, preserving unsaved edits. */
export function PaiMaterialWorkspace({
  candidate,
  categoryId,
  principalId,
  open,
  onClose,
  onMobileChat,
  onContextChange,
  onSaved,
  onUnavailable,
}: {
  candidate: DomainCandidate;
  categoryId: string;
  principalId: string;
  open: boolean;
  onClose: () => void;
  onMobileChat?: () => void;
  onContextChange: (id: string, context: MaterialContext | undefined) => void;
  onSaved: () => void;
  onUnavailable: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [data, setData] = useState<{
    item: CategoryKnowledge | CategoryParameter | null;
    parameters: CategoryParameter[];
  } | null>(null);
  const [error, setError] = useState("");
  const command = candidate.command,
    kind = editableMaterial(candidate)!;
  const updateContext = useCallback(
    (context: MaterialContext | undefined) =>
      onContextChange(candidate.event_id, context),
    [candidate.event_id, onContextChange],
  );
  useEffect(() => {
    if (open) dialog.current?.show();
    else dialog.current?.close();
  }, [open]);
  useEffect(() => {
    let live = true;
    const root = `v1/categories/${categoryId}`;
    void (async () => {
      const parameters = await materialPages<CategoryParameter>(
        browserApi,
        `${root}/parameters`,
      );
      let item: CategoryKnowledge | CategoryParameter | null = null;
      const savedId =
        candidate.state === "adopted" ? candidate.receipt?.subject_id : null;
      if (kind === "parameter" && (savedId || command?.payload.parameter_id)) {
        item =
          parameters.find(
            (row) =>
              row.parameter_id === (savedId || command?.payload.parameter_id) &&
              (savedId ||
                row.version === command?.payload.expected_current_version),
          ) ?? null;
        if (!item) throw new Error("参数原版本已变化，请读取新版后继续完善。");
      } else if (
        kind !== "parameter" &&
        (savedId || command?.payload.supersedes)
      ) {
        const base = command?.payload.supersedes as
          | { lineage_id: string; expected_version: number }
          | undefined;
        const rows = [
          ...(await materialPages<CategoryKnowledge>(
            browserApi,
            `${root}/knowledge?kind=${kind}&status=active`,
          )),
          ...(await materialPages<CategoryKnowledge>(
            browserApi,
            `${root}/knowledge?kind=${kind}&status=withdrawn`,
          )),
        ];
        item =
          rows.find(
            (row) =>
              row.lineage_id === (savedId || base?.lineage_id) &&
              (savedId || row.version === base?.expected_version),
          ) ?? null;
        if (!item || !item.content || item.source_changes?.length)
          throw new Error("原资料或来源已变化，请重新读取后继续完善。");
      }
      if (!live) return;
      if (savedId && candidate.material_binding) {
        const binding = candidate.material_binding;
        // A server receipt plus the authoritative object read settles a lost response.
        sessionStorage.removeItem(
          materialJournalKey(
            principalId,
            categoryId,
            `${binding.target}:candidate:${binding.digest}`,
          ),
        );
      }
      setData({ item, parameters });
    })().catch((failure) => {
      if (live) {
        setData(null);
        setError(failure.message);
        updateContext(undefined);
        if ([401, 403].includes(failure.status)) onUnavailable();
      }
    });
    return () => {
      live = false;
    };
  }, [
    candidate,
    command,
    categoryId,
    principalId,
    kind,
    updateContext,
    onUnavailable,
  ]);
  return (
    <dialog
      ref={dialog}
      className="candidate-editor material-workspace"
      aria-label="品类资料编辑区"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <div className="candidate-editor-body">
        <PaiMobileWorkspaceSwitch view="chat" onClick={onMobileChat ?? onClose} />
        {data ? (
          <CategoryMaterialEditor
            candidate={command ?? undefined}
            categoryId={categoryId}
            kind={kind}
            item={data.item}
            parameters={data.parameters}
            api={browserApi}
            onClose={onClose}
            onSaved={onSaved}
            onOpenPai={updateContext}
            onContextChange={updateContext}
            onUnavailable={onUnavailable}
          />
        ) : (
          <>
            <Button variant="ghost" size="sm" onClick={onClose}>
              返回对话
            </Button>
            <p role={error ? "alert" : "status"}>
              {error || "正在读取当前品类资料…"}
            </p>
          </>
        )}
      </div>
    </dialog>
  );
}

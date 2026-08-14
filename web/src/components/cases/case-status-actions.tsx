import { Button } from "@/components/ui/button";

import { caseStatusLabels } from "./case-list";
import { CaseProjectForm, type CaseProjectResult, type CaseProjectValues } from "./case-project-form";
import type { DevelopmentCase } from "./case-types";

export function CaseStatusActions({
  busy,
  developmentCase,
  onCreateProject,
  onTransition,
}: {
  busy: boolean;
  developmentCase: DevelopmentCase;
  onCreateProject: (values: CaseProjectValues) => Promise<CaseProjectResult>;
  onTransition: (toStatus: DevelopmentCase["status"]) => void;
}) {
  if (developmentCase.status === "approved") {
    return (
      <CaseProjectForm busy={busy} developmentCase={developmentCase} onSubmit={onCreateProject} />
    );
  }
  if (developmentCase.status === "converted" || developmentCase.status === "rejected") {
    return (
      <p className="mt-4 rounded-lg border bg-muted/40 p-3 text-xs text-muted-foreground">
        {caseStatusLabels[developmentCase.status]}为终态，内容与状态均已锁定。
      </p>
    );
  }
  return (
    <div className="mt-4 flex flex-wrap justify-end gap-2 border-t pt-4">
      {developmentCase.status === "draft" ? (
        <Button className="h-11 sm:h-8" disabled={busy} onClick={() => onTransition("evaluating")}>
          进入评估
        </Button>
      ) : (
        <>
          <Button className="h-11 sm:h-8" disabled={busy} onClick={() => onTransition("rejected")} variant="outline">
            拒绝案例
          </Button>
          <Button className="h-11 sm:h-8" disabled={busy} onClick={() => onTransition("approved")}>
            批准评估
          </Button>
        </>
      )}
    </div>
  );
}

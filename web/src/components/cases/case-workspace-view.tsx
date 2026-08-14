import { WorkspaceShell } from "@/components/workspace-shell";
import type { WorkspaceIdentity } from "@/components/workspace-types";

import { CaseForm, type CaseFormValues, type CaseSubmissionResult } from "./case-form";
import { CaseList } from "./case-list";
import type { CaseProjectResult, CaseProjectValues } from "./case-project-form";
import { CaseStatusActions } from "./case-status-actions";
import type { DevelopmentCase } from "./case-types";

export function CaseWorkspaceView({
  canEdit,
  cases,
  errorMessage,
  identity,
  loggingOut,
  onCancelEdit,
  onCreateProject,
  onLogout,
  onSelect,
  onTransition,
  onUpdate,
  saving,
  selectedCase,
  statusMessage,
}: {
  canEdit: boolean;
  cases: DevelopmentCase[];
  errorMessage: string | null;
  identity: WorkspaceIdentity;
  loggingOut: boolean;
  onCancelEdit: () => void;
  onCreateProject: (developmentCase: DevelopmentCase, values: CaseProjectValues) => Promise<CaseProjectResult>;
  onLogout: () => void;
  onSelect: (developmentCase: DevelopmentCase) => void;
  onTransition: (developmentCase: DevelopmentCase, toStatus: DevelopmentCase["status"]) => void;
  onUpdate: (developmentCase: DevelopmentCase, values: CaseFormValues) => Promise<CaseSubmissionResult>;
  saving: boolean;
  selectedCase: DevelopmentCase | null;
  statusMessage: string | null;
}) {
  const terminal = selectedCase?.status === "converted" || selectedCase?.status === "rejected";
  return (
    <WorkspaceShell active="cases" identity={identity} loggingOut={loggingOut} onLogout={onLogout}>
      {statusMessage ? (
        <p className="mb-4 rounded-lg border border-success/30 bg-success/10 px-3 py-2 text-sm text-success" role="status">
          {statusMessage}
        </p>
      ) : null}
      {errorMessage ? (
        <p className="mb-4 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
          {errorMessage}
        </p>
      ) : null}
      <div className="border-b pb-4">
        <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">Discovery</p>
        <h1 className="mt-1 text-lg font-semibold">开发案例</h1>
        <p className="mt-1 text-sm text-muted-foreground">把已批准需求转成可评估、可决策、可立项的正式对象。</p>
      </div>
      <div className="mt-6 grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_384px]">
        <CaseList canEdit={canEdit} cases={cases} onSelect={onSelect} selectedId={selectedCase?.id ?? null} />
        {selectedCase && canEdit ? (
          <section aria-label="编辑开发案例" className="rounded-lg border bg-card p-4">
            {!terminal ? (
              <CaseForm
                busy={saving}
                developmentCase={selectedCase}
                key={selectedCase.id}
                onCancel={onCancelEdit}
                onSubmit={(values) => onUpdate(selectedCase, values)}
              />
            ) : (
              <div>
                <h2 className="font-semibold">{selectedCase.code}</h2>
                <p className="mt-1 text-sm text-muted-foreground">{selectedCase.title}</p>
              </div>
            )}
            <CaseStatusActions
              busy={saving}
              developmentCase={selectedCase}
              onCreateProject={(values) => onCreateProject(selectedCase, values)}
              onTransition={(toStatus) => onTransition(selectedCase, toStatus)}
            />
          </section>
        ) : null}
      </div>
    </WorkspaceShell>
  );
}

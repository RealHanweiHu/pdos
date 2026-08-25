import { PlusIcon } from "@phosphor-icons/react";

import { Button } from "@/components/ui/button";
import { WorkspaceShell } from "@/components/workspace-shell";
import type { WorkspaceIdentity } from "@/components/workspace-types";

import {
  RequirementConversionForm,
  type RequirementConversionResult,
  type RequirementConversionValues,
} from "./requirement-conversion-form";
import {
  RequirementForm,
  type RequirementFormValues,
  type RequirementSubmissionResult,
} from "./requirement-form";
import { CustomerForm } from "./customer-form";
import type { CustomerCreateInput } from "./requirement-api";
import { CrmIntakeReview, type CrmReviewResult } from "./crm-intake-review";
import { RequirementList } from "./requirement-list";
import type { CustomerSummary, Requirement } from "./requirement-types";

export function RequirementPoolView({
  canEdit,
  creatingCustomer,
  creating,
  customerBusy,
  customerError,
  customers,
  convertingRequirement,
  editingRequirement,
  identity,
  loggingOut,
  onCancelCreate,
  onCancelCustomer,
  onCancelConversion,
  onCancelEdit,
  onCreate,
  onCreateCustomer,
  onConvert,
  onBeginConversion,
  onLogout,
  onNew,
  onNewCustomer,
  onReviewCrm,
  onSelect,
  onUpdate,
  requirements,
  saving,
  statusMessage,
}: {
  canEdit: boolean;
  creatingCustomer: boolean;
  creating: boolean;
  customerBusy: boolean;
  customerError: string | null;
  customers: CustomerSummary[];
  convertingRequirement: Requirement | null;
  editingRequirement: Requirement | null;
  identity: WorkspaceIdentity;
  loggingOut: boolean;
  onCancelCreate: () => void;
  onCancelCustomer: () => void;
  onCancelConversion: () => void;
  onCancelEdit: () => void;
  onCreate: (values: RequirementFormValues) => Promise<RequirementSubmissionResult>;
  onCreateCustomer: (input: CustomerCreateInput) => Promise<boolean>;
  onConvert: (
    requirement: Requirement,
    values: RequirementConversionValues,
  ) => Promise<RequirementConversionResult>;
  onBeginConversion: (requirement: Requirement) => void;
  onLogout: () => void;
  onNew: () => void;
  onNewCustomer: () => void;
  onReviewCrm: (
    requirement: Requirement,
    decision: "establish" | "reject",
    rationale: string,
  ) => Promise<CrmReviewResult>;
  onSelect: (requirement: Requirement) => void;
  onUpdate: (
    requirement: Requirement,
    values: RequirementFormValues,
  ) => Promise<RequirementSubmissionResult>;
  requirements: Requirement[];
  saving: boolean;
  statusMessage: string | null;
}) {
  return (
    <WorkspaceShell
      active="requirements"
      identity={identity}
      loggingOut={loggingOut}
      onLogout={onLogout}
    >
      {statusMessage ? (
        <p
          className="mb-4 rounded-lg border border-success/30 bg-success/10 px-3 py-2 text-sm text-success"
          role="status"
        >
          {statusMessage}
        </p>
      ) : null}
      <div className="flex items-start justify-between gap-4 border-b pb-4">
        <div>
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">
            Intake
          </p>
          <h1 className="mt-1 text-lg font-semibold">需求池</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            记录客户需求与验收依据，为立项评估保留可信入口。
          </p>
        </div>
        {canEdit ? (
          <div className="flex flex-wrap justify-end gap-2">
            <Button className="h-11 sm:h-8" onClick={onNewCustomer} variant="outline">新建客户</Button>
            <Button className="h-11 sm:h-8" onClick={onNew}>
              <PlusIcon aria-hidden="true" />
              新建需求
            </Button>
          </div>
        ) : null}
      </div>

      <div className="mt-6 grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_384px]">
        <RequirementList
          canEdit={canEdit}
          onSelect={onSelect}
          requirements={requirements}
          selectedId={editingRequirement?.id ?? null}
        />
        {creatingCustomer ? (
          <section aria-label="新建客户" className="rounded-lg border bg-card p-4">
            <CustomerForm busy={customerBusy} error={customerError} onCancel={onCancelCustomer} onSubmit={onCreateCustomer} />
          </section>
        ) : creating ? (
          <section aria-label="新建需求" className="rounded-lg border bg-card p-4">
            <RequirementForm
              busy={saving}
              customers={customers}
              onCancel={onCancelCreate}
              onSubmit={onCreate}
            />
          </section>
        ) : convertingRequirement ? (
          <section aria-label="转为开发案例" className="rounded-lg border bg-card p-4">
            <RequirementConversionForm
              busy={saving}
              onCancel={onCancelConversion}
              onSubmit={(values) => onConvert(convertingRequirement, values)}
              requirement={convertingRequirement}
            />
          </section>
        ) : editingRequirement ? (
          <section aria-label="编辑需求" className="rounded-lg border bg-card p-4">
            <RequirementForm
              busy={saving}
              customers={customers}
              key={editingRequirement.id}
              onCancel={onCancelEdit}
              onSubmit={(values) => onUpdate(editingRequirement, values)}
              requirement={editingRequirement}
            />
            {editingRequirement.source === "crm" && editingRequirement.status === "draft" ? (
              <CrmIntakeReview
                busy={saving}
                onReview={(decision, rationale) =>
                  onReviewCrm(editingRequirement, decision, rationale)
                }
              />
            ) : null}
            {editingRequirement.status === "approved" ? (
              <div className="mt-4 border-t pt-4">
                <p className="text-xs text-muted-foreground">批准后的需求可执行一次正式转化。</p>
                <Button
                  className="mt-3 h-11 w-full sm:h-8"
                  onClick={() => onBeginConversion(editingRequirement)}
                  variant="outline"
                >
                  转为开发案例
                </Button>
              </div>
            ) : null}
          </section>
        ) : null}
      </div>
    </WorkspaceShell>
  );
}

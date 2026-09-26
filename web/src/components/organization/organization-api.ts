import { isRecord, responseBody } from "@/components/workspace-api";

import type {
  Delegation,
  DelegationCreate,
  Department,
  HandoverResult,
  HandoverPreview,
} from "./organization-types";

const ORG = "/api/admin/organization";

function isStringOrNull(value: unknown): value is string | null {
  return typeof value === "string" || value === null;
}

async function requireOk(response: Response, fallback: string): Promise<unknown> {
  if (!response.ok) {
    const body = await responseBody(response).catch(() => null);
    const detail = isRecord(body) && isRecord(body.detail) ? body.detail : null;
    throw new Error(detail && typeof detail.message === "string" ? detail.message : fallback);
  }
  return responseBody(response);
}

function parseDepartment(value: unknown): Department {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.name !== "string" ||
    !isStringOrNull(value.parent_department_id) ||
    typeof value.created_at !== "string" ||
    typeof value.updated_at !== "string"
  ) {
    throw new Error("invalid department response");
  }
  return value as Department;
}

function parseDelegation(value: unknown): Delegation {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.principal_user_id !== "string" ||
    typeof value.delegate_user_id !== "string" ||
    typeof value.starts_at !== "string" ||
    typeof value.ends_at !== "string" ||
    typeof value.reason !== "string" ||
    typeof value.created_by_user_id !== "string" ||
    !isStringOrNull(value.revoked_at) ||
    !isStringOrNull(value.revoked_by_user_id) ||
    typeof value.created_at !== "string"
  ) {
    throw new Error("invalid delegation response");
  }
  return value as Delegation;
}

export async function requestDepartments(): Promise<Department[]> {
  const body = await requireOk(
    await fetch(`${ORG}/departments`, { cache: "no-store", credentials: "same-origin" }),
    "部门列表暂不可用",
  );
  if (!isRecord(body) || !Array.isArray(body.items)) throw new Error("invalid department list");
  return body.items.map(parseDepartment);
}

export async function createDepartment(
  name: string,
  parentDepartmentId: string | null = null,
): Promise<Department> {
  const body = await requireOk(
    await fetch(`${ORG}/departments`, {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, parent_department_id: parentDepartmentId }),
    }),
    "创建部门失败",
  );
  return parseDepartment(body);
}

export async function setPlacement(
  userId: string,
  placement: { department_id: string | null; manager_user_id: string | null },
): Promise<void> {
  await requireOk(
    await fetch(`${ORG}/users/${encodeURIComponent(userId)}/placement`, {
      method: "PUT",
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(placement),
    }),
    "设置组织归属失败",
  );
}

export async function requestEscalationChain(userId: string): Promise<string[]> {
  const body = await requireOk(
    await fetch(`${ORG}/users/${encodeURIComponent(userId)}/escalation-chain`, {
      cache: "no-store",
      credentials: "same-origin",
    }),
    "升级链暂不可用",
  );
  if (
    !isRecord(body) ||
    !Array.isArray(body.manager_user_ids) ||
    !body.manager_user_ids.every((item) => typeof item === "string")
  ) {
    throw new Error("invalid escalation chain response");
  }
  return body.manager_user_ids as string[];
}

export async function requestDelegations(): Promise<Delegation[]> {
  const body = await requireOk(
    await fetch(`${ORG}/delegations`, { cache: "no-store", credentials: "same-origin" }),
    "代理列表暂不可用",
  );
  if (!isRecord(body) || !Array.isArray(body.items)) throw new Error("invalid delegation list");
  return body.items.map(parseDelegation);
}

export async function grantDelegation(payload: DelegationCreate): Promise<Delegation> {
  const body = await requireOk(
    await fetch(`${ORG}/delegations`, {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
    "创建代理失败",
  );
  return parseDelegation(body);
}

export async function revokeDelegation(delegationId: string): Promise<Delegation> {
  const body = await requireOk(
    await fetch(`${ORG}/delegations/${encodeURIComponent(delegationId)}/revoke`, {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
    }),
    "撤销代理失败",
  );
  return parseDelegation(body);
}

export async function handOver(payload: {
  from_user_id: string;
  to_user_id: string;
  deactivate_source: boolean;
  expected_digest: string;
}): Promise<HandoverResult> {
  const body = await requireOk(
    await fetch(`${ORG}/handover`, {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
    "批量移交失败",
  );
  if (
    !isRecord(body) ||
    typeof body.from_user_id !== "string" ||
    typeof body.to_user_id !== "string" ||
    !isRecord(body.transferred_counts) ||
    typeof body.deactivated !== "boolean"
  ) {
    throw new Error("invalid handover response");
  }
  return {
    from_user_id: body.from_user_id,
    to_user_id: body.to_user_id,
    transferred_counts: Object.fromEntries(
      Object.entries(body.transferred_counts).filter(
        ([, count]) => typeof count === "number" && Number.isSafeInteger(count),
      ),
    ) as Record<string, number>,
    deactivated: body.deactivated,
  };
}


export async function previewHandover(payload: {
  from_user_id: string; to_user_id: string;
}): Promise<HandoverPreview> {
  const body = await requireOk(await fetch(`${ORG}/handover/preview`, {
    method: "POST", cache: "no-store", credentials: "same-origin",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  }), "交接清单准备失败");
  const count = (value: unknown): value is number =>
    typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
  if (!isRecord(body) || typeof body.from_user_id !== "string" ||
      typeof body.to_user_id !== "string" || typeof body.basis_digest !== "string" ||
      !count(body.transfer_count) || !count(body.manual_count) ||
      !count(body.delegations_to_revoke) || !count(body.project_access_count) || !Array.isArray(body.groups)) {
    throw new Error("交接清单格式不完整，请重新准备");
  }
  const groups = body.groups.map((group: unknown) => {
    if (!isRecord(group) || typeof group.key !== "string" || typeof group.label !== "string" ||
        !count(group.count) || typeof group.can_transfer !== "boolean" ||
        !Array.isArray(group.reasons) || !group.reasons.every((v: unknown) => typeof v === "string") ||
        !Array.isArray(group.items)) throw new Error("交接分类格式不完整");
    const items = group.items.map((item: unknown) => {
      if (!isRecord(item) || typeof item.id !== "string" || typeof item.title !== "string" ||
          typeof item.href !== "string" || !/^\/(projects\?project=[0-9a-f-]+(?:&tab=overview&id_handoff=[0-9a-f-]+&id_freeze=[0-9a-f-]+|&tab=overview&id_freeze_request=[0-9a-f-]+&id_revision=[0-9a-f-]+|&tab=overview&schedule_responsibility_node=[0-9a-f-]+|&tab=overview&approval_request_kind=(?:execution|baseline)&approval_request_id=[0-9a-f-]+|&tab=overview&approval_policy_kind=(?:execution|baseline|commitment)&approval_policy_id=[0-9a-f-]+|&tab=overview&id_owner_revision=[0-9a-f-]+|&tab=overview&input_wait_id=[0-9a-f-]+|&tab=decisions&meeting_recurrence=[0-9a-f-]+|&tab=decisions&meeting=[0-9a-f-]+&meeting_roster_user=[0-9a-f-]+|&tab=decisions&meeting=[0-9a-f-]+&agenda_owner_id=[0-9a-f-]+|&tab=decisions&decision_owner_id=[0-9a-f-]+|&tab=overview&specification_owner_id=[0-9a-f-]+|&tab=overview&resource_allocation_id=[0-9a-f-]+|&tab=overview&resource_reservation_id=[0-9a-f-]+|&tab=overview&reservation_owner_id=[0-9a-f-]+|&tab=quality&quality_owner_kind=(?:complaint|ncr|capa|certification)&quality_owner_id=[0-9a-f-]+|&tab=overview&completion_item=(?:configuration|bom|manufacturing|test_certification|training|residuals|quality_follow_up)|&tab=gates&gate=[0-9a-f-]+&gate_round=[0-9a-f-]+&gate_signer=[0-9a-f-]+|&tab=work-items&entity_id=[0-9a-f-]+|&tab=engineering&change_ecr_id=[0-9a-f-]+&change_task_id=[0-9a-f-]+)?|product-work(?:\?space=[0-9a-f-]+&responsibility_kind=(?:research|work|definition|package|strategy|experiment|opportunity|space|node|subscription)&responsibility_id=[0-9a-f-]+)?|knowledge\?source_owner_id=[0-9a-f-]+|initial-plans\/[0-9a-f-]+(?:\?node=[a-zA-Z0-9_.:-]{1,128})?|cases(?:\/[0-9a-f-]+\/reviews\?(?:policy|review)=[0-9a-f-]+)?|governance\/organization)$/.test(item.href)) {
        throw new Error("交接对象入口格式不完整");
      }
      return { id: item.id, title: item.title, href: item.href };
    });
    return { key: group.key, label: group.label, count: group.count,
      can_transfer: group.can_transfer, reasons: group.reasons as string[], items };
  });
  return { from_user_id: body.from_user_id, to_user_id: body.to_user_id,
    basis_digest: body.basis_digest, transfer_count: body.transfer_count,
    manual_count: body.manual_count, delegations_to_revoke: body.delegations_to_revoke, project_access_count: body.project_access_count, groups };
}

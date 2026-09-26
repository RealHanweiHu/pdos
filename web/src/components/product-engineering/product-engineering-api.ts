import { isRecord, responseBody } from "@/components/workspace-api";

import type {
  DevelopmentBom,
  DevelopmentBomCreateInput,
  DevelopmentBomItem,
  DevelopmentBomType,
  ErpBomReference,
  ProductEngineeringRegister,
  ProductSpecification,
  SpecificationCreateInput,
} from "./product-engineering-types";

const bomTypes = ["cost", "ebom", "prototype"] as const;
const erpReferenceTypes = ["mbom", "production_version", "routing"] as const;

function isNullableString(value: unknown): value is string | null {
  return typeof value === "string" || value === null;
}

function hasTimestamps(value: Record<string, unknown>) {
  return typeof value.created_at === "string" && typeof value.updated_at === "string";
}

function isBomItem(value: unknown): value is DevelopmentBomItem {
  if (!isRecord(value) || !hasTimestamps(value)) return false;
  const cost = value.cost;
  return (
    typeof value.id === "string" &&
    typeof value.bom_id === "string" &&
    isNullableString(value.parent_item_id) &&
    Number.isInteger(value.line_number) &&
    typeof value.part_number === "string" &&
    typeof value.description === "string" &&
    typeof value.quantity === "string" &&
    typeof value.unit === "string" &&
    isNullableString(value.material_reference) &&
    isRecord(value.attributes) &&
    (cost === null ||
      (isRecord(cost) &&
        typeof cost.currency === "string" &&
        typeof cost.unit_cost === "string" &&
        isNullableString(cost.cost_category)))
  );
}

export function isProductSpecification(value: unknown): value is ProductSpecification {
  return (
    isRecord(value) &&
    hasTimestamps(value) &&
    typeof value.id === "string" &&
    typeof value.project_id === "string" &&
    typeof value.created_by_user_id === "string" &&
    typeof value.code === "string" &&
    typeof value.title === "string" &&
    Number.isInteger(value.version) &&
    isNullableString(value.requirement_id) &&
    isNullableString(value.owner_user_id) &&
    isNullableString(value.verification_method) &&
    isNullableString(value.acceptance_criteria) &&
    (value.criticality === "standard" || value.criticality === "key") &&
    isRecord(value.content)
  );
}

export function isDevelopmentBom(value: unknown): value is DevelopmentBom {
  return (
    isRecord(value) &&
    hasTimestamps(value) &&
    typeof value.id === "string" &&
    typeof value.project_id === "string" &&
    isNullableString(value.specification_id) &&
    typeof value.created_by_user_id === "string" &&
    bomTypes.includes(value.bom_type as DevelopmentBomType) &&
    typeof value.code === "string" &&
    typeof value.name === "string" &&
    Number.isInteger(value.version) &&
    isNullableString(value.notes) &&
    Array.isArray(value.items) &&
    value.items.every(isBomItem)
  );
}

export function isErpBomReference(value: unknown): value is ErpBomReference {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.project_id === "string" &&
    isNullableString(value.bom_id) &&
    erpReferenceTypes.includes(
      value.reference_type as (typeof erpReferenceTypes)[number],
    ) &&
    typeof value.source_system === "string" &&
    typeof value.external_id === "string" &&
    isNullableString(value.external_url) &&
    isRecord(value.metadata) &&
    typeof value.created_at === "string"
  );
}

async function errorMessage(response: Response) {
  try {
    const body = await responseBody(response);
    if (isRecord(body) && isRecord(body.detail) && typeof body.detail.message === "string") {
      return body.detail.message.slice(0, 240);
    }
  } catch {
    // Keep malformed upstream errors opaque and bounded.
  }
  return `Product engineering request failed (${response.status})`;
}

async function readItem<T>(response: Response, guard: (value: unknown) => value is T) {
  if (!response.ok) throw new Error(await errorMessage(response));
  const body = await responseBody(response);
  if (!guard(body)) throw new Error("Invalid product engineering response");
  return body;
}

async function readList<T>(response: Response, guard: (value: unknown) => value is T) {
  if (!response.ok) throw new Error(await errorMessage(response));
  const body = await responseBody(response);
  if (!isRecord(body) || !Array.isArray(body.items) || !body.items.every(guard)) {
    throw new Error("Invalid product engineering list response");
  }
  return body.items;
}

function collectionUrl(projectId: string, collection: "boms" | "erp-references" | "specifications") {
  return `/api/projects/${encodeURIComponent(projectId)}/product-engineering/${collection}`;
}

function mutation(body: object): RequestInit {
  return {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export async function requestProductEngineering(projectId: string): Promise<ProductEngineeringRegister> {
  const [specificationResponse, bomResponse, referenceResponse] = await Promise.all([
    fetch(collectionUrl(projectId, "specifications"), {
      cache: "no-store",
      credentials: "same-origin",
    }),
    fetch(collectionUrl(projectId, "boms"), { cache: "no-store", credentials: "same-origin" }),
    fetch(collectionUrl(projectId, "erp-references"), {
      cache: "no-store",
      credentials: "same-origin",
    }),
  ]);
  const [specifications, boms, erpReferences] = await Promise.all([
    readList(specificationResponse, isProductSpecification),
    readList(bomResponse, isDevelopmentBom),
    readList(referenceResponse, isErpBomReference),
  ]);
  return { specifications, boms, erpReferences };
}

export async function createSpecification(projectId: string, input: SpecificationCreateInput) {
  return readItem(
    await fetch(collectionUrl(projectId, "specifications"), mutation(input)),
    isProductSpecification,
  );
}

export async function createDevelopmentBom(projectId: string, input: DevelopmentBomCreateInput) {
  return readItem(
    await fetch(collectionUrl(projectId, "boms"), mutation(input)),
    isDevelopmentBom,
  );
}

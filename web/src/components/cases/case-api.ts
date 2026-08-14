import { isRecord, requestIdentity, responseBody } from "@/components/workspace-api";
import type { WorkspaceIdentity } from "@/components/workspace-types";

import type { DevelopmentCase } from "./case-types";

export type LoadedCases = {
  identity: WorkspaceIdentity;
  cases: DevelopmentCase[];
};

function isDevelopmentCase(value: unknown): value is DevelopmentCase {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === "string" &&
    typeof value.requirement_id === "string" &&
    typeof value.code === "string" &&
    typeof value.title === "string" &&
    (typeof value.summary === "string" || value.summary === null) &&
    ["draft", "evaluating", "approved", "rejected", "converted"].includes(
      String(value.status),
    ) &&
    isRecord(value.business_case) &&
    (typeof value.created_by_user_id === "string" || value.created_by_user_id === null) &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string"
  );
}

export async function readCase(response: Response): Promise<DevelopmentCase> {
  const body = await responseBody(response);
  if (!isDevelopmentCase(body)) throw new Error("invalid Development Case response");
  return body;
}

export async function requestCases(): Promise<LoadedCases | null> {
  const identity = await requestIdentity();
  if (identity === null) return null;
  const response = await fetch("/api/development-cases", {
    cache: "no-store",
    credentials: "same-origin",
  });
  if (response.status === 401) return null;
  if (!response.ok) throw new Error("Development Case workspace unavailable");
  const body = await responseBody(response);
  if (
    !isRecord(body) ||
    !Array.isArray(body.items) ||
    !body.items.every(isDevelopmentCase)
  ) {
    throw new Error("invalid Development Case list response");
  }
  return { identity, cases: body.items };
}

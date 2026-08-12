import { isRecord, responseBody } from "@/components/workspace-api";

export type ProjectActivity = {
  id: number;
  event_type: string;
  entity: string;
  entity_id: string;
  timestamp: string;
};

function isProjectActivity(value: unknown): value is ProjectActivity {
  return (
    isRecord(value) &&
    typeof value.id === "number" &&
    Number.isSafeInteger(value.id) &&
    typeof value.event_type === "string" &&
    typeof value.entity === "string" &&
    typeof value.entity_id === "string" &&
    typeof value.timestamp === "string"
  );
}

export async function requestProjectActivity(projectId: string): Promise<ProjectActivity[]> {
  const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/activity`, {
    cache: "no-store",
    credentials: "same-origin",
  });
  if (!response.ok) throw new Error("项目活动暂不可用");
  const body = await responseBody(response);
  if (!isRecord(body) || !Array.isArray(body.items) || !body.items.every(isProjectActivity)) {
    throw new Error("invalid Project activity response");
  }
  return body.items;
}

import { isRecord, responseBody } from "@/components/workspace-api";

import { isProjectMember } from "./project-work-item-api";
import type { ProjectMember } from "./project-work-item-types";

export type MemberCandidate = { user_id: string; display_name: string; role: string };

const openWorkLabels: Record<string, string> = {
  tasks: "任务",
  issues: "问题",
  risks: "风险",
  complaints: "投诉",
  ncrs: "NCR",
  capa_actions: "CAPA 行动",
};

const codeMessages: Record<string, string> = {
  PROJECT_OWNER_MEMBERSHIP_REQUIRED: "项目负责人必须保留在成员中。",
  PROJECT_MEMBER_EXISTS: "该用户已经是项目成员。",
  PROJECT_MEMBER_NOT_FOUND: "该用户已不是项目成员，请刷新后重试。",
  PROJECT_MEMBER_USER_NOT_FOUND: "用户不存在或已停用。",
  PROJECT_ARCHIVED: "项目已归档，成员不可变更。",
  PROJECT_ACCESS_DENIED: "你没有管理该项目成员的权限。",
};

function isCandidate(value: unknown): value is MemberCandidate {
  return (
    isRecord(value) &&
    typeof value.user_id === "string" &&
    typeof value.display_name === "string" &&
    typeof value.role === "string"
  );
}

async function failure(response: Response): Promise<Error> {
  try {
    const body = await responseBody(response);
    if (isRecord(body) && isRecord(body.detail)) {
      const { code, open_work: openWork } = body.detail;
      if (code === "PROJECT_MEMBER_HAS_OPEN_WORK" && isRecord(openWork)) {
        const parts = Object.entries(openWork).map(([key, count]) => `${openWorkLabels[key] ?? key} ${String(count)}`);
        return new Error(`该成员仍负责未完成的工作（${parts.join("、")}），请先转交后再移除。`);
      }
      if (typeof code === "string" && codeMessages[code]) return new Error(codeMessages[code]);
    }
  } catch {
    // Fall through to the bounded generic message.
  }
  return new Error(`成员操作失败（${response.status}），请稍后重试。`);
}

async function readMembers(response: Response): Promise<ProjectMember[]> {
  if (!response.ok) throw await failure(response);
  const body = await responseBody(response);
  if (!isRecord(body) || !Array.isArray(body.items) || !body.items.every(isProjectMember)) {
    throw new Error("invalid Project member list response");
  }
  return body.items;
}

function membersUrl(projectId: string, ...segments: string[]) {
  return ["/api/projects", projectId, "members", ...segments]
    .map((segment, index) => (index === 0 ? segment : encodeURIComponent(segment)))
    .join("/");
}

export async function requestMemberCandidates(projectId: string): Promise<MemberCandidate[]> {
  const response = await fetch(membersUrl(projectId, "candidates"), { cache: "no-store", credentials: "same-origin" });
  if (!response.ok) throw await failure(response);
  const body = await responseBody(response);
  if (!isRecord(body) || !Array.isArray(body.items) || !body.items.every(isCandidate)) {
    throw new Error("invalid member candidate response");
  }
  return body.items;
}

export async function addProjectMember(projectId: string, userId: string) {
  return readMembers(
    await fetch(membersUrl(projectId), {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
    }),
  );
}

export async function removeProjectMember(projectId: string, userId: string) {
  return readMembers(await fetch(membersUrl(projectId, userId), { method: "DELETE", credentials: "same-origin" }));
}

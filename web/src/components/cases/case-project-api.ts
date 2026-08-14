import { responseBody } from "@/components/workspace-api";

import type { CaseProjectResult, CaseProjectValues } from "./case-project-form";
import type { DevelopmentCase } from "./case-types";

export type CaseProjectRequestResult = CaseProjectResult & { unauthorized?: boolean };

export async function requestProjectCreation(
  developmentCase: DevelopmentCase,
  values: CaseProjectValues,
): Promise<CaseProjectRequestResult> {
  try {
    const response = await fetch("/api/projects", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ development_case_id: developmentCase.id, ...values }),
    });
    if (response.status === 401) {
      return { ok: false, unauthorized: true, message: "登录已失效，正在返回登录页。" };
    }
    if (!response.ok) {
      return { ok: false, message: "项目未创建，请检查 Case 状态或项目编号。" };
    }
    const body = await responseBody(response);
    if (body === null || typeof body !== "object" || !("id" in body) || typeof body.id !== "string") {
      return { ok: false, message: "项目响应无效，请稍后重试。" };
    }
    return { ok: true };
  } catch {
    return { ok: false, message: "网络连接失败，请稍后重试。" };
  }
}

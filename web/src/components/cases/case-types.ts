export type DevelopmentCase = {
  id: string;
  requirement_id: string;
  code: string;
  title: string;
  summary: string | null;
  status: "draft" | "evaluating" | "approved" | "rejected" | "converted";
  business_case: Record<string, unknown>;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
};

export function caseStatusLabel(status: DevelopmentCase["status"]) {
  return {
    draft: "草稿",
    evaluating: "评估中",
    approved: "已批准",
    rejected: "已拒绝",
    converted: "已转项目",
  }[status];
}

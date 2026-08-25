export type WorkItemPriority = "low" | "medium" | "high" | "critical";

export type TaskStatus = "todo" | "in_progress" | "blocked" | "done" | "skipped";
export type TaskReadiness = "ready" | "waiting" | "blocked" | "complete" | "waiting_approval";

export type ProjectTask = {
  id: string;
  project_id: string;
  stage_id: string | null;
  parent_task_id: string | null;
  assignee_user_id: string | null;
  title: string;
  description: string | null;
  status: TaskStatus;
  blocked_reason: string | null;
  priority: WorkItemPriority;
  start_date: string | null;
  due_date: string | null;
  completed_at: string | null;
  dependency_task_ids: string[];
  unresolved_dependency_ids: string[];
  readiness: TaskReadiness;
  created_at: string;
  updated_at: string;
};

export type IssueStatus = "open" | "analysis" | "action" | "verification" | "closed";

export type ProjectIssue = {
  id: string;
  project_id: string;
  stage_id: string | null;
  owner_user_id: string | null;
  reported_by_user_id: string;
  title: string;
  description: string | null;
  status: IssueStatus;
  severity: WorkItemPriority;
  root_cause: string | null;
  resolution: string | null;
  target_date: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type RiskStatus = "open" | "mitigating" | "watching" | "closed";

export type ProjectRisk = {
  id: string;
  project_id: string;
  owner_user_id: string | null;
  title: string;
  description: string | null;
  status: RiskStatus;
  likelihood: number;
  impact: number;
  score: number;
  mitigation_plan: string | null;
  contingency_plan: string | null;
  target_date: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ProjectWorkItems = {
  tasks: ProjectTask[];
  issues: ProjectIssue[];
  risks: ProjectRisk[];
};

export type TaskCreateInput = {
  title: string;
  description?: string | null;
  stage_id?: string | null;
  start_date?: string | null;
  due_date?: string | null;
  priority: WorkItemPriority;
  dependency_task_ids: string[];
};

export type IssueCreateInput = {
  title: string;
  severity: WorkItemPriority;
};

export type RiskCreateInput = {
  title: string;
  likelihood: number;
  impact: number;
};

export type TaskTransitionInput = {
  to_status: TaskStatus;
  blocked_reason?: string;
};

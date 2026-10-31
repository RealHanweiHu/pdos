export type ProjectStage = {
  id: string;
  code: string;
  name: string;
  description: string | null;
  sequence: number;
  /** Plan baseline and actual dates; absent on payloads from before migration 0031. */
  planned_start_date?: string | null;
  planned_end_date?: string | null;
  entered_at?: string | null;
  exited_at?: string | null;
};

export type ProjectWorkflow = {
  id: string;
  code: string;
  name: string;
  description: string | null;
  version: number;
  is_active: boolean;
  stages: ProjectStage[];
};

export type Project = {
  id: string;
  development_case_id: string | null;
  customer_id: string | null;
  workflow: ProjectWorkflow;
  current_stage: ProjectStage;
  owner_user_id: string;
  code: string;
  name: string;
  description: string | null;
  status: "draft" | "proposed" | "approved" | "active" | "on_hold" | "completed" | "cancelled" | "archived";
  start_date: string | null;
  target_date: string | null;
  created_at: string;
  updated_at: string;
};

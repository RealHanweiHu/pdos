export type MyWorkProjectRef = {
  id: string;
  code: string;
  name: string;
};

export type MyWorkTask = {
  id: string;
  project: MyWorkProjectRef;
  title: string;
  status: string;
  priority: string;
  due_date: string | null;
};

export type MyWorkIssue = {
  id: string;
  project: MyWorkProjectRef;
  title: string;
  status: string;
  severity: string;
  target_date: string | null;
};

export type MyWorkRisk = {
  id: string;
  project: MyWorkProjectRef;
  title: string;
  status: string;
  likelihood: number;
  impact: number;
  target_date: string | null;
};

export type MyWorkCapaAction = {
  id: string;
  project: MyWorkProjectRef;
  ncr_id: string;
  action_type: string;
  description: string;
  status: string;
  due_date: string;
};

export type MyWorkGateSignoff = {
  id: string;
  project: MyWorkProjectRef;
  gate_id: string;
  gate_code: string;
  gate_name: string;
  slot: string;
  requirement: string;
  round_number: number;
  review_due_at: string | null;
};

export type MyWorkFinding = {
  id: string;
  project: MyWorkProjectRef;
  finding_type: string;
  status?: "pending_review" | "accepted";
  title: string;
  created_at: string;
};

export type MyWorkCounts = {
  tasks: number;
  issues: number;
  risks: number;
  capa_actions: number;
  gate_signoffs: number;
  findings: number;
  cross_schedule_approvals?: number;
  id_design_actions?: number;
  change_execution_confirmations?: number;
  risk_followup_actions?: number;
  task_takeover_actions?: number;
  cost_freeze_approvals?: number;
};

export type MyNotification = {
  id: string;
  project: MyWorkProjectRef;
  policy_key: string;
  target_entity: string;
  target_entity_id: string;
  title: string;
  status: string;
  escalation_level: number;
  fire_at: string;
  fired_at: string | null;
  acknowledged_at: string | null;
};

export type MyNotifications = {
  items: MyNotification[];
  unread_count: number;
  digest: { policy_key: string; count: number }[];
};

export type MyWorkCollection = keyof MyWorkCounts;
export type MyWorkPage = { offset: number; next_offset: number | null; revision: string };

export type MyWork = {
  pages?: Partial<Record<MyWorkCollection, MyWorkPage>>;
  tasks: MyWorkTask[];
  issues: MyWorkIssue[];
  risks: MyWorkRisk[];
  capa_actions: MyWorkCapaAction[];
  gate_signoffs: MyWorkGateSignoff[];
  findings: MyWorkFinding[];
  counts: MyWorkCounts;
  id_design_actions?: MyWorkIdDesign[];
  change_execution_confirmations?: MyWorkChangeExecution[];
  risk_followup_actions?: MyWorkRiskFollowup[];
  task_takeover_actions?: MyWorkTaskTakeover[];
  cost_freeze_approvals?: MyWorkCostFreeze[];
  cross_schedule_approvals?: { id: string; project: MyWorkProjectRef; title: string; operation: "add" | "remove" | "replace"; created_at: string }[];
};

export type MyWorkIdDesign = { id: string; project: MyWorkProjectRef; kind: "freeze" | "handoff"; revision_id: string; freeze_id: string | null; title: string; created_at: string };

export type MyWorkChangeExecution={id:string;project:MyWorkProjectRef;binding_id:string;ecr_id:string;task_id:string;ecr_code:string;title:string;action:"retest"|"rereview"|"recertification"|"coordination";revision_number:number;created_at:string};

export type MyWorkRiskFollowup = { id: string; project: MyWorkProjectRef; risk_id: string; task_id: string; title: string; mode: "review" | "submit"; created_at: string };

export type MyWorkTaskTakeover = { id: string; project: MyWorkProjectRef; task_id: string; title: string; mode: "review" | "revise"; revision: number; due_date: string | null; priority: string; status: string; created_at: string };

export type MyWorkCostFreeze = { id: string; project: MyWorkProjectRef; title: string; created_at: string };

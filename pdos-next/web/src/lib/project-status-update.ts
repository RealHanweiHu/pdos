export type NamedProjectUpdate = {
  id: string;
  revision: number;
  actor: { id: string; name: string | null };
  fact_summary: string;
  next_steps: string;
  task_refs: { id: string; revision: number }[];
  created_at: string;
  receipt_id: string;
};

export type WorkspaceIdentity = {
  tenant: {
    id: string;
    slug: string;
    name: string;
  };
  user: {
    id: string;
    tenant_id: string;
    username: string;
    display_name: string;
    role: string;
    email: string | null;
    is_active: boolean;
  };
};

export type CustomerSummary = {
  id: string;
  code: string;
  name: string;
  status: "active" | "inactive";
};

export type Requirement = {
  id: string;
  code: string;
  title: string;
  description: string | null;
  source: string | null;
  status: "draft" | "proposed" | "approved" | "rejected" | "converted";
  priority: "low" | "medium" | "high" | "critical";
  acceptance_criteria: string[];
  customer: CustomerSummary | null;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
};

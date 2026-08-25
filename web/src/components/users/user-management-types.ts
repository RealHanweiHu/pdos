export const USER_ROLES = [
  "owner",
  "admin",
  "project_manager",
  "engineer",
  "quality",
  "supplier",
  "customer",
] as const;

export type UserRole = (typeof USER_ROLES)[number];

export const ROLE_LABELS: Record<UserRole, string> = {
  owner: "Owner",
  admin: "Admin",
  project_manager: "Project Manager",
  engineer: "Engineer",
  quality: "Quality",
  supplier: "Supplier",
  customer: "Customer",
};

export type ManagedUser = {
  id: string;
  tenant_id: string;
  username: string;
  display_name: string;
  email: string | null;
  role: UserRole;
  is_active: boolean;
  last_signed_in_at: string | null;
  created_at: string;
  updated_at: string;
};

export type UserCreate = {
  username: string;
  display_name: string;
  email: string | null;
  role: UserRole;
  password: string;
};

export type UserUpdate = Partial<
  Pick<ManagedUser, "display_name" | "email" | "role" | "is_active">
>;

export const USER_ROLES = [
  "owner",
  "admin",
  "product_manager",
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
  product_manager: "产品经理",
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
  work_modules?: WorkModule[];
};

export type UserCreate = {
  username: string;
  display_name: string;
  email: string | null;
  role: UserRole;
  password: string;
};

export type UserUpdate = Partial<
  Pick<ManagedUser, "display_name" | "email" | "role" | "is_active" | "work_modules">
>;
import type { WorkModule } from "../work-modules";

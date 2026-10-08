import type { WorkModule } from "./work-modules";

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
    work_modules?: WorkModule[];
  };
};

export type LoginPayload = {
  tenant_slug: string;
  username: string;
  password: string;
};

export type SetupPayload = LoginPayload & {
  tenant_name: string;
  display_name: string;
};

export type SubmissionResult =
  | { ok: true }
  | {
      ok: false;
      message: string;
    };

export type AuthIdentity = {
  tenant: { id: string; slug: string; name: string };
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

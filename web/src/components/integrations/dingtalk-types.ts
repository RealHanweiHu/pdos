export type DingTalkStatus = {
  configured: boolean;
  binding_status: string | null;
  corp_id: string | null;
  linked: boolean;
  delivery_enabled: boolean;
};

export type DingTalkOutboxItem = {
  id: string;
  project_id: string | null;
  operation: string;
  status: string;
  attempt_count: number;
  remote_reference: string | null;
  last_error_code: string | null;
};

export type DingTalkBootstrap = {
  status: DingTalkStatus;
  outbox: DingTalkOutboxItem[] | null;
};

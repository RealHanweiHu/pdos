export type PlatformLink = {
  id: string; category_id: string; product_id: string; product_name: string;
  variant_id: string | null; variant_name: string | null; version: number;
  action: "attach" | "detach"; current_version: number; attached: boolean;
  compatibility: string | null; platform_version: string | null; reason: string;
  provenance: { origin: "human" | "ai_draft"; writer_id: string; confirmed_by: string; created_at: string };
};
export type Platform = {
  id: string; code: string; name: string; description: string; links: PlatformLink[];
  provenance: PlatformLink["provenance"];
};
export type PlatformList = { items: Platform[]; next_cursor: string | null; link_scope: string };
export type PlatformPayload = {
  product_id: string; variant_id: string | null; platform_id: string | null;
  new_platform: { code: string; name: string; description: string } | null;
  action: "attach" | "detach"; compatibility: string | null; platform_version: string | null;
  reason: string; expected_link_version: number; confirmation_token?: string;
};
export type PlatformCommand = {
  command_id: string; idempotency_key: string; operation: "platform.link.create";
  product_id: string; expected_revision: number; source_read_set: [];
  payload: PlatformPayload;
};
export type PlatformPreview = {
  command: PlatformCommand; expires_at: string; confirmation_token: string;
  review: { platform: Pick<Platform, "code" | "name" | "description">;
    product_name: string; variant_name: string | null; next_link_version: number; effect: string };
};

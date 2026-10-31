export type PreviewEntry = { id: string; label: string; href: string };
export type PreviewCase = {
  id: string; title: string; summary: string; limit: string;
  categoryId: string; productId: string; projectId: string; projectName: string;
  roleIds: string[]; entries: PreviewEntry[]; counts: { label: string; value: number }[];
};
export type PreviewRole = { id: string; caseId: string; label: string; name: string; principalId: string; tenantId: string };
export type PreviewCatalog = { version: 1; created_at: string; expires_at: string; cases: PreviewCase[]; roles: PreviewRole[] };

/** Project selection narrows workbench reads; server permissions remain authoritative. */
export function projectBuildsPath(productId: string, projectId = ""): string {
  const path = `v1/products/${productId}/builds`;
  return projectId ? `${path}?${new URLSearchParams({ project_id: projectId })}` : path;
}

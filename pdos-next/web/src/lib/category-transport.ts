import type { WorkspaceTransport } from "@/lib/workspace-api";

/** Bind every workspace resource to one explicit category; only scoped URLs reach the BFF. */
export function categoryTransport(categoryId: string, transport: WorkspaceTransport): WorkspaceTransport {
  const prefix = `v1/categories/${categoryId}/`;
  return <T>(resource: string, body?: unknown): Promise<T> => {
    if (resource.startsWith("v1/categories/") && !resource.startsWith(prefix)) {
      return Promise.reject(new Error("请求与当前品类不一致。"));
    }
    const path = resource.startsWith("v1/") && resource !== "v1/session" && !resource.startsWith(prefix)
      ? prefix + resource.slice(3) : resource;
    const envelope = body && typeof body === "object" ? body as Record<string, unknown> : null;
    const command = envelope !== null && typeof envelope.operation === "string"
      && typeof envelope.command_id === "string" && typeof envelope.payload === "object";
    const payload = command && body && typeof body === "object"
      ? { ...body, category_id: categoryId } : body;
    return transport<T>(path, payload).then(value => {
      if (command && value && typeof value === "object" && "command" in value) {
        const returned = (value as { command: Record<string, unknown> }).command;
        if (!returned || returned.category_id !== categoryId) {
          throw new Error("返回命令与当前品类不一致。");
        }
      }
      return value;
    });
  };
}

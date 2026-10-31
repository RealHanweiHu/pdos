import type { MaterialContext } from "@/components/category-material-editor";

/** Page inputs are user-supplied material, never authoritative scope or facts.
 * Scope and source permissions continue to be bound by the run on the server. */
export function materialContextText(context?: MaterialContext): string {
  if (!context) return "";
  const serialized = JSON.stringify({
    type: context.kind,
    title: context.title,
    id: context.id ?? null,
    version: context.version ?? null,
    unsaved_input: context.draft ?? null,
  });
  let bounded =
    serialized.length <= 6000
      ? serialized
      : JSON.stringify({
          type: context.kind,
          title: context.title,
          id: context.id ?? null,
          version: context.version ?? null,
          truncated: true,
          instruction:
            "页面资料过长，以下为部分内容；请读取原对象完整固定版本，未保存部分需向用户核对，不能视为完整材料。",
          excerpt: serialized.slice(0, 5200),
        });
  if (bounded.length > 6000)
    bounded = JSON.stringify({
      type: context.kind,
      id: context.id ?? null,
      truncated: true,
      instruction:
        "页面资料过长，仅提供片段；请重读原对象，未保存内容须向用户核对。",
      excerpt: serialized.slice(0, 2200),
    });
  return `当前页面资料（请按服务器权限重新读取固定版本；未保存输入仅供讨论）：\n${bounded}`;
}
export function withMaterialContext(goal: string, contextText = ""): string {
  const combined = contextText
    ? `${goal.trim()}\n\n${contextText}`
    : goal.trim();
  if (combined.length > 8000)
    throw new Error(
      "本次输入与品类上下文超过长度限制，请减少编辑内容或取消携带后再发送。",
    );
  return combined;
}

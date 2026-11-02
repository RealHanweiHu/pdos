/** 浏览器侧通用 BFF 读取：GET 无体、POST JSON；错误保留服务端 code/status/detail/recovery。 */
export async function browserApi<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  const value = await response.json();
  if (!response.ok) throw Object.assign(new Error(value.message ?? "服务暂不可用。"), { code: value.code, status: response.status, detail: value.detail, recovery: value.recovery });
  return value;
}

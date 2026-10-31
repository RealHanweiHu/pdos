import { readFile, stat } from "node:fs/promises";
import path from "node:path";

export async function readPlanSource(): Promise<{ markdown: string; updated: Date } | { failure: string }> {
  const relative = "tasks/ai-native-integrated-todo.md", cwd = process.cwd();
  const candidates = [process.env.PDOS_TODO_FILE, path.resolve(cwd, relative), path.resolve(cwd, "..", "..", relative), path.resolve(cwd, "..", relative)];
  for (const candidate of candidates) {
    if (!candidate) continue;
    try {
      const [markdown, info] = await Promise.all([readFile(candidate, "utf8"), stat(candidate)]);
      return { markdown, updated: info.mtime };
    } catch { /* Try the next known location of the single active checklist. */ }
  }
  return { failure: "当前进展暂不可读，请核对本地预览是否从项目目录启动。" };
}

export type CategoryDraft = {
  name: string;
  description: string;
  status: "ready" | "created" | "discarded" | "superseded";
  deidentified: boolean;
  categoryId?: string;
};

// Deterministic synthetic preview only. Unspecified information stays blank.
export function categoryDraftFromPrompt(
  prompt: string,
  previous?: CategoryDraft,
): CategoryDraft {
  const clean = (value: string) =>
    value.trim().replace(/^[“「"'：:]+|[”」"']+$/g, "");
  const named = prompt.match(
    /(?:品类名称|名称|名字)\s*(?:改为|改成|叫|是|为|[:：])\s*([^，。；\n]+)/,
  );
  const before =
    prompt.match(
      /(?:新建|创建|新增|建立)(?:一个)?\s*[“「"']([^”」"']+)[”」"']\s*(?:的)?品类/,
    ) ??
    prompt.match(
      /(?:新建|创建|新增|建立)(?:一个)?(?:叫|名为)?\s*([^，。；\n]{1,40}?)\s*(?:的)?品类/,
    );
  const after = prompt.match(
    /(?:新建|创建|新增|建立)(?:一个)?品类\s*(?:[:：]|叫|名为|是)\s*([^，。；\n]+)/,
  );
  const scenario = prompt.match(
    /(?:主要场景|使用场景|场景)\s*(?:改为|改成|是|为|[:：])\s*([^。；\n]+)/,
  );
  const name = clean(
    named?.[1] ?? before?.[1] ?? after?.[1] ?? previous?.name ?? "",
  );
  return {
    name: /^(一个|新|新的|一个新的)$/.test(name) ? "" : name,
    description: clean(scenario?.[1] ?? previous?.description ?? ""),
    status: "ready",
    deidentified: false,
  };
}

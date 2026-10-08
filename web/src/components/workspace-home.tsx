"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { requestIdentity } from "@/components/workspace-api";
import { getWorkHomeHref } from "@/components/workspace-experience";
import type { WorkspaceIdentity } from "@/components/workspace-types";

function OpenWorkHome({ identity }: { identity: WorkspaceIdentity }) {
  const { replace } = useRouter();
  const destination = getWorkHomeHref(identity.user.role);
  useEffect(() => { replace(destination); }, [destination, replace]);
  return <main aria-busy="true" className="mx-auto max-w-6xl px-4 py-10 text-sm text-muted-foreground">正在打开{identity.user.display_name}的{destination === "/my-work" ? "工作台" : "已授权项目"}…</main>;
}

export function WorkspaceHome() {
  const { replace } = useRouter();
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    requestIdentity().then(value => {
      if (!active) return;
      if (!value) replace("/login");
      else setIdentity(value);
    }, () => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [attempt, replace]);
  if (identity) return <OpenWorkHome identity={identity} />;
  if (failed) return <main className="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center px-6 text-center"><h1 className="text-lg font-semibold">工作首页暂不可用</h1><p className="mt-2 text-sm text-muted-foreground">无法核对当前账号，请重新读取。</p><Button className="mt-4" onClick={() => { setFailed(false); setAttempt(value => value + 1); }}>重新加载</Button></main>;
  return <main aria-busy="true" className="mx-auto max-w-6xl px-4 py-10 text-sm text-muted-foreground">正在打开你的工作区…</main>;
}

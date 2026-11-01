"use client";

import { ArrowCounterClockwise, X } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { skillTitle } from "@/lib/agent-skills";
import { toggleContinuedSkill } from "@/lib/continued-skills";
import type { RequestedSkill } from "@/lib/run-start-intent";
import type { WorkspaceTransport } from "@/lib/workspace-api";
import { SkillPicker } from "./skill-picker";

export function ContinuedSkillPicker({
  api, resource, continued, excluded, onExcludedChange, requested, onRequestedChange, disabled,
}: {
  api: WorkspaceTransport;
  resource?: "v1/agent-skills" | "v1/personal/agent-skills";
  continued: RequestedSkill[];
  excluded: string[];
  onExcludedChange: (value: string[]) => void;
  requested: RequestedSkill[];
  onRequestedChange: (value: RequestedSkill[]) => void;
  disabled: boolean;
}) {
  const inherited = continued.filter(skill => !requested.some(item => item.key === skill.key));
  return <div className="flex min-w-0 flex-wrap items-center gap-2" role="group" aria-label="本轮技能">
    {inherited.length > 0 && <div className="flex min-w-0 flex-wrap items-center gap-1.5">
      <span className="text-xs text-muted-foreground">沿用上轮</span>
      {inherited.map(skill => {
        const removed = excluded.includes(skill.key), title = skillTitle(skill.key);
        return <Button key={skill.key} type="button" size="sm" variant={removed ? "ghost" : "outline"}
          className="h-auto max-w-full gap-1.5 whitespace-normal py-1 text-xs"
          disabled={disabled} aria-pressed={!removed}
          aria-label={`${removed ? "恢复" : "移除"}沿用技能 ${title}`}
          onClick={() => onExcludedChange(toggleContinuedSkill(continued, excluded, skill.key))}>
          <span>{title} · {skill.version}{removed && " · 已移除"}</span>
          {removed ? <ArrowCounterClockwise size={12} aria-hidden="true"/> : <X size={12} aria-hidden="true"/>}
        </Button>;
      })}
    </div>}
    <SkillPicker api={api} resource={resource} value={requested} onChange={onRequestedChange} disabled={disabled}/>
  </div>;
}

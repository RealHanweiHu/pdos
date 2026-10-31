import { planCleanText } from "./plan-progress";

export type CurrentMilestone = { id: string; title: string; status: string; detail: string };
export type CurrentProgress = { milestones: CurrentMilestone[]; highlights: { title: string; text: string }[] };

/** Only the active queue is current progress; archived N/P/Q counts are not a completion rate. */
export function parseCurrentProgress(markdown: string): CurrentProgress {
  const start = markdown.indexOf('<a id="current-queue"></a>');
  if (start < 0) return { milestones: [], highlights: [] };
  const queue = markdown.slice(start).split('<a id="queue-history-')[0];
  const milestones: CurrentMilestone[] = [], highlights: CurrentProgress["highlights"] = [];
  for (const line of queue.split(/\r?\n/)) {
    const row = line.match(/^\|\s*(M\d+)\s+([^|]+)\|\s*([^|]+)\|\s*(.*?)\s*\|$/);
    if (row) milestones.push({ id: row[1], title: planCleanText(row[2]), status: planCleanText(row[3]), detail: planCleanText(row[4]) });
    const note = line.match(/^\*\*((?:S1 最小演示切片|待用户处理)[^*]*)\*\*[:：](.*)$/);
    if (note) highlights.push({ title: planCleanText(note[1]), text: planCleanText(note[2]) });
  }
  return { milestones, highlights };
}

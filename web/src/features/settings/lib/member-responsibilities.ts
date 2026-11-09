/** Members page read model: category grant holders joined with project team roles (D33). */
export type Participant = { id: string; name: string };
export type TeamRole = { key: string; name: string; lead: boolean };
export type TeamReading = {
  project: { id: string; name: string; owner_id: string; visibility: string };
  members: { principal_id: string; name: string; is_owner: boolean; roles: TeamRole[] }[];
};
export type ProjectRef = { id: string; name: string; categoryId: string; productId: string };
export type MemberAssignment = { projectId: string; projectName: string; owner: boolean; roles: TeamRole[] };
export type MemberRow = { id: string; name: string; categoryMember: boolean; assignments: MemberAssignment[] };
export type MemberApi = <T>(path: string) => Promise<T>;

const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0;

/** Reject a partial team reading; it never shows as "no responsibilities". */
export function parseTeam(value: unknown, projectId: string): TeamReading {
  if (!record(value) || !record(value.project) || value.project.id !== projectId || !text(value.project.name) || !Array.isArray(value.members)
    || !value.members.every(member => record(member) && text(member.principal_id) && typeof member.name === "string" && typeof member.is_owner === "boolean"
      && Array.isArray(member.roles) && member.roles.every(role => record(role) && text(role.key) && typeof role.name === "string" && typeof role.lead === "boolean")))
    throw new Error("项目团队资料未完整取得。");
  return value as TeamReading;
}

/** Read each visible project's team with bounded concurrency; failures are counted, not hidden. */
export async function readTeams(api: MemberApi, projects: ProjectRef[], limit = 4): Promise<{ teams: TeamReading[]; unavailable: number }> {
  const teams: TeamReading[] = [];
  let unavailable = 0, next = 0;
  async function worker() {
    while (next < projects.length) {
      const project = projects[next++];
      try {
        teams.push(parseTeam(await api<unknown>(`v1/categories/${project.categoryId}/products/${project.productId}/projects/${project.id}/team`), project.id));
      } catch { unavailable += 1; }
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, projects.length) }, worker));
  const order = new Map(projects.map((project, index) => [project.id, index]));
  teams.sort((a, b) => (order.get(a.project.id) ?? 0) - (order.get(b.project.id) ?? 0));
  return { teams, unavailable };
}

/** Category members first (server order), then team members who are not in that list. */
export function memberRows(participants: Participant[], teams: TeamReading[]): MemberRow[] {
  const rows = new Map<string, MemberRow>(participants.map(person => [person.id, { id: person.id, name: person.name, categoryMember: true, assignments: [] }]));
  for (const team of teams) for (const member of team.members) {
    const row = rows.get(member.principal_id) ?? { id: member.principal_id, name: member.name || "姓名暂不可读", categoryMember: false, assignments: [] };
    row.assignments.push({ projectId: team.project.id, projectName: team.project.name, owner: member.is_owner, roles: member.roles });
    rows.set(member.principal_id, row);
  }
  return [...rows.values()];
}

/** "结构工程（主责）、测试" — the owner role is named explicitly. */
export function responsibilityText(assignment: MemberAssignment): string {
  const roles = assignment.roles.map(role => `${role.name || role.key}${role.lead ? "（主责）" : ""}`);
  return [assignment.owner ? "项目负责人" : "", ...roles].filter(Boolean).join("、") || "成员（角色待补充）";
}

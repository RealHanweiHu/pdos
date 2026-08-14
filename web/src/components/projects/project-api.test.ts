import { describe, expect, it } from "vitest";

import { isProject } from "./project-api";

const migratedProject = {
  id: "project-1",
  development_case_id: null,
  customer_id: null,
  workflow: {
    id: "workflow-1",
    code: "npd-cehub-project-1",
    name: "NPD · S18-01",
    description: "CEHub v1 imported NPD workflow",
    version: 1,
    is_active: true,
    stages: [
      {
        id: "stage-1",
        code: "concept",
        name: "概念阶段",
        description: null,
        sequence: 1,
      },
    ],
  },
  current_stage: {
    id: "stage-1",
    code: "concept",
    name: "概念阶段",
    description: null,
    sequence: 1,
  },
  owner_user_id: "user-1",
  code: "S18-01",
  name: "S18 试点项目",
  description: null,
  status: "active",
  start_date: null,
  target_date: null,
  created_at: "2026-08-11T16:00:00Z",
  updated_at: "2026-08-11T16:00:00Z",
};

describe("Project API contract", () => {
  it("accepts migrated Projects without a Development Case", () => {
    expect(isProject(migratedProject)).toBe(true);
  });
});

# PDOS Web

Next.js App Router application for PDOS. The implementation follows `docs/design/2026-08-09-ui-baseline.md`.

## Commands

```bash
pnpm dev
pnpm test
pnpm lint
pnpm typecheck
pnpm build
```

## UI contract

- Tailwind CSS v4 + shadcn/ui (`radix-nova`)
- Geist / Geist Mono via `next/font`
- Phosphor is the only icon family; import Server Component icons from `@phosphor-icons/react/ssr`
- Company orange: `#c2410c` in light mode and `#fb923c` in dark mode
- One 8px radius system, except documented full-pill filters
- Theme defaults to the system preference and supports a manual light/dark toggle

## Implemented routes

- `/login` and `/setup`: local account authentication through the same-origin session BFF
- `/requirements`: tenant-scoped Requirement pool with create/edit, optional Customer association, and the one-time approved Requirement→Case action
- `/cases`: role-aware Development Case list/editor with explicit state transitions and approved Case→Project creation
- `/projects`: membership-aware Project list/editor with seven-stage Timeline, explicit lifecycle transitions, and adjacent-stage progression
- `/events`: Owner/Admin-only, read-only event debugger with stable cursor filters, catalog coverage, consumers, envelope, and payload inspection
- `/api/requirements`, `/api/development-cases`, `/api/projects`, and their item/action routes: server-only BFF endpoints that forward the HttpOnly session token without exposing it to client JavaScript
- `/api/projects/{projectId}/tasks|issues|risks` plus item/transition routes: bounded, project-scoped work-item BFF contracts for the S1-6 workspace
- `/api/events` and `/api/events/catalog`: allowlisted-query, read-only BFF endpoints for the internal event debugger

Business screens are added only by their canonical Sprint work items. Task, Issue, and Risk data
contracts are complete; their five-tab Project Workspace presentation remains reserved for S1-6.

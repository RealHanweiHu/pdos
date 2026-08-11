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
- `/cases`: role-aware Development Case list/editor with explicit state transitions, loading/error/empty states, and responsive light/dark layouts
- `/api/requirements`, `/api/development-cases`, and their item/action routes: server-only BFF endpoints that forward the HttpOnly session token without exposing it to client JavaScript

Business screens are added only by their canonical Sprint work items. Project creation and Workflow/Stage instantiation remain reserved for S1-3.

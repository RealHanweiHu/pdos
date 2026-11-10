"""BOM designators, declared alternates and import provenance (D98, P79, P113; F35/F37).

Two columns on existing BOM tables; no new table, function or policy. Existing
rows keep an empty designator list and no import basis. Downgrade is refused
once any row carries either, so imported history is never silently dropped.
"""

UP_SQL = (
    "ALTER TABLE public.bom_lines ADD COLUMN reference_designators jsonb NOT NULL "
    "DEFAULT '[]'::jsonb",
    "ALTER TABLE public.bom_lines ALTER COLUMN reference_designators DROP DEFAULT",
    "ALTER TABLE public.bom_lines ADD CONSTRAINT ck_bom_lines_reference_designators "
    "CHECK (jsonb_typeof(reference_designators) = 'array')",
    "ALTER TABLE public.bom_lines ADD COLUMN alternates jsonb NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE public.bom_lines ALTER COLUMN alternates DROP DEFAULT",
    "ALTER TABLE public.bom_lines ADD CONSTRAINT ck_bom_lines_alternates "
    "CHECK (jsonb_typeof(alternates) = 'array')",
    "ALTER TABLE public.bom_revisions ADD COLUMN import_basis jsonb",
    "ALTER TABLE public.bom_revisions ADD CONSTRAINT ck_bom_revisions_import_basis "
    "CHECK (import_basis IS NULL OR jsonb_typeof(import_basis) = 'object')",
)
DOWN_SQL = (
    """DO $$ BEGIN
     IF EXISTS(SELECT 1 FROM public.bom_lines WHERE reference_designators<>'[]'::jsonb
       OR alternates<>'[]'::jsonb)
     OR EXISTS(SELECT 1 FROM public.bom_revisions WHERE import_basis IS NOT NULL) THEN
     RAISE EXCEPTION 'BOM designators, alternates and import provenance require s0_0900';
     END IF; END $$""",
    "ALTER TABLE public.bom_revisions DROP CONSTRAINT ck_bom_revisions_import_basis",
    "ALTER TABLE public.bom_revisions DROP COLUMN import_basis",
    "ALTER TABLE public.bom_lines DROP CONSTRAINT ck_bom_lines_alternates",
    "ALTER TABLE public.bom_lines DROP COLUMN alternates",
    "ALTER TABLE public.bom_lines DROP CONSTRAINT ck_bom_lines_reference_designators",
    "ALTER TABLE public.bom_lines DROP COLUMN reference_designators",
)

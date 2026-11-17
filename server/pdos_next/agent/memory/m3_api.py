"""M3 routes: 我的工作 · 记忆复核, correction routes, revision review, system rules.

Personal routes are for the human acting for themself; the revision review and
system-rule routes for a current tenant administrator, named. None is a T0/T1/T2
business command: a review item or a revision candidate is not a business
record. The writes they lead to keep their own paths (``scope_note.save`` for a
team note, the "我的记忆" path for a personal note, the prompt and skill
activation flows for a draft).
"""

from uuid import UUID


def register(result, transaction, context_dependency):
    from . import corrections, distillation, procedural

    @result.get("/v1/personal/memory/review-items")
    def reading_review_items(ctx=context_dependency):
        with transaction(ctx, read_snapshot=True) as session:
            return corrections.listing(session, ctx)

    @result.post("/v1/personal/memory/review-items/{item_id}/routes")
    def routing_correction(item_id: UUID, data: corrections.RouteInput, ctx=context_dependency):
        with transaction(ctx) as session:
            return corrections.add_route(session, ctx, item_id, data)

    @result.post("/v1/personal/memory/review-items/{item_id}/decision")
    def deciding_review_item(item_id: UUID, data: corrections.DecisionInput,
                             ctx=context_dependency):
        with transaction(ctx) as session:
            return corrections.decide(session, ctx, item_id, data)

    @result.get("/v1/personal/memory-policy/skill-revisions")
    def reading_revisions(ctx=context_dependency):
        # The administrator check takes a share lock, so this is not a read-only snapshot.
        with transaction(ctx) as session:
            return procedural.listing(session, ctx)

    @result.post("/v1/personal/memory-policy/skill-revisions/{candidate_id}/decision")
    def deciding_revision(candidate_id: UUID, data: procedural.RevisionDecision,
                          ctx=context_dependency):
        with transaction(ctx) as session:
            return procedural.decide(session, ctx, candidate_id, data)

    @result.get("/v1/personal/memory-policy/system-rules")
    def reading_rules(ctx=context_dependency):
        with transaction(ctx) as session:
            procedural._admin(session, ctx)
            return distillation.rules_view(session, ctx.tenant_id)

    @result.post("/v1/personal/memory-policy/system-rules/{rule_key}")
    def setting_rule(rule_key: str, data: distillation.RuleSetting, ctx=context_dependency):
        with transaction(ctx) as session:
            return distillation.set_rule(session, ctx, rule_key, data)

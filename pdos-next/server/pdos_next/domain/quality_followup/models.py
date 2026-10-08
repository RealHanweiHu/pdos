"""No new aggregate or Current table.

Root's append_issue callback appends the existing QualityIssueVersion and moves
its existing QualityIssueCurrent, including actioning → awaiting_verification.
Root owns the corresponding model checks/registration/monotonic migration.
"""

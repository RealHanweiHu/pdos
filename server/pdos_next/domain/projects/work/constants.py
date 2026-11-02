"""Closed operation identities; none is a T2 or external action."""

CREATE = "work.task.create"
ASSIGN = "work.task.assign"
ACCEPT = "work.task.accept"
COMMIT = "work.commitment.accept"
START = "work.task.start"
SUBMIT = "work.task.submit"
REVIEW = "work.task.review"
STATUS = "work.status_update.create"
OPERATIONS = {
    CREATE: ("T0", "task.created"),
    ASSIGN: ("T1", "task.assigned"),
    ACCEPT: ("T1", "task.accepted"),
    COMMIT: ("T1", "commitment.accepted"),
    START: ("T1", "task.started"),
    SUBMIT: ("T1", "task.submitted"),
    REVIEW: ("T1", "task.reviewed"),
    STATUS: ("T1", "project.status_updated"),
}
TASK_OPERATIONS = frozenset({CREATE, ASSIGN, ACCEPT, START, SUBMIT, REVIEW})

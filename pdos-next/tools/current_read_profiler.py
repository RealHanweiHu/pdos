"""Explicit same-Engine observational timing; Root-only unless workers are enabled."""

from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from hashlib import sha256
from inspect import getsourcefile, iscoroutinefunction
from pathlib import Path
from re import match
from threading import RLock, current_thread, get_ident, local
from time import perf_counter_ns
from types import ModuleType

from sqlalchemy import event
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

_LOCK = RLock()
_ACTIVE_ENGINES = set()
_ACTIVE_TARGETS = set()
_SQL_VERBS = frozenset(
    "SELECT INSERT UPDATE DELETE WITH CREATE ALTER DROP BEGIN COMMIT ROLLBACK "
    "SAVEPOINT RELEASE SET SHOW EXPLAIN GRANT REVOKE TRUNCATE ANALYZE VACUUM "
    "LOCK DO COPY DISCARD RESET".split()
)


@dataclass(frozen=True)
class OwnerTarget:
    module: ModuleType
    attribute: str
    label: str


def _label(value):
    if type(value) is not str or match(r"[A-Za-z0-9_.:-]{1,100}\Z", value) is None:
        raise ValueError("Use a static safe timing label, without data or credentials")
    return value


def _binding(function):
    source = getsourcefile(function)
    path = Path(source) if source is not None else None
    return {
        "module": function.__module__,
        "qualname": function.__qualname__,
        "source_file": str(path.resolve()) if path is not None else None,
        "file_sha256": sha256(path.read_bytes()).hexdigest()
        if path is not None and path.is_file()
        else None,
    }


def _verb(statement):
    text = statement.lstrip()
    # Summarization only: no rewritten statement or normalized params reach SQLA.
    for _ in range(8):
        if text.startswith("--"):
            _, separator, text = text.partition("\n")
            if not separator:
                return "UNKNOWN"
        elif text.startswith("/*"):
            _, separator, text = text.partition("*/")
            if not separator:
                return "UNKNOWN"
        else:
            break
        text = text.lstrip()
    token = match(r"[A-Za-z]+", text)
    verb = token.group(0).upper() if token is not None else "UNKNOWN"
    return verb if verb in _SQL_VERBS else "UNKNOWN"


class CurrentReadProfiler:
    """Wrap explicit module functions and Engine events in one exclusive context.

    Default mode retains the original Root-only observation. Worker mode requires
    an exact actual Session/Connection binding for owners. Worker SQL is never
    attributed to Root sections; no thread or request correlation is invented.
    Existing local aliases may bypass declared module attributes.
    """

    def __init__(self, engine, targets, *, case_label="root_case", include_worker_threads=False):
        if not isinstance(engine, Engine):
            raise TypeError("Supply the actual SQLAlchemy Engine, not a Session/proxy")
        if type(include_worker_threads) is not bool:
            raise TypeError("Worker observation requires an explicit boolean")
        self.engine = engine
        self.targets = tuple(targets)
        self.case_label = _label(case_label)
        self.include_worker_threads = include_worker_threads
        self._entered = False
        self._closed = False
        self._root_thread = None
        self._started = None
        self._finished = None
        self._patched = []
        self._listeners = []
        self._data_lock = RLock()
        self._thread_local = local()
        self._thread_states = {}
        self._section_stack = []
        self._inflight = defaultdict(list)
        self._owners = defaultdict(lambda: defaultdict(int))
        self._sections = defaultdict(lambda: defaultdict(int))
        self._queries = defaultdict(lambda: defaultdict(int))
        self._bindings = {}
        self._conditions = defaultdict(int)

    def __enter__(self):
        if self._entered or self._closed:
            raise RuntimeError("One profiler instance supports one context only")
        keys = []
        originals = []
        labels = set()
        for target in self.targets:
            if not isinstance(target, OwnerTarget) or not isinstance(target.module, ModuleType):
                raise TypeError("Owner targets must identify explicit module attributes")
            _label(target.attribute)
            _label(target.label)
            key = (target.module, target.attribute)
            original = getattr(target.module, target.attribute)
            if key in keys or target.label in labels:
                raise ValueError("Target attributes and labels must be unique")
            if not callable(original) or iscoroutinefunction(original):
                raise TypeError("This tool supports synchronous callable owners only")
            keys.append(key)
            labels.add(target.label)
            originals.append(original)
            self._bindings[target.label] = _binding(original)
        with _LOCK:
            if self.engine in _ACTIVE_ENGINES or any(key in _ACTIVE_TARGETS for key in keys):
                raise RuntimeError("Concurrent/nested profiler ownership is forbidden")
            _ACTIVE_ENGINES.add(self.engine)
            _ACTIVE_TARGETS.update(keys)
        self._root_thread = get_ident()
        self._entered = True
        self._started = perf_counter_ns()
        try:
            for target, original in zip(self.targets, originals, strict=True):
                wrapper = self._wrap(target.label, original)
                self._patched.append((target, original, wrapper))
                setattr(target.module, target.attribute, wrapper)
            for name, callback in (
                ("before_cursor_execute", self._before),
                ("after_cursor_execute", self._after),
                ("handle_error", self._error),
            ):
                event.listen(self.engine, name, callback)
                self._listeners.append((name, callback))
        except BaseException:
            self._restore()
            raise
        return self

    def __exit__(self, exc_type, exc, traceback):
        # No exception or result is suppressed/replaced by normal cleanup.
        self._restore()
        return False

    def _root(self):
        return self._entered and get_ident() == self._root_thread

    def _thread_state(self):
        state = getattr(self._thread_local, "state", None)
        if state is None:
            state = {"owners": []}
            self._thread_local.state = state
        self._thread_states[current_thread()] = state
        return state

    def _owner_scope(self, args, kwargs, state):
        if not self.include_worker_threads:
            return get_ident() == self._root_thread
        session = args[0] if args else kwargs.get("s", kwargs.get("session"))
        if isinstance(session, Session):
            # Read the actual local bind; do not call a custom get_bind resolver,
            # query a Session, discover URLs, or infer scope from SQL/payload data.
            bound = session.bind
            if bound is self.engine or (
                isinstance(bound, Connection) and bound.engine is self.engine
            ):
                return True
            if isinstance(bound, (Engine, Connection)):
                self._conditions["owner_calls_bound_to_another_engine"] += 1
                return False
        self._conditions["owner_calls_without_exact_engine_binding"] += 1
        return False

    def _wrap(self, label, original):
        @wraps(original)
        def wrapper(*args, **kwargs):
            frame, state = None, None
            try:
                with self._data_lock:
                    if self._entered and (self.include_worker_threads or self._root()):
                        state = self._thread_state()
                        if self._owner_scope(args, kwargs, state):
                            frame = {"label": label, "started": perf_counter_ns(), "children": 0}
                            state["owners"].append(frame)
            except Exception:
                with self._data_lock:
                    if self._entered:
                        self._conditions["owner_observation_failures"] += 1
            if frame is None:
                return original(*args, **kwargs)
            failed = False
            try:
                return original(*args, **kwargs)
            except BaseException:
                failed = True
                raise
            finally:
                elapsed = perf_counter_ns() - frame["started"]
                with self._data_lock:
                    state["owners"].pop()
                    if state["owners"]:
                        state["owners"][-1]["children"] += elapsed
                    if self._entered:
                        stats = self._owners[label]
                        stats["calls"] += 1
                        stats["failures"] += int(failed)
                        stats["inclusive_ns"] += elapsed
                        stats["exclusive_ns"] += max(0, elapsed - frame["children"])

        return wrapper

    @contextmanager
    def section(self, label):
        """Label existing work/wait; do not replace sleep or any domain clock."""
        if not self._root():
            raise RuntimeError("Sections require the entered context's original Root thread")
        label = _label(label)
        frame = {"label": label, "started": perf_counter_ns(), "children": 0}
        self._section_stack.append(frame)
        try:
            yield
        finally:
            elapsed = perf_counter_ns() - frame["started"]
            self._section_stack.pop()
            if self._section_stack:
                self._section_stack[-1]["children"] += elapsed
            stats = self._sections[label]
            stats["calls"] += 1
            stats["inclusive_ns"] += elapsed
            stats["exclusive_ns"] += max(0, elapsed - frame["children"])

    def _before(self, conn, cursor, statement, parameters, context, executemany):
        try:
            with self._data_lock:
                if not self._entered or conn.engine is not self.engine:
                    return
                is_root = get_ident() == self._root_thread
                if not self.include_worker_threads and not is_root:
                    return
                state = self._thread_state()
                key = (
                    sha256(statement.encode("utf-8", errors="replace")).hexdigest(),
                    _verb(statement),
                    state["owners"][-1]["label"]
                    if state["owners"]
                    else ("root" if is_root else "unattributed"),
                    self._section_stack[-1]["label"]
                    if is_root and self._section_stack
                    else "unsectioned"
                    if is_root
                    else "unattributed",
                )
                pair = (current_thread(), id(conn), id(context))
                self._inflight[pair].append((key, perf_counter_ns(), bool(executemany)))
        except Exception:
            with self._data_lock:
                if self._entered:
                    self._conditions["query_observation_failures"] += 1

    def _finish_query(self, conn, context, *, failed):
        try:
            with self._data_lock:
                if not self._entered or conn is None or conn.engine is not self.engine:
                    return
                is_root = get_ident() == self._root_thread
                if not self.include_worker_threads and not is_root:
                    return
                pair = (current_thread(), id(conn), id(context))
                frames = self._inflight.get(pair)
                if not frames:
                    self._conditions["unmatched_completion_events"] += 1
                    return
                key, started, many = frames.pop()
                if not frames:
                    del self._inflight[pair]
                elapsed = perf_counter_ns() - started
                stats = self._queries[key]
                stats["count"] += 1
                stats["failures"] += int(failed)
                stats["executemany_calls"] += int(many)
                stats["elapsed_ns"] += elapsed
                if not is_root:
                    self._conditions["unattributed_worker_section_queries"] += 1
        except Exception:
            with self._data_lock:
                if self._entered:
                    self._conditions["query_observation_failures"] += 1

    def _after(self, conn, cursor, statement, parameters, context, executemany):
        self._finish_query(conn, context, failed=False)

    def _error(self, exception_context):
        # Observe only identity/timing; never serialize exceptions/params/rows.
        context = exception_context.execution_context
        if context is not None:
            self._finish_query(exception_context.connection, context, failed=True)

    def _restore(self):
        if self._closed:
            return
        with self._data_lock:
            self._finished = perf_counter_ns()
            self._entered = False
            self._conditions["active_owner_calls_at_exit"] = sum(
                len(state["owners"]) for state in self._thread_states.values()
            )
            self._conditions["observed_threads"] = len(self._thread_states)
        for name, callback in reversed(self._listeners):
            try:
                event.remove(self.engine, name, callback)
            except Exception:
                # Instrumentation cleanup must not replace a domain exception.
                # The report marks the case invalid; an inactive listener makes
                # no observations and never changes SQL/parameters/return values.
                self._conditions["listener_cleanup_failures"] += 1
        self._listeners.clear()
        for target, original, wrapper in reversed(self._patched):
            if getattr(target.module, target.attribute) is not wrapper:
                self._conditions["target_changed_during_measurement"] += 1
            setattr(target.module, target.attribute, original)
        with _LOCK:
            _ACTIVE_ENGINES.discard(self.engine)
            for target in self.targets:
                _ACTIVE_TARGETS.discard((target.module, target.attribute))
        with self._data_lock:
            self._conditions["unfinished_queries"] = sum(map(len, self._inflight.values()))
            self._inflight.clear()
            self._thread_states.clear()  # Never clear a still-running owner's local stack.
            self._closed = True

    def report(self):
        if not self._closed:
            raise RuntimeError("Report only after finally restored the measured context")
        queries = [
            {
                "statement_sha256": key[0],
                "verb": key[1],
                "owner": key[2],
                "section": key[3],
                **stats,
            }
            for key, stats in sorted(self._queries.items())
        ]
        return {
            "schema_version": "pdos-root-current-read-profile-v2"
            if self.include_worker_threads
            else "pdos-root-current-read-profile-v1",
            "case_label": self.case_label,
            "elapsed_ns": self._finished - self._started,
            "scope": {
                "root_thread_only": not self.include_worker_threads,
                "worker_threads_explicitly_enabled": self.include_worker_threads,
                "worker_owner_requires_exact_session_engine_binding": self.include_worker_threads,
                "worker_sections_are_unattributed_never_inherit_root_section": True,
                "sql_pairs_use_thread_connection_execution_context": True,
                "concurrent_owner_durations_can_exceed_wall_time": self.include_worker_threads,
                "same_actual_engine_only": True,
                "source_bindings_captured_before_install": True,
                "sections_are_explicit_labels_not_inferred_sleep": True,
                "nested_inclusive_durations_overlap_do_not_sum": True,
                "instrumentation_overhead_is_included": True,
                "existing_local_aliases_may_bypass_wrapped_module_attributes": True,
                "no_domain_clock_transaction_return_value_owner_read_set_changed": True,
                "sql_params_text_rows_credentials_emitted": False,
            },
            "source_bindings": self._bindings,
            "profiler_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "owners": {key: dict(value) for key, value in sorted(self._owners.items())},
            "sections": {key: dict(value) for key, value in sorted(self._sections.items())},
            "query_count": sum(value["count"] for value in self._queries.values()),
            "queries": queries,
            "conditions": dict(self._conditions),
            "measurement_is_not_qualification_or_execution_permission": True,
        }

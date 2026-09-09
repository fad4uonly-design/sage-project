"""SOUP service implementation — experiment comparison, trial recording, and ranking."""

from __future__ import annotations

import inspect
from typing import Any

from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.events.bus import EventBus
from sage.events.events import Event
from sage.evolver.service import EvolverRepository
from sage.logging import get_logger
from sage.soup.interfaces import SoupEngine, VariantRunner
from sage.soup.introspect import DecisionTrace, build_decision_trace_from_report
from sage.soup.models import (
    EvalCase,
    SoupRankingEntry,
    SoupReport,
    SoupRun,
    SoupTrial,
    SoupTrialResult,
)
from sage.soup.scorer import CaseScorer, clamp_score, keyword_overlap_scorer
from sage.utils.time import utcnow_iso

log = get_logger(__name__)


async def default_stub_runner(payload: str, test_input: str) -> str:
    """Stub variant runner: echoes payload with test input (zero-cost offline default)."""
    return f"[variant] {payload}\n[input] {test_input}"


class SoupRepository(BaseRepository):
    """Database repository for SOUP runs and trials."""

    def __init__(self, db: Database) -> None:
        super().__init__(db)

    async def get_run_by_id(self, run_id: str) -> SoupRun | None:
        row = await self.db.fetchone("SELECT * FROM soup_runs WHERE id = ?", (run_id,))
        if row is None:
            return None
        return self._row_to_run(row)

    async def get_trials_by_run(self, run_id: str) -> list[SoupTrial]:
        rows = await self.db.fetchall("SELECT * FROM soup_trials WHERE run_id = ?", (run_id,))
        return [self._row_to_trial(r) for r in rows]

    async def insert_run(self, run: SoupRun) -> None:
        await self.db.execute(
            """
            INSERT INTO soup_runs (
                id, name, eval_set_name, baseline_variant_id, winner_variant_id, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.id,
                run.name,
                run.eval_set_name,
                run.baseline_variant_id,
                run.winner_variant_id,
                run.status,
                run.created_at,
            ),
        )

    async def insert_trials(self, trials: list[SoupTrial]) -> None:
        for t in trials:
            await self.db.execute(
                """
                INSERT INTO soup_trials (
                    id, run_id, variant_id, case_id, score, response, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (t.id, t.run_id, t.variant_id, t.case_id, t.score, t.response, t.created_at),
            )

    def _row_to_run(self, row: Any) -> SoupRun:
        return SoupRun(
            id=row["id"],
            name=row["name"],
            eval_set_name=row["eval_set_name"],
            baseline_variant_id=row["baseline_variant_id"],
            winner_variant_id=row["winner_variant_id"],
            status=row["status"],
            created_at=row["created_at"],
        )

    def _row_to_trial(self, row: Any) -> SoupTrial:
        return SoupTrial(
            id=row["id"],
            run_id=row["run_id"],
            variant_id=row["variant_id"],
            case_id=row["case_id"],
            score=row["score"],
            response=row["response"],
            created_at=row["created_at"],
        )


class SoupService(SoupEngine):
    """SOUP subsystem coordinator for running multi-variant offline comparisons."""

    def __init__(
        self,
        db: Database,
        evolver_repo: EvolverRepository,
        events: EventBus | None = None,
    ) -> None:
        self._repo = SoupRepository(db)
        self._evolver_repo = evolver_repo
        self._events = events

    async def run_comparison(
        self,
        *,
        name: str,
        variant_ids: list[str],
        eval_set: list[EvalCase],
        runner: VariantRunner | None = None,
        scorer: CaseScorer | None = None,
        eval_set_name: str = "builtin",
    ) -> SoupReport:
        """Execute a full SOUP comparison experiment."""
        if not variant_ids:
            raise ValueError("SOUP requires at least one variant ID (the baseline).")
        if not eval_set:
            raise ValueError("SOUP requires a non-empty eval set.")

        actual_runner = runner or default_stub_runner
        actual_scorer = scorer or keyword_overlap_scorer

        # Validate and load all variants
        variants = []
        for vid in variant_ids:
            v = await self._evolver_repo.get_by_id(vid)
            if v is None:
                raise KeyError(f"Variant not found: {vid}")
            if v.status == "retired":
                raise ValueError(f"Variant {vid} is retired and cannot be compared.")
            variants.append(v)

        baseline_variant_id = variant_ids[0]
        ranking: list[SoupRankingEntry] = []
        trials_to_persist: list[SoupTrial] = []

        run_id = f"soup_{utcnow_iso().replace(':', '').replace('-', '').replace('.', '')[:15]}"
        now = utcnow_iso()

        for variant in variants:
            per_case: list[SoupTrialResult] = []
            for test_case in eval_set:
                # Execute runner (async or sync)
                if inspect.iscoroutinefunction(actual_runner):
                    response = await actual_runner(variant.payload, test_case.input)
                else:
                    res = actual_runner(variant.payload, test_case.input)
                    if inspect.isawaitable(res):
                        response = await res
                    else:
                        response = res

                raw_score = actual_scorer(response, test_case)
                score = clamp_score(raw_score)

                trial_res = SoupTrialResult(
                    case_id=test_case.id,
                    score=score,
                    response=response,
                )
                per_case.append(trial_res)

                trials_to_persist.append(
                    SoupTrial(
                        run_id=run_id,
                        variant_id=variant.id,
                        case_id=test_case.id,
                        score=score,
                        response=response,
                        created_at=now,
                    )
                )

            mean_score = sum(c.score for c in per_case) / len(per_case) if per_case else 0.0
            ranking.append(
                SoupRankingEntry(
                    variant_id=variant.id,
                    name=variant.name,
                    is_baseline=(variant.id == baseline_variant_id),
                    mean_score=round(mean_score, 2),
                    per_case=per_case,
                )
            )

        # Winner calculation: best challenger that strictly beats baseline
        baseline = next((e for e in ranking if e.is_baseline), ranking[0])
        challengers = [e for e in ranking if not e.is_baseline]

        winner: SoupRankingEntry | None = None
        if challengers:
            best_challenger = max(challengers, key=lambda e: e.mean_score)
            if best_challenger.mean_score > baseline.mean_score:
                winner = best_challenger

        winner_variant_id = winner.variant_id if winner else None
        margin = round(winner.mean_score - baseline.mean_score, 2) if winner else None

        # Persist run and trials
        soup_run = SoupRun(
            id=run_id,
            name=name.strip(),
            eval_set_name=eval_set_name,
            baseline_variant_id=baseline_variant_id,
            winner_variant_id=winner_variant_id,
            status="completed",
            created_at=now,
        )

        await self._repo.insert_run(soup_run)
        if trials_to_persist:
            await self._repo.insert_trials(trials_to_persist)

        # Mark evaluated status in evolver
        for entry in ranking:
            try:
                await self._evolver_repo.update_status(entry.variant_id, "evaluated")
            except Exception as exc:
                log.warning("soup.update_status_failed", variant_id=entry.variant_id, error=str(exc))

        report = SoupReport(
            run_id=run_id,
            baseline_variant_id=baseline_variant_id,
            winner_variant_id=winner_variant_id,
            ranking=ranking,
            margin=margin,
        )

        log.info(
            "soup.comparison_completed",
            run_id=run_id,
            baseline=baseline_variant_id,
            winner=winner_variant_id,
            margin=margin,
        )

        if self._events:
            await self._events.publish(
                Event(
                    type="soup.comparison_completed",
                    payload={
                        "run_id": run_id,
                        "winner_variant_id": winner_variant_id,
                        "margin": margin,
                    },
                    source="soup",
                )
            )

        return report

    async def get_run(self, run_id: str) -> SoupRun | None:
        return await self._repo.get_run_by_id(run_id)

    async def get_trials(self, run_id: str) -> list[SoupTrial]:
        return await self._repo.get_trials_by_run(run_id)

    async def get_decision_trace(self, run_id: str) -> DecisionTrace:
        """Build an explainable decision trace for a completed run."""
        run = await self.get_run(run_id)
        if run is None:
            raise KeyError(f"SOUP run not found: {run_id}")

        trials = await self.get_trials(run_id)
        variant_ids = list({t.variant_id for t in trials})

        # Reconstruct SoupReport from persistent trials
        ranking: list[SoupRankingEntry] = []
        for vid in variant_ids:
            v = await self._evolver_repo.get_by_id(vid)
            v_name = v.name if v else f"variant#{vid}"
            v_trials = [t for t in trials if t.variant_id == vid]
            per_case = [
                SoupTrialResult(case_id=t.case_id, score=t.score, response=t.response)
                for t in v_trials
            ]
            mean_score = sum(t.score for t in per_case) / len(per_case) if per_case else 0.0
            ranking.append(
                SoupRankingEntry(
                    variant_id=vid,
                    name=v_name,
                    is_baseline=(vid == run.baseline_variant_id),
                    mean_score=round(mean_score, 2),
                    per_case=per_case,
                )
            )

        baseline_entry = next((e for e in ranking if e.is_baseline), ranking[0])
        winner_entry = next((e for e in ranking if e.variant_id == run.winner_variant_id), None)
        margin = round(winner_entry.mean_score - baseline_entry.mean_score, 2) if winner_entry else None

        report = SoupReport(
            run_id=run.id,
            baseline_variant_id=run.baseline_variant_id,
            winner_variant_id=run.winner_variant_id,
            ranking=ranking,
            margin=margin,
        )

        return build_decision_trace_from_report(report, run.name, run.eval_set_name)


class SoupModule(BaseModule):
    """Lifecycle and dependency injection module for the SOUP subsystem."""

    name = "soup"
    version = "0.6.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._service: SoupService | None = None

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        # Ensure SOUP tables exist
        try:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS soup_runs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    eval_set_name TEXT NOT NULL,
                    baseline_variant_id TEXT NOT NULL,
                    winner_variant_id TEXT,
                    status TEXT NOT NULL DEFAULT 'completed',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_soup_runs_status ON soup_runs(status);

                CREATE TABLE IF NOT EXISTS soup_trials (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    variant_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    score REAL NOT NULL,
                    response TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_soup_trials_run ON soup_trials(run_id);
                CREATE INDEX IF NOT EXISTS idx_soup_trials_variant ON soup_trials(variant_id);
                """
            )
        except Exception:
            log.exception("soup.table_init_failed")

        evolver_repo = self.container.resolve(EvolverRepository)
        events = self.container.try_resolve(EventBus)

        self._service = SoupService(db, evolver_repo, events)
        self.container.register_instance(SoupRepository, self._service._repo)
        self.container.register_instance(SoupService, self._service)
        self.container.register_instance(SoupEngine, self._service)

    async def _on_health(self) -> HealthStatus | None:
        if self._service is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        return HealthStatus.healthy(self.name, "ok")


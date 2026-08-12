"""Fail-closed before/after regression comparison infrastructure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..domain import JSONValue
from ..evidence import deterministic_id, sha256_digest


@dataclass(frozen=True, slots=True)
class RegressionState:
    state_id: str
    functional: Mapping[str, str]
    capabilities: Mapping[str, Mapping[str, JSONValue]]
    compatibility: Mapping[str, str]
    configuration: Mapping[str, str]
    risks: Mapping[str, Mapping[str, JSONValue]]

    @property
    def digest(self) -> str:
        return sha256_digest(
            {
                "state_id": self.state_id,
                "functional": dict(self.functional),
                "capabilities": {key: dict(value) for key, value in self.capabilities.items()},
                "compatibility": dict(self.compatibility),
                "configuration": dict(self.configuration),
                "risks": {key: dict(value) for key, value in self.risks.items()},
            }
        )


@dataclass(frozen=True, slots=True)
class RegressionPlanV3:
    plan_id: str
    mandatory_checks: tuple[str, ...]
    expected_configuration_changes: tuple[str, ...]
    fail_closed: bool = True

    @property
    def digest(self) -> str:
        return sha256_digest(
            {
                "plan_id": self.plan_id,
                "mandatory_checks": list(self.mandatory_checks),
                "expected_configuration_changes": list(self.expected_configuration_changes),
                "fail_closed": self.fail_closed,
            }
        )


@dataclass(frozen=True, slots=True)
class RegressionFinding:
    check_id: str
    category: str
    outcome: str
    mandatory: bool
    before: JSONValue
    after: JSONValue
    reason: str


@dataclass(frozen=True, slots=True)
class RegressionComparison:
    comparison_id: str
    before_digest: str
    after_digest: str
    plan_digest: str
    verdict: str
    findings: tuple[RegressionFinding, ...]
    configuration_changes: tuple[str, ...]
    new_risks: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.verdict == "PASS"


class RegressionFramework:
    def compare(
        self,
        before: RegressionState,
        after: RegressionState,
        plan: RegressionPlanV3,
    ) -> RegressionComparison:
        findings: list[RegressionFinding] = []
        mandatory = set(plan.mandatory_checks)

        for check in sorted(mandatory):
            category, separator, name = check.partition(":")
            if not separator:
                findings.append(
                    RegressionFinding(check, "plan", "FAIL", True, None, None, "Malformed mandatory check")
                )
                continue
            if category == "functional":
                old = before.functional.get(name)
                new = after.functional.get(name)
                passed = new == "PASS" and (old in {None, "PASS"})
                reason = "Functional check passed" if passed else "Functional behavior regressed or is missing"
            elif category == "capability":
                old = before.capabilities.get(name)
                new = after.capabilities.get(name)
                passed = _capability_not_regressed(old, new)
                reason = "Capability retained/improved" if passed else "Validated capability regressed or is missing"
            elif category == "compatibility":
                old = before.compatibility.get(name)
                new = after.compatibility.get(name)
                passed = _compatibility_rank(new) >= _compatibility_rank(old)
                reason = "Compatibility retained/improved" if passed else "Compatibility regressed or is missing"
            elif category == "configuration":
                old = before.configuration.get(name)
                new = after.configuration.get(name)
                passed = new is not None
                reason = "Configuration state captured" if passed else "Configuration state missing"
            elif category == "risk":
                old = before.risks.get(name)
                new = after.risks.get(name)
                passed = not _blocking_risk(new)
                reason = "No blocking risk" if passed else "Blocking risk present"
            else:
                old = new = None
                passed = False
                reason = "Unknown regression category"
            findings.append(
                RegressionFinding(
                    check_id=check,
                    category=category,
                    outcome="PASS" if passed else "FAIL",
                    mandatory=True,
                    before=_json(old),
                    after=_json(new),
                    reason=reason,
                )
            )

        configuration_changes = tuple(
            sorted(
                key
                for key in set(before.configuration) | set(after.configuration)
                if before.configuration.get(key) != after.configuration.get(key)
            )
        )
        unexpected_changes = set(configuration_changes) - set(plan.expected_configuration_changes)
        if unexpected_changes:
            findings.append(
                RegressionFinding(
                    check_id="configuration:unexpected_changes",
                    category="configuration",
                    outcome="FAIL",
                    mandatory=True,
                    before=list(sorted(before.configuration)),
                    after=list(sorted(after.configuration)),
                    reason="Unexpected configuration changes: " + ", ".join(sorted(unexpected_changes)),
                )
            )

        new_risks = tuple(
            sorted(
                key
                for key, risk in after.risks.items()
                if key not in before.risks and _blocking_risk(risk)
            )
        )
        if new_risks:
            findings.append(
                RegressionFinding(
                    check_id="risk:new_blocking",
                    category="risk",
                    outcome="FAIL",
                    mandatory=True,
                    before=[],
                    after=list(new_risks),
                    reason="New blocking risks were introduced",
                )
            )
        failed = any(item.mandatory and item.outcome != "PASS" for item in findings)
        verdict = "FAIL" if failed and plan.fail_closed else ("INCONCLUSIVE" if failed else "PASS")
        comparison_id = deterministic_id(
            "regression-comparison", before.digest, after.digest, plan.digest
        )
        return RegressionComparison(
            comparison_id=comparison_id,
            before_digest=before.digest,
            after_digest=after.digest,
            plan_digest=plan.digest,
            verdict=verdict,
            findings=tuple(findings),
            configuration_changes=configuration_changes,
            new_risks=new_risks,
        )


def _capability_not_regressed(old, new) -> bool:
    if old is None:
        return new is not None and new.get("validation") == "VALIDATED"
    if old.get("validation") == "VALIDATED":
        if new is None or new.get("validation") != "VALIDATED":
            return False
        old_score = old.get("score")
        new_score = new.get("score")
        if isinstance(old_score, (int, float)) and isinstance(new_score, (int, float)):
            return new_score >= old_score
    return new is not None


def _compatibility_rank(value) -> int:
    return {
        None: -1,
        "INCOMPATIBLE": 0,
        "UNKNOWN": 1,
        "COMPATIBLE_WITH_ADAPTER": 2,
        "COMPATIBLE": 3,
    }.get(value, -1)


def _blocking_risk(value) -> bool:
    return bool(value and value.get("blocking")) or bool(
        value and value.get("severity") in {"CRITICAL"}
    )


def _json(value) -> JSONValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return str(value)

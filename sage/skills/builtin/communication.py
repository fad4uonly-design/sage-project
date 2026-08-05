"""Shared communication skills."""

from __future__ import annotations

from sage.skills.base import BaseSkill
from sage.skills.models import SkillCategory, SkillManifest, SkillRequest, SkillResult


class EmailDraftSkill(BaseSkill):
    manifest = SkillManifest(
        id="skill_comm_email",
        name="Email Drafting",
        category=SkillCategory.COMMUNICATION,
        description="Professional email draft structure",
        tags=["email", "draft email", "write an email", "message to"],
        examples=["draft email to supplier about delayed shipment"],
    )

    async def run(self, request: SkillRequest) -> SkillResult:
        task = self._task(request)
        lines = [
            "**Email Draft**",
            "",
            f"**Subject:** Re: {task[:80] or 'Follow-up'}",
            "",
            "Hi [Name],",
            "",
            f"I'm writing regarding {task[:120] or 'our recent discussion'}.",
            "",
            "**Context:** [1–2 sentences]",
            "**Request / next step:** [clear ask + date]",
            "**Why it matters:** [impact]",
            "",
            "Happy to adjust if needed — thank you,",
            "[Your name]",
        ]
        return self._ok(
            "\n".join(lines),
            steps=[{"id": "s1", "title": "Draft", "status": "done"}],
            confidence=0.7,
            request=request,
        )


class MeetingNotesSkill(BaseSkill):
    manifest = SkillManifest(
        id="skill_comm_meeting_notes",
        name="Meeting Notes",
        category=SkillCategory.COMMUNICATION,
        description="Meeting notes template with actions",
        tags=["meeting notes", "minutes", "standup notes", "meeting summary"],
        examples=["meeting notes template for weekly ops"],
    )

    async def run(self, request: SkillRequest) -> SkillResult:
        task = self._task(request)
        lines = [
            f"**Meeting Notes** — {task[:100] or 'Working session'}",
            "",
            "- **Attendees:** ",
            "- **Date:** ",
            "",
            "**Agenda / discussion**",
            "1. ",
            "2. ",
            "",
            "**Decisions**",
            "- ",
            "",
            "**Action items**",
            "| Owner | Action | Due |",
            "|---|---|---|",
            "|  |  |  |",
            "",
            "**Parking lot**",
            "- ",
        ]
        return self._ok(
            "\n".join(lines),
            steps=[{"id": "s1", "title": "Template", "status": "done"}],
            confidence=0.72,
            request=request,
        )


class ExecutiveBriefSkill(BaseSkill):
    manifest = SkillManifest(
        id="skill_comm_presentation",
        name="Presentation Brief",
        category=SkillCategory.COMMUNICATION,
        description="Slide-style presentation outline",
        tags=["presentation", "slides", "pitch deck", "briefing deck"],
        examples=["presentation outline for board update"],
    )

    async def run(self, request: SkillRequest) -> SkillResult:
        task = self._task(request)
        lines = [
            f"**Presentation Brief** — {task[:120]}",
            "",
            "1. Title & hook",
            "2. Problem / opportunity",
            "3. Insight (data)",
            "4. Options considered",
            "5. Recommendation",
            "6. Plan & resources",
            "7. Risks & mitigations",
            "8. Ask / decision needed",
            "",
            "One idea per slide; appendix ≤ 30.",
        ]
        return self._ok(
            "\n".join(lines),
            steps=[{"id": "s1", "title": "Outline", "status": "done"}],
            confidence=0.7,
            request=request,
        )

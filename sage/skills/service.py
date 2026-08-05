"""Skills module — boots shared Skill Library into DI."""

from __future__ import annotations

from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.logging import get_logger
from sage.permissions.interfaces import PermissionManager
from sage.skills.builtin import register_builtin_skills
from sage.skills.interfaces import SkillLibrary
from sage.skills.library import DefaultSkillLibrary

log = get_logger(__name__)


class SkillsModule(BaseModule):
    name = "skills"
    version = "0.3.2"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._lib: DefaultSkillLibrary | None = None

    async def _on_initialize(self) -> None:
        pm = self.container.try_resolve(PermissionManager)  # type: ignore[type-abstract]
        self._lib = DefaultSkillLibrary(permission_manager=pm)
        n = register_builtin_skills(self._lib)
        self.container.register_instance(SkillLibrary, self._lib)  # type: ignore[type-abstract]
        self.container.register_instance(DefaultSkillLibrary, self._lib)
        log.info("skills.ready", count=n)

    async def _on_health(self) -> HealthStatus | None:
        if self._lib is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        return HealthStatus.healthy(self.name, "ok", skills=self._lib.count())

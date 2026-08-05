"""Automation Manager — scheduled and event-driven workflow/skill triggers."""

from sage.automation.manager import AutomationManager, DefaultAutomationManager
from sage.automation.service import AutomationModule

__all__ = ["AutomationManager", "AutomationModule", "DefaultAutomationManager"]

"""Capability Registry — declare what agents/tools can do."""

from sage.capabilities.interfaces import CapabilityRegistry
from sage.capabilities.models import CapabilityDescriptor
from sage.capabilities.service import CapabilitiesModule

__all__ = ["CapabilityDescriptor", "CapabilityRegistry", "CapabilitiesModule"]

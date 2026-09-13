/**
 * SAGE Core
 *
 * Central intelligence orchestration boundary.
 *
 * Core owns the components that determine and produce SAGE's response:
 *   - router
 *   - brain
 *
 * The brain is SAGE's model-facing intelligence interface.
 * The concrete model provider remains swappable.
 *
 * Memory and notes remain explicit application capabilities for now.
 */
 
import { route } from "./router";
import { getArchitecture } from "./architecture";
import { getModelProvider } from "./model";

export function getSAGECore() {
  return {
    router: route,
    // Language is the current production role. Other text roles can be
    // configured independently through getModelProvider(role).
    brain: getModelProvider("language"),
    models: {
      forRole: getModelProvider,
    },
    architecture: getArchitecture(),
  };
}

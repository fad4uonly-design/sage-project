"""RouterSummarizer — a real ``SummarizeFn`` backed by ``ModelRouter``.

This is the SAGE-native, model-agnostic replacement for the blocked summarizer
slot. It implements the :class:`SummarizeFn` contract from
``sage.core.web_learner`` (topic + search results -> a concise summary string)
by routing the request through the existing ``ModelRouter`` to whichever
language model the runtime is configured with (by default the local Ollama
provider).

Design constraints honored here:

* No model, URL, or provider is hard-coded — ``ModelRouter.get_language_model()``
  applies the SAGE configuration (``models.default_provider``,
  ``models.local_model_name``, ``models.local_base_url`` ...).
* The existing ``LocalLanguageModel`` adapter is used through the normal routing
  path — no second model client is constructed.
* ``WebLearner`` is left untouched; its ``_BlockedSummarizer`` remains the safe,
  never-faking default. ``RouterSummarizer`` is simply an alternative
  ``SummarizeFn`` wired in explicitly when a live model runtime is present.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sage.core.web_learner import SummarizeFn, WebLearnError, WebResult
from sage.logging import get_logger
from sage.models.interfaces import CompletionRequest, Message, ModelRouter

log = get_logger(__name__)

#: Default system prompt for the summarization turn.
_DEFAULT_SYSTEM_PROMPT: Final[str] = (
    "You are a concise research assistant. Summarize the search results for the "
    "given topic into ONE factual paragraph (plain text, no markdown headers, no "
    "bulleted list). If the results conflict, note the conflict. If the results "
    "do not address the topic, say so briefly instead of fabricating."
)

#: Default budget for the generated summary.
_DEFAULT_MAX_TOKENS: Final[int] = 512


class RouterSummarizer:
    """``SummarizeFn`` backed by a ``ModelRouter`` -> configured language model.

    Args:
        router: the SAGE ``ModelRouter``; model/provider/base_url are obtained
            exclusively through ``router.get_language_model()``.
        system_prompt: optional override for the system turn.
        temperature: optional override; ``None`` lets the model/router default.
        max_tokens: optional override; ``None`` lets the model/router default.
    """

    def __init__(
        self,
        router: ModelRouter,
        *,
        system_prompt: str = _DEFAULT_SYSTEM_PROMPT,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        if router is None:  # defensive — the contract wants an explicit router
            raise ValueError("RouterSummarizer requires a ModelRouter instance")
        self._router = router
        self._system_prompt = system_prompt
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def __call__(self, topic: str, results: Sequence[WebResult]) -> str:
        # WebLearner only hands us usable, non-empty, deduped results, but guard
        # anyway: an empty input must not fabricate content.
        if not results:
            return ""

        parts: list[str] = [
            f"Topic: {topic.strip()}",
            "Summarize the following search results into one concise, factual paragraph:",
        ]
        for result in results:
            parts.append(f"[{result.source}]\n{result.content}")
        user_content = "\n\n".join(parts)

        request = CompletionRequest(
            messages=[
                Message(role="system", content=self._system_prompt),
                Message(role="user", content=user_content),
            ],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )

        # All model selection lives in the router; we never construct a client.
        try:
            model = self._router.get_language_model()
            response = await model.complete(request)
        except Exception as exc:  # surface as the domain error SAGE expects
            raise WebLearnError(f"RouterSummarizer model call failed: {exc}") from exc

        summary = (response.content or "").strip()
        if not summary:
            raise WebLearnError("RouterSummarizer produced an empty summary")
        return summary


def make_router_summarizer(router: ModelRouter) -> SummarizeFn:
    """Convenience factory: a ``RouterSummarizer`` bound to ``router``."""
    return RouterSummarizer(router)

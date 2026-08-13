from __future__ import annotations

from .config import settings


# v0.20.5 intentionally has no text-grid protocol.  Vision-language models
# are good at judging and designing images, not at reliably emitting thousands
# of position-sensitive characters.  The configured image model returns the
# model-authored pattern visual; pattern_engine then performs only mechanical
# sampling and official-colour mapping.
PLANNER_VERSION = "direct-pattern-image-v6"


def planner_status() -> dict:
    provider = settings.image_provider.strip().lower()
    configured = (
        settings.dashscope_api_key is not None and bool(settings.dashscope_workspace_id)
        if provider == "dashscope"
        else settings.openai_api_key is not None
    )
    return {
        "enabled": settings.pattern_ai_mode != "off",
        "configured": configured,
        "provider": provider,
        "model": settings.image_model,
        "plannerVersion": PLANNER_VERSION,
    }

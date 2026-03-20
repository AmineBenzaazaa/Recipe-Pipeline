from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptDraft:
    prompt_type: str
    prompt_text: str
    placement: str
    description: str
    seo_metadata: dict
    aspect_ratio: str

    def to_payload(self) -> dict:
        return {
            "type": self.prompt_type,
            "prompt": self.prompt_text,
            "placement": self.placement,
            "description": self.description,
            "seo_metadata": dict(self.seo_metadata),
        }


@dataclass(frozen=True)
class PromptSpec:
    prompt_type: str
    raw_prompt_text: str
    finalized_prompt_text: str
    placement: str
    description: str
    seo_metadata: dict
    aspect_ratio: str

    def to_payload(self) -> dict:
        return {
            "type": self.prompt_type,
            "prompt": self.finalized_prompt_text,
            "placement": self.placement,
            "description": self.description,
            "seo_metadata": dict(self.seo_metadata),
        }

from src.prompts.service import (
    build_template_prompt_bundle,
    build_template_prompt_payload,
    finalize_prompt_bundle,
    finalize_prompt_map,
)
from src.config import Settings
from src.formatters import build_image_prompts
from src.midjourney_prompts import generate_template_prompts
from src.models import Recipe


def test_shared_template_payload_and_bundle_use_same_source():
    bundle = build_template_prompt_bundle(
        dish_name="Blueberry Muffins",
        focus_keyword="blueberry muffins",
        style_anchor="Shared visual anchor",
        seed=77,
    )
    payload = build_template_prompt_payload(
        dish_name="Blueberry Muffins",
        focus_keyword="blueberry muffins",
        style_anchor="Shared visual anchor",
        seed=77,
    )

    assert [item.prompt_type for item in bundle] == [
        "featured",
        "instructions_process",
        "serving",
    ]
    assert [item.to_payload() for item in bundle] == payload
    assert "Shared visual anchor" in payload[0]["prompt"]


def test_finalize_prompt_map_applies_reference_image_only_to_supported_types():
    finalized = finalize_prompt_map(
        {
            "featured": "Chocolate cake hero image --seed 12",
            "instructions_process": "Hands frosting the cake --seed 12",
            "serving": "Slice of cake on plate --seed 12",
        },
        reference_image_url="https://example.com/reference.jpg",
        sanitize=False,
    )

    assert finalized["featured"].startswith("https://example.com/reference.jpg ")
    assert not finalized["instructions_process"].startswith("https://example.com/reference.jpg ")
    assert finalized["serving"].startswith("https://example.com/reference.jpg ")


def test_finalize_prompt_bundle_returns_typed_specs():
    bundle = build_template_prompt_bundle(
        dish_name="Lemon Cookies",
        focus_keyword="lemon cookies",
        style_anchor="Anchor",
        seed=22,
    )

    specs = finalize_prompt_bundle(bundle, sanitize=True)

    assert [item.prompt_type for item in specs] == [
        "featured",
        "instructions_process",
        "serving",
    ]
    assert all("--v 7" in item.finalized_prompt_text for item in specs)


def test_legacy_template_wrappers_share_the_same_template_source():
    formatters_payload = build_image_prompts(
        "Blueberry Muffins",
        "blueberry muffins",
        "Shared visual anchor",
        77,
    )
    midjourney_payload = generate_template_prompts(
        Recipe(name="Blueberry Muffins"),
        "blueberry muffins",
        Settings(style_anchor="Shared visual anchor"),
        77,
    )

    assert formatters_payload == midjourney_payload

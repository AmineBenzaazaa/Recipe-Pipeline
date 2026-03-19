from src.model_routing import (
    count_faq_items,
    evaluate_row_quality,
    resolve_model_fallback_config,
)


def test_count_faq_items_counts_question_lines():
    faq_text = "Q: One?\nA: 1\n\nQ: Two?\nA: 2\n\nQ: Three?\nA: 3"
    assert count_faq_items(faq_text) == 3


def test_evaluate_row_quality_reports_reasons():
    row = {"recipe_text": "short", "faq_text": "Q: Only one?\nA: yes"}
    ok, reasons = evaluate_row_quality(row, min_recipe_chars=100, min_faq_count=2)
    assert ok is False
    assert any(reason.startswith("recipe_text_too_short") for reason in reasons)
    assert any(reason.startswith("faq_count_too_low") for reason in reasons)


def test_resolve_model_fallback_config_enabled():
    cfg = resolve_model_fallback_config(
        current_model_name="gpt-5-mini",
        env={
            "ENABLE_MODEL_FALLBACK": "true",
            "PRIMARY_MODEL_NAME": "gpt-5-mini",
            "FALLBACK_MODEL_NAME": "gpt-5.2",
            "MODEL_FALLBACK_MIN_RECIPE_CHARS": "900",
            "MODEL_FALLBACK_MIN_FAQ_COUNT": "4",
        },
    )
    assert cfg.enabled is True
    assert cfg.primary_model == "gpt-5-mini"
    assert cfg.fallback_model == "gpt-5.2"
    assert cfg.min_recipe_chars == 900
    assert cfg.min_faq_count == 4


def test_resolve_model_fallback_config_disables_when_same_model():
    cfg = resolve_model_fallback_config(
        current_model_name="gpt-5-mini",
        env={
            "ENABLE_MODEL_FALLBACK": "true",
            "PRIMARY_MODEL_NAME": "gpt-5-mini",
            "FALLBACK_MODEL_NAME": "gpt-5-mini",
        },
    )
    assert cfg.enabled is False

import logging

import generate_recipe_batch as batch


def test_prefix_prompt_with_invalid_url_returns_prompt_only():
    prompt = "hero food photo prompt"
    assert batch._prefix_prompt_with_image_url(prompt, "not-a-url") == prompt


def test_validated_prompt_image_url_rejects_invalid_url(caplog):
    logger = logging.getLogger("generate_recipe_batch_test")
    caplog.set_level(logging.WARNING, logger="generate_recipe_batch_test")

    result = batch._validated_prompt_image_url(
        "not-a-url",
        timeout_seconds=1.0,
        logger=logger,
    )

    assert result == ""
    assert "skipping prompt URL prefix" in caplog.text


def test_validated_prompt_image_url_rejects_unreachable_or_non_image(monkeypatch, caplog):
    logger = logging.getLogger("generate_recipe_batch_test")
    caplog.set_level(logging.WARNING, logger="generate_recipe_batch_test")
    monkeypatch.setattr(batch, "_fetch_image_size", lambda *args, **kwargs: None)

    result = batch._validated_prompt_image_url(
        "https://example.com/source.jpg",
        timeout_seconds=1.0,
        logger=logger,
    )

    assert result == ""
    assert "unreachable or not a valid image" in caplog.text


def test_validated_prompt_image_url_accepts_reachable_image(monkeypatch):
    logger = logging.getLogger("generate_recipe_batch_test")
    monkeypatch.setattr(batch, "_fetch_image_size", lambda *args, **kwargs: (1024, 768))

    result = batch._validated_prompt_image_url(
        "https://example.com/source.jpg",
        timeout_seconds=1.0,
        logger=logger,
    )

    assert result == "https://example.com/source.jpg"


def test_default_headers_include_ingredients_and_pin_columns():
    assert "ingredients_image_prompt" in batch.DEFAULT_HEADERS
    assert "pin_image_prompt" in batch.DEFAULT_HEADERS
    assert "ingredients_image_generated_url" in batch.DEFAULT_HEADERS
    assert "pin_image_generated_url" in batch.DEFAULT_HEADERS


def test_apply_image_aliases_adds_ingredients_and_pin_aliases():
    row = {
        "ingredients_image_generated_url": "https://cdn.example/ingredients.png",
        "pin_image_generated_url": "https://cdn.example/pin.png",
    }

    batch._apply_image_aliases(row)

    assert row["ingredients_image_url"] == "https://cdn.example/ingredients.png"
    assert row["pin_image_url"] == "https://cdn.example/pin.png"

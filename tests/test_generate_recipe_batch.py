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

from src.midjourney_prompt_sanitizer import sanitize_midjourney_prompt


def test_sanitizer_removes_leading_dash_comma_and_quality_param():
    prompt = (
        "-, Pinterest-style hero shot locked on the dish itself. "
        "Single subject only, no props. --ar 3:2 --seed 123456 --quality 5 --v 7"
    )
    cleaned = sanitize_midjourney_prompt(prompt, "featured")

    assert cleaned.startswith("Pinterest-style hero shot locked on the dish itself.")
    assert "--quality" not in cleaned
    assert "--ar 3:2" in cleaned
    assert "--seed 123456" in cleaned
    assert cleaned.endswith("--v 7")


def test_sanitizer_strips_unknown_midjourney_params():
    prompt = "Prompt: blueberry muffins --foo bar --ar 2:3 --seed 42"
    cleaned = sanitize_midjourney_prompt(prompt, "serving")

    assert "--foo" not in cleaned
    assert "blueberry muffins" in cleaned
    assert "--ar 2:3" in cleaned
    assert "--seed 42" in cleaned
    assert cleaned.endswith("--v 7")


def test_sanitizer_adds_default_aspect_ratio_for_prompt_type():
    prompt = "Mixing dough in bowl with hands, natural light"
    cleaned = sanitize_midjourney_prompt(prompt, "instructions_process")

    assert "--ar 2:3" in cleaned
    assert cleaned.endswith("--v 7")


def test_sanitizer_preserves_supported_style_stylize_and_quality():
    prompt = (
        "Ultra realistic dessert hero shot --ar 2:3 --seed 98765 --v 6 "
        "--style raw --s 300 --q 1"
    )
    cleaned = sanitize_midjourney_prompt(prompt, "featured")

    assert "--ar 2:3" in cleaned
    assert "--seed 98765" in cleaned
    assert "--v 6" in cleaned
    assert "--style raw" in cleaned
    assert "--s 300" in cleaned
    assert "--q 1" in cleaned


def test_sanitizer_adds_default_aspect_ratio_for_ingredients_and_pin():
    ingredients_cleaned = sanitize_midjourney_prompt(
        "Neatly arranged cookie ingredients on marble",
        "ingredients",
    )
    pin_cleaned = sanitize_midjourney_prompt(
        "Full Pinterest recipe pin with hero food and overlay zone",
        "pin",
    )

    assert "--ar 2:3" in ingredients_cleaned
    assert "--ar 2:3" in pin_cleaned

from src.prompt_rules import apply_pinterest_ctr_rules


def test_featured_rules_preserve_reference_and_seed_and_add_ctr_language():
    prompt = (
        "https://example.com/source.jpg Professional food photography of lemon cupcakes, "
        "Pinterest viral recipe style, Exact same batch as the featured image. focus on the recipe. "
        "no text no words no letters no typography no watermark no logo no branding no labels "
        "--ar 1:1 --seed 42 --v 6"
    )

    updated = apply_pinterest_ctr_rules({"featured": prompt})["featured"]

    assert updated.startswith("https://example.com/source.jpg ")
    assert "tight food-first framing" in updated
    assert "bright, appetizing, natural-looking pastel color" in updated
    assert "no text, no watermark, no labels, no branding, no packaging, no CGI, no synthetic texture" in updated
    assert "Pinterest viral" not in updated
    assert "Exact same batch as the featured image" not in updated
    assert "--ar 3:2" in updated
    assert "--seed 42" in updated
    assert "--v 6" in updated


def test_process_rules_use_vertical_action_language_and_preserve_food_safety():
    prompt = (
        "Instructions-only process photo of chicken soup, same batch as featured image, "
        "hands cooking, no text no watermark, no pork, no bacon, no ham --seed 123"
    )

    updated = apply_pinterest_ctr_rules({"instructions-process": prompt})["instructions-process"]

    assert "hands actively performing one clear cooking or baking step" in updated
    assert "the action should read instantly at mobile size" in updated
    assert "no pork, no bacon, no ham, no lard, no gelatin, no alcohol" in updated
    assert "--ar 2:3" in updated
    assert "--seed 123" in updated


def test_wprm_rules_are_light_touch_and_keep_existing_ratio():
    prompt = "Recipe card image of blueberry muffins, no text no watermark --ar 4:5 --seed 9"

    updated = apply_pinterest_ctr_rules({"wprm_recipecard": prompt})["wprm_recipecard"]

    assert "clean food-forward recipe card image" in updated
    assert "--ar 4:5" in updated
    assert "--seed 9" in updated
    assert "no text, no watermark, no labels, no branding, no packaging, no CGI, no synthetic texture" in updated

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


def test_process_rules_enforce_six_panel_collage_and_preserve_food_safety():
    prompt = (
        "Instructions-only process photo of chicken soup, same batch as featured image, "
        "hands cooking, no text no watermark, no pork, no bacon, no ham --seed 123"
    )

    updated = apply_pinterest_ctr_rules({"instructions-process": prompt})["instructions-process"]

    assert "single vertical recipe process collage divided into 6 equal panels in a 2-column 3-row grid" in updated
    assert "never show plating, serving, finished dish presentation, or the final product" in updated
    assert "panels 1, 3, and 6 show no hands" in updated
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


def test_ingredients_rules_use_neat_vertical_layout_language():
    prompt = (
        "Ingredients flat lay for Easter sugar cookies with frosting and sprinkles, "
        "Pinterest viral, no text no watermark --seed 55"
    )

    updated = apply_pinterest_ctr_rules({"ingredients": prompt})["ingredients"]

    assert "ingredients arranged neatly with balanced spacing" in updated
    assert "easy to read visually at mobile size" in updated
    assert "bright, appetizing, natural-looking pastel ingredient color" in updated
    assert "--ar 2:3" in updated
    assert "--seed 55" in updated


def test_pin_rules_add_overlay_zone_and_mobile_ctr_language():
    prompt = "Recipe collage for strawberry cheesecake bars, Pinterest viral, no words --seed 14"

    updated = apply_pinterest_ctr_rules({"pin": prompt})["pin"]

    assert "designed for maximum mobile CTR with strong visual hierarchy" in updated
    assert "clear collage hierarchy with the hero food first" in updated
    assert "reserve a clean uncluttered title overlay area" in updated
    assert "Pinterest viral" not in updated
    assert "--ar 2:3" in updated
    assert "--seed 14" in updated

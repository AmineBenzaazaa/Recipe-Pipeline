from src.extract_recipe import _parse_recipe_from_jsonld


def test_jsonld_recipe_extraction():
    html = """
    <html><head>
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "Recipe",
      "name": "Test Soup",
      "description": "A tasty soup.",
      "recipeYield": "4 servings",
      "prepTime": "PT10M",
      "cookTime": "PT20M",
      "totalTime": "PT30M",
      "recipeIngredient": ["1 cup water", "1 tsp salt"],
      "recipeInstructions": [
        {"@type": "HowToStep", "text": "Boil water."},
        {"@type": "HowToStep", "text": "Add salt."}
      ],
      "nutrition": {"calories": "200 calories"},
      "recipeCuisine": "American",
      "recipeCategory": "Soup",
      "image": ["https://example.com/image.jpg"]
    }
    </script>
    </head><body></body></html>
    """
    recipe = _parse_recipe_from_jsonld(html, "https://example.com")
    assert recipe is not None
    assert recipe.name == "Test Soup"
    assert recipe.prep_time == "10 min"
    assert recipe.cook_time == "20 min"
    assert recipe.total_time == "30 min"
    assert recipe.servings == "4 servings"
    assert recipe.ingredients == ["1 cup water", "1 tsp salt"]
    assert recipe.instructions == ["Boil water.", "Add salt."]
    assert recipe.calories == "200 calories"
    assert recipe.cuisine == "American"
    assert recipe.course == "Soup"
    assert recipe.image_urls == ["https://example.com/image.jpg"]

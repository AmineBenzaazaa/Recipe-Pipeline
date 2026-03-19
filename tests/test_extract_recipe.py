from src.extract_recipe import _fallback_extract_recipe, _parse_recipe_from_jsonld


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


def test_fallback_filters_nav_noise_in_lists():
    html = """
    <html>
      <head><title>Air Fryer Dog Treats - Example Site</title></head>
      <body>
        <h2>Ingredients</h2>
        <ul>
          <li>1 cup oat flour</li>
          <li>1/2 cup pumpkin puree</li>
          <li>See also Homemade Pumpkin and Turkey Dog Treats</li>
          <li>Categories</li>
          <li>Contact Us</li>
        </ul>
        <h2>Instructions</h2>
        <ol>
          <li>Preheat oven to 350°F (175°C).</li>
          <li>Mix oat flour and pumpkin puree until dough forms.</li>
          <li>Leave a comment</li>
          <li>Privacy Policy</li>
        </ol>
      </body>
    </html>
    """

    recipe = _fallback_extract_recipe(html, "https://example.com/air-fryer-dog-treats")

    assert recipe.ingredients == ["1 cup oat flour", "1/2 cup pumpkin puree"]
    assert recipe.instructions == [
        "Preheat oven to 350°F (175°C).",
        "Mix oat flour and pumpkin puree until dough forms.",
    ]


def test_fallback_section_lines_stop_before_footer_noise():
    html = """
    <html>
      <head><title>Peanut Butter Dog Treats</title></head>
      <body>
        <article>
          <h2>Ingredients</h2>
          <p>1 cup oat flour</p>
          <p>1/2 cup peanut butter</p>
          <h2>Instructions</h2>
          <p>1. Mix all ingredients in a bowl.</p>
          <p>2. Roll dough and cut shapes.</p>
          <p>3. Bake at 350°F for 20 minutes.</p>
          <h3>Categories</h3>
          <p>Dog treats</p>
          <p>Latest Posts</p>
        </article>
      </body>
    </html>
    """

    recipe = _fallback_extract_recipe(html, "https://example.com/peanut-butter-dog-treats")

    assert recipe.ingredients == ["1 cup oat flour", "1/2 cup peanut butter"]
    assert recipe.instructions == [
        "Mix all ingredients in a bowl.",
        "Roll dough and cut shapes.",
        "Bake at 350°F for 20 minutes.",
    ]

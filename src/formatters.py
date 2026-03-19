import hashlib
import re
from typing import List

from .models import FAQItem, Recipe


def seed_from_string(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "recipe"


def build_image_prompts(
    dish_name: str, focus_keyword: str, style_anchor: str, seed: int
) -> List[dict]:
    """
    Build professional image prompts for recipe articles.
    
    These prompts are designed for high-quality, professional food photography
    suitable for blog articles and recipe websites. They explicitly exclude
    text overlays and ensure professional composition.
    """
    dish = dish_name or "the dish"
    slug = _slugify(focus_keyword)
    
    # Professional photography rules optimized for Midjourney
    # Midjourney responds well to specific, descriptive terms and quality indicators
    # CRITICAL: Multiple explicit text exclusions to prevent text overlays
    professional_rules = (
        "professional food photography, magazine quality, editorial style, "
        "absolutely no text, no text overlay, no watermark, no labels, no writing, "
        "no letters, no words, no typography, no branding, no logo, no text on food, "
        "no text on plate, no text on background, completely text-free, "
        "clean composition, pure food photography, "
        "high resolution, sharp focus, professional lighting, restaurant quality, "
        "food styling, appetizing, photogenic, commercial food photography, "
        "8k, ultra detailed, professional shot, food photography award winning"
    )
    
    return [
        {
            "type": "featured",
            "prompt": (
                f"Professional food photography of {dish}, hero shot of the finished recipe, "
                f"beautifully styled and plated, showcasing all key ingredients and textures, "
                f"clean white or neutral background, professional composition, appetizing presentation, "
                f"{professional_rules}, "
                f"{style_anchor}, "
                f"exact visual consistency for batch reference, "
                f"no text no words no letters no typography no watermark no logo no branding no labels "
                f"--ar 3:2 --seed {seed} --v 7"
            ),
            "placement": "Top of article (before introduction)",
            "description": "Hero shot of the finished dish - professional food photography",
            "seo_metadata": {
                "alt_text": f"Professional food photography of {focus_keyword} - finished dish hero shot",
                "filename": f"{slug}-featured.jpg",
                "caption": f"Beautifully presented {dish} ready to enjoy",
                "description": f"Professional hero shot of {dish} showcasing the finished recipe",
            },
        },
        {
            "type": "instructions_process",
            "prompt": (
                f"Professional food photography of {dish} preparation process, "
                f"hands working with fresh ingredients, mixing kneading or cooking techniques, "
                f"action shot showing the cooking process, ingredients visible, professional styling, "
                f"clean background, natural lighting, vertical composition, "
                f"{professional_rules}, "
                f"{style_anchor}, "
                f"same visual style and batch as featured image for consistency, "
                f"no text no words no letters no typography no watermark no logo no branding no labels "
                f"--ar 2:3 --seed {seed} --v 7"
            ),
            "placement": "Middle of article (in instructions section)",
            "description": "Professional process photography showing cooking techniques",
            "seo_metadata": {
                "alt_text": f"Professional food photography of preparing {focus_keyword} - cooking process",
                "filename": f"instructions-process-{slug}.jpg",
                "caption": f"Step-by-step preparation of {dish}",
                "description": f"Professional process photography showing hands preparing {dish}",
            },
        },
        {
            "type": "serving",
            "prompt": (
                f"Professional food photography of {dish}, elegantly plated and ready to serve, "
                f"beautiful presentation on high-quality dinnerware, garnished and styled professionally, "
                f"appetizing composition, restaurant-quality presentation, inviting and photogenic, "
                f"clean background, professional food styling, natural lighting, "
                f"{professional_rules}, "
                f"{style_anchor}, "
                f"same visual style and batch as featured image for consistency, "
                f"no text no words no letters no typography no watermark no logo no branding no labels "
                f"--ar 2:3 --seed {seed} --v 7"
            ),
            "placement": "Before serving section",
            "description": "Professional serving presentation photography",
            "seo_metadata": {
                "alt_text": f"Professional food photography of {focus_keyword} - serving presentation",
                "filename": f"serving-{slug}.jpg",
                "caption": f"Elegantly plated {dish} ready to serve",
                "description": f"Professional serving presentation of {dish} on beautiful dinnerware",
            },
        },
    ]


def _strip_quantity(text: str) -> str:
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"^[\d\s/.\-]+", "", text)
    text = re.sub(
        r"^(cup|cups|tbsp|tablespoon|tablespoons|tsp|teaspoon|teaspoons|oz|ounce|ounces|"
        r"g|kg|ml|l|lb|pound|pounds|pinch|dash)\b",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"\b(optional|to taste)\b", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip(" ,.-")


def build_prompt_dish_name(recipe: Recipe, focus_keyword: str) -> str:
    """
    Build an enhanced dish name for image prompt generation.
    
    This function creates a descriptive dish name by combining the recipe name
    with key ingredients. It filters out common stop words (like salt, pepper)
    and focuses on distinctive ingredients that help generate better image prompts.
    
    Args:
        recipe: Recipe object containing name and ingredients
        focus_keyword: Primary keyword for the recipe
    
    Returns:
        Enhanced dish name string suitable for image generation prompts.
        Examples:
        - "Chocolate Chip Cookies, featuring dark chocolate, vanilla, butter"
        - "Pumpkin Soup, soft pumpkin-spice cookies with cinnamon frosting"
    
    Example:
        >>> recipe = Recipe(
        ...     name="Cookies",
        ...     ingredients=["2 cups flour", "1 cup chocolate chips", "vanilla extract"]
        ... )
        >>> name = build_prompt_dish_name(recipe, "chocolate cookies")
        >>> print(name)
        Cookies, featuring chocolate chips, vanilla extract
    """
    base = recipe.name or focus_keyword or "the dish"
    lowered_ingredients = " ".join(recipe.ingredients).lower()
    if "pumpkin" in lowered_ingredients and "cinnamon" in lowered_ingredients:
        return f"{base}, soft pumpkin-spice cookies with cinnamon frosting swirls"
    if "cookie" in base.lower() and "frosting" in lowered_ingredients:
        return f"{base}, soft cookies topped with creamy frosting"
    stop_words = {
        "salt",
        "pepper",
        "water",
        "flour",
        "sugar",
        "butter",
        "oil",
        "vanilla",
        "egg",
        "eggs",
        "milk",
        "cream",
        "baking powder",
        "baking soda",
    }
    details = []
    for item in recipe.ingredients[:12]:
        cleaned = _strip_quantity(item)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if any(word in lowered for word in stop_words):
            if "brown sugar" in lowered or "pumpkin" in lowered or "cinnamon" in lowered:
                pass
            else:
                continue
        if cleaned not in details:
            details.append(cleaned)
        if len(details) >= 4:
            break
    if details:
        return f"{base}, featuring {', '.join(details)}"
    return base


def format_faq_text(items: List[FAQItem]) -> str:
    blocks = []
    for item in items:
        blocks.append(f"Q: {item.question}\nA: {item.answer}")
    return "\n\n".join(blocks)


def _format_value(value: str, fallback: str) -> str:
    return value if value else fallback


def format_recipe_text(recipe: Recipe) -> str:
    """
    Format a Recipe object into a human-readable text string.
    
    This function formats all recipe data into a structured text format suitable
    for display or storage. Missing fields are replaced with sensible defaults
    to ensure the output is always readable.
    
    Args:
        recipe: Recipe object to format
    
    Returns:
        Formatted recipe text with the following structure:
        - Title
        - Description (if available)
        - Prep time, Cook time, Total time
        - Servings/Yield
        - Calories
        - Cuisine
        - Course
        - Ingredients list (bulleted)
        - Instructions list (numbered)
        - Notes (if available)
    
    Example:
        >>> recipe = Recipe(
        ...     name="Chocolate Chip Cookies",
        ...     ingredients=["2 cups flour", "1 cup sugar"],
        ...     instructions=["Mix ingredients", "Bake at 350F"]
        ... )
        >>> text = format_recipe_text(recipe)
        >>> print(text)
        Title: Chocolate Chip Cookies
        Prep: 15 min
        Cook: 20 min
        ...
    """
    lines = [f"Title: {_format_value(recipe.name, 'Recipe Title')}"]
    if recipe.description:
        lines.append(f"Description: {recipe.description}")

    lines.extend(
        [
            f"Prep: {_format_value(recipe.prep_time, '15 min')}",
            f"Cook: {_format_value(recipe.cook_time, '20 min')}",
            f"Total: {_format_value(recipe.total_time, '35 min')}",
            f"Servings/Yield: {_format_value(recipe.servings, '4 servings')}",
            f"Calories: {_format_value(recipe.calories, '300 calories')}",
            f"Cuisine: {_format_value(recipe.cuisine, 'American')}",
            f"Course: {_format_value(recipe.course, 'Main Course')}",
            "",
            "Ingredients:",
        ]
    )

    if recipe.ingredients:
        lines.extend([f"- {item}" for item in recipe.ingredients])
    else:
        lines.append("- See source")

    lines.append("")
    lines.append("Instructions:")
    if recipe.instructions:
        for idx, step in enumerate(recipe.instructions, start=1):
            lines.append(f"{idx}. {step}")
    else:
        lines.append("1. See source")

    if recipe.notes:
        lines.append("")
        lines.append(f"Notes: {recipe.notes}")

    return "\n".join(lines)

"""
Midjourney prompt generation using GPT (legacy approach).

This module generates Midjourney prompts using GPT analysis of recipe content,
following the proven approach from legacy.py.
"""

import json
import logging
import re
from typing import Dict, List, Optional

from .config import Settings
from .models import Recipe
from .openai_client import responses_create_text


def generate_random_seed() -> int:
    """Generate a random seed for Midjourney consistency."""
    import random
    return random.randint(1000000000, 9999999999)


def generate_midjourney_prompts_gpt(
    recipe: Recipe,
    focus_keyword: str,
    recipe_text: str,
    settings: Settings,
    logger: logging.Logger,
) -> List[Dict]:
    """
    Generate 3 Midjourney image prompts using GPT analysis (legacy approach).
    
    This uses GPT to analyze the recipe content and generate customized prompts
    specific to the actual dish, following the proven legacy.py approach.
    
    Args:
        recipe: Recipe object with extracted data
        focus_keyword: Focus keyword for SEO
        recipe_text: Formatted recipe text
        settings: Application settings
        logger: Logger instance
    
    Returns:
        List of 3 prompt dictionaries (featured, instructions_process, serving)
    """
    if not settings.openai_api_key:
        logger.info("OpenAI API key not set; using template prompts")
        return _generate_template_prompts(recipe, focus_keyword, settings)
    
    # Generate a unique seed for this recipe batch
    seed = generate_random_seed()
    
    # Use focus keyword or recipe name
    if not focus_keyword:
        focus_keyword = recipe.name or "recipe"
    
    # Universal style anchor (from legacy.py)
    style_anchor = "Exact same batch as the featured image. focus on the recipe."
    
    # Build article content context (first 3000 chars like legacy)
    article_context = recipe_text[:3000] if recipe_text else ""
    if not article_context:
        # Fallback: build context from recipe data
        article_context = f"""
Recipe: {recipe.name or focus_keyword}
Description: {recipe.description or 'Delicious recipe'}
Ingredients: {', '.join(recipe.ingredients[:10]) if recipe.ingredients else 'Various ingredients'}
Instructions: {', '.join(recipe.instructions[:5]) if recipe.instructions else 'Follow recipe steps'}
"""
    
    prompt = f"""
You are a professional food photography director and SEO expert specializing in MidJourney prompts.

Analyze this recipe article and generate exactly 3 MidJourney image prompts with comprehensive SEO metadata:

Article Topic: {recipe.name or focus_keyword}
Focus Keyword: {focus_keyword}
Article Content:
{article_context}

Generate prompts for these 3 images in order:
1. Featured Image (Hero shot – top of article)
2. Instructions-only process photo (Middle of article, in the instructions section) --ar 2:3
3. Serving Image (Within the Serving/Serving Suggestions section if it exists)

STRICT RULES FOR IMAGE GENERATION:
- Featured image should be a hero shot of the finished dish
- Instructions process photo should show hands preparing/cooking the dish in 2:3 vertical format
- Serving image should show elegant plating and presentation
- Maintain exact continuity between all images using the same style anchor and seed
- NO text overlay, NO watermark, NO labels, NO writing on the image
- Professional magazine-quality food photography
- Clean composition, appetizing presentation

For each image, provide:
- A detailed MidJourney prompt with style anchor and seed
- Exact placement location in the article
- Brief description of what the image shows
- Complete SEO metadata (alt text, filename, caption, description)

SEO Requirements:
- Alt Text: Must include exact keyword "{focus_keyword}"
- Filename: Hyphenated, lowercase, include keyword (e.g., {focus_keyword.lower().replace(' ', '-')}-featured.jpg)
- Caption: Short, descriptive, human-readable sentence
- Description: Full sentence describing dish with continuity reference

Use this seed for ALL prompts: {seed}
Include this style anchor in ALL prompts: "{style_anchor}"

Return the response in this exact JSON format:
{{
  "seed": {seed},
  "focus_keyword": "{focus_keyword}",
  "images": [
    {{
      "type": "featured",
      "prompt": "Photo-realistic food photography of [dish name], hero shot of the finished recipe with all key details visible. Exact batch reference for later steps. {style_anchor} --ar 3:2 --seed {seed}",
      "placement": "Top of article (before introduction)",
      "description": "Hero shot of the finished dish",
      "seo_metadata": {{
        "alt_text": "Alt text including exact keyword '{focus_keyword}'",
        "filename": "suggested-filename-with-keyword.jpg",
        "caption": "Short descriptive caption for humans",
        "description": "Full sentence description with dish reference"
      }}
    }},
    {{
      "type": "instructions_process",
      "prompt": "Instructions-only process photo of [dish name] preparation, hands working with ingredients and cooking techniques. Same batch as featured image, vertical composition showing cooking process. {style_anchor} --ar 2:3 --seed {seed}",
      "placement": "Middle of article (in instructions section)",
      "description": "Hands preparing the dish during cooking process",
      "seo_metadata": {{
        "alt_text": "Preparing {focus_keyword} step by step cooking process",
        "filename": "instructions-process-filename.jpg",
        "caption": "Step-by-step preparation of the dish",
        "description": "Detailed cooking process showing hands preparing the recipe"
      }}
    }},
    {{
      "type": "serving",
      "prompt": "Elegant serving presentation of [dish name], beautifully plated and ready to serve. Same batch as featured image, showing the dish in its final serving context. {style_anchor} --ar 2:3 --seed {seed}",
      "placement": "Before serving section",
      "description": "Dish being served",
      "seo_metadata": {{
        "alt_text": "{focus_keyword} being served on beautiful dinnerware",
        "filename": "serving-filename.jpg",
        "caption": "Serving the finished dish caption",
        "description": "Serving description with continuity"
      }}
    }}
  ]
}}

Make the prompts specific to the actual recipe content. Replace [dish name] with the actual dish name "{recipe.name or focus_keyword}". Ensure all SEO metadata fields are properly populated with keyword-optimized content. Add "no text no words no letters no typography no watermark no logo no branding no labels" to each prompt before the --ar parameter.
"""
    
    try:
        payload = {
            "model": settings.model_name,
            "input": [
                {
                    "role": "system",
                    "content": "You are a professional food photography director. Generate detailed MidJourney prompts with exact placement metadata."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.3,
            "max_output_tokens": 2000
        }
        
        output_text = responses_create_text(settings, payload, logger)
        
        # Try to parse JSON response
        try:
            # Extract JSON from response if it's wrapped in markdown
            if "```json" in output_text:
                json_text = output_text.split("```json")[1].split("```")[0].strip()
            elif "```" in output_text:
                json_text = output_text.split("```")[1].split("```")[0].strip()
            else:
                # Try to find JSON in the text
                json_text = _extract_json_from_text(output_text)
            
            if not json_text:
                raise ValueError("No JSON found in response")
            
            data = json.loads(json_text)
            
            # Extract images array
            images = data.get("images", [])
            if not images or len(images) != 3:
                raise ValueError("Invalid images array")
            
            # Ensure prompts have the no-text exclusions
            for img in images:
                prompt_text = img.get("prompt", "")
                if "no text" not in prompt_text.lower():
                    # Add no-text exclusions before --ar parameter
                    prompt_text = prompt_text.replace(" --ar", ", no text no words no letters no typography no watermark no logo no branding no labels --ar")
                    img["prompt"] = prompt_text
            
            return images
            
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(f"Failed to parse GPT prompt response: {e}; using template prompts")
            return generate_template_prompts(recipe, focus_keyword, settings, seed)
    
    except Exception as e:
        logger.warning(f"GPT prompt generation failed: {e}; using template prompts")
        return generate_template_prompts(recipe, focus_keyword, settings)


def _extract_json_from_text(text: str) -> str:
    """Extract JSON from text response."""
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    return match.group(1) if match else ""


def generate_template_prompts(
    recipe: Recipe,
    focus_keyword: str,
    settings: Settings,
    seed: Optional[int] = None
) -> List[Dict]:
    """
    Generate template prompts (fallback when GPT is unavailable).
    
    Uses the legacy.py template structure with simpler, cleaner prompts.
    """
    if seed is None:
        seed = generate_random_seed()
    
    dish_name = recipe.name or focus_keyword or "the dish"
    style_anchor = "Exact same batch as the featured image. focus on the recipe."
    keyword_slug = focus_keyword.lower().replace(' ', '-') if focus_keyword else "recipe"
    
    return [
        {
            "type": "featured",
            "prompt": f"Photo-realistic food photography of {dish_name}, hero shot of the finished recipe with all key details visible. Exact batch reference for later steps. {style_anchor} no text no words no letters no typography no watermark no logo no branding no labels --ar 3:2 --seed {seed} --quality 5",
            "placement": "Top of article (before introduction)",
            "description": "Hero shot of the finished dish",
            "seo_metadata": {
                "alt_text": f"{focus_keyword} finished dish on elegant plate" if focus_keyword else f"{dish_name} finished dish",
                "filename": f"{keyword_slug}-featured.jpg",
                "caption": f"Delicious {dish_name} ready to serve",
                "description": f"This stunning {dish_name} showcases the perfect balance of flavors and presentation."
            }
        },
        {
            "type": "instructions_process",
            "prompt": f"Instructions-only process photo of {dish_name} preparation, hands working with ingredients and cooking techniques. Same batch as featured image, vertical composition showing cooking process. {style_anchor} no text no words no letters no typography no watermark no logo no branding no labels --ar 2:3 --seed {seed} --quality 5",
            "placement": "Middle of article (in instructions section)",
            "description": "Hands preparing the dish during cooking process",
            "seo_metadata": {
                "alt_text": f"Preparing {focus_keyword} step by step cooking process" if focus_keyword else f"Preparing {dish_name} step by step",
                "filename": f"{keyword_slug}-instructions-process.jpg",
                "caption": f"Step-by-step preparation of {dish_name}",
                "description": f"Detailed cooking process showing hands preparing the {dish_name} recipe."
            }
        },
        {
            "type": "serving",
            "prompt": f"Elegant serving presentation of {dish_name}, beautifully plated and ready to serve. Same batch as featured image, showing the dish in its final serving context. {style_anchor} no text no words no letters no typography no watermark no logo no branding no labels --ar 2:3 --seed {seed} --quality 5",
            "placement": "Before serving section",
            "description": "Dish being served",
            "seo_metadata": {
                "alt_text": f"{focus_keyword} being served on beautiful dinnerware" if focus_keyword else f"{dish_name} being served",
                "filename": f"{keyword_slug}-serving.jpg",
                "caption": f"Serving the finished {dish_name}",
                "description": f"This beautifully plated {dish_name} is ready to impress your guests."
            }
        }
    ]


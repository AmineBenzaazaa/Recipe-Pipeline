import re
from typing import Iterable, Optional

from .models import Recipe


_REPLACEMENTS = [
    (r"\bpork\s+belly\b", "beef belly"),
    (r"\bpork\s+chops?\b", "lamb chops"),
    (r"\bpork\s+shoulder\b", "lamb shoulder"),
    (r"\bpork\s+tenderloin\b", "beef tenderloin"),
    (r"\bpork\s+loin\b", "beef loin"),
    (r"\bpork\s+ribs?\b", "beef ribs"),
    (r"\bground\s+pork\b", "ground chicken"),
    (r"\bpork\s+sausage\b", "beef sausage"),
    (r"\bbacon\s+fat\b", "smoked olive oil"),
    (r"\bbacon\s+grease\b", "smoked olive oil"),
    (r"\bbacon\s+bits\b", "smoked turkey bits"),
    (r"\bbacon\b", "turkey bacon"),
    (r"\bham\s+hocks?\b", "smoked turkey legs"),
    (r"\bham\b", "turkey ham"),
    (r"\bprosciutto\b", "turkey prosciutto"),
    (r"\bpancetta\b", "turkey pancetta"),
    (r"\bguanciale\b", "beef cheek"),
    (r"\bpepperoni\b", "beef pepperoni"),
    (r"\bsalami\b", "beef salami"),
    (r"\bchorizo\b", "beef chorizo"),
    (r"\bkielbasa\b", "beef kielbasa"),
    (r"\bandouille\b", "beef andouille"),
    (r"\bbratwurst\b", "beef bratwurst"),
    (r"\bhot\s+dog(s)?\b", "beef hot dog"),
    (r"\blard\b", "vegetable shortening"),
    (r"\bpork\b", "chicken"),
    (r"\bgelatin\b", "agar-agar powder"),
    (r"\bmarshmallows?\b", "vanilla marshmallows"),
    (r"\bvanilla\s+extract\b", "vanilla bean paste"),
    (r"\bwhite\s+wine\b", "chicken broth"),
    (r"\bred\s+wine\b", "beef broth"),
    (r"\bcooking\s+wine\b", "broth"),
    (r"\bwine\b(?!\s+vinegar)", "broth"),
    (r"\bbeer\b", "sparkling water"),
    (r"\blager\b", "sparkling water"),
    (r"\bale\b", "sparkling water"),
    (r"\bstout\b", "sparkling water"),
    (r"\bsake\b", "rice vinegar"),
    (r"\bmirin\b", "rice vinegar"),
    (r"\bcooking\s+sherry\b", "sherry vinegar"),
    (r"\bsherry\b(?!\s+vinegar)", "sherry vinegar"),
    (r"\bbrandy\b", "apple juice"),
    (r"\bbourbon\b", "apple cider"),
    (r"\bwhiskey\b", "apple cider"),
    (r"\bwhisky\b", "apple cider"),
    (r"\brum\b", "molasses"),
    (r"\bvodka\b", "citrus juice"),
    (r"\bgin\b", "citrus juice"),
    (r"\btequila\b", "citrus juice"),
    (r"\btriple\s+sec\b", "orange juice"),
    (r"\bamaretto\b", "almond extract"),
    (r"\bkahlua\b", "coffee extract"),
]


def _preserve_case(original: str, replacement: str) -> str:
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper():
        return replacement.title()
    return replacement


def _apply_replacements(text: str) -> str:
    if not text:
        return text
    updated = text
    for pattern, replacement in _REPLACEMENTS:
        updated = re.sub(
            pattern,
            lambda match: _preserve_case(match.group(0), replacement),
            updated,
            flags=re.I,
        )
    updated = re.sub(
        r"\b(?<!chicken\s)(?<!turkey\s)(?<!beef\s)(?<!lamb\s)(?<!vegan\s)(?<!plant-based\s)sausage\b",
        lambda match: _preserve_case(match.group(0), "beef sausage"),
        updated,
        flags=re.I,
    )
    return updated


def sanitize_text_halal(text: Optional[str]) -> Optional[str]:
    if not text:
        return text
    return _apply_replacements(text)


def sanitize_lines_halal(lines: Iterable[str]) -> list[str]:
    return [_apply_replacements(line) for line in lines]


def make_recipe_halal(recipe: Recipe) -> Recipe:
    data = recipe.model_dump()
    data["name"] = sanitize_text_halal(data.get("name"))
    data["description"] = sanitize_text_halal(data.get("description"))
    data["notes"] = sanitize_text_halal(data.get("notes"))
    data["ingredients"] = sanitize_lines_halal(data.get("ingredients") or [])
    data["instructions"] = sanitize_lines_halal(data.get("instructions") or [])
    return Recipe(**data)

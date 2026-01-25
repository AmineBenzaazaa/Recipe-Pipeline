"""
Constants used throughout the Recipe Pipeline.

Centralizing constants makes the codebase more maintainable and reduces
magic numbers and strings scattered throughout the code.
"""


class ImageTypes:
    """Image type identifiers for generated images."""
    FEATURED = "featured"
    INSTRUCTIONS_PROCESS = "instructions_process"
    SERVING = "serving"
    RECIPE_CARD = "WPRM_recipecard"


class ExtractionMethods:
    """Recipe extraction method identifiers."""
    JSONLD = "jsonld"
    FALLBACK = "fallback"
    GPT = "gpt_fallback"


class TimeUnits:
    """Time unit strings for recipe metadata."""
    MINUTES = "min"
    HOURS = "hr"


# Processing limits
DEFAULT_IMAGE_LIMIT = 3
MAX_INGREDIENTS_FOR_PROMPT = 12
MAX_INSTRUCTIONS_FOR_PROMPT = 5
MAX_INGREDIENTS_FOR_CONTEXT = 20
MAX_INSTRUCTIONS_FOR_CONTEXT = 10
MAX_FAQ_ITEMS = 10
MIN_FAQ_ITEMS = 6

# Text processing limits
MAX_TEXT_LENGTH_FOR_GPT = 12000
MAX_INGREDIENT_LENGTH = 200
MAX_INSTRUCTION_LENGTH = 1000

# Image processing
MIN_IMAGE_AREA = 40000  # pixels (200x200 minimum)
DEFAULT_IMAGE_SIZE = "1024x1024"
LANDSCAPE_IMAGE_SIZE = "1536x1024"  # 3:2 aspect ratio
PORTRAIT_IMAGE_SIZE = "1024x1536"   # 2:3 aspect ratio

# Validation thresholds
MAX_SERVINGS = 100
MAX_CALORIES = 5000
MAX_TITLE_LENGTH = 40
MAX_TITLE_WORDS = 3

# API defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_REQUEST_TIMEOUT = 30.0
DEFAULT_SLEEP_SECONDS = 1.0

# Regex patterns
ISO8601_DURATION_PATTERN = r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?"
TIME_PATTERN = r"(?P<num>\d+(?:\s*-\s*\d+)?)\s*(?P<unit>hr|hrs|hour|hours|min|mins|minute|minutes)"

# Invalid tokens for metadata extraction
INVALID_LABEL_TOKENS = {
    "contact",
    "instagram",
    "pinterest",
    "facebook",
    "recipe",
    "recipes",
    "newsletter",
    "privacy",
    "cookies",
    "baked",
    "baking",
}

# Stop words for ingredient filtering
INGREDIENT_STOP_WORDS = {
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


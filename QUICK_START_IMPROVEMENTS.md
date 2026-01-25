# Quick Start: Implementing Improvements

This guide shows you how to start implementing the improvements outlined in `IMPROVEMENTS.md`.

## ✅ Already Implemented

I've created the following foundation files that you can start using immediately:

### 1. Custom Exception Hierarchy (`src/exceptions.py`)
- Structured exceptions with context
- Better error tracking
- Usage example:
```python
from src.exceptions import ExtractionError, APIError

try:
    recipe = extract_recipe(html, url)
except Exception as e:
    raise ExtractionError(
        "Failed to extract recipe",
        url=url,
        method="jsonld",
        context={"error": str(e)}
    )
```

### 2. Result Pattern (`src/result.py`)
- Explicit success/failure handling
- Prevents silent failures
- Usage example:
```python
from src.result import Result

def fetch_recipe(url: str) -> Result[Recipe]:
    try:
        recipe = extract_recipe(url)
        return Result.ok(recipe)
    except Exception as e:
        return Result.fail(e)

# Usage
result = fetch_recipe(url)
if result.success:
    process_recipe(result.value)
else:
    logger.error(f"Failed: {result.error}")
```

### 3. Constants Module (`src/constants.py`)
- Centralized constants
- No more magic numbers
- Usage example:
```python
from src.constants import (
    MAX_INGREDIENTS_FOR_PROMPT,
    ImageTypes,
    ExtractionMethods
)

if len(ingredients) > MAX_INGREDIENTS_FOR_PROMPT:
    ingredients = ingredients[:MAX_INGREDIENTS_FOR_PROMPT]
```

### 4. Validators (`src/validators.py`)
- URL validation
- Input sanitization
- Usage example:
```python
from src.validators import validate_url_or_raise, sanitize_string

# Validate URL before processing
validate_url_or_raise(url)

# Sanitize user input
clean_name = sanitize_string(recipe_name, max_length=200)
```

## Next Steps

### Step 1: Update Existing Code to Use New Utilities

#### Update `generate_recipe_batch.py`:
```python
# Add at top
from src.validators import validate_url_or_raise
from src.exceptions import ValidationError

# Update _validate_url function
def _validate_url(url: str) -> bool:
    try:
        validate_url_or_raise(url)
        return True
    except ValidationError:
        return False
```

#### Update `extract_recipe.py`:
```python
# Add imports
from src.constants import ExtractionMethods
from src.exceptions import ExtractionError

# Update extraction to use constants
recipe.extraction_method = ExtractionMethods.JSONLD
```

### Step 2: Add Type Hints

Start adding type hints to functions that don't have them:

```python
# Before
def process_recipe(keyword, url, settings, logger):
    ...

# After
from typing import Dict, Optional
from src.config import Settings
import logging

def process_recipe(
    keyword: str,
    url: str,
    settings: Settings,
    logger: logging.Logger
) -> Optional[Dict[str, str]]:
    ...
```

### Step 3: Improve Error Handling

Replace silent failures with explicit error handling:

```python
# Before
def get_faqs(keyword, recipe, settings, logger):
    faqs = _serper_faqs(query, settings, logger)
    if not faqs:
        faqs = _serpapi_faqs(query, settings, logger)
    return faqs

# After
from src.result import Result
from src.exceptions import APIError

def get_faqs(keyword, recipe, settings, logger) -> Result[List[FAQItem]]:
    try:
        faqs = _serper_faqs(query, settings, logger)
        if faqs:
            return Result.ok(faqs)
        
        faqs = _serpapi_faqs(query, settings, logger)
        if faqs:
            return Result.ok(faqs)
        
        return Result.fail(APIError("No FAQs found", service="serper+serpapi"))
    except Exception as e:
        return Result.fail(APIError(f"FAQ fetch failed: {e}", service="unknown"))
```

### Step 4: Add Comprehensive Docstrings

Add docstrings to public functions:

```python
def extract_recipe_from_html(
    html: str,
    source_url: str,
    settings: Settings,
    logger: logging.Logger,
    gpt_fallback: bool = True,
) -> Recipe:
    """
    Extract recipe data from HTML content using multiple extraction strategies.
    
    This function attempts to extract recipe information using the following
    strategies in order:
    1. JSON-LD structured data (most reliable)
    2. HTML fallback parsing (medium reliability)
    3. GPT-based extraction (if enabled and API key available)
    
    Args:
        html: Raw HTML content from the recipe page
        source_url: Original URL of the recipe (for reference)
        settings: Application settings including API keys
        logger: Logger instance for recording extraction process
        gpt_fallback: Whether to use GPT extraction if other methods fail
    
    Returns:
        Recipe object with extracted data. Fields may be None if not found.
    
    Raises:
        ExtractionError: If all extraction methods fail and gpt_fallback is False
    
    Example:
        >>> html = fetch_html("https://example.com/recipe")
        >>> recipe = extract_recipe_from_html(html, "https://example.com/recipe", settings, logger)
        >>> print(recipe.name)
        "Chocolate Chip Cookies"
    """
    # Implementation...
```

## Testing the Improvements

Create a test file to verify the new utilities work:

```python
# tests/test_validators.py
import pytest
from src.validators import validate_url, validate_url_or_raise, ValidationError

def test_validate_url_valid():
    assert validate_url("https://example.com/recipe") is True
    assert validate_url("http://example.com") is True

def test_validate_url_invalid():
    assert validate_url("javascript:alert('xss')") is False
    assert validate_url("invalid://url") is False
    assert validate_url("") is False

def test_validate_url_or_raise():
    validate_url_or_raise("https://example.com")  # Should not raise
    
    with pytest.raises(ValidationError):
        validate_url_or_raise("invalid://url")
```

## Migration Checklist

- [ ] Update imports to use new exception classes
- [ ] Replace magic numbers with constants
- [ ] Add URL validation before processing
- [ ] Add type hints to all public functions
- [ ] Add docstrings to all public functions
- [ ] Replace silent failures with Result pattern or exceptions
- [ ] Update tests to use new utilities
- [ ] Update error handling in main processing loop

## Benefits You'll See Immediately

1. **Better Error Messages**: Structured exceptions provide context
2. **Fewer Bugs**: URL validation prevents malicious input
3. **Easier Maintenance**: Constants in one place
4. **Better IDE Support**: Type hints enable autocomplete
5. **Clearer Intent**: Result pattern makes error handling explicit

## Need Help?

Refer to `IMPROVEMENTS.md` for detailed explanations of each improvement and why it matters.


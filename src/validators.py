"""
Validation utilities for the Recipe Pipeline.

This module provides validation functions for URLs, data, and other inputs
to improve security and data quality.
"""

import re
from urllib.parse import urlparse
from typing import Optional

from .exceptions import ValidationError


ALLOWED_SCHEMES = {'http', 'https'}
BLOCKED_DOMAINS = {'localhost', '127.0.0.1', '0.0.0.0'}
MALICIOUS_PATTERNS = [r'[<>"\']', r'javascript:', r'data:', r'vbscript:']


def validate_url(url: str) -> bool:
    """
    Validate that a URL is safe and well-formed.
    
    Args:
        url: The URL string to validate (can be None)
    
    Returns:
        True if the URL is valid and safe, False otherwise
    
    Example:
        >>> validate_url("https://example.com/recipe")
        True
        >>> validate_url("javascript:alert('xss')")
        False
        >>> validate_url(None)
        False
    """
    if url is None or not isinstance(url, str) or not url.strip():
        return False
    
    try:
        parsed = urlparse(url.strip())
        
        # Check scheme
        if parsed.scheme not in ALLOWED_SCHEMES:
            return False
        
        # Check for blocked domains
        if parsed.netloc.lower() in BLOCKED_DOMAINS:
            return False
        
        # Check for malicious patterns
        for pattern in MALICIOUS_PATTERNS:
            if re.search(pattern, url, re.IGNORECASE):
                return False
        
        # Basic format validation
        if not parsed.netloc:
            return False
        
        return True
    except Exception:
        return False


def validate_url_or_raise(url: str) -> None:
    """
    Validate a URL and raise an exception if invalid.
    
    Args:
        url: The URL string to validate
    
    Raises:
        ValidationError: If the URL is invalid
    
    Example:
        >>> validate_url_or_raise("https://example.com")
        >>> validate_url_or_raise("invalid://url")
        ValidationError: Invalid URL format or scheme
    """
    if not validate_url(url):
        raise ValidationError(
            "Invalid URL format or scheme",
            field="url",
            value=url,
            context={"allowed_schemes": list(ALLOWED_SCHEMES)}
        )


def validate_recipe_data(recipe_data: dict) -> bool:
    """
    Validate that recipe data contains required fields.
    
    Args:
        recipe_data: Dictionary containing recipe information
    
    Returns:
        True if the recipe data is valid, False otherwise
    """
    required_fields = ['ingredients', 'instructions']
    
    for field in required_fields:
        if field not in recipe_data:
            return False
        value = recipe_data[field]
        if not isinstance(value, list) or len(value) == 0:
            return False
    
    return True


def sanitize_string(value: Optional[str], max_length: Optional[int] = None) -> Optional[str]:
    """
    Sanitize a string value by trimming whitespace and optionally limiting length.
    
    Args:
        value: The string to sanitize
        max_length: Optional maximum length
    
    Returns:
        Sanitized string or None if value is None/empty
    """
    if not value:
        return None
    
    sanitized = value.strip()
    
    if max_length and len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
    
    return sanitized if sanitized else None


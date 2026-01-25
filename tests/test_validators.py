"""
Tests for validation utilities.

This module tests URL validation and input sanitization functions.
"""

import pytest

from src.validators import (
    validate_url,
    validate_url_or_raise,
    validate_recipe_data,
    sanitize_string,
)
from src.exceptions import ValidationError


def test_validate_url_valid():
    """Test validation of valid URLs."""
    assert validate_url("https://example.com/recipe") is True
    assert validate_url("http://example.com") is True
    assert validate_url("https://www.example.com/path/to/recipe?param=value") is True


def test_validate_url_invalid():
    """Test validation of invalid URLs."""
    assert validate_url("javascript:alert('xss')") is False
    assert validate_url("invalid://url") is False
    assert validate_url("") is False
    assert validate_url("localhost") is False
    # Note: localhost and 127.0.0.1 are blocked by BLOCKED_DOMAINS
    assert validate_url("http://localhost:8080") is False
    assert validate_url("http://127.0.0.1") is False
    # Test None as well
    assert validate_url(None) is False


def test_validate_url_malicious_patterns():
    """Test that malicious patterns are rejected."""
    assert validate_url("https://example.com<script>") is False
    assert validate_url("https://example.com\"onclick") is False
    assert validate_url("data:text/html,<script>alert('xss')</script>") is False


def test_validate_url_or_raise_valid():
    """Test validate_url_or_raise with valid URL."""
    # Should not raise
    validate_url_or_raise("https://example.com")


def test_validate_url_or_raise_invalid():
    """Test validate_url_or_raise with invalid URL."""
    with pytest.raises(ValidationError) as exc_info:
        validate_url_or_raise("invalid://url")
    
    assert exc_info.value.field == "url"
    assert "Invalid URL" in str(exc_info.value)


def test_validate_recipe_data_valid():
    """Test validation of valid recipe data."""
    data = {
        "ingredients": ["1 cup flour", "2 eggs"],
        "instructions": ["Mix ingredients", "Bake at 350F"]
    }
    assert validate_recipe_data(data) is True


def test_validate_recipe_data_missing_fields():
    """Test validation of recipe data with missing fields."""
    data = {"ingredients": ["1 cup flour"]}
    assert validate_recipe_data(data) is False
    
    data = {"instructions": ["Mix ingredients"]}
    assert validate_recipe_data(data) is False


def test_validate_recipe_data_empty_lists():
    """Test validation of recipe data with empty lists."""
    data = {
        "ingredients": [],
        "instructions": ["Mix ingredients"]
    }
    assert validate_recipe_data(data) is False


def test_sanitize_string():
    """Test string sanitization."""
    assert sanitize_string("  test  ") == "test"
    assert sanitize_string(None) is None
    assert sanitize_string("") is None
    assert sanitize_string("   ") is None


def test_sanitize_string_max_length():
    """Test string sanitization with max length."""
    long_string = "a" * 100
    result = sanitize_string(long_string, max_length=50)
    assert len(result) == 50
    assert result == "a" * 50


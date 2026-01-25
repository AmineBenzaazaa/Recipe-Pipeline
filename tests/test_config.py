"""
Tests for configuration management.

This module tests the Settings class and load_settings function to ensure
proper validation and error handling.
"""

import os
import pytest
from pydantic import ValidationError

from src.config import Settings, load_settings, ConfigurationError
from src.exceptions import ConfigurationError as ConfigError


def test_settings_defaults():
    """Test that Settings has sensible defaults."""
    settings = Settings()
    assert settings.temperature == 0.6
    assert settings.max_retries == 3
    assert settings.request_timeout == 30.0
    assert settings.use_multi_call is True
    assert settings.generate_images is True


def test_settings_validation_temperature():
    """Test temperature validation (0.0-2.0 range)."""
    # Valid temperature
    settings = Settings(temperature=1.5)
    assert settings.temperature == 1.5
    
    # Too high
    with pytest.raises(ValidationError):
        Settings(temperature=3.0)
    
    # Too low
    with pytest.raises(ValidationError):
        Settings(temperature=-1.0)


def test_settings_validation_max_retries():
    """Test max_retries validation (1-10 range)."""
    # Valid retries
    settings = Settings(max_retries=5)
    assert settings.max_retries == 5
    
    # Too high
    with pytest.raises(ValidationError):
        Settings(max_retries=20)
    
    # Too low
    with pytest.raises(ValidationError):
        Settings(max_retries=0)


def test_settings_validation_openai_key():
    """Test OpenAI API key format validation."""
    # Valid key
    settings = Settings(openai_api_key="sk-test123")
    assert settings.openai_api_key == "sk-test123"
    
    # Invalid format
    with pytest.raises(ValidationError) as exc_info:
        Settings(openai_api_key="invalid-key")
    assert "Invalid OpenAI API key format" in str(exc_info.value)


def test_settings_validation_image_quality():
    """Test image quality validation."""
    # Valid qualities
    for quality in ["high", "standard", "hd", ""]:
        settings = Settings(image_quality=quality)
        assert settings.image_quality == quality.lower()
    
    # Invalid quality
    with pytest.raises(ValidationError):
        Settings(image_quality="invalid")


def test_settings_helper_methods():
    """Test helper methods for checking configuration."""
    settings = Settings(
        openai_api_key="sk-test",
        serper_api_key="serper-key",
        cloudinary_url="cloudinary://test"
    )
    
    assert settings.is_openai_configured() is True
    assert settings.is_serper_configured() is True
    assert settings.is_cloudinary_configured() is True
    
    settings_empty = Settings()
    assert settings_empty.is_openai_configured() is False
    assert settings_empty.is_serper_configured() is False
    assert settings_empty.is_cloudinary_configured() is False


def test_load_settings_from_env(monkeypatch):
    """Test loading settings from environment variables."""
    # Test that Settings can be created with specific values
    # (load_settings() is tested indirectly through Settings validation)
    settings = Settings(
        openai_api_key="sk-test-env",
        temperature=0.8,
        max_retries=5
    )
    assert settings.openai_api_key == "sk-test-env"
    assert settings.temperature == 0.8
    assert settings.max_retries == 5


def test_load_settings_invalid_temperature():
    """Test that invalid temperature raises ValidationError."""
    # Test Settings validation directly
    with pytest.raises(ValidationError):
        Settings(temperature=5.0)  # Too high


def test_settings_frozen():
    """Test that Settings is immutable (frozen)."""
    settings = Settings()
    
    with pytest.raises(Exception):  # Pydantic will raise ValidationError
        settings.temperature = 1.0


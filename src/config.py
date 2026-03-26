"""
Configuration management for the Recipe Pipeline.

This module provides validated settings loaded from environment variables
with sensible defaults and type checking.
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, ConfigDict

from .exceptions import ConfigurationError

# Legacy-style simple style anchor (from legacy.py)
DEFAULT_STYLE_ANCHOR = "Exact same batch as the featured image. focus on the recipe."


def _parse_bool(value: str) -> bool:
    """Parse a string value to boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "y"}
    return False


class Settings(BaseModel):
    """
    Application settings with validation.
    
    All settings can be provided via environment variables or .env file.
    Settings are validated on initialization to catch configuration errors early.
    
    Attributes:
        openai_api_key: OpenAI API key (required for GPT features)
        serper_api_key: Serper API key (optional, for search features)
        serpapi_api_key: SerpAPI key (optional, alternative to Serper)
        style_anchor: Style description for image generation
        model_name: GPT model name for text generation
        vision_model: GPT model name for vision tasks
        image_model: Model name for image generation
        image_quality: Quality setting for generated images
        image_engine: Image generation engine ("midjourney" or "openai")
        temperature: Sampling temperature (0.0-2.0)
        target_words: Target word count for generated content
        use_multi_call: Whether to use multi-call for long content
        request_timeout: HTTP request timeout in seconds
        max_retries: Maximum retry attempts for failed requests
        user_agent: User agent string for HTTP requests
        accept_language: Optional Accept-Language header for HTTP requests
        sleep_seconds: Delay between requests in seconds
        generate_images: Whether to generate images
        image_output_dir: Directory for saving generated images
        cloudinary_url: Cloudinary URL for image uploads
        cloudinary_upload_preset: Cloudinary upload preset name
        cloudinary_folder: Cloudinary folder for uploaded images
        imagine_api_url: Base URL for ImagineAPI (Directus) instance
        imagine_api_token: API token for ImagineAPI
        imagine_api_poll_seconds: Poll interval for ImagineAPI status checks
        imagine_api_timeout_seconds: Timeout for ImagineAPI image generation
        imagine_api_auto_start: Auto-start ImagineAPI stack if unreachable
        imagine_api_startup_timeout_seconds: Timeout for ImagineAPI startup checks
        midjourney_worker_path: Path to Midjourney worker script
        midjourney_headless: Run Midjourney browser headless
        midjourney_auto_fallback_headful: Retry in headful mode if headless fails
        midjourney_timeout_seconds: Timeout for Midjourney waits
        midjourney_profile_dir: Persistent browser profile directory
        midjourney_cookies_file: Cookies JSON export for Midjourney
        midjourney_storage_state: Playwright storage state file path
        midjourney_session_id: Optional session id to isolate Midjourney profiles
        midjourney_queue_mode: Keep a single Midjourney browser open for the batch
        midjourney_queue_poll_seconds: Poll interval for queue mode
        midjourney_queue_exit_seconds: Exit delay when queue is empty
    """
    
    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())
    
    openai_api_key: str = Field(default="", description="OpenAI API key")
    serper_api_key: str = Field(default="", description="Serper API key")
    serpapi_api_key: str = Field(default="", description="SerpAPI key")
    style_anchor: str = Field(
        default=DEFAULT_STYLE_ANCHOR,
        description="Style anchor for image generation prompts"
    )
    model_name: str = Field(
        default="gpt-4.1",
        description="GPT model name for text generation"
    )
    vision_model: str = Field(
        default="gpt-4.1",
        description="GPT model name for vision tasks"
    )
    image_model: str = Field(
        default="gpt-image-1.5",
        description="Model name for image generation"
    )
    image_quality: str = Field(
        default="high",
        description="Image quality setting (high, standard, hd)"
    )
    image_engine: str = Field(
        default="openai",
        description="Image generation engine (midjourney, openai, imagineapi)"
    )
    temperature: float = Field(
        default=0.6,
        ge=0.0,
        le=2.0,
        description="Sampling temperature for text generation"
    )
    target_words: int = Field(
        default=1800,
        ge=100,
        le=10000,
        description="Target word count for generated content"
    )
    use_multi_call: bool = Field(
        default=True,
        description="Use multi-call for long content generation"
    )
    request_timeout: float = Field(
        default=30.0,
        gt=0.0,
        le=300.0,
        description="HTTP request timeout in seconds"
    )
    max_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum retry attempts for failed requests"
    )
    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        description="User agent string for HTTP requests"
    )
    accept_language: str = Field(
        default="",
        description=(
            "Optional Accept-Language header for HTTP requests. "
            "Leave empty to avoid forcing a language."
        ),
    )
    sleep_seconds: float = Field(
        default=1.0,
        ge=0.0,
        le=60.0,
        description="Delay between requests in seconds"
    )
    generate_images: bool = Field(
        default=False,
        description="Whether to actually generate images (prompts are always generated)"
    )
    use_vision_prompts: bool = Field(
        default=False,
        description="Whether to use Vision API for enhanced prompts (expensive). If False, uses template prompts."
    )
    skip_metadata_enrichment: bool = Field(
        default=False,
        description="Skip GPT-based metadata enrichment to save costs"
    )
    skip_gpt_faqs: bool = Field(
        default=False,
        description="Skip GPT FAQ generation, only use search APIs"
    )
    image_output_dir: str = Field(
        default="generated_images",
        description="Directory for saving generated images"
    )
    cloudinary_url: str = Field(
        default="",
        description="Cloudinary URL for image uploads"
    )
    cloudinary_upload_preset: str = Field(
        default="",
        description="Cloudinary upload preset name"
    )
    cloudinary_folder: str = Field(
        default="recipe-pipeline",
        description="Cloudinary folder for uploaded images"
    )
    imagine_api_url: str = Field(
        default="",
        description="ImagineAPI base URL (e.g. http://localhost:8055)"
    )
    imagine_api_token: str = Field(
        default="",
        description="ImagineAPI API token"
    )
    imagine_api_poll_seconds: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Polling interval for ImagineAPI (seconds)"
    )
    imagine_api_timeout_seconds: int = Field(
        default=600,
        ge=30,
        le=3600,
        description="Timeout for ImagineAPI image generation (seconds)"
    )
    imagine_api_auto_start: bool = Field(
        default=False,
        description="Auto-start ImagineAPI stack if API is unreachable"
    )
    imagine_api_startup_timeout_seconds: int = Field(
        default=120,
        ge=30,
        le=1800,
        description="Timeout for ImagineAPI startup checks (seconds)"
    )
    midjourney_worker_path: str = Field(
        default="midjourney_engine/midjourney_worker.py",
        description="Path to Midjourney worker script"
    )
    midjourney_headless: bool = Field(
        default=False,
        description="Run Midjourney browser in headless mode"
    )
    midjourney_auto_fallback_headful: bool = Field(
        default=False,
        description="Retry Midjourney run in headful mode if headless is blocked"
    )
    midjourney_timeout_seconds: int = Field(
        default=300,
        ge=30,
        le=1800,
        description="Timeout for Midjourney waits (seconds)"
    )
    midjourney_profile_dir: str = Field(
        default=".playwright/discord-profile",
        description="Persistent browser profile directory"
    )
    midjourney_cookies_file: str = Field(
        default="midjourney_cookies.json",
        description="Cookies JSON export for Midjourney"
    )
    midjourney_storage_state: str = Field(
        default="",
        description="Playwright storage state file path"
    )
    midjourney_session_id: str = Field(
        default="",
        description="Optional session id to isolate Midjourney profiles"
    )
    midjourney_queue_mode: bool = Field(
        default=True,
        description="Keep a single Midjourney browser open while processing a batch"
    )
    midjourney_queue_poll_seconds: int = Field(
        default=2,
        ge=1,
        le=30,
        description="Polling interval for Midjourney queue mode"
    )
    midjourney_queue_exit_seconds: int = Field(
        default=10,
        ge=2,
        le=120,
        description="Seconds to wait before exiting queue mode when idle"
    )
    image_realism_scoring: bool = Field(
        default=False,
        description="Use vision model to score and select the most realistic image (imagineapi only)"
    )
    
    @field_validator('openai_api_key')
    @classmethod
    def validate_openai_key(cls, v: str) -> str:
        """Validate OpenAI API key format (if provided)."""
        if v and not v.startswith('sk-'):
            raise ValueError(
                'Invalid OpenAI API key format. Keys should start with "sk-"'
            )
        return v
    
    @field_validator('image_quality')
    @classmethod
    def validate_image_quality(cls, v: str) -> str:
        """Validate image quality setting."""
        valid_qualities = {'high', 'standard', 'hd', ''}
        if v.lower() not in valid_qualities:
            raise ValueError(
                f'Invalid image quality: {v}. Must be one of {valid_qualities}'
            )
        return v.lower()

    @field_validator('image_engine')
    @classmethod
    def validate_image_engine(cls, v: str) -> str:
        """Validate image engine setting."""
        value = (v or "").strip().lower()
        valid_engines = {"midjourney", "openai", "imagineapi"}
        if value not in valid_engines:
            raise ValueError(
                f'Invalid image engine: {v}. Must be one of {valid_engines}'
            )
        return value
    
    @field_validator('model_name', 'vision_model')
    @classmethod
    def validate_model_name(cls, v: str) -> str:
        """Validate model name format."""
        if not v or len(v.strip()) == 0:
            raise ValueError('Model name cannot be empty')
        return v.strip()
    
    def is_openai_configured(self) -> bool:
        """Check if OpenAI API is configured."""
        return bool(self.openai_api_key)
    
    def is_serper_configured(self) -> bool:
        """Check if Serper API is configured."""
        return bool(self.serper_api_key)
    
    def is_serpapi_configured(self) -> bool:
        """Check if SerpAPI is configured."""
        return bool(self.serpapi_api_key)
    
    def is_cloudinary_configured(self) -> bool:
        """Check if Cloudinary is configured."""
        return bool(self.cloudinary_url)

    def is_imagineapi_configured(self) -> bool:
        """Check if ImagineAPI is configured."""
        return bool(self.imagine_api_url and self.imagine_api_token)


def load_settings() -> Settings:
    """
    Load and validate settings from environment variables.
    
    Settings are loaded from:
    1. Environment variables
    2. .env file (if present)
    
    Returns:
        Validated Settings object
        
    Raises:
        ConfigurationError: If required settings are invalid or missing
        
    Example:
        >>> settings = load_settings()
        >>> if settings.is_openai_configured():
        ...     print("OpenAI is configured")
    """
    load_dotenv()
    shared_env_path = Path(__file__).resolve().parents[1] / "midjourney_engine" / ".shared.env"
    if shared_env_path.exists():
        load_dotenv(dotenv_path=shared_env_path, override=False)
    
    try:
        # Parse boolean values from environment
        use_multi_call = _parse_bool(os.getenv("USE_MULTI_CALL", "true"))
        generate_images = _parse_bool(os.getenv("GENERATE_IMAGES", "true"))
        image_realism_scoring = _parse_bool(
            os.getenv("IMAGE_REALISM_SCORING", "false")
        )
        
        settings = Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        serper_api_key=os.getenv("SERPER_API_KEY", ""),
        serpapi_api_key=os.getenv("SERPAPI_API_KEY", ""),
        style_anchor=os.getenv("STYLE_ANCHOR", DEFAULT_STYLE_ANCHOR),
        model_name=os.getenv("MODEL_NAME", "gpt-4.1"),
        vision_model=os.getenv("VISION_MODEL", "gpt-4.1"),
        image_model=os.getenv("IMAGE_MODEL", "gpt-image-1.5"),
        image_quality=os.getenv("IMAGE_QUALITY", "high"),
        image_engine=os.getenv("IMAGE_ENGINE", "openai"),
        temperature=float(os.getenv("TEMPERATURE", "0.6")),
        target_words=int(os.getenv("TARGET_WORDS", "1800")),
            use_multi_call=use_multi_call,
        request_timeout=float(os.getenv("REQUEST_TIMEOUT", "30")),
        max_retries=int(os.getenv("MAX_RETRIES", "3")),
        user_agent=os.getenv(
            "USER_AGENT",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36",
        ),
        sleep_seconds=float(os.getenv("SLEEP_SECONDS", "1.0")),
            accept_language=os.getenv("ACCEPT_LANGUAGE", ""),
            generate_images=generate_images,
            use_vision_prompts=_parse_bool(os.getenv("USE_VISION_PROMPTS", "false")),
            skip_metadata_enrichment=_parse_bool(os.getenv("SKIP_METADATA_ENRICHMENT", "false")),
            skip_gpt_faqs=_parse_bool(os.getenv("SKIP_GPT_FAQS", "false")),
        image_output_dir=os.getenv("IMAGE_OUTPUT_DIR", "generated_images"),
        cloudinary_url=os.getenv("CLOUDINARY_URL", ""),
        cloudinary_upload_preset=os.getenv("CLOUDINARY_UPLOAD_PRESET", ""),
        cloudinary_folder=os.getenv("CLOUDINARY_FOLDER", "recipe-pipeline"),
        imagine_api_url=os.getenv("IMAGINE_API_URL", os.getenv("PUBLIC_URL", "")),
        imagine_api_token=os.getenv("IMAGINE_API_TOKEN", os.getenv("API_TOKEN", "")),
        imagine_api_poll_seconds=int(os.getenv("IMAGINE_API_POLL_SECONDS", "5")),
        imagine_api_timeout_seconds=int(os.getenv("IMAGINE_API_TIMEOUT_SECONDS", "600")),
        imagine_api_auto_start=_parse_bool(os.getenv("IMAGINE_API_AUTO_START", "false")),
        imagine_api_startup_timeout_seconds=int(
            os.getenv("IMAGINE_API_STARTUP_TIMEOUT_SECONDS", "120")
        ),
        midjourney_worker_path=os.getenv(
            "MIDJOURNEY_WORKER_PATH", "midjourney_engine/midjourney_worker.py"
        ),
        midjourney_headless=_parse_bool(os.getenv("MIDJOURNEY_HEADLESS", "false")),
        midjourney_auto_fallback_headful=_parse_bool(
            os.getenv("MIDJOURNEY_AUTO_FALLBACK_HEADFUL", "false")
        ),
        midjourney_timeout_seconds=int(os.getenv("MIDJOURNEY_TIMEOUT_SECONDS", "300")),
        midjourney_profile_dir=os.getenv(
            "MIDJOURNEY_PROFILE_DIR", ".playwright/discord-profile"
        ),
        midjourney_cookies_file=os.getenv(
            "MIDJOURNEY_COOKIES_FILE", "midjourney_cookies.json"
        ),
        midjourney_storage_state=os.getenv("MIDJOURNEY_STORAGE_STATE", ""),
        midjourney_session_id=os.getenv("MIDJOURNEY_SESSION_ID", ""),
        midjourney_queue_mode=_parse_bool(os.getenv("MIDJOURNEY_QUEUE_MODE", "true")),
        midjourney_queue_poll_seconds=int(os.getenv("MIDJOURNEY_QUEUE_POLL_SECONDS", "2")),
        midjourney_queue_exit_seconds=int(os.getenv("MIDJOURNEY_QUEUE_EXIT_SECONDS", "10")),
        image_realism_scoring=image_realism_scoring,
    )
        
        return settings
    except ValueError as e:
        raise ConfigurationError(
            f"Invalid configuration: {e}",
            context={"error": str(e)}
        ) from e
    except Exception as e:
        raise ConfigurationError(
            f"Failed to load settings: {e}",
            context={"error": str(e)}
        ) from e

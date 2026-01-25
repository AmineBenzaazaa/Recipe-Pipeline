"""
Custom exception hierarchy for the Recipe Pipeline.

This module defines structured exceptions that provide better error context
and enable more sophisticated error handling throughout the application.
"""


class RecipePipelineError(Exception):
    """Base exception for all recipe pipeline errors."""
    
    def __init__(self, message: str, context: dict = None):
        super().__init__(message)
        self.message = message
        self.context = context or {}


class ExtractionError(RecipePipelineError):
    """Raised when recipe extraction fails."""
    
    def __init__(self, message: str, url: str = None, method: str = None, context: dict = None):
        super().__init__(message, context)
        self.url = url
        self.method = method


class APIError(RecipePipelineError):
    """Raised when an external API call fails."""
    
    def __init__(
        self,
        message: str,
        service: str = None,
        status_code: int = None,
        retry_after: int = None,
        context: dict = None
    ):
        super().__init__(message, context)
        self.service = service
        self.status_code = status_code
        self.retry_after = retry_after


class ValidationError(RecipePipelineError):
    """Raised when data validation fails."""
    
    def __init__(self, message: str, field: str = None, value: any = None, context: dict = None):
        super().__init__(message, context)
        self.field = field
        self.value = value


class ConfigurationError(RecipePipelineError):
    """Raised when configuration is invalid or missing."""
    pass


class ImageGenerationError(RecipePipelineError):
    """Raised when image generation fails."""
    
    def __init__(self, message: str, prompt: str = None, image_type: str = None, context: dict = None):
        super().__init__(message, context)
        self.prompt = prompt
        self.image_type = image_type


"""
Retry utilities for the Recipe Pipeline.

This module provides reusable retry logic to reduce code duplication
and ensure consistent retry behavior across the codebase.
"""

import logging
from typing import TypeVar, Callable, Type, Tuple, Any
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    RetryError,
)

import requests

from .config import Settings
from .exceptions import APIError

T = TypeVar('T')


def with_retry(
    max_attempts: int = 3,
    exceptions: Tuple[Type[Exception], ...] = (requests.RequestException,),
    min_wait: float = 1.0,
    max_wait: float = 8.0,
    multiplier: float = 1.0,
) -> Callable:
    """
    Decorator to add retry logic to a function.
    
    Args:
        max_attempts: Maximum number of retry attempts
        exceptions: Tuple of exception types to retry on
        min_wait: Minimum wait time between retries in seconds
        max_wait: Maximum wait time between retries in seconds
        multiplier: Multiplier for exponential backoff
    
    Returns:
        Decorated function with retry logic
    
    Example:
        >>> @with_retry(max_attempts=5)
        ... def fetch_data(url: str) -> dict:
        ...     response = requests.get(url)
        ...     response.raise_for_status()
        ...     return response.json()
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        def wrapper(*args, **kwargs) -> T:
            retryer = Retrying(
                stop=stop_after_attempt(max_attempts),
                wait=wait_exponential(multiplier=multiplier, min=min_wait, max=max_wait),
                retry=retry_if_exception_type(exceptions),
                reraise=True,
            )
            for attempt in retryer:
                with attempt:
                    return func(*args, **kwargs)
            # This should never be reached due to reraise=True, but type checker needs it
            raise RetryError("Retry exhausted")
        return wrapper
    return decorator


def create_retryer(
    settings: Settings,
    exceptions: Tuple[Type[Exception], ...] = (requests.RequestException,),
) -> Retrying:
    """
    Create a Retrying instance configured from settings.
    
    Args:
        settings: Application settings
        exceptions: Tuple of exception types to retry on
    
    Returns:
        Configured Retrying instance
    
    Example:
        >>> retryer = create_retryer(settings)
        >>> for attempt in retryer:
        ...     with attempt:
        ...         result = make_api_call()
    """
    return Retrying(
        stop=stop_after_attempt(settings.max_retries),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(exceptions),
        reraise=True,
    )


def execute_with_retry(
    func: Callable[..., T],
    settings: Settings,
    logger: logging.Logger,
    *args,
    exceptions: Tuple[Type[Exception], ...] = (requests.RequestException,),
    **kwargs,
) -> T:
    """
    Execute a function with retry logic based on settings.
    
    This is a convenience function that wraps the retry logic
    and provides consistent error handling.
    
    Args:
        func: Function to execute
        settings: Application settings
        logger: Logger instance
        *args: Positional arguments to pass to func
        exceptions: Exception types to retry on
        **kwargs: Keyword arguments to pass to func
    
    Returns:
        Result from func
    
    Raises:
        APIError: If all retry attempts fail
    
    Example:
        >>> result = execute_with_retry(
        ...     requests.get,
        ...     settings,
        ...     logger,
        ...     "https://api.example.com/data"
        ... )
    """
    retryer = create_retryer(settings, exceptions)
    
    try:
        for attempt in retryer:
            with attempt:
                return func(*args, **kwargs)
    except requests.RequestException as e:
        status_code = getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None
        retry_after = None
        if hasattr(e, 'response') and e.response is not None:
            retry_after = e.response.headers.get('Retry-After')
            if retry_after:
                try:
                    retry_after = int(retry_after)
                except ValueError:
                    retry_after = None
        
        logger.error(
            f"Request failed after {settings.max_retries} attempts: {e}",
            extra={"status_code": status_code, "retry_after": retry_after}
        )
        
        raise APIError(
            f"Request failed: {e}",
            status_code=status_code,
            retry_after=retry_after,
            context={"max_retries": settings.max_retries}
        ) from e
    except Exception as e:
        logger.error(f"Unexpected error in retry logic: {e}")
        raise


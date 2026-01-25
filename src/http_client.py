"""
HTTP client with connection pooling and retry logic.

This module provides a reusable HTTP client that handles connection pooling,
retry logic, and consistent error handling across the application.
"""

import logging
from typing import Optional, Dict, Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import Settings
from .retry import execute_with_retry
from .exceptions import APIError


class HTTPClient:
    """
    HTTP client with connection pooling and automatic retries.
    
    This client maintains a session with connection pooling for better
    performance and handles retries automatically based on settings.
    
    Example:
        >>> client = HTTPClient(settings, logger)
        >>> response = client.get("https://api.example.com/data")
        >>> data = response.json()
    """
    
    def __init__(self, settings: Settings, logger: logging.Logger):
        """
        Initialize HTTP client with connection pooling.
        
        Args:
            settings: Application settings
            logger: Logger instance
        """
        self.settings = settings
        self.logger = logger
        self.session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=settings.max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "DELETE"],
            raise_on_status=False,
        )
        
        # Configure adapter with connection pooling
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=20,
            pool_block=False,
        )
        
        # Mount adapters for both HTTP and HTTPS
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Set default headers
        self.session.headers.update({
            "User-Agent": settings.user_agent,
        })
    
    def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        **kwargs
    ) -> requests.Response:
        """
        Perform a GET request with retry logic.
        
        Args:
            url: URL to request
            params: Query parameters
            headers: Additional headers
            timeout: Request timeout (defaults to settings.request_timeout)
            **kwargs: Additional arguments for requests.get
        
        Returns:
            Response object
        
        Raises:
            APIError: If the request fails after all retries
        """
        timeout = timeout or self.settings.request_timeout
        request_headers = {**self.session.headers}
        if headers:
            request_headers.update(headers)
        
        def _get():
            response = self.session.get(
                url,
                params=params,
                headers=request_headers,
                timeout=timeout,
                **kwargs
            )
            # Raise for status codes that should trigger retries
            if response.status_code >= 500:
                raise requests.RequestException(
                    f"Server error: {response.status_code}"
                )
            return response
        
        try:
            return execute_with_retry(
                _get,
                self.settings,
                self.logger,
                exceptions=(requests.RequestException,)
            )
        except APIError:
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in GET request: {e}")
            raise APIError(
                f"GET request failed: {e}",
                context={"url": url}
            ) from e
    
    def post(
        self,
        url: str,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        **kwargs
    ) -> requests.Response:
        """
        Perform a POST request with retry logic.
        
        Args:
            url: URL to request
            json: JSON data to send
            data: Form data to send
            headers: Additional headers
            timeout: Request timeout (defaults to settings.request_timeout)
            **kwargs: Additional arguments for requests.post
        
        Returns:
            Response object
        
        Raises:
            APIError: If the request fails after all retries
        """
        timeout = timeout or self.settings.request_timeout
        request_headers = {**self.session.headers}
        if headers:
            request_headers.update(headers)
        
        def _post():
            response = self.session.post(
                url,
                json=json,
                data=data,
                headers=request_headers,
                timeout=timeout,
                **kwargs
            )
            # Raise for status codes that should trigger retries
            if response.status_code >= 500:
                raise requests.RequestException(
                    f"Server error: {response.status_code}"
                )
            return response
        
        try:
            return execute_with_retry(
                _post,
                self.settings,
                self.logger,
                exceptions=(requests.RequestException,)
            )
        except APIError:
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in POST request: {e}")
            raise APIError(
                f"POST request failed: {e}",
                context={"url": url}
            ) from e
    
    def close(self):
        """Close the session and release resources."""
        self.session.close()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False


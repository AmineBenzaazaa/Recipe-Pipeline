"""
Result pattern implementation for better error handling.

This module provides a Result type that explicitly handles success and failure
cases, making error handling more explicit and preventing silent failures.
"""

from typing import TypeVar, Generic, Optional, Callable
from dataclasses import dataclass

T = TypeVar('T')
E = TypeVar('E', bound=Exception)


@dataclass
class Result(Generic[T]):
    """
    A Result type that represents either success (with a value) or failure (with an error).
    
    This pattern helps avoid silent failures and makes error handling explicit.
    
    Example:
        >>> result = Result.ok("success value")
        >>> if result.success:
        ...     print(result.value)
        ... else:
        ...     print(f"Error: {result.error}")
    """
    value: Optional[T] = None
    error: Optional[Exception] = None
    success: bool = False
    
    @classmethod
    def ok(cls, value: T) -> 'Result[T]':
        """Create a successful result with a value."""
        return cls(value=value, success=True)
    
    @classmethod
    def fail(cls, error: Exception) -> 'Result[T]':
        """Create a failed result with an error."""
        return cls(error=error, success=False)
    
    def unwrap_or(self, default: T) -> T:
        """Return the value if successful, otherwise return the default."""
        return self.value if self.success else default
    
    def unwrap_or_else(self, func: Callable[[Exception], T]) -> T:
        """Return the value if successful, otherwise call func with the error."""
        return self.value if self.success else func(self.error)
    
    def map(self, func: Callable[[T], 'Result[T]']) -> 'Result[T]':
        """Apply a function to the value if successful."""
        if self.success:
            return func(self.value)
        return self
    
    def is_ok(self) -> bool:
        """Check if the result is successful."""
        return self.success
    
    def is_err(self) -> bool:
        """Check if the result is an error."""
        return not self.success


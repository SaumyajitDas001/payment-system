"""
Domain exceptions.
Each exception maps to a specific HTTP status code.
The global exception handler in main.py converts these to proper API responses.
"""

from fastapi import HTTPException, status


class PaymentSystemException(HTTPException):
    """Base exception for all domain errors."""
    def __init__(self, detail: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(status_code=status_code, detail=detail)


class UserNotFoundException(PaymentSystemException):
    def __init__(self, user_id: str = ""):
        super().__init__(
            detail=f"User not found: {user_id}" if user_id else "User not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class UserAlreadyExistsException(PaymentSystemException):
    def __init__(self, email: str = ""):
        super().__init__(
            detail=f"User with email '{email}' already exists",
            status_code=status.HTTP_409_CONFLICT,
        )


class WalletNotFoundException(PaymentSystemException):
    def __init__(self):
        super().__init__(
            detail="Wallet not found for this user",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class InsufficientBalanceException(PaymentSystemException):
    def __init__(self, available: str = "", required: str = ""):
        detail = "Insufficient balance"
        if available and required:
            detail = f"Insufficient balance: available={available}, required={required}"
        super().__init__(
            detail=detail,
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
        )


class DuplicateTransactionException(PaymentSystemException):
    def __init__(self):
        super().__init__(
            detail="Duplicate transaction — this idempotency key has already been processed",
            status_code=status.HTTP_409_CONFLICT,
        )


class SelfTransferException(PaymentSystemException):
    def __init__(self):
        super().__init__(
            detail="Cannot transfer money to yourself",
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class OptimisticLockException(PaymentSystemException):
    def __init__(self):
        super().__init__(
            detail="Concurrent modification detected — please retry",
            status_code=status.HTTP_409_CONFLICT,
        )

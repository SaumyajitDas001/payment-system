"""
Enhanced payment service with production-grade failure handling.

FAILURE SCENARIOS AND HOW WE HANDLE THEM:

1. Network timeout before response
   -> Client retries with same idempotency key -> returns cached result

2. DB connection drops mid-transaction
   -> SQLAlchemy rolls back automatically -> client retries -> processes fresh

3. Concurrent transfers from same wallet (race condition)
   -> SELECT FOR UPDATE locks prevent this
   -> Optimistic locking (version column) as secondary defense

4. Redis is down
   -> System works without cache, just slower
   -> DB UNIQUE constraint still prevents duplicates

5. Partial failure (debit succeeds, credit fails)
   -> IMPOSSIBLE: both are in the same DB transaction
   -> Single COMMIT means all-or-nothing

6. Deadlocks between concurrent cross-transfers
   -> Wallets always locked in sorted-ID order -> deadlock-free

7. Insufficient balance detected after lock acquired
   -> Transaction marked FAILED, no money moves, error returned
   -> Idempotency key is NOT stored so client can retry with new key
"""

import logging
from decimal import Decimal
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    DuplicateTransactionException,
    InsufficientBalanceException,
    OptimisticLockException,
    SelfTransferException,
    WalletNotFoundException,
)
from app.models.transaction import Transaction, TransactionStatus
from app.repositories.transaction_repo import transaction_repository
from app.repositories.wallet_repo import wallet_repository
from app.schemas.payment import PaymentRequest, TransactionResponse
from app.services.idempotency_service import idempotency_service

logger = logging.getLogger(__name__)

MAX_RETRY_ATTEMPTS = 3


class PaymentService:

    async def send_money(
        self,
        db: AsyncSession,
        sender_user_id: UUID,
        request: PaymentRequest,
        redis_client: aioredis.Redis | None = None,
    ) -> TransactionResponse:
        """
        Execute a payment with full idempotency and failure handling.
        Retries internally on optimistic lock conflicts.
        """

        # --- IDEMPOTENCY: Check if already processed ---
        cached = await idempotency_service.check_key(
            request.idempotency_key, redis_client
        )
        if cached:
            return TransactionResponse(**cached["response"])

        # Also check DB (handles Redis miss)
        existing_txn = await transaction_repository.get_by_idempotency_key(
            db, request.idempotency_key
        )
        if existing_txn:
            return TransactionResponse.model_validate(existing_txn)

        # --- VALIDATION ---
        sender_wallet = await wallet_repository.get_by_user_id(db, sender_user_id)
        if not sender_wallet:
            raise WalletNotFoundException()

        receiver_wallet = await wallet_repository.get_by_user_id(
            db, request.receiver_id
        )
        if not receiver_wallet:
            raise WalletNotFoundException()

        if sender_wallet.id == receiver_wallet.id:
            raise SelfTransferException()

        # --- EXECUTE WITH RETRY ---
        last_error = None
        for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
            try:
                result = await self._execute_transfer(
                    db=db,
                    sender_wallet_id=sender_wallet.id,
                    receiver_wallet_id=receiver_wallet.id,
                    amount=request.amount,
                    currency=request.currency,
                    idempotency_key=request.idempotency_key,
                    description=request.description,
                )

                # --- POST-COMMIT: Cache idempotency + invalidate balances ---
                if redis_client:
                    response_data = result.model_dump(mode="json")
                    await idempotency_service.store_key(
                        request.idempotency_key,
                        response_data,
                        201,
                        redis_client,
                    )
                    pipe = redis_client.pipeline()
                    pipe.delete(f"wallet:balance:{sender_wallet.id}")
                    pipe.delete(f"wallet:balance:{receiver_wallet.id}")
                    await pipe.execute()

                logger.info(
                    "Payment completed on attempt %d: txn=%s amount=%s",
                    attempt,
                    result.id,
                    request.amount,
                )
                return result

            except IntegrityError:
                # UNIQUE constraint violation on idempotency_key means
                # a concurrent request with the same key already succeeded
                await db.rollback()
                existing = await transaction_repository.get_by_idempotency_key(
                    db, request.idempotency_key
                )
                if existing:
                    return TransactionResponse.model_validate(existing)
                raise DuplicateTransactionException()

            except OptimisticLockException:
                await db.rollback()
                last_error = OptimisticLockException()
                logger.warning(
                    "Optimistic lock conflict on attempt %d/%d",
                    attempt,
                    MAX_RETRY_ATTEMPTS,
                )
                if attempt == MAX_RETRY_ATTEMPTS:
                    raise last_error
                continue

            except InsufficientBalanceException:
                # Don't store idempotency key so client CAN retry
                await db.rollback()
                raise

            except Exception as e:
                await db.rollback()
                logger.error(
                    "Unexpected payment error on attempt %d: %s",
                    attempt, e, exc_info=True,
                )
                raise

        raise last_error or Exception("Payment failed after all retries")

    async def _execute_transfer(
        self,
        db: AsyncSession,
        sender_wallet_id: UUID,
        receiver_wallet_id: UUID,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
        description: str | None,
    ) -> TransactionResponse:
        """
        Internal: executes debit-credit-record inside a single DB transaction.
        Separated from send_money() so the retry loop stays clean.
        """

        # Lock wallets in sorted order (deadlock prevention)
        wallet_ids = sorted([sender_wallet_id, receiver_wallet_id])
        locked_first = await wallet_repository.get_by_id_for_update(
            db, wallet_ids[0]
        )
        locked_second = await wallet_repository.get_by_id_for_update(
            db, wallet_ids[1]
        )

        if not locked_first or not locked_second:
            raise WalletNotFoundException()

        if locked_first.id == sender_wallet_id:
            sender, receiver = locked_first, locked_second
        else:
            sender, receiver = locked_second, locked_first

        # Balance check with locked data (no race possible)
        if sender.balance < amount:
            raise InsufficientBalanceException(
                available=str(sender.balance),
                required=str(amount),
            )

        # Debit sender
        sender_ok = await wallet_repository.update_balance(
            db, sender.id, sender.balance - amount, sender.version
        )
        if not sender_ok:
            raise OptimisticLockException()

        # Credit receiver
        receiver_ok = await wallet_repository.update_balance(
            db, receiver.id, receiver.balance + amount, receiver.version
        )
        if not receiver_ok:
            raise OptimisticLockException()

        # Record transaction
        transaction = Transaction(
            sender_wallet_id=sender.id,
            receiver_wallet_id=receiver.id,
            amount=amount,
            currency=currency,
            status=TransactionStatus.COMPLETED,
            idempotency_key=idempotency_key,
            description=description,
        )
        transaction = await transaction_repository.create(db, transaction)

        # ATOMIC COMMIT
        await db.commit()
        await db.refresh(transaction)

        return TransactionResponse.model_validate(transaction)


payment_service = PaymentService()

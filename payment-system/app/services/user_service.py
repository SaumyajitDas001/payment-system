"""
User service.
Orchestrates user registration (with automatic wallet creation) and login.
Business rules live here; database access is delegated to repositories.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UserAlreadyExistsException, UserNotFoundException
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.models.wallet import Wallet
from app.repositories.user_repo import user_repository
from app.repositories.wallet_repo import wallet_repository
from app.schemas.user import TokenResponse, UserCreate, UserLogin, UserResponse


class UserService:

    async def register(self, db: AsyncSession, data: UserCreate) -> UserResponse:
        """
        Register a new user and create their wallet atomically.
        If either operation fails, both roll back.
        """
        # Check for duplicate email
        existing = await user_repository.get_by_email(db, data.email)
        if existing:
            raise UserAlreadyExistsException(data.email)

        # Create user
        user = User(
            email=data.email,
            password_hash=hash_password(data.password),
            full_name=data.full_name,
        )
        user = await user_repository.create(db, user)

        # Create wallet for the user (same transaction)
        wallet = Wallet(user_id=user.id)
        await wallet_repository.create(db, wallet)

        # Single commit — both user and wallet are created atomically
        await db.commit()
        await db.refresh(user)

        return UserResponse.model_validate(user)

    async def login(self, db: AsyncSession, data: UserLogin) -> TokenResponse:
        """Authenticate user and return a JWT token."""
        user = await user_repository.get_by_email(db, data.email)
        if not user or not verify_password(data.password, user.password_hash):
            raise UserNotFoundException()

        token = create_access_token(data={"sub": str(user.id)})
        return TokenResponse(access_token=token)

    async def get_user(self, db: AsyncSession, user_id) -> UserResponse:
        user = await user_repository.get_by_id(db, user_id)
        if not user:
            raise UserNotFoundException(str(user_id))
        return UserResponse.model_validate(user)


user_service = UserService()

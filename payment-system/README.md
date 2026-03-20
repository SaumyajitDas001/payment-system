# Real-Time Payment Processing System

A production-grade, microservices-ready payment processing backend built with **FastAPI**, **PostgreSQL**, and **Redis**. Supports user wallets, P2P transfers, idempotent transactions, and low-latency cached balance lookups.

Designed to demonstrate financial-system engineering patterns: ACID atomicity, deadlock prevention, optimistic locking, two-tier idempotency, and cache-aside with write-through invalidation.

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| API | FastAPI (Python 3.12) | Async REST endpoints with auto-generated OpenAPI docs |
| Database | PostgreSQL 16 | Source of truth — ACID transactions, row-level locking |
| Cache | Redis 7 | Sub-millisecond balance lookups, idempotency dedup, rate limiting |
| ORM | SQLAlchemy 2.0 (async) | Type-safe models with connection pooling |
| Auth | JWT (python-jose) | Stateless token-based authentication |
| Validation | Pydantic v2 | Request/response schemas with strict type checking |
| Containers | Docker Compose | One-command local development environment |

---

## Quick Start

### Prerequisites

- Docker & Docker Compose
- (Optional) Python 3.12+ for running outside Docker

### Run with Docker (recommended)

```bash
# Clone and start all services
git clone <your-repo-url>
cd payment-system
docker-compose up --build

# In another terminal — initialize database tables
docker-compose exec app python -m scripts.init_db
```

The API is live at **http://localhost:8000** and Swagger docs at **http://localhost:8000/docs**.

### Run without Docker

```bash
# Install dependencies
pip install -r requirements.txt

# Start PostgreSQL and Redis locally, then:
export DATABASE_URL=postgresql+asyncpg://payment_user:payment_pass@localhost:5432/payment_db
export REDIS_URL=redis://localhost:6379/0

# Initialize tables
python -m scripts.init_db

# Start the server
uvicorn app.main:app --reload --port 8000
```

---

## API Endpoints

### Public

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/users/register` | Create user + wallet atomically |
| `POST` | `/api/v1/users/login` | Authenticate, returns JWT |
| `GET` | `/health` | Health check with Redis status |

### Protected (Bearer token required)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/users/me` | Current user profile |
| `GET` | `/api/v1/wallets/me` | Wallet balance (Redis-accelerated) |
| `POST` | `/api/v1/wallets/me/top-up` | Add funds to wallet |
| `POST` | `/api/v1/payments/send` | Transfer money (idempotent, rate-limited) |
| `GET` | `/api/v1/payments/history` | Paginated transaction history |
| `GET` | `/api/v1/payments/transactions/{id}` | Single transaction detail |

### Example: Complete Payment Flow

```bash
# 1. Register two users
curl -X POST http://localhost:8000/api/v1/users/register \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@example.com", "password": "securepass1", "full_name": "Alice Smith"}'

curl -X POST http://localhost:8000/api/v1/users/register \
  -H "Content-Type: application/json" \
  -d '{"email": "bob@example.com", "password": "securepass2", "full_name": "Bob Jones"}'

# 2. Login as Alice
curl -X POST http://localhost:8000/api/v1/users/login \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@example.com", "password": "securepass1"}'
# → {"access_token": "eyJ...", "token_type": "bearer"}

# 3. Top up Alice's wallet
curl -X POST http://localhost:8000/api/v1/wallets/me/top-up \
  -H "Authorization: Bearer eyJ..." \
  -H "Content-Type: application/json" \
  -d '{"amount": "100.00"}'

# 4. Send $50 to Bob (use Bob's user ID from registration response)
curl -X POST http://localhost:8000/api/v1/payments/send \
  -H "Authorization: Bearer eyJ..." \
  -H "Content-Type: application/json" \
  -d '{
    "receiver_id": "<bob-user-id>",
    "amount": "50.00",
    "idempotency_key": "550e8400-e29b-41d4-a716-446655440000",
    "description": "Lunch money"
  }'

# 5. Retry the same request (same idempotency_key) — returns cached result, no double charge
curl -X POST http://localhost:8000/api/v1/payments/send \
  -H "Authorization: Bearer eyJ..." \
  -H "Content-Type: application/json" \
  -d '{
    "receiver_id": "<bob-user-id>",
    "amount": "50.00",
    "idempotency_key": "550e8400-e29b-41d4-a716-446655440000",
    "description": "Lunch money"
  }'
# → Same response, same transaction ID. Alice is only charged once.

# 6. Check transaction history
curl http://localhost:8000/api/v1/payments/history \
  -H "Authorization: Bearer eyJ..."
```

---

## Project Structure

```
payment-system/
├── app/
│   ├── api/v1/                  # Route handlers
│   │   ├── users.py             #   Register, login, profile
│   │   ├── wallets.py           #   Balance, top-up
│   │   └── payments.py          #   Send money, history
│   ├── core/                    # Infrastructure
│   │   ├── config.py            #   Environment settings (pydantic-settings)
│   │   ├── database.py          #   Async SQLAlchemy engine + session
│   │   ├── redis.py             #   Redis connection factory
│   │   ├── security.py          #   bcrypt hashing + JWT tokens
│   │   ├── exceptions.py        #   Domain error types
│   │   └── logging_config.py    #   JSON (prod) / readable (dev) logging
│   ├── middleware/               # Cross-cutting concerns
│   │   ├── auth.py              #   JWT token extraction
│   │   ├── rate_limiter.py      #   Redis sliding-window rate limiter
│   │   ├── request_context.py   #   Request-ID tracing
│   │   └── error_handler.py     #   Global exception → JSON response
│   ├── models/                  # SQLAlchemy ORM models
│   │   ├── user.py              #   Users table
│   │   ├── wallet.py            #   Wallets table (CHECK balance >= 0)
│   │   └── transaction.py       #   Transactions table (immutable ledger)
│   ├── repositories/            # Database access (no business logic)
│   │   ├── user_repo.py         #   CRUD, email lookup
│   │   ├── wallet_repo.py       #   FOR UPDATE locking, version updates
│   │   └── transaction_repo.py  #   Paginated history, idempotency lookup
│   ├── schemas/                 # Pydantic request/response models
│   │   ├── user.py              #   UserCreate, UserResponse, TokenResponse
│   │   ├── wallet.py            #   WalletResponse, WalletTopUp
│   │   └── payment.py           #   PaymentRequest, TransactionResponse
│   ├── services/                # Business logic
│   │   ├── user_service.py      #   Registration + wallet creation
│   │   ├── wallet_service.py    #   Cache-aside balance reads
│   │   ├── payment_service.py   #   Atomic transfers with retry logic
│   │   ├── idempotency_service.py  # Two-tier deduplication
│   │   └── cache_manager.py     #   All Redis operations
│   └── main.py                  # FastAPI app with lifespan + middleware
├── scripts/
│   └── init_db.py               # Create tables from ORM models
├── tests/                       # Test directory
├── docker-compose.yml           # PostgreSQL + Redis + App
├── Dockerfile                   # Python 3.12 slim image
├── requirements.txt             # Pinned dependencies
└── .env                         # Environment variables
```

---

## Architecture & Design Patterns

### Clean Architecture (Layered)

```
Request → Routes → Schemas (validate) → Services (logic) → Repositories (DB) → PostgreSQL
                                              ↕
                                        Cache Manager → Redis
```

Each layer only talks to the one directly below it. You can swap PostgreSQL for DynamoDB by changing only the repository layer.

### Payment Flow (Critical Path)

1. **Idempotency check** — Redis (0.2ms) → DB fallback (4ms)
2. **Validation** — Sender ≠ receiver, both wallets exist
3. **Lock wallets** — `SELECT FOR UPDATE` in sorted UUID order (deadlock-free)
4. **Balance check** — Against locked (fresh) data
5. **Atomic transfer** — Debit + credit + transaction record in single `COMMIT`
6. **Post-commit** — Invalidate cache, store idempotency key

### Key Design Decisions

| Decision | Why |
|----------|-----|
| `DECIMAL(18,2)` for money | Float arithmetic produces rounding errors (0.1 + 0.2 ≠ 0.3) |
| `CHECK (balance >= 0)` | Database-level safety net — rejects negative balances even if code has bugs |
| Sorted lock ordering | Prevents deadlocks when two users send to each other simultaneously |
| Version column (optimistic lock) | Catches concurrent modifications that slip past row-level locks |
| Two-tier idempotency | Redis for speed (99% of checks), DB UNIQUE for durability (survives Redis restart) |
| Cache invalidation (not update) | Safer for financial data — stale cache self-heals on next read |
| Graceful degradation | Every Redis call is try/except — system works without cache, just slower |

---

## Database Schema

### Users
- UUID primary key (no sequential ID leakage)
- Unique email with index
- Soft-delete via `is_active` flag (regulatory compliance)

### Wallets
- 1:1 with users (enforced by UNIQUE on `user_id`)
- `DECIMAL(18,2)` balance with `CHECK >= 0`
- `version` column for optimistic locking

### Transactions
- Immutable ledger (INSERT-only, never updated)
- References sender and receiver wallets
- `CHECK (sender ≠ receiver)` prevents self-transfers
- `UNIQUE` on `idempotency_key` prevents duplicates at DB level
- Composite indexes on `(wallet_id, created_at DESC)` for fast history queries

---

## Redis Key Schema

| Key Pattern | Value | TTL | Purpose |
|------------|-------|-----|---------|
| `wallet:balance:{uuid}` | Decimal string | 5 min | Fast balance lookups |
| `wallet:info:{uuid}` | JSON object | 10 min | Full wallet metadata |
| `idempotency:{key}` | JSON response | 24 hr | Duplicate payment prevention |
| `rate_limit:{uid}:{path}` | Counter | 1 min | Sliding-window rate limiting |

---

## Rate Limits

| Endpoint | Limit | Rationale |
|----------|-------|-----------|
| `POST /payments/send` | 20/min | Prevents rapid-fire transfers |
| `GET /wallets/me` | 200/min | Users refresh balance frequently |
| `POST /users/register` | 5/min | Prevents spam account creation |

---

## Error Response Format

All errors return a consistent JSON structure:

```json
{
  "error": "insufficient_funds",
  "detail": "Insufficient balance: available=50.00, required=100.00",
  "request_id": "7f3a4b2c-..."
}
```

The `request_id` is returned in every response (also as `X-Request-ID` header) for debugging and support correlation.

---

## Configuration

All settings are loaded from environment variables (see `.env`):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `SECRET_KEY` | `change-me-in-production` | JWT signing key |
| `DEBUG` | `false` | Enables verbose logging and SQL echo |
| `IDEMPOTENCY_KEY_TTL_HOURS` | `24` | How long idempotency keys are valid |

---

## Production Considerations

Things to add before deploying to production:

- **Alembic migrations** — Replace `init_db.py` with versioned schema migrations
- **HTTPS** — Terminate TLS at the load balancer or reverse proxy
- **Secret management** — Use AWS Secrets Manager / Vault instead of `.env`
- **Monitoring** — Add Prometheus metrics, Datadog APM, or similar
- **Database replicas** — Read replicas for transaction history queries
- **Background jobs** — Celery or similar for: stale idempotency key cleanup, failed transaction recovery, balance reconciliation
- **Audit logging** — Separate append-only audit table for compliance
- **Input sanitization** — Additional validation beyond Pydantic for edge cases
- **Load testing** — Verify concurrency behavior under realistic traffic with Locust or k6

---

## License

This project is built for educational and portfolio purposes.

# PlayToPay Payout Engine

PlayToPay is a merchant payout engine built for an assignment challenge. It models merchant balances, immutable ledger entries, idempotent payout creation, and asynchronous payout settlement with retries.

The project includes a Django REST API, Celery workers, PostgreSQL, Redis, and a React dashboard for viewing balances, payout history, ledger activity, and creating new payouts.

## Live Demo

- Frontend: https://frontend-indol-tau-62.vercel.app
- API through Vercel proxy: https://frontend-indol-tau-62.vercel.app/api/v1
- Demo merchant ID: `11111111-1111-4111-8111-111111111111`

Use the Vercel proxy URL for browser/API checks from the deployed frontend. The raw EC2 backend is HTTP-only, so direct calls from the HTTPS frontend would be blocked by mixed-content rules.

## Tech Stack

- Backend: Django 5, Django REST Framework
- Database: PostgreSQL
- Queue: Celery, Redis
- Frontend: React, Vite, Tailwind CSS
- Deployment: Vercel frontend, Docker Compose backend on AWS EC2

## Core Features

- Merchant-scoped API using `X-Merchant-Id`
- Immutable ledger entries for credits, payout holds, releases, and completion markers
- Cached merchant balance projection for fast reads and atomic balance updates
- Idempotent payout creation using `Idempotency-Key`
- Concurrency-safe balance holds using PostgreSQL row locks and conditional updates
- Payout state machine: `pending -> processing -> completed|failed`
- Celery worker for async settlement simulation and retry handling
- React dashboard for balance, ledger, payout history, and payout creation

## Architecture Notes

The balance system uses two layers:

- `LedgerEntry`: append-only audit history.
- `MerchantBalance`: cached projection used for reads and atomic payout holds.

When a payout is requested, the service:

1. Claims or replays an idempotency key scoped to the merchant.
2. Locks the merchant balance row.
3. Performs a database-side conditional update with `available_balance_paise >= amount_paise`.
4. Creates a `pending` payout and a negative `payout_hold` ledger entry.
5. Stores the exact response against the idempotency key for safe retries.

The worker later claims pending or retryable payouts with `SELECT ... FOR UPDATE SKIP LOCKED`, simulates settlement, and moves payouts to `completed` or `failed`.

See [EXPLAINER.md](./EXPLAINER.md) for the detailed concurrency, idempotency, and state-machine explanation.

## Database Schema

The Django app uses PostgreSQL with UUID primary keys and stores all money amounts in paise.

### `payouts_merchant`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Primary key |
| `name` | varchar(255) | Merchant display name |
| `email` | varchar(254) | Optional email |
| `created_at` | timestamp | Created automatically |

### `payouts_bankaccount`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Primary key |
| `merchant_id` | UUID | Foreign key to `payouts_merchant.id`, cascades on delete |
| `label` | varchar(255) | Account label |
| `account_number_masked` | varchar(32) | Masked account number only |
| `ifsc` | varchar(32) | Bank IFSC code |
| `is_active` | boolean | Defaults to `true` |
| `created_at` | timestamp | Created automatically |

### `payouts_merchantbalance`

| Column | Type | Notes |
| --- | --- | --- |
| `merchant_id` | UUID | Primary key and one-to-one foreign key to `payouts_merchant.id`, cascades on delete |
| `available_balance_paise` | bigint | Funds available for new payouts |
| `held_balance_paise` | bigint | Funds reserved for pending/processing payouts |
| `version` | bigint | Incremented during balance mutations |
| `updated_at` | timestamp | Updated automatically |

### `payouts_payout`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Primary key |
| `merchant_id` | UUID | Foreign key to `payouts_merchant.id`, cascades on delete |
| `bank_account_id` | UUID | Foreign key to `payouts_bankaccount.id`, protected from delete |
| `amount_paise` | bigint | Must be at least `1` |
| `status` | varchar(32) | `pending`, `processing`, `completed`, or `failed` |
| `attempt_count` | integer | Worker settlement attempts |
| `next_retry_at` | timestamp | Nullable retry schedule |
| `last_attempted_at` | timestamp | Nullable last worker attempt |
| `failure_code` | varchar(64) | Optional failure code |
| `failure_reason` | text | Optional failure details |
| `created_at` | timestamp | Created automatically |
| `updated_at` | timestamp | Updated automatically |

Indexes:

- `status`
- `next_retry_at`
- `created_at`
- Composite index on `merchant_id`, `status`, `created_at DESC`

### `payouts_ledgerentry`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Primary key |
| `merchant_id` | UUID | Foreign key to `payouts_merchant.id`, cascades on delete |
| `entry_type` | varchar(32) | `credit`, `payout_hold`, `payout_release`, or `payout_completed` |
| `amount_paise` | bigint | Signed ledger amount |
| `payout_id` | UUID | Nullable foreign key to `payouts_payout.id`, protected from delete |
| `reference` | varchar(255) | Optional external/internal reference |
| `metadata` | jsonb | Optional structured metadata |
| `created_at` | timestamp | Created automatically |

Indexes:

- `created_at`
- Composite index on `merchant_id`, `created_at DESC`

### `payouts_idempotencykey`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Primary key |
| `merchant_id` | UUID | Foreign key to `payouts_merchant.id`, cascades on delete |
| `key` | UUID | Client-provided idempotency key |
| `request_fingerprint` | varchar(64) | Hash of the original request payload |
| `request_method` | varchar(16) | Original HTTP method |
| `request_path` | varchar(255) | Original request path |
| `status_code` | integer | Stored response status, nullable while in progress |
| `response_body` | jsonb | Stored response body, nullable while in progress |
| `payout_id` | UUID | Nullable foreign key to `payouts_payout.id`, set null if payout is deleted |
| `is_in_progress` | boolean | Tracks an active first request |
| `created_at` | timestamp | Created automatically |
| `expires_at` | timestamp | Defaults to 24 hours after creation |

Constraints and indexes:

- Unique constraint on `merchant_id`, `key`
- Index on `expires_at`

## Repository Structure

```text
backend/
  config/                  Django and Celery configuration
  payouts/                 Payout domain models, services, tasks, API views, tests
frontend/
  src/                     React dashboard
bin/                       Deployment process entrypoints
docker-compose.yml         Local Postgres, Redis, API, worker, beat
docker-compose.prod.yml    Production backend stack
DEPLOYMENT.md              Deployment notes and verification commands
```

## Local Setup

### 1. Start Postgres and Redis

```bash
docker compose up -d db redis
```

### 2. Configure and run the backend

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python backend/manage.py migrate
python backend/manage.py seed_demo_data
python backend/manage.py runserver
```

The API will run at:

```text
http://localhost:8000/api/v1
```

### 3. Run Celery worker and beat

In separate terminals:

```bash
. .venv/bin/activate
cd backend
celery -A config worker --loglevel=info
```

```bash
. .venv/bin/activate
cd backend
celery -A config beat --loglevel=info
```

### 4. Configure and run the frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

The dashboard will run at:

```text
http://localhost:5173
```

### 5. Set a demo merchant ID

The seed command creates demo merchants. To print their IDs:

```bash
. .venv/bin/activate
python backend/manage.py shell -c "from payouts.models import Merchant; print(*Merchant.objects.values_list('name', 'id'), sep='\n')"
```

Use one UUID as:

- `X-Merchant-Id` for API requests
- `VITE_DEMO_MERCHANT_ID` in `frontend/.env`

If you want a stable local merchant ID, set `DEMO_MERCHANT_ID` in `.env` before running `seed_demo_data`.

## Run With Docker Compose

To run the backend stack locally with Docker:

```bash
docker compose up --build
```

This starts:

- PostgreSQL on `5432`
- Redis on `6379`
- Django API on `8000`
- Celery worker
- Celery beat

The frontend is still run separately with Vite for faster iteration.

## Environment Variables

Backend `.env`:

```text
DATABASE_URL=postgresql://playto:playto@localhost:5432/playto_pay
REDIS_URL=redis://localhost:6379/0
DJANGO_SECRET_KEY=playto-dev-secret-key
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
CORS_ALLOWED_ORIGINS=http://localhost:5173
RUN_DEMO_SEED_ON_DEPLOY=false
DEMO_MERCHANT_ID=
```

Frontend `frontend/.env`:

```text
VITE_API_BASE_URL=http://localhost:8000/api/v1
VITE_DEMO_MERCHANT_ID=<seeded merchant uuid>
```

## API Reference

All endpoints are under `/api/v1`.

All requests require:

```text
X-Merchant-Id: <merchant uuid>
```

Payout creation also requires:

```text
Idempotency-Key: <uuid>
```

### Endpoints

```text
GET  /merchant/balance
GET  /merchant/ledger?limit=20
GET  /merchant/bank-accounts
GET  /payouts
POST /payouts
```

### Create Payout

```bash
curl -sS -X POST http://localhost:8000/api/v1/payouts \
  -H "Content-Type: application/json" \
  -H "X-Merchant-Id: <merchant uuid>" \
  -H "Idempotency-Key: <uuid>" \
  -d '{
    "amount_paise": 10000,
    "bank_account_id": "<bank account uuid>"
  }'
```

Expected successful response:

```json
{
  "id": "payout-uuid",
  "status": "pending",
  "amount_paise": 10000,
  "bank_account_id": "bank-account-uuid",
  "created_at": "2026-04-29T00:00:00Z"
}
```

Replaying the same request with the same `Idempotency-Key` returns the original response without creating a duplicate payout. Reusing the same key with a different payload returns `422 idempotency_payload_mismatch`.

## Seed Data

Run:

```bash
python backend/manage.py seed_demo_data
```

This creates three demo merchants:

- `Nimbus Studio`
- `Cedar Freelance`
- `Atlas Growth`

Each merchant gets one bank account. `Atlas Growth` includes a retryable `processing` payout to demonstrate worker retry behavior.

## Tests

Backend tests:

```bash
. .venv/bin/activate
python backend/manage.py test payouts.tests
```

Frontend build check:

```bash
cd frontend
npm install
npm run build
```

Useful backend sanity check:

```bash
python backend/manage.py check
```

## Deployment

The deployed version uses:

- Vercel for the Vite frontend
- AWS EC2 with Docker Compose for Django, Celery, PostgreSQL, and Redis

Deployment files included in this repo:

- `Dockerfile`
- `docker-compose.prod.yml`
- `Procfile`
- `bin/start-web`
- `bin/start-worker`
- `bin/start-beat`
- `frontend/vercel.json`
- `Caddyfile`

See [DEPLOYMENT.md](./DEPLOYMENT.md) for the full deployment process, environment variables, and verification commands.

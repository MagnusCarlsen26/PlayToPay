# PlayToPay Explainer

## 1. The Ledger

Balance calculation query:

```sql
WITH ledger_totals AS (
    SELECT
        merchant_id,
        COALESCE(SUM(amount_paise), 0) AS computed_available
    FROM payouts_ledgerentry
    GROUP BY merchant_id
),
held_totals AS (
    SELECT
        merchant_id,
        COALESCE(SUM(amount_paise), 0) AS computed_held
    FROM payouts_payout
    WHERE status IN ('pending', 'processing')
    GROUP BY merchant_id
)
SELECT
    m.merchant_id,
    m.available_balance_paise AS cached_available,
    m.held_balance_paise AS cached_held,
    COALESCE(lt.computed_available, 0) AS computed_available,
    COALESCE(ht.computed_held, 0) AS computed_held
FROM payouts_merchantbalance m
LEFT JOIN ledger_totals lt
    ON lt.merchant_id = m.merchant_id
LEFT JOIN held_totals ht
    ON ht.merchant_id = m.merchant_id;
```

My thought process was:

1. Credits and debits could have been separate tables, but their schema would be almost identical, so that would add duplication without much benefit.
2. A single ledger table with an `entry_type` field gives one ordered transaction history per merchant.
3. The next choice was whether amounts should always be positive and interpreted by `entry_type`, or whether the amount itself should carry direction.
4. I chose signed amounts because the database can calculate available balance with a simple `SUM(amount_paise)`.
5. I still keep `entry_type` because humans and queries need semantic meaning: credit, payout hold, payout release, and payout completed.

So the ledger is append-only, signed, and typed. The signed amount is for arithmetic.

Credits are +ve. 
Payout holds are -ve, so available balance drops as soon as funds are reserved. 
Failed payout releases are +ve, which cancels the hold. 
Completed payouts use a zero-value marker because the money was already deducted when the hold was created.

Merchant balance is cached. An atomic transaction is done when an entry is addede in ledger and balance is updated.

## 2. The Lock

Code that prevents two concurrent payouts from overdrawing the same balance:

```python
with transaction.atomic():
    key_record = IdempotencyKey.objects.select_for_update().get(id=key_record.id)
    bank_account = _lock_bank_account(merchant=merchant, bank_account_id=bank_account_id)
    MerchantBalance.objects.select_for_update().get(merchant=merchant)
    updated_rows = (
        MerchantBalance.objects.filter(merchant=merchant, available_balance_paise__gte=amount_paise)
        .update(
            available_balance_paise=F("available_balance_paise") - amount_paise,
            held_balance_paise=F("held_balance_paise") + amount_paise,
            version=F("version") + 1,
        )
    )
    if updated_rows != 1:
        response = {"error": InsufficientFunds.message, "code": InsufficientFunds.error_code}
        _finalize_idempotency(key_record, status_code=InsufficientFunds.status_code, body=response)
        return ServiceResponse(status_code=InsufficientFunds.status_code, body=response)
```

Assuming the two concurrent requests have different idempotency keys.

Primitive: PostgreSQL `SELECT ... FOR UPDATE` inside `transaction.atomic()`.

When two concurrent payout requests arrive at the same time, exactly one of them gets the row-level lock for the merchant's `MerchantBalance`.

The other request waits until the first transaction commits or rolls back. When the second request gets the lock, it sees the updated balance from the first request.

Example with balance `10000` and two payout requests of `6000`:

```text
Request A                  PostgreSQL MerchantBalance row              Request B
---------                  ------------------------------              ---------
BEGIN
SELECT ... FOR UPDATE  ->  locks merchant balance row
                            available = 10000

                                                                      BEGIN
                                                                      SELECT ... FOR UPDATE
                                                                      waits for row lock

UPDATE balance
WHERE available >= 6000 ->  available = 4000
                            held = 6000
COMMIT                  ->  releases row lock

                                                                      lock acquired
                                                                      sees available = 4000
                                                                      UPDATE balance
                                                                      WHERE available >= 6000
                                                                      affects 0 rows
                                                                      returns insufficient funds
```

## 3. The Idempotency

The system stores every idempotency key in `IdempotencyKey`.

One merchant, the same key can only be inserted once.

```python
models.UniqueConstraint(fields=["merchant", "key"], name="uniq_merchant_idempotency_key")
```

On the first request, the system creates an `IdempotencyKey` row with the help of key, fingerpring of request and is_in_process=`True`

If the same key comes again, the insert hits the unique constraint. Then the system loads the existing row and knows it has seen the key before.

What happens next:

- Same key + same payload + first request already finished: return the stored `status_code` and `response_body`.
- Same key + different payload: reject it as `idempotency_payload_mismatch`.
- Same key + same payload while the first request is still running: return `409 idempotency_conflict` / "Request in progress."

So the second in-flight request does not create another payout. It sees the existing key row with `is_in_progress=True` and stops.

## 4. The State Machine

Failed-to-completed is blocked in `backend/payouts/services.py`.

Allowed transitions:

```python
VALID_TRANSITIONS = {
    Payout.Status.PENDING: {Payout.Status.PROCESSING},
    Payout.Status.PROCESSING: {Payout.Status.COMPLETED, Payout.Status.FAILED},
    Payout.Status.COMPLETED: set(),
    Payout.Status.FAILED: set(),
}
```

The check:

```python
def assert_transition(current_status: str, new_status: str) -> None:
    if new_status not in VALID_TRANSITIONS[current_status]:
        raise InvalidPayoutTransition(f"Cannot transition payout from {current_status} to {new_status}.")
```

`failed -> completed` is blocked because `VALID_TRANSITIONS[Payout.Status.FAILED]` is an empty set.

`complete_payout()` calls this before changing the status:

```python
def complete_payout(payout_id) -> Payout:
    with transaction.atomic():
        payout = Payout.objects.select_for_update().select_related("merchant", "bank_account").get(id=payout_id)
        assert_transition(payout.status, Payout.Status.COMPLETED)
        payout.status = Payout.Status.COMPLETED
```

## 5. The AI Audit

I did the high-level design myself: ledger model, balance projection, idempotency behavior, locking approach, and payout state machine.

Due to the time constraint, I was not able to deeply review every AI-generated line by line. I did do a high-level backend review and flagged weak areas.

Example 1:

```python
# TODO: Make sure this isn't vulnerable to SQL injecttion
RECONCILIATION_SQL = """
WITH ledger_totals AS (
```

Example 2:

```python
# TODO: This function is too long. Try to break this down into smaller functions.
def request_payout(
```

Example 3:

```python
# TODO: Probably this transaction.atomic() is not needed.
# because there is already transaction.atomic() inside _claim_idempotency_key()
with transaction.atomic():
```

Example 4:

```text
Too long names: available_balance_paise, held_balance_paise -> avail_bal, held_bal.
It is understood that the value is in paise. In future if we have multiple currencies, these names will be harder to change.
```

Example 5:

```python
# This should use timedelta(hours=<some constant from config>)
if not created:
    if key_record.request_fingerprint != fingerprint:
        raise IdempotencyPayloadMismatch
    if key_record.is_in_progress:
        raise IdempotencyConflict
    return ServiceResponse(status_code=key_record.status_code, body=key_record.response_body)
```

from django.db.models import QuerySet

from .models import BankAccount, LedgerEntry, Merchant, MerchantBalance, Payout

RECONCILIATION_SQL = """
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
""".strip()


def get_merchant_balance(merchant: Merchant) -> MerchantBalance:
    return MerchantBalance.objects.select_related("merchant").get(merchant=merchant)


def get_merchant_ledger(merchant: Merchant) -> QuerySet[LedgerEntry]:
    return LedgerEntry.objects.filter(merchant=merchant).order_by("-created_at")


def get_merchant_payouts(merchant: Merchant) -> QuerySet[Payout]:
    return Payout.objects.filter(merchant=merchant).select_related("bank_account").order_by("-created_at")


def get_merchant_bank_accounts(merchant: Merchant) -> QuerySet[BankAccount]:
    return BankAccount.objects.filter(merchant=merchant, is_active=True).order_by("created_at")

from payouts.models import BankAccount, LedgerEntry, Merchant, MerchantBalance


def create_merchant_with_balance(*, name: str = "Test Merchant", amount_paise: int = 10000):
    merchant = Merchant.objects.create(name=name, email="test@example.com")
    bank_account = BankAccount.objects.create(
        merchant=merchant,
        label="Primary",
        account_number_masked="xxxx1111",
        ifsc="HDFC0001111",
    )
    MerchantBalance.objects.create(merchant=merchant, available_balance_paise=amount_paise, held_balance_paise=0)
    LedgerEntry.objects.create(
        merchant=merchant,
        entry_type=LedgerEntry.EntryType.CREDIT,
        amount_paise=amount_paise,
        reference="seed-credit",
    )
    return merchant, bank_account

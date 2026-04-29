from rest_framework import serializers

from .models import BankAccount, LedgerEntry, MerchantBalance, Payout


class PayoutRequestSerializer(serializers.Serializer):
    amount_paise = serializers.IntegerField(min_value=1)
    bank_account_id = serializers.UUIDField()


class MerchantBalanceSerializer(serializers.ModelSerializer):
    merchant_id = serializers.UUIDField(source="merchant_id", read_only=True)
    total_balance_paise = serializers.SerializerMethodField()

    class Meta:
        model = MerchantBalance
        fields = ["merchant_id", "available_balance_paise", "held_balance_paise", "total_balance_paise"]

    def get_total_balance_paise(self, obj: MerchantBalance) -> int:
        return obj.available_balance_paise + obj.held_balance_paise


class LedgerEntrySerializer(serializers.ModelSerializer):
    payout_id = serializers.UUIDField(source="payout_id", read_only=True)

    class Meta:
        model = LedgerEntry
        fields = ["id", "entry_type", "amount_paise", "created_at", "payout_id", "reference", "metadata"]


class PayoutSerializer(serializers.ModelSerializer):
    bank_account_id = serializers.UUIDField(source="bank_account_id", read_only=True)

    class Meta:
        model = Payout
        fields = [
            "id",
            "amount_paise",
            "status",
            "attempt_count",
            "bank_account_id",
            "created_at",
            "updated_at",
            "failure_code",
            "failure_reason",
        ]


class BankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankAccount
        fields = ["id", "label", "account_number_masked", "ifsc", "is_active"]

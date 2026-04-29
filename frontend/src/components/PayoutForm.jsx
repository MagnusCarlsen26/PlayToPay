import { useEffect, useState } from "react";

import { createPayout, fetchBankAccounts } from "../api";

const LAST_KEY_STORAGE = "playto:last-idempotency-key";

export default function PayoutForm({ onPayoutCreated }) {
  const [bankAccounts, setBankAccounts] = useState([]);
  const [amountRupees, setAmountRupees] = useState("");
  const [bankAccountId, setBankAccountId] = useState("");
  const [status, setStatus] = useState({ kind: "idle", message: "" });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchBankAccounts().then((data) => {
      setBankAccounts(data.results);
      if (data.results[0]) {
        setBankAccountId(data.results[0].id);
      }
    });
  }, []);

  async function handleSubmit(event) {
    event.preventDefault();
    setLoading(true);
    setStatus({ kind: "idle", message: "" });

    const existingKey = window.localStorage.getItem(LAST_KEY_STORAGE);
    const idempotencyKey = existingKey || crypto.randomUUID();
    window.localStorage.setItem(LAST_KEY_STORAGE, idempotencyKey);

    try {
      const payload = {
        amount_paise: Math.round(Number(amountRupees || 0) * 100),
        bank_account_id: bankAccountId,
        idempotencyKey,
      };
      const payout = await createPayout(payload);
      window.localStorage.removeItem(LAST_KEY_STORAGE);
      setAmountRupees("");
      setStatus({ kind: "success", message: `Payout ${payout.id} created.` });
      onPayoutCreated?.();
    } catch (error) {
      setStatus({ kind: "error", message: error.message });
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur-sm">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="font-display text-2xl text-sand">Request payout</h2>
          <p className="text-sm text-steel">Payouts may remain processing briefly and auto-retry.</p>
        </div>
      </div>
      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <label className="text-sm text-steel">
          Amount in INR
          <input
            type="number"
            min="1"
            step="0.01"
            value={amountRupees}
            onChange={(event) => setAmountRupees(event.target.value)}
            className="mt-2 w-full rounded-2xl border border-white/10 bg-ink/70 px-4 py-3 text-sand outline-none"
            required
          />
        </label>
        <label className="text-sm text-steel">
          Bank account
          <select
            value={bankAccountId}
            onChange={(event) => setBankAccountId(event.target.value)}
            className="mt-2 w-full rounded-2xl border border-white/10 bg-ink/70 px-4 py-3 text-sand outline-none"
            required
          >
            {bankAccounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.label} • {account.account_number_masked}
              </option>
            ))}
          </select>
        </label>
      </div>
      <button
        type="submit"
        disabled={loading}
        className="mt-6 rounded-full bg-ember px-5 py-3 font-semibold text-white transition hover:brightness-110 disabled:opacity-60"
      >
        {loading ? "Submitting..." : "Request payout"}
      </button>
      {status.message ? (
        <div className={`mt-4 text-sm ${status.kind === "error" ? "text-red-300" : "text-emerald-300"}`}>
          {status.message}
        </div>
      ) : null}
    </form>
  );
}

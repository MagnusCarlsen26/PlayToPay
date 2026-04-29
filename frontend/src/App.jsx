import { useEffect, useState } from "react";

import { fetchBalance, fetchLedger, fetchPayouts } from "./api";
import BalanceCards from "./components/BalanceCards";
import LedgerTable from "./components/LedgerTable";
import PayoutForm from "./components/PayoutForm";
import PayoutHistoryTable from "./components/PayoutHistoryTable";

export default function App() {
  const [balance, setBalance] = useState(null);
  const [ledger, setLedger] = useState([]);
  const [payouts, setPayouts] = useState([]);

  async function refresh() {
    const [balanceData, ledgerData, payoutData] = await Promise.all([
      fetchBalance(),
      fetchLedger(),
      fetchPayouts(),
    ]);
    setBalance(balanceData);
    setLedger(ledgerData.results);
    setPayouts(payoutData.results);
  }

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <main className="min-h-screen px-5 py-10 text-white md:px-10">
      <div className="mx-auto max-w-7xl">
        <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.4em] text-ember">Playto Pay</div>
            <h1 className="mt-3 font-display text-5xl text-sand">Merchant payout engine</h1>
            <p className="mt-3 max-w-2xl text-base text-steel">
              Cross-border balances, payout holds, async settlement, and status retries in one challenge-focused dashboard.
            </p>
          </div>
        </div>
        <BalanceCards balance={balance} />
        <div className="mt-8 grid gap-8 lg:grid-cols-[1.1fr_0.9fr]">
          <div className="space-y-8">
            <LedgerTable entries={ledger} />
            <PayoutHistoryTable payouts={payouts} />
          </div>
          <PayoutForm onPayoutCreated={refresh} />
        </div>
      </div>
    </main>
  );
}

function formatMoney(paise) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format((paise || 0) / 100);
}

export default function BalanceCards({ balance }) {
  const cards = [
    { label: "Available", value: balance?.available_balance_paise, tone: "from-emerald-500/30" },
    { label: "Held", value: balance?.held_balance_paise, tone: "from-amber-500/30" },
    { label: "Total", value: balance?.total_balance_paise, tone: "from-sky-500/30" },
  ];

  return (
    <div className="grid gap-4 md:grid-cols-3">
      {cards.map((card) => (
        <div
          key={card.label}
          className={`rounded-3xl border border-white/10 bg-white/5 p-5 backdrop-blur-sm shadow-2xl shadow-black/20 bg-gradient-to-br ${card.tone} to-transparent`}
        >
          <div className="text-sm uppercase tracking-[0.25em] text-steel">{card.label}</div>
          <div className="mt-3 font-display text-3xl text-sand">{formatMoney(card.value)}</div>
        </div>
      ))}
    </div>
  );
}

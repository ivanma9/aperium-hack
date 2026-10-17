import { FactorPanel } from "@/components/FactorPanel";

export const metadata = { title: "CPI factors" };

export default function FactorsPage() {
  return (
    <div className="page fp-page">
      <main className="fp-main">
        <FactorPanel />
      </main>
    </div>
  );
}

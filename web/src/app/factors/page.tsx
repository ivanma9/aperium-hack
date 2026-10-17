import { FactorPanel } from "@/components/FactorPanel";

export const metadata = { title: "CPI factors" };

export default function FactorsPage() {
  return (
    <div className="page">
      <main className="wrap">
        <FactorPanel />
      </main>
    </div>
  );
}

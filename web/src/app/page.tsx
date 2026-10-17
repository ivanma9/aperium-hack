import { Suspense } from "react";
import { connection } from "next/server";
import { Dashboard } from "@/components/Dashboard";
import { getMockSnapshot } from "@/lib/feed/mock";

async function LiveDashboard() {
  // The snapshot is live data: read it at request time.
  await connection();
  // Swap for the REST reads (GET /v1/flow, /v1/vessels, /v1/cpi/energy) when the backend lands.
  const initial = await getMockSnapshot();
  return <Dashboard initial={initial} />;
}

/** Prerendered shell: the empty stage, so nothing shifts when the HUD streams in. */
function StageFallback() {
  return (
    <div className="page">
      <main className="wrap" aria-busy="true">
        <div className="stage" />
      </main>
    </div>
  );
}

export default function Home() {
  return (
    <Suspense fallback={<StageFallback />}>
      <LiveDashboard />
    </Suspense>
  );
}

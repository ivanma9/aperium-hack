import { Suspense } from "react";
import { connection } from "next/server";
import { Dashboard } from "@/components/Dashboard";
import { getMockSnapshot } from "@/lib/feed/mock";
import { fetchGeographies, type Geography } from "@/lib/geographies";

const APERIUM_API_URL = process.env.APERIUM_API_URL ?? "http://127.0.0.1:8000";

async function LiveDashboard() {
  // Geographies and the snapshot are live data: read them at request time.
  await connection();
  let geographies: Geography[];
  try {
    // Monitored geographies + port geofences live in Postgres, served by the collector.
    geographies = await fetchGeographies(APERIUM_API_URL);
  } catch (err) {
    return <BackendOffline reason={err instanceof Error ? err.message : String(err)} />;
  }
  // Flow/CPI are still simulated; swap for the real stream's REST reads when it exists.
  const initial = await getMockSnapshot(geographies);
  return <Dashboard geographies={geographies} initial={initial} />;
}

/** Without the collector there are no geographies to show, so say so plainly. */
function BackendOffline({ reason }: { reason: string }) {
  return (
    <div className="page">
      <main className="wrap">
        <div className="stage offline">
          <div className="glass offline-card" role="alert">
            <h1 className="wordmark">Tidemark</h1>
            <p>
              Can&apos;t load the monitored geographies from the Aperium collector at{" "}
              <span className="mono">{APERIUM_API_URL}</span>.
            </p>
            <p className="caption mono">{reason}</p>
            <p className="caption">
              Start everything with <span className="mono">./dev.sh</span> from the repo root (Postgres, collector and HUD),
              then reload.
            </p>
          </div>
        </div>
      </main>
    </div>
  );
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

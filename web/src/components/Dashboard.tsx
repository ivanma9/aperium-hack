"use client";

import type { Snapshot } from "@/lib/feed/types";
import type { Geography } from "@/lib/geographies";
import { MapStage } from "./MapStage";
import { Brand, HudToggle, LocationBar, MapAttribution, OutcomeCard } from "./Overlays";
import { TidemarkProvider, useTidemark } from "./TidemarkProvider";
import { ViewPanel, ViewTabs } from "./ViewPanels";

function Hud() {
  const hudVisible = useTidemark((s) => s.hudVisible);
  return (
    <div className={`page ${hudVisible ? "hud-on" : "hud-off"}`}>
      <main className="wrap">
        <div className="shell">
          <div className="stage">
            <MapStage />
            <HudToggle />
            {/* On narrow screens the toggle row moves to the top; keep the map credit at the bottom edge. */}
            <MapAttribution className="attribution-mobile" />
            <div className="ov ov-top">
              <Brand />
              {hudVisible && <LocationBar />}
            </div>
            {hudVisible && <OutcomeCard />}
          </div>
          {hudVisible && (
            <>
              <ViewTabs />
              <ViewPanel />
            </>
          )}
        </div>
      </main>
    </div>
  );
}

export function Dashboard({ geographies, initial }: { geographies: Geography[]; initial: Snapshot }) {
  return (
    <TidemarkProvider geographies={geographies} initial={initial}>
      <Hud />
    </TidemarkProvider>
  );
}

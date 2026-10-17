"use client";

import type { Snapshot } from "@/lib/feed/types";
import { MapStage } from "./MapStage";
import { Brand, HudToggle, LocationBar, OutcomeCard } from "./Overlays";
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

export function Dashboard({ initial }: { initial: Snapshot }) {
  return (
    <TidemarkProvider initial={initial}>
      <Hud />
    </TidemarkProvider>
  );
}

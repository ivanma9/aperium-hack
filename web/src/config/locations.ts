/**
 * Monitored locations. Rough estimates — verify base flow and bypass capacity
 * against EIA chokepoint data before relying on them.
 *
 * Every map coordinate uses the shared `0 -15 800 450` viewBox. `bbox` maps that
 * viewBox to lon/lat (equirectangular), so the stream can speak lat/lon while the
 * stylized map keeps working until a real imagery layer replaces it.
 */

export type Point = readonly [x: number, y: number];

export interface MapLabel {
  x: number;
  y: number;
  size: number;
  text: string;
  opacity: number;
}

export interface LocationConfig {
  id: string;
  /** API slug, used in REST paths. */
  slug: string;
  short: string;
  name: string;
  /** Baseline transit flow, mb/d. */
  baseMbd: number;
  /** Max flow the bypass (pipeline or reroute) can absorb, mb/d. */
  bypassCapMbd: number;
  bypassLabel: string;
  /** Scales the scenario risk premium for this location. */
  premiumMultiplier: number;
  /** [west, south, east, north] in degrees, mapped onto the viewBox. */
  bbox: readonly [number, number, number, number];
  imageryProvider: string;
  geometry: {
    land: readonly string[];
    lake?: string;
    lanes: { outbound: readonly Point[]; inbound: readonly Point[] };
    gates: string;
    labels: readonly MapLabel[];
  };
  destinations: { outbound: readonly string[]; inbound: readonly string[] };
}

export const VIEWBOX = { x: 0, y: -15, width: 800, height: 450 } as const;

const circle = (x: number, y: number, r: number) =>
  `M${x - r},${y}a${r},${r} 0 1,0 ${2 * r},0a${r},${r} 0 1,0 ${-2 * r},0 `;

const label = (x: number, y: number, size: number, text: string, opacity: number): MapLabel => ({
  x,
  y,
  size,
  text,
  opacity,
});

export const LOCATIONS: readonly LocationConfig[] = [
  {
    id: "hormuz",
    slug: "hormuz",
    short: "Hormuz",
    name: "Strait of Hormuz",
    baseMbd: 20,
    bypassCapMbd: 2.6,
    bypassLabel: "Pipeline bypass",
    premiumMultiplier: 1,
    bbox: [55.2, 25.4, 57.8, 27.2],
    imageryProvider: "SENTINEL-2 L2A",
    geometry: {
      land: [
        "M0,-15 L800,-15 L800,150 C740,160 690,150 640,130 C590,110 540,95 480,100 C420,105 380,120 330,125 C270,130 220,120 160,135 C110,148 60,160 0,170 Z",
        "M380,435 L420,300 C430,270 455,240 480,230 C500,225 510,250 515,280 C530,330 600,360 660,380 L800,400 L800,435 Z",
        "M0,435 L0,335 C80,322 160,332 240,352 C300,367 350,392 380,435 Z",
        "M224,165 C230,150 330,138 376,150 C382,160 300,172 224,165 Z " +
          circle(432, 132, 7) +
          circle(460, 150, 6) +
          circle(196, 192, 5) +
          circle(232, 200, 3.5) +
          circle(112, 300, 5),
      ],
      lanes: {
        outbound: [[0, 270], [160, 258], [310, 234], [430, 204], [530, 200], [650, 240], [800, 300]],
        inbound: [[800, 282], [650, 222], [530, 184], [430, 186], [310, 214], [160, 238], [0, 250]],
      },
      gates: "M400,60 L400,370 M600,60 L600,370",
      labels: [
        label(560, 55, 12, "IRAN", 0.6),
        label(450, 268, 10, "MUSANDAM", 0.6),
        label(40, 392, 11, "UAE", 0.6),
        label(34, 215, 10, "PERSIAN GULF", 0.4),
        label(650, 345, 10, "GULF OF OMAN", 0.4),
      ],
    },
    destinations: {
      outbound: ["Ningbo", "Jamnagar", "Chiba", "Ulsan", "Qingdao", "Rotterdam"],
      inbound: ["Ras Tanura", "Basrah", "Ruwais", "Mina al-Ahmadi", "Kharg"],
    },
  },
  {
    id: "malacca",
    slug: "malacca",
    short: "Malacca",
    name: "Strait of Malacca",
    baseMbd: 23.5,
    bypassCapMbd: 18,
    bypassLabel: "Lombok / Sunda reroute",
    premiumMultiplier: 0.5,
    bbox: [97.5, 0.8, 104.3, 6.2],
    imageryProvider: "SENTINEL-2 L2A",
    geometry: {
      land: [
        "M300,-15 L800,-15 L800,330 C760,340 720,330 690,345 C650,300 600,260 540,220 C470,170 400,110 340,40 C325,20 310,0 300,-15 Z",
        "M0,120 C80,160 160,200 250,250 C340,300 420,350 500,400 C520,415 540,430 545,435 L0,435 Z",
        "M693,356 C700,347 732,347 737,356 C732,364 700,364 693,356 Z",
        circle(660, 420, 8) + circle(705, 425, 6),
      ],
      lanes: {
        outbound: [[40, 20], [180, 110], [320, 190], [460, 255], [580, 310], [680, 375], [800, 385]],
        inbound: [[800, 400], [680, 392], [575, 327], [452, 272], [310, 207], [168, 127], [25, 37]],
      },
      gates: "M330,125 L270,245 M610,255 L550,375",
      labels: [
        label(520, 110, 12, "MALAY PENINSULA", 0.6),
        label(120, 340, 12, "SUMATRA", 0.6),
        label(20, 100, 10, "ANDAMAN SEA", 0.4),
        label(700, 335, 10, "SINGAPORE", 0.6),
      ],
    },
    destinations: {
      outbound: ["Ningbo", "Yokohama", "Ulsan", "Kaohsiung", "Qingdao", "Dalian"],
      inbound: ["Ras Tanura", "Fujairah", "Jamnagar", "Basrah", "Sikka"],
    },
  },
  {
    id: "bab-el-mandeb",
    slug: "bab-el-mandeb",
    short: "Bab el-Mandeb",
    name: "Bab el-Mandeb",
    baseMbd: 4.5,
    bypassCapMbd: 4,
    bypassLabel: "Cape of Good Hope reroute",
    premiumMultiplier: 0.5,
    bbox: [42.0, 11.3, 45.4, 14.2],
    imageryProvider: "SENTINEL-2 L2A",
    geometry: {
      land: [
        "M260,-15 L800,-15 L800,250 C740,255 680,240 620,250 C570,258 520,240 490,215 C450,180 400,120 340,60 C310,30 280,10 260,-15 Z",
        "M0,30 C60,80 130,140 200,200 C260,250 320,290 380,300 C420,307 450,330 470,370 C500,400 560,410 620,420 L800,425 L800,435 L0,435 Z",
        circle(468, 232, 6),
      ],
      lanes: {
        outbound: [[100, -5], [220, 90], [330, 180], [420, 250], [520, 290], [650, 315], [800, 320]],
        inbound: [[800, 340], [650, 333], [515, 308], [408, 268], [315, 196], [205, 106], [85, 10]],
      },
      gates: "M360,135 L300,235 M550,240 L490,340",
      labels: [
        label(620, 120, 12, "YEMEN", 0.6),
        label(40, 200, 11, "ERITREA", 0.6),
        label(60, 340, 11, "DJIBOUTI", 0.6),
        label(230, 150, 10, "RED SEA", 0.4),
        label(600, 385, 10, "GULF OF ADEN", 0.4),
      ],
    },
    destinations: {
      outbound: ["Singapore", "Jamnagar", "Fujairah", "Ningbo", "Mombasa"],
      inbound: ["Rotterdam", "Trieste", "Augusta", "Yanbu", "Ain Sukhna"],
    },
  },
  {
    id: "suez",
    slug: "suez",
    short: "Suez",
    name: "Suez Canal",
    baseMbd: 5,
    bypassCapMbd: 2.5,
    bypassLabel: "SUMED pipeline",
    premiumMultiplier: 0.4,
    bbox: [31.4, 29.8, 33.4, 31.4],
    imageryProvider: "SENTINEL-2 L2A",
    geometry: {
      land: [
        "M0,70 C120,60 260,80 380,72 L392,150 L384,230 L380,300 L395,380 C330,400 300,430 280,435 L0,435 Z",
        "M420,70 C540,85 680,60 800,75 L800,435 L520,435 C470,420 430,400 412,380 L420,300 L432,230 L414,150 Z",
      ],
      lake: "M396,215 C410,205 424,225 426,250 C428,275 414,290 402,285 C390,270 388,235 396,215 Z",
      lanes: {
        outbound: [[397, -10], [398, 72], [403, 150], [405, 230], [404, 300], [402, 380], [425, 440]],
        inbound: [[440, 440], [412, 380], [414, 300], [416, 230], [413, 150], [408, 72], [407, -10]],
      },
      gates: "M370,150 H440 M365,300 H450",
      labels: [
        label(40, 40, 11, "MEDITERRANEAN", 0.4),
        label(150, 260, 12, "EGYPT", 0.6),
        label(600, 260, 12, "SINAI", 0.6),
        label(300, 60, 10, "Port Said", 0.6),
        label(330, 412, 10, "Suez", 0.6),
      ],
    },
    destinations: {
      outbound: ["Jeddah", "Singapore", "Fujairah", "Jamnagar", "Ningbo"],
      inbound: ["Rotterdam", "Trieste", "Algeciras", "Augusta", "Constanța"],
    },
  },
];

export const DEFAULT_LOCATION_ID = "hormuz";

export function getLocation(id: string): LocationConfig {
  return LOCATIONS.find((l) => l.id === id) ?? LOCATIONS[0];
}

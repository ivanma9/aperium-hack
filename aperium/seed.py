"""Initial rows for the `geographies` and `ports` tables.

Inserted with ON CONFLICT DO NOTHING on startup, so rows edited in the database
are kept. The database, served at /api/geographies and /api/ports, is the source of
truth for the collector's geofences and for the HUD's monitored geographies.
Edit them in the database (or here, for a fresh database).

Coordinates: geography geometry is [lon, lat] (GeoJSON order). Port bounds keep the
API's established `bounds_lat_lon` = [[south, west], [north, east]] order.
Lanes and gates are hand-placed approximations of the main tanker routes (good to a
few km), not official traffic separation schemes. Flow and bypass figures are rough
estimates to verify against EIA chokepoint data.
"""

PORTS = [
    {"id": "fujairah", "name": "Fujairah", "geography_id": "hormuz", "bounds_lat_lon": [[25.05, 56.32], [25.28, 56.65]]},
    {"id": "shahid_rajaee", "name": "Shahid Rajaee", "geography_id": "hormuz", "bounds_lat_lon": [[26.95, 55.95], [27.18, 56.20]]},
    {"id": "khor_fakkan", "name": "Khor Fakkan", "geography_id": "hormuz", "bounds_lat_lon": [[25.30, 56.32], [25.45, 56.55]]},
    {"id": "jebel_ali", "name": "Jebel Ali", "geography_id": "hormuz", "bounds_lat_lon": [[24.90, 54.95], [25.12, 55.15]]},
]

_MALACCA = [[97.6, 5.95], [98.6, 4.85], [99.6, 3.85], [100.6, 2.95], [101.4, 2.45], [102.3, 1.92], [103.0, 1.5],
            [103.6, 1.2], [104.0, 1.22], [104.5, 1.35]]
_BAB = [[41.9, 15.2], [42.4, 14.3], [42.9, 13.45], [43.2, 12.95], [43.33, 12.6], [43.6, 12.3], [44.2, 12.05], [45.2, 12.0]]
_SUEZ = [[32.33, 31.45], [32.32, 31.27], [32.31, 30.85], [32.29, 30.58], [32.33, 30.42], [32.4, 30.32], [32.48, 30.2],
         [32.56, 29.95], [32.57, 29.8]]

GEOGRAPHIES = [
    {
        "id": "hormuz", "slug": "hormuz", "short_name": "Hormuz", "name": "Strait of Hormuz", "sort_order": 1,
        "base_mbd": 20, "bypass_cap_mbd": 2.6, "bypass_label": "Pipeline bypass", "premium_multiplier": 1,
        # Frames the strait and all four port geofences (Jebel Ali → Shahid Rajaee).
        "bbox": [54.85, 24.85, 57.2, 27.25],
        "imagery_provider": "SENTINEL-2 L2A",
        # Laden traffic leaves the Gulf on the southern lane; ballast comes in on the northern one.
        "lanes": {
            "outbound": [[54.4, 25.98], [55.4, 26.16], [56.0, 26.42], [56.35, 26.5], [56.58, 26.44], [56.85, 26.15], [57.6, 25.55]],
            "inbound": [[57.6, 25.72], [56.95, 26.25], [56.65, 26.58], [56.35, 26.64], [56.0, 26.54], [55.4, 26.36], [54.4, 26.14]],
        },
        "lane_offset_px": None,
        "gates": [[[56.12, 26.28], [56.12, 26.72]], [[56.78, 25.98], [56.78, 26.62]]],
        "destinations": {
            "outbound": ["Ningbo", "Jamnagar", "Chiba", "Ulsan", "Qingdao", "Rotterdam"],
            "inbound": ["Ras Tanura", "Basrah", "Ruwais", "Mina al-Ahmadi", "Kharg"],
        },
    },
    {
        "id": "malacca", "slug": "malacca", "short_name": "Malacca", "name": "Strait of Malacca", "sort_order": 2,
        "base_mbd": 23.5, "bypass_cap_mbd": 18, "bypass_label": "Lombok / Sunda reroute", "premium_multiplier": 0.5,
        "bbox": [97.5, 0.8, 104.6, 6.1], "imagery_provider": "SENTINEL-2 L2A",
        "lanes": {"outbound": _MALACCA, "inbound": _MALACCA[::-1]}, "lane_offset_px": 4,
        "gates": [[[100.35, 2.65], [100.85, 3.25]], [[102.1, 1.7], [102.5, 2.15]]],
        "destinations": {
            "outbound": ["Ningbo", "Yokohama", "Ulsan", "Kaohsiung", "Qingdao", "Dalian"],
            "inbound": ["Ras Tanura", "Fujairah", "Jamnagar", "Basrah", "Sikka"],
        },
    },
    {
        "id": "bab-el-mandeb", "slug": "bab-el-mandeb", "short_name": "Bab el-Mandeb", "name": "Bab el-Mandeb", "sort_order": 3,
        "base_mbd": 4.5, "bypass_cap_mbd": 4, "bypass_label": "Cape of Good Hope reroute", "premium_multiplier": 0.5,
        "bbox": [41.8, 11.6, 45.3, 15.3], "imagery_provider": "SENTINEL-2 L2A",
        "lanes": {"outbound": _BAB, "inbound": _BAB[::-1]}, "lane_offset_px": 4,
        "gates": [[[42.85, 13.25], [43.25, 13.5]], [[43.5, 12.1], [43.75, 12.5]]],
        "destinations": {
            "outbound": ["Singapore", "Jamnagar", "Fujairah", "Ningbo", "Mombasa"],
            "inbound": ["Rotterdam", "Trieste", "Augusta", "Yanbu", "Ain Sukhna"],
        },
    },
    {
        "id": "suez", "slug": "suez", "short_name": "Suez", "name": "Suez Canal", "sort_order": 4,
        "base_mbd": 5, "bypass_cap_mbd": 2.5, "bypass_label": "SUMED pipeline", "premium_multiplier": 0.4,
        "bbox": [31.9, 29.75, 32.9, 31.5], "imagery_provider": "SENTINEL-2 L2A",
        "lanes": {"outbound": _SUEZ, "inbound": _SUEZ[::-1]}, "lane_offset_px": 3,
        "gates": [[[32.22, 30.85], [32.4, 30.85]], [[32.47, 30.05], [32.65, 30.05]]],
        "destinations": {
            "outbound": ["Jeddah", "Singapore", "Fujairah", "Jamnagar", "Ningbo"],
            "inbound": ["Rotterdam", "Trieste", "Algeciras", "Augusta", "Constanța"],
        },
    },
]

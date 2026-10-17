import unittest

from aperium.tracking import Store, normalize


def message(**overrides):
    report = dict(UserID=123456789, Latitude=25.16, Longitude=56.4,
                  Sog=0.5, Cog=30, Valid=True, NavigationalStatus=1)
    report.update(overrides)
    return {"MessageType": "PositionReport", "MetaData": {"ShipName": "TEST"},
            "Message": {"PositionReport": report}}


class TrackingTests(unittest.TestCase):
    def test_invalid_and_unavailable_values(self):
        for change in ({"Latitude": 91}, {"Longitude": 181}, {"Latitude": float('nan')},
                       {"Valid": False}, {"UserID": 0}):
            self.assertIsNone(normalize(message(**change), 100))
        result = normalize(message(Sog=102.3, Cog=360), 100)
        self.assertIsNone(result["speed_knots"])
        self.assertIsNone(result["course"])

    def test_go_timestamp(self):
        data = message()
        data["MetaData"]["time_utc"] = "2026-01-01 00:00:00.123456789 +0000 UTC"
        result = normalize(data, 1767225610)
        self.assertAlmostEqual(result["observed_at"], 1767225600.123456)
        self.assertEqual(result["time_source"], "provider")

    def test_class_b_and_metadata_fallback(self):
        for kind in ("StandardClassBPositionReport", "ExtendedClassBPositionReport"):
            data = {"MessageType": kind, "MetaData": {"MMSI": 123456789, "latitude": 25.16, "longitude": 56.4},
                    "Message": {kind: {"Sog": 2}}}
            self.assertEqual(normalize(data, 100)["latitude"], 25.16)

    def test_deduplication_out_of_order_staleness_and_restart(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'test.sqlite3')
            store = Store(path)
            newer = normalize(message(), 200)
            store.save(newer)
            store.save(newer)
            store.save(normalize(message(Latitude=25.2), 100))
            self.assertEqual(len(store.history('123456789', 100)), 2)
            self.assertEqual(store.vessels(250, 60)[0]['latitude'], 25.16)
            self.assertFalse(store.vessels(250, 60)[0]['stale'])
            self.assertTrue(store.vessels(261, 60)[0]['stale'])
            store.close()
            store = Store(path)
            self.assertEqual(len(store.vessels(250, 60)), 1)
            store.save(normalize(message(Latitude=26), 300))
            self.assertFalse(store.vessels(310, 60)[0]['inside_geofence'])
            store.close()


if __name__ == '__main__':
    unittest.main()

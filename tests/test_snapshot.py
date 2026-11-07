import json
import tempfile
import unittest
from pathlib import Path

from taos.data.snapshot import SnapshotStore


class SnapshotStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_v2_all_false_is_kept(self):
        path = self.tmp / "v2.json"
        games = {str(1000 + i): {"A": False, "B": False} for i in range(6)}
        path.write_text(
            json.dumps({"_meta": {"version": 2}, **games}), encoding="utf-8"
        )

        store = SnapshotStore(path)

        self.assertEqual(len(store), 6)

    def test_v1_all_false_is_rebuilt(self):
        path = self.tmp / "v1.json"
        games = {str(2000 + i): {"A": False, "B": False} for i in range(6)}
        path.write_text(json.dumps(games), encoding="utf-8")

        store = SnapshotStore(path)

        self.assertEqual(len(store), 0)
        self.assertTrue(any(p.name.startswith("v1.broken-") for p in self.tmp.iterdir()))

    def test_existing_state_is_not_overwritten(self):
        path = self.tmp / "snap.json"
        path.write_text(
            json.dumps({"_meta": {"version": 2}, "10": {"A": True}}),
            encoding="utf-8",
        )

        store = SnapshotStore(path, "123")
        store.record_if_new(10, {"A": False}, authoritative=True)

        self.assertTrue(store.get(10)["A"])

    def test_missing_state_is_recorded(self):
        path = self.tmp / "snap.json"

        store = SnapshotStore(path, "123")
        store.record_if_new(10, {"A": True, "B": False}, authoritative=True)

        reloaded = SnapshotStore(path, "123")
        self.assertEqual(reloaded.get(10), {"A": True, "B": False})

    def test_other_account_is_ignored(self):
        path = self.tmp / "snap.json"
        path.write_text(
            json.dumps({"_meta": {"version": 2, "steam_id64": "111"}, "10": {"A": True}}),
            encoding="utf-8",
        )

        store = SnapshotStore(path, "222")
        store.record_if_new(11, {"A": True}, authoritative=True)

        self.assertTrue(store.account_mismatch)
        self.assertEqual(store.get(11), {})


if __name__ == "__main__":
    unittest.main()

import unittest
import uuid
from pathlib import Path

from measurement_ledger import MeasurementLedger


class LedgerTests(unittest.TestCase):
    def test_create_persists_and_update_edits_identity_only(self):
        path = Path(__file__).with_name(f".test-records-{uuid.uuid4().hex}.json")
        try:
            ledger = MeasurementLedger(path)
            record = ledger.create("Jessie", "A01", "first", {"foot_length_mm": 243.26}, 10, "capture.json")
            loaded = MeasurementLedger(path)
            self.assertEqual(loaded.records[0]["foot_length_mm"], 243.3)
            updated = loaded.update_identity(record["id"], "J. Lin", "A02", "rechecked")
            self.assertEqual(updated["subject_name"], "J. Lin")
            self.assertEqual(updated["foot_length_mm"], 243.3)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

"""Keep the blind gold selection separate from development checkpoints."""
import csv
import unittest

from schema import ROOT, load_apps
from pipeline.common import SAMPLE_NAMES


ORIGINAL_CHECKPOINT_NAMES = {"DealCloud", "Meta Ads", "Sherlock", "Notion", "Stripe"}


class GoldTemplateTests(unittest.TestCase):
    def test_gold_selection_excludes_both_development_checkpoints(self):
        with (ROOT / "gold" / "gold_template.csv").open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        names = {row["name"] for row in rows}
        self.assertEqual(len(rows), 25)
        self.assertEqual(len(names), 25)
        self.assertFalse(names & SAMPLE_NAMES, f"Gold/dev10 overlap: {names & SAMPLE_NAMES}")
        self.assertFalse(names & ORIGINAL_CHECKPOINT_NAMES,
                         f"Gold/original checkpoint overlap: {names & ORIGINAL_CHECKPOINT_NAMES}")
        catalog = {app.name: app for app in load_apps()}
        for row in rows:
            with self.subTest(app=row["name"]):
                app = catalog[row["name"]]
                self.assertEqual(row["id"], str(app.id))
                self.assertEqual(row["category"], app.category.value)
                self.assertTrue(all(not value for key, value in row.items()
                                    if key not in {"id", "name", "category"}))


if __name__ == "__main__":
    unittest.main()

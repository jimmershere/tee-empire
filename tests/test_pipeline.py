"""End-to-end dry-run tests for the empire pipeline."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from empire.core import brands as brands_mod
from empire.core import fixtures
from empire.core.orchestrator import Orchestrator
from empire.core.store import Store
from empire.core.concepts import generate_concept


class IsolatedDBTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        self.store = Store(self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()


class TestBrandsLoad(IsolatedDBTest):
    def test_brands_present(self) -> None:
        slugs = brands_mod.list_brand_slugs()
        self.assertIn("earl_biggers", slugs)
        self.assertIn("nickle_ts", slugs)
        eb = brands_mod.load_brand("earl_biggers")
        self.assertEqual(eb.slug, "earl_biggers")
        self.assertGreater(len(eb.lanes), 0)
        self.assertGreater(len(eb.palette), 0)


class TestConceptGen(IsolatedDBTest):
    def test_force_multipliers_preserves_handle(self) -> None:
        """force_multipliers seeds carry their own punctuation (×, *, Σ) — pass through verbatim."""
        brand = brands_mod.load_brand("earl_biggers")
        c = generate_concept(brand, "10×*", "force_multipliers", use_api=False)
        self.assertEqual(c.brand, "earl_biggers")
        self.assertEqual(c.lane, "force_multipliers")
        self.assertEqual(c.product_title, "10×*")  # verbatim
        self.assertIn("monospace", c.design_prompt.lower())  # coder/terminal voicing

    def test_biggers_brand_prefix(self) -> None:
        """biggers (merged grown-ups lane) titles are brand-prefixed."""
        brand = brands_mod.load_brand("earl_biggers")
        c = generate_concept(brand, "Running on Spite", "biggers", use_api=False)
        self.assertEqual(c.lane, "biggers")
        self.assertTrue(c.product_title.startswith("Earl Biggers:"))
        self.assertIn("cartoon", c.design_prompt.lower())


class TestPromptCraft(IsolatedDBTest):
    """Anti-hallucination prompt-craft skill (from exec_dashbd)."""

    def test_avoid_clause_per_subject(self) -> None:
        from empire.core import prompt_craft
        cm = prompt_craft.avoid_clause("cartoon_mascot")
        self.assertIn("Avoid:", cm)
        self.assertIn("extra limbs", cm)
        self.assertIn("watermark", cm)  # universal

        ty = prompt_craft.avoid_clause("typography_only")
        self.assertIn("no people", ty)
        self.assertIn("garbled text", ty)

    def test_enhance_appends_avoid_to_biggers_prompts(self) -> None:
        brand = brands_mod.load_brand("earl_biggers")
        c = generate_concept(brand, "Do It Tired", "biggers", use_api=False)
        self.assertIn("Avoid:", c.design_prompt)
        self.assertIn("extra limbs", c.design_prompt)

    def test_enhance_uses_typography_vocab_for_force_multipliers(self) -> None:
        brand = brands_mod.load_brand("earl_biggers")
        c = generate_concept(brand, "10×*", "force_multipliers", use_api=False)
        self.assertIn("Avoid:", c.design_prompt)
        self.assertIn("garbled text", c.design_prompt)
        # No anatomy vocab in typography-only mode
        self.assertNotIn("extra limbs", c.design_prompt)

    def test_enhance_idempotent(self) -> None:
        from empire.core import prompt_craft
        raw = "test prompt"
        once = prompt_craft.enhance_design_prompt(raw, subject="cartoon_mascot")
        twice = prompt_craft.enhance_design_prompt(once, subject="cartoon_mascot")
        self.assertEqual(once, twice)  # second pass detects existing Avoid clause and no-ops

    def test_nickle_ts_concept(self) -> None:
        brand = brands_mod.load_brand("nickle_ts")
        c = generate_concept(brand, "Coffee Milk Loyalty", "ri_pride", use_api=False)
        self.assertEqual(c.brand, "nickle_ts")
        self.assertIn("rhode island", " ".join(c.tags).lower())
        self.assertIn("rhode island", c.design_prompt.lower())


class TestImportFixtures(IsolatedDBTest):
    def test_import_legacy_concepts_and_designs(self) -> None:
        legacy = Path("/app/cc/sources/earl-biggers")
        if not legacy.exists():
            self.skipTest("legacy earl-biggers sources not present")
        c, d = fixtures.import_earl_biggers_from_path(legacy, self.store)
        self.assertGreaterEqual(c, 40)  # we have 45 concepts + 15 design-derived
        self.assertGreaterEqual(d, 15)
        loaded = self.store.list_concepts(brand="earl_biggers")
        self.assertGreaterEqual(len(loaded), 40)


class TestFullDryRun(IsolatedDBTest):
    def test_full_run_earl_biggers(self) -> None:
        brand = brands_mod.load_brand("earl_biggers")
        orch = Orchestrator(store=self.store, dry_run=True)
        report = orch.full_run(brand, lanes=["force_multipliers"], per_lane=2,
                               send_etsy=True, send_printify=True, send_reviews=False)
        self.assertEqual(report.brand, "earl_biggers")
        self.assertEqual(len(report.planned), 2)
        self.assertEqual(len(report.designed), 2)
        self.assertEqual(len(report.listed_printify), 2)
        self.assertEqual(len(report.listed_etsy), 2)

    def test_full_run_nickle_ts(self) -> None:
        brand = brands_mod.load_brand("nickle_ts")
        orch = Orchestrator(store=self.store, dry_run=True)
        report = orch.full_run(brand, lanes=["ri_pride", "comfort_classics"], per_lane=2,
                               send_etsy=True, send_printify=True, send_reviews=False)
        self.assertEqual(report.brand, "nickle_ts")
        self.assertEqual(len(report.planned), 4)
        self.assertEqual(len(report.designed), 4)


class TestStorePersistence(IsolatedDBTest):
    def test_concept_idempotent(self) -> None:
        brand = brands_mod.load_brand("earl_biggers")
        c1 = generate_concept(brand, "Bigger Mood", "biggers", use_api=False)
        self.store.upsert_concept(c1)
        self.store.upsert_concept(c1)
        rows = self.store.list_concepts(brand="earl_biggers")
        self.assertEqual(len(rows), 1)

    def test_listing_upsert_unique_by_external_id(self) -> None:
        brand = brands_mod.load_brand("earl_biggers")
        orch = Orchestrator(store=self.store, dry_run=True)
        orch.plan(brand, lanes=["biggers"], per_lane=1)
        orch.design(brand)
        first = orch.list_to_printify(brand)
        again = orch.list_to_printify(brand)
        ids_first = sorted(l.external_id for l in first)
        ids_again = sorted(l.external_id for l in again)
        self.assertEqual(ids_first, ids_again)


if __name__ == "__main__":
    unittest.main()

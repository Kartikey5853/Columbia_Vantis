import asyncio
import os
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from persistence.models import NormalizedProduct, NormalizedVariant
from persistence.supabase_client import get_supabase_client, SupabaseClient
from persistence.run_store import (
    get_or_create_daily_run,
    update_run_stage,
    update_run_counts,
    complete_run,
    fail_run,
    save_run_report,
    get_daily_run_report,
    get_all_daily_reports,
    get_business_date,
    get_scraper_id,
)
from persistence.checkpoint_store import (
    get_completed_listing_pages,
    record_listing_page_started,
    record_listing_page_completed,
    record_listing_page_failed,
    init_product_progress,
    get_incomplete_products,
    mark_product_in_progress,
    mark_product_completed,
    mark_product_failed,
)
from persistence.product_store import (
    upsert_canonical_product,
    record_price_if_changed,
    get_canonical_product_by_id,
    get_all_canonical_products,
)
from persistence.diagnostics import get_database_storage_stats, format_storage_report


class MockSupabaseClient(SupabaseClient):
    """
    In-memory mock for Supabase PostgREST database.
    Used for hermetic testing of constraints, price-history deduplication,
    crash-recovery, and page checkpoints without external state mutation.
    """

    def __init__(self):
        self.tables = {
            "scrapers": [
                {"id": "00000000-0000-0000-0000-000000000001", "name": "tata", "source": "tatacliq", "enabled": True},
                {"id": "00000000-0000-0000-0000-000000000002", "name": "columbia", "source": "columbia_sportswear_india", "enabled": True},
            ],
            "products": [],
            "price_history": [],
            "scrape_runs": [],
            "scrape_listing_pages": [],
            "scrape_product_progress": [],
        }

    async def select(self, table: str, columns: str = "*", filters=None, order=None, limit=None, single=False):
        rows = list(self.tables.get(table, []))
        if filters:
            for k, fval in filters.items():
                if fval.startswith("eq."):
                    val = fval[3:]
                    rows = [r for r in rows if str(r.get(k)) == str(val)]
                elif fval.startswith("neq."):
                    val = fval[4:]
                    rows = [r for r in rows if str(r.get(k)) != str(val)]
                elif fval.startswith("gt."):
                    val = fval[3:]
                    rows = [r for r in rows if str(r.get(k)) > str(val)]

        if order:
            parts = order.split(".")
            col = parts[0]
            desc = len(parts) > 1 and parts[1].lower() == "desc"
            rows.sort(key=lambda r: str(r.get(col, "")), reverse=desc)

        if limit is not None:
            rows = rows[: int(limit)]

        if single:
            return rows[0] if rows else None
        return rows

    async def insert(self, table: str, data, return_representation=True):
        items = data if isinstance(data, list) else [data]
        inserted = []
        for it in items:
            row = dict(it)
            if "id" not in row:
                row["id"] = str(uuid.uuid4())
            self.tables[table].append(row)
            inserted.append(row)
        return inserted if return_representation else []

    async def upsert(self, table: str, data, on_conflict=None, return_representation=True):
        items = data if isinstance(data, list) else [data]
        results = []
        for it in items:
            row = dict(it)
            conflict_keys = [k.strip() for k in on_conflict.split(",")] if on_conflict else ["id"]
            
            # Check match
            existing_idx = None
            for idx, existing in enumerate(self.tables[table]):
                if all(str(existing.get(k)) == str(row.get(k)) for k in conflict_keys):
                    existing_idx = idx
                    break

            if existing_idx is not None:
                # Merge / update
                merged = dict(self.tables[table][existing_idx])
                merged.update(row)
                self.tables[table][existing_idx] = merged
                results.append(merged)
            else:
                if "id" not in row:
                    row["id"] = str(uuid.uuid4())
                self.tables[table].append(row)
                results.append(row)

        return results if return_representation else []

    async def update(self, table: str, data, filters, return_representation=False):
        matched = []
        for row in self.tables[table]:
            match = True
            for k, fval in filters.items():
                if fval.startswith("eq."):
                    if str(row.get(k)) != str(fval[3:]):
                        match = False
                        break
            if match:
                row.update(data)
                matched.append(row)
        return matched if return_representation else []

    async def delete(self, table: str, filters):
        kept = []
        for row in self.tables.get(table, []):
            match = True
            for k, fval in filters.items():
                if fval.startswith("eq."):
                    if str(row.get(k)) != str(fval[3:]):
                        match = False
                        break
            if not match:
                kept.append(row)
        self.tables[table] = kept
        return True

    async def rpc(self, func_name: str, params=None):
        if func_name == "get_database_size_stats":
            stats = []
            for t in ["products", "price_history", "scrape_runs", "scrape_listing_pages", "scrape_product_progress", "scrapers"]:
                cnt = len(self.tables.get(t, []))
                sz = cnt * 400 + 8192
                stats.append({
                    "table_name": t,
                    "row_count": cnt,
                    "total_size_bytes": sz,
                    "total_size_pretty": f"{sz / 1024:.1f} kB"
                })
            stats.append({
                "table_name": "__total_database__",
                "row_count": 0,
                "total_size_bytes": 1048576,
                "total_size_pretty": "1.0 MB"
            })
            return stats
        return None


class ScraperPersistenceTestSuite(unittest.IsolatedAsyncioTestCase):
    """
    Comprehensive 10-point test suite matching all specification criteria.
    """

    async def asyncSetUp(self):
        # Default to MockSupabaseClient for unit testing to enable crash injection & deterministic simulation
        self.client = MockSupabaseClient()

    # ---------------------------------------------------------------------
    # TEST 1 — Product exists
    # ---------------------------------------------------------------------
    async def test_01_product_exists(self):
        """Verifies product normalization, persistence in Supabase, and attribute preservation."""
        for source in ["tata", "columbia"]:
            norm = NormalizedProduct(
                source=source,
                source_product_id=f"test_prod_{source}_101",
                title=f"{source.title()} Trail Jacket",
                sku=f"SKU_{source.upper()}_101",
                price=3499.00,
                mrp=4999.00,
                available=True,
                image_url=f"https://img.example.com/{source}/101.jpg",
                url=f"https://example.com/{source}/101",
                variants=[NormalizedVariant(size="L", sku=f"SKU_{source.upper()}_101_L", price=3499.00)]
            )
            persisted = await upsert_canonical_product(norm, client=self.client)
            self.assertIsNotNone(persisted.get("id"))
            self.assertEqual(persisted["source_product_id"], norm.source_product_id)
            self.assertEqual(persisted["title"], norm.title)
            self.assertEqual(float(persisted["current_price"]), 3499.00)
            self.assertEqual(float(persisted["current_mrp"]), 4999.00)

            # Query back
            fetched = await get_canonical_product_by_id(persisted["id"], client=self.client)
            self.assertEqual(fetched["source_product_id"], norm.source_product_id)

    # ---------------------------------------------------------------------
    # TEST 2 — Product count
    # ---------------------------------------------------------------------
    async def test_02_product_count(self):
        """Verifies scraped product IDs match persisted IDs exactly."""
        scraped_ids = [f"tata_item_{i}" for i in range(10)]
        for sid in scraped_ids:
            p = NormalizedProduct(
                source="tata",
                source_product_id=sid,
                title=f"Tata Item {sid}",
                price=1999.0,
            )
            await upsert_canonical_product(p, client=self.client)

        db_products = await get_all_canonical_products("tata", client=self.client)
        persisted_ids = {p["source_product_id"] for p in db_products}
        self.assertEqual(set(scraped_ids), persisted_ids)
        self.assertEqual(len(db_products), 10)

    # ---------------------------------------------------------------------
    # TEST 3 — Duplicate protection
    # ---------------------------------------------------------------------
    async def test_03_duplicate_protection(self):
        """Verifies running the same scrape twice does not double rows; maintains uniqueness on (scraper_id, source_product_id)."""
        product = NormalizedProduct(
            source="tata",
            source_product_id="duplicate_test_1",
            title="Tata Unique Shell",
            price=2499.0,
            mrp=2999.0
        )
        # Ingestion 1
        await upsert_canonical_product(product, client=self.client)
        count_1 = len(await get_all_canonical_products("tata", client=self.client))

        # Ingestion 2 (Duplicate scrape)
        await upsert_canonical_product(product, client=self.client)
        count_2 = len(await get_all_canonical_products("tata", client=self.client))

        self.assertEqual(count_1, count_2, "Product row count must not increase on duplicate scrape")

    # ---------------------------------------------------------------------
    # TEST 4 — Price history deduplication
    # ---------------------------------------------------------------------
    async def test_04_price_history(self):
        """
        Verifies:
        ₹2499 -> same ₹2499 (no entry) -> ₹1999 (1 entry)
        Expected history: [2499, 1999], NOT [2499, 2499, 1999].
        """
        prod = await upsert_canonical_product(
            NormalizedProduct(source="columbia", source_product_id="price_test_prod", title="Columbia Fleece", price=2499.0, mrp=2499.0),
            client=self.client
        )
        pid = prod["id"]

        # Run 1: initial price ₹2499
        recorded_1 = await record_price_if_changed(pid, 2499.0, 2499.0, scrape_run_id="run_1", client=self.client)
        self.assertTrue(recorded_1, "Initial price must be recorded")

        # Run 2: same price ₹2499
        recorded_2 = await record_price_if_changed(pid, 2499.0, 2499.0, scrape_run_id="run_2", client=self.client)
        self.assertFalse(recorded_2, "Unchanged price must NOT create a duplicate entry")

        # Run 3: price drop to ₹1999
        recorded_3 = await record_price_if_changed(pid, 1999.0, 2499.0, scrape_run_id="run_3", client=self.client)
        self.assertTrue(recorded_3, "Price change must be recorded")

        history = await self.client.select("price_history", filters={"product_id": f"eq.{pid}"}, order="recorded_at.asc")
        self.assertEqual(len(history), 2, "Must contain exactly 2 price records")
        self.assertEqual(float(history[0]["price"]), 2499.0)
        self.assertEqual(float(history[1]["price"]), 1999.0)

    # ---------------------------------------------------------------------
    # TEST 5 — Resume after crash
    # ---------------------------------------------------------------------
    async def test_05_resume_after_crash(self):
        """Simulates scraper termination after 5 products, then resumes to completion without duplicates."""
        run = await get_or_create_daily_run("tata", client=self.client)
        run_id = run["id"]

        # Ingest 10 products
        products = []
        for i in range(10):
            p = await upsert_canonical_product(
                NormalizedProduct(source="tata", source_product_id=f"crash_item_{i}", title=f"Item {i}", price=1000.0 + i),
                client=self.client
            )
            await init_product_progress(run_id, p["id"], f"crash_item_{i}", client=self.client)
            products.append(p)

        # Complete only first 5
        for i in range(5):
            await mark_product_completed(run_id, products[i]["id"], variant_count=1, client=self.client)

        # Scraper crashes here.
        # Now restart and resume:
        incomplete = await get_incomplete_products(run_id, client=self.client)
        self.assertEqual(len(incomplete), 5, "Exactly 5 products must be pending completion")

        # Resume processing remaining 5
        for it in incomplete:
            await mark_product_completed(run_id, it["product_id"], variant_count=1, client=self.client)

        remaining = await get_incomplete_products(run_id, client=self.client)
        self.assertEqual(len(remaining), 0, "All products must be completed after resume")

        # Verify no duplicate products
        all_tata = await get_all_canonical_products("tata", client=self.client)
        self.assertEqual(len(all_tata), 10)

    # ---------------------------------------------------------------------
    # TEST 6 — Failed product retry
    # ---------------------------------------------------------------------
    async def test_06_failed_product(self):
        """Forces product failure, verifies failed status, restarts, and completes on retry."""
        run = await get_or_create_daily_run("columbia", client=self.client)
        run_id = run["id"]

        p = await upsert_canonical_product(
            NormalizedProduct(source="columbia", source_product_id="fail_prod_1", title="Failing Prod", price=1500.0),
            client=self.client
        )
        pid = p["id"]
        await init_product_progress(run_id, pid, "fail_prod_1", client=self.client)

        # Force failure
        await mark_product_failed(run_id, pid, "Simulated network timeout", client=self.client)

        # Verify failure recorded
        incomplete = await get_incomplete_products(run_id, client=self.client)
        self.assertEqual(len(incomplete), 1)
        self.assertEqual(incomplete[0]["status"], "failed")

        # Retry and complete
        await mark_product_completed(run_id, pid, variant_count=2, client=self.client)

        completed_check = await get_incomplete_products(run_id, client=self.client)
        self.assertEqual(len(completed_check), 0, "Product must be successfully completed after retry")

    # ---------------------------------------------------------------------
    # TEST 7 — HTTP/API failure protection
    # ---------------------------------------------------------------------
    async def test_07_http_api_failure(self):
        """Simulates 429, timeout, connection failure; verifies product is NEVER marked completed."""
        run = await get_or_create_daily_run("tata", client=self.client)
        run_id = run["id"]

        p = await upsert_canonical_product(
            NormalizedProduct(source="tata", source_product_id="http_fail_prod", title="Error Prod", price=1200.0),
            client=self.client
        )
        pid = p["id"]
        await init_product_progress(run_id, pid, "http_fail_prod", client=self.client)

        # Simulate errors
        for error_scenario in ["HTTP 429 Rate Limited", "TimeoutError 7.0s", "Malformed JSON"]:
            await mark_product_failed(run_id, pid, error_scenario, client=self.client)
            incomplete = await get_incomplete_products(run_id, client=self.client)
            self.assertEqual(len(incomplete), 1)
            self.assertNotEqual(incomplete[0]["status"], "completed")

    # ---------------------------------------------------------------------
    # TEST 8 — Zero variants handling
    # ---------------------------------------------------------------------
    async def test_08_zero_variants(self):
        """Simulates legitimate product with 0 variants; verifies persisted as completed with variant_count=0."""
        run = await get_or_create_daily_run("tata", client=self.client)
        run_id = run["id"]

        p = await upsert_canonical_product(
            NormalizedProduct(source="tata", source_product_id="zero_var_prod", title="Zero Variant Hat", price=799.0, variants=[]),
            client=self.client
        )
        pid = p["id"]
        await init_product_progress(run_id, pid, "zero_var_prod", client=self.client)

        # Legitimate 0 variants must complete successfully
        await mark_product_completed(run_id, pid, variant_count=0, client=self.client)

        incomplete = await get_incomplete_products(run_id, client=self.client)
        self.assertEqual(len(incomplete), 0)

        # Check DB progress entry
        rows = await self.client.select("scrape_product_progress", filters={"product_id": f"eq.{pid}"})
        self.assertEqual(rows[0]["status"], "completed")
        self.assertEqual(rows[0]["variant_count"], 0)

    # ---------------------------------------------------------------------
    # TEST 9 — Listing page checkpoint
    # ---------------------------------------------------------------------
    async def test_09_listing_checkpoint(self):
        """Terminates during listing collection; verifies completed pages are skipped upon restart."""
        run = await get_or_create_daily_run("tata", client=self.client)
        run_id = run["id"]

        # Page 0 completes
        await record_listing_page_started(run_id, 0, client=self.client)
        await record_listing_page_completed(run_id, 0, product_count=40, client=self.client)

        # Page 1 fails mid-way
        await record_listing_page_started(run_id, 1, client=self.client)
        await record_listing_page_failed(run_id, 1, "Connection dropped", client=self.client)

        # Restart
        completed = await get_completed_listing_pages(run_id, client=self.client)
        self.assertIn(0, completed, "Page 0 must remain marked completed")
        self.assertNotIn(1, completed, "Page 1 must not be marked completed")

        # Resume page 1
        await record_listing_page_completed(run_id, 1, product_count=40, client=self.client)
        completed_after = await get_completed_listing_pages(run_id, client=self.client)
        self.assertIn(1, completed_after)

    # ---------------------------------------------------------------------
    # TEST 10 — Database size diagnostic
    # ---------------------------------------------------------------------
    async def test_10_database_size(self):
        """Runs the database size diagnostic function and verifies the output format."""
        stats = await get_database_storage_stats(client=self.client)
        report = format_storage_report(stats)

        self.assertIn("Supabase Database", report)
        self.assertIn("products:", report)
        self.assertIn("price_history:", report)
        self.assertIn("scrape_runs:", report)
    # ---------------------------------------------------------------------
    # TEST 11 — Structured report persistence in scrape_runs
    # ---------------------------------------------------------------------
    async def test_11_run_report_storage(self):
        """Verifies structured JSON report is persisted in scrape_runs and readable via run_store."""
        run = await get_or_create_daily_run("myntra", client=self.client)
        run_id = run["id"]

        test_report = {
            "scraper": "myntra",
            "status": "completed",
            "products_scraped": 42,
            "resumed_from_page": 5,
            "completed_pages": [1, 2, 3, 4, 5],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Persist report
        await save_run_report(run_id, test_report, client=self.client)

        # Retrieve specific report
        rep = await get_daily_run_report("myntra", client=self.client)
        self.assertIsNotNone(rep)
        self.assertEqual(rep["scraper"], "myntra")
        self.assertEqual(rep["products_scraped"], 42)
        self.assertEqual(rep["resumed_from_page"], 5)

        # Retrieve all daily reports
        all_reps = await get_all_daily_reports(client=self.client)
        self.assertIn("myntra", all_reps["reports"])
        self.assertEqual(all_reps["reports"]["myntra"]["products_scraped"], 42)

    # ---------------------------------------------------------------------
    # TEST 12 — Checkpoint-based page resume calculation
    # ---------------------------------------------------------------------
    async def test_12_page_checkpoint_resume(self):
        """Verifies that if 5 pages (1..5) are completed, resume calculates next start page as 6."""
        run = await get_or_create_daily_run("myntra", client=self.client)
        run_id = run["id"]

        # Simulate 5 pages completed
        for p in range(1, 6):
            await record_listing_page_started(run_id, p, client=self.client)
            await record_listing_page_completed(run_id, p, product_count=10, client=self.client)

        completed_pages = await get_completed_listing_pages(run_id, client=self.client)
        self.assertEqual(set(completed_pages), {1, 2, 3, 4, 5})

        # Next page to scrape should be max + 1 = 6
        next_page = max(completed_pages) + 1 if completed_pages else 1
        self.assertEqual(next_page, 6)


if __name__ == "__main__":
    unittest.main()

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import urllib.request
import urllib.error

# Ensure UTF-8 output across platforms
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import psutil
except ImportError:
    psutil = None


def format_bytes(num_bytes: int) -> str:
    """Format bytes into human-readable string (KB, MB, etc.)."""
    for unit in ["B", "KB", "MB", "GB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} TB"


def get_runner_resources() -> tuple[str, str]:
    """Capture GitHub Actions runner CPU and memory utilization."""
    if psutil:
        try:
            cpu = f"{psutil.cpu_percent(interval=0.1)}%"
            mem = psutil.virtual_memory()
            mem_str = f"{mem.percent}% ({mem.used // (1024 * 1024)} MB / {mem.total // (1024 * 1024)} MB)"
            return cpu, mem_str
        except Exception:
            pass
    return "unavailable", "unavailable"


def get_render_metrics(api_key: str | None, service_id: str | None) -> tuple[str, str]:
    if not api_key or not service_id:
        return "unavailable", "unavailable"

    try:
        req = urllib.request.Request(
            f"https://api.render.com/v1/services/{service_id}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            metrics = data.get("metrics", {})
            cpu = metrics.get("cpu", "unavailable")
            mem = metrics.get("memory", "unavailable")
            return str(cpu), str(mem)
    except Exception:
        pass

    return "unavailable", "unavailable"


def wait_for_service(service_url: str, max_wait_seconds: int, interval_seconds: int) -> tuple[bool, float, str]:
    """
    Poll the root endpoint until the service responds HTTP 200 with an online status
    or max_wait_seconds is exceeded.
    """
    root_url = service_url.rstrip("/") + "/"
    print(f"Waiting for Render service to become available at {root_url}...")
    print(f"(Timeout: {max_wait_seconds}s, Poll interval: {interval_seconds}s)")

    start_wait = time.perf_counter()
    attempts = 0

    while time.perf_counter() - start_wait < max_wait_seconds:
        attempts += 1
        call_start = time.perf_counter()
        try:
            req = urllib.request.Request(
                root_url,
                headers={"User-Agent": "GitHub-Actions-Scraper-Tester/2.0", "Accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                call_latency = time.perf_counter() - call_start
                if resp.status == 200:
                    raw_body = resp.read().decode("utf-8", errors="replace")
                    try:
                        data = json.loads(raw_body)
                        status_field = str(data.get("status", "")).lower()
                        if status_field == "online" or "status" in data or "service" in data:
                            print(f"  Attempt {attempts}: Service is ONLINE (status=200, latency={call_latency:.3f}s)")
                            return True, call_latency, "Online"
                    except json.JSONDecodeError:
                        print(f"  Attempt {attempts}: Received HTTP 200 (non-JSON)")
                        return True, call_latency, "Online (non-JSON)"
        except urllib.error.HTTPError as e:
            elapsed = int(time.perf_counter() - start_wait)
            print(f"  Attempt {attempts} ({elapsed}s elapsed): HTTP {e.code} - waiting...")
        except (urllib.error.URLError, TimeoutError, ConnectionResetError) as e:
            elapsed = int(time.perf_counter() - start_wait)
            print(f"  Attempt {attempts} ({elapsed}s elapsed): Service waking up/not ready - waiting...")
        except Exception as e:
            elapsed = int(time.perf_counter() - start_wait)
            print(f"  Attempt {attempts} ({elapsed}s elapsed): Connection error ({e}) - waiting...")

        time.sleep(interval_seconds)

    total_waited = time.perf_counter() - start_wait
    return False, total_waited, f"Service unreachable after {total_waited:.1f}s"


def validate_columbia_products(products: list) -> dict:
    """Validate item-level fields for Columbia product records."""
    stats = {
        "valid_products": 0,
        "invalid_products": 0,
        "missing_sku": 0,
        "missing_title": 0,
        "invalid_price": 0,
        "invalid_url": 0
    }

    for p in products:
        if not isinstance(p, dict):
            stats["invalid_products"] += 1
            continue

        item_invalid = False

        sku = p.get("sku")
        if not sku or not str(sku).strip():
            stats["missing_sku"] += 1
            item_invalid = True

        title = p.get("title")
        if not title or not str(title).strip():
            stats["missing_title"] += 1
            item_invalid = True

        price = p.get("price") if p.get("price") is not None else p.get("current_price")
        if price is None:
            stats["invalid_price"] += 1
            item_invalid = True
        else:
            try:
                numeric_price = float(price)
                if numeric_price <= 0:
                    stats["invalid_price"] += 1
                    item_invalid = True
            except (ValueError, TypeError):
                stats["invalid_price"] += 1
                item_invalid = True

        url = p.get("url")
        if not url or not (str(url).startswith("http://") or str(url).startswith("https://")):
            stats["invalid_url"] += 1
            item_invalid = True

        if item_invalid:
            stats["invalid_products"] += 1
        else:
            stats["valid_products"] += 1

    return stats


def validate_tata_products(products: list) -> dict:
    """Validate item-level fields for Tata CLiQ product records."""
    stats = {
        "valid_products": 0,
        "invalid_products": 0,
        "missing_product_id": 0,
        "missing_title": 0,
        "invalid_price": 0,
        "invalid_url": 0,
        "missing_variants": 0,
        "total_variants_found": 0
    }

    for p in products:
        if not isinstance(p, dict):
            stats["invalid_products"] += 1
            continue

        item_invalid = False

        pid = p.get("product_id") or p.get("source_product_id")
        if not pid or not str(pid).strip():
            stats["missing_product_id"] += 1
            item_invalid = True

        title = p.get("title")
        if not title or not str(title).strip():
            stats["missing_title"] += 1
            item_invalid = True

        price = p.get("price") if p.get("price") is not None else p.get("current_price")
        if price is None:
            stats["invalid_price"] += 1
            item_invalid = True
        else:
            try:
                numeric_price = float(price)
                if numeric_price <= 0:
                    stats["invalid_price"] += 1
                    item_invalid = True
            except (ValueError, TypeError):
                stats["invalid_price"] += 1
                item_invalid = True

        url = p.get("url")
        if not url or not (str(url).startswith("http://") or str(url).startswith("https://")):
            stats["invalid_url"] += 1
            item_invalid = True

        variants = p.get("variants")
        if not isinstance(variants, list):
            stats["missing_variants"] += 1
            item_invalid = True
        else:
            stats["total_variants_found"] += len(variants)

        if item_invalid:
            stats["invalid_products"] += 1
        else:
            stats["valid_products"] += 1

    return stats


SCRAPER_METADATA = {
    "columbia": {
        "job_key": "columbia",
        "endpoint": "/scrape",
        "result_file": "columbia-test-result.json",
        "display_name": "Columbia",
    },
    "adv": {
        "job_key": "adv",
        "endpoint": "/scrape/adv",
        "result_file": "adv-test-result.json",
        "display_name": "Adventuras",
    },
    "myntra": {
        "job_key": "myntra",
        "endpoint": "/scrape/myntra",
        "result_file": "myntra-test-result.json",
        "display_name": "Myntra",
    },
    "tata": {
        "job_key": "tatacliq",
        "endpoint": "/scrape/tata",
        "result_file": "tata-test-result.json",
        "display_name": "Tata CLiQ",
    },
}


def validate_generic_products(products: list) -> dict:
    """Validate item-level fields for generic products (Adventuras, Myntra, etc.)."""
    stats = {
        "valid_products": 0,
        "invalid_products": 0,
        "missing_product_id": 0,
        "missing_title": 0,
        "invalid_price": 0,
        "invalid_url": 0,
        "total_variants_found": 0
    }
    for p in products:
        if not isinstance(p, dict):
            stats["invalid_products"] += 1
            continue

        item_invalid = False
        pid = p.get("product_id") or p.get("source_product_id") or p.get("sku")
        if not pid or not str(pid).strip():
            stats["missing_product_id"] += 1
            item_invalid = True

        title = p.get("title")
        if not title or not str(title).strip():
            stats["missing_title"] += 1
            item_invalid = True

        price = p.get("price") if p.get("price") is not None else p.get("current_price")
        if price is None:
            stats["invalid_price"] += 1
            item_invalid = True
        else:
            try:
                if float(price) <= 0:
                    stats["invalid_price"] += 1
                    item_invalid = True
            except (ValueError, TypeError):
                stats["invalid_price"] += 1
                item_invalid = True

        url = p.get("url")
        if not url or not (str(url).startswith("http://") or str(url).startswith("https://")):
            stats["invalid_url"] += 1
            item_invalid = True

        variants = p.get("variants")
        if isinstance(variants, list):
            stats["total_variants_found"] += len(variants)

        if item_invalid:
            stats["invalid_products"] += 1
        else:
            stats["valid_products"] += 1

    return stats


def validate_products(products: list, source_name: str) -> dict:
    if "tata" in source_name:
        return validate_tata_products(products)
    if "columbia" in source_name:
        return validate_columbia_products(products)
    return validate_generic_products(products)


def test_async_job_pipeline(args) -> bool:
    """
    Triggers POST /scrape?scrapers=... to start background pipeline, then polls
    GET /scrape/status/{job_id} until completed or failed.
    Supports running any subset of scrapers selectively.
    """
    service_url = args.service_url.rstrip("/")

    # Step 1: Health check if not skipped
    if not args.skip_wait:
        online, latency, msg = wait_for_service(
            service_url,
            max_wait_seconds=args.deploy_wait_seconds,
            interval_seconds=args.health_check_interval
        )
        if not online:
            print(f"❌ Render service health check timed out: {msg}", file=sys.stderr)
            return False

    raw_scrapers = getattr(args, "scrapers", None) or os.getenv("SCRAPERS", "columbia,adv,myntra,tata")
    alias_map = {"columbiasportswear": "columbia", "adventuras": "adv", "tatacliq": "tata"}
    parsed_req = [alias_map.get(s.strip().lower(), s.strip().lower()) for s in raw_scrapers.split(",") if s.strip()]
    canonical_order = ["columbia", "adv", "myntra", "tata"]
    active_scrapers = [s for s in canonical_order if s in parsed_req] or canonical_order
    params = [f"scrapers={scrapers_param}"]
    if getattr(args, "limit", None):
        params.append(f"limit={args.limit}")
    if getattr(args, "force", False):
        params.append("force=true")
    trigger_url = f"{service_url}/scrape?{'&'.join(params)}"

    print("\n" + "=" * 50)
    print("      TRIGGERING ASYNC SCRAPER PIPELINE")
    print("=" * 50)
    print(f"Target: POST {trigger_url}")

    # Trigger background scrape job
    job_id = None
    job_data = None
    req = urllib.request.Request(
        trigger_url,
        data=b"",
        headers={
            "User-Agent": "GitHub-Actions-Scraper-Tester/2.0",
            "Accept": "application/json"
        },
        method="POST"
    )

    t_start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            if data.get("status") == "already_completed":
                print(f"ℹ️ All requested scrapers ({', '.join(data.get('scrapers', []))}) already completed today in database.")
                job_data = {
                    "status": "completed",
                    "scrapers": data.get("summary", {}),
                    "product_count": sum(v.get("completed_products", 0) for v in data.get("summary", {}).values())
                }
                job_id = "already_completed_today"
            else:
                job_id = data.get("job_id")
                print(f"✅ Job accepted (HTTP {resp.status}): job_id={job_id}")
                print(f"Status URL: {service_url}/scrape/status/{job_id}\n")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            err_data = json.loads(raw)
            if e.code == 409 and "active_job" in err_data:
                job_id = err_data["active_job"]["job_id"]
                print(f"⚠️ A job was already active (HTTP 409): job_id={job_id}. Attaching to poll status...\n")
        except Exception:
            pass
        if not job_id:
            print(f"❌ Failed to trigger scrape job: HTTP {e.code} - {raw}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"❌ Failed to trigger scrape job: {e}", file=sys.stderr)
        return False

    # Step 2: Poll status loop
    poll_url = f"{service_url}/scrape/status/{job_id}" if job_id != "already_completed_today" else None
    if poll_url:
        print(f"Polling job status every {args.health_check_interval}s ({args.health_check_interval // 60}m) (Timeout: {args.scrape_timeout_seconds}s)...")
    consecutive_404 = 0

    while (time.perf_counter() - t_start < args.scrape_timeout_seconds) and (job_id != "already_completed_today"):
        try:
            p_req = urllib.request.Request(
                poll_url,
                headers={"User-Agent": "GitHub-Actions-Scraper-Tester/2.0", "Accept": "application/json"}
            )
            with urllib.request.urlopen(p_req, timeout=30) as p_resp:
                if p_resp.status == 200:
                    consecutive_404 = 0
                    job_data = json.loads(p_resp.read().decode("utf-8"))
                    status = job_data.get("status", "unknown")
                    curr_scraper = job_data.get("current_scraper") or "-"
                    pct = job_data.get("progress_percentage", 0.0)
                    elapsed = job_data.get("elapsed_seconds", round(time.perf_counter() - t_start, 1))
                    prods = job_data.get("product_count", 0)
                    vars_ = job_data.get("variant_count", 0)

                    log_line = f"[JOB {job_id} | {elapsed:.1f}s] Status: {status.upper()} | Scraper: {curr_scraper} | Progress: {pct:.1f}% | Products: {prods:,} | Variants: {vars_:,}"
                    print(log_line, flush=True)

                    if status in ("completed", "failed"):
                        break
        except urllib.error.HTTPError as e:
            print(f"  [Poll Warning] HTTP Error {e.code} ({e.reason}). Retrying in {args.health_check_interval}s...", flush=True)
            if e.code in (404, 502, 503, 504):
                consecutive_404 += 1
                # Check root status fallback if server rebooted / job was auto-resumed
                try:
                    fb_req = urllib.request.Request(f"{service_url}/scrape/status", headers={"Accept": "application/json"})
                    with urllib.request.urlopen(fb_req, timeout=15) as fb_resp:
                        if fb_resp.status == 200:
                            fb_data = json.loads(fb_resp.read().decode("utf-8"))
                            fb_status = fb_data.get("status")
                            if fb_status in ("running", "queued") and fb_data.get("job_id"):
                                new_job_id = fb_data["job_id"]
                                if new_job_id != job_id:
                                    print(f"  [Recovery] Attached to resumed job {new_job_id} after server restart.")
                                    job_id = new_job_id
                                    poll_url = f"{service_url}/scrape/status/{job_id}"
                                job_data = fb_data
                                consecutive_404 = 0
                            elif fb_status == "completed":
                                print("  [Recovery] All scrapers for today have completed successfully in database.")
                                job_data = fb_data
                                break
                            else:
                                print(f"  [Recovery] Server status is '{fb_status}'. Waiting for pipeline progress...")
                except Exception:
                    pass
        except Exception as e:
            print(f"  [Poll Warning] Could not fetch job status: {e}. Retrying in {args.health_check_interval}s...", flush=True)

        time.sleep(args.health_check_interval)

    total_poll_time = time.perf_counter() - t_start
    is_timed_out = not job_data or job_data.get("status") not in ("completed", "failed")

    if is_timed_out:
        print(f"\n❌ Scraper job polling timed out after {total_poll_time:.1f}s", file=sys.stderr)
        final_status = "timed_out"
    else:
        final_status = job_data.get("status", "unknown")
        print(f"\nJob finished with status: {final_status.upper()} in {total_poll_time:.1f}s\n")

    # Step 3: Fetch results and validate all requested scrapers
    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)

    # Fetch authoritative daily summary from /scrape/status to merge with job_data
    daily_db_summary = {}
    try:
        db_req = urllib.request.Request(f"{service_url}/scrape/status", headers={"Accept": "application/json"})
        with urllib.request.urlopen(db_req, timeout=15) as db_resp:
            if db_resp.status == 200:
                root_status_data = json.loads(db_resp.read().decode("utf-8"))
                daily_db_summary = root_status_data.get("scrapers", {})
                if not job_data:
                    job_data = root_status_data
    except Exception as e:
        print(f"Notice: Could not fetch daily summary from /scrape/status: {e}")

    if job_data:
        (results_dir / f"job-{job_id}.json").write_text(json.dumps(job_data, indent=2), encoding="utf-8")

    scrapers_dict = job_data.get("scrapers", {}) if job_data else {}
    all_success = True

    for s_name in active_scrapers:
        meta = SCRAPER_METADATA.get(s_name)
        if not meta:
            continue
        job_key = meta["job_key"]
        s_info = dict(scrapers_dict.get(job_key) or scrapers_dict.get(s_name, {}))

        # Merge with database daily summary if available
        db_info = daily_db_summary.get(s_name, {})
        if not s_info.get("status") or s_info.get("status") in ("queued", "pending"):
            if db_info.get("status"):
                s_info["status"] = db_info.get("status")
        if (not s_info.get("duration_seconds") or s_info.get("duration_seconds") == 0.0) and db_info.get("duration_seconds"):
            s_info["duration_seconds"] = db_info.get("duration_seconds")
        if (not s_info.get("product_count") or s_info.get("product_count") == 0) and db_info.get("completed_products"):
            s_info["product_count"] = db_info.get("completed_products")
        if db_info.get("error") and not s_info.get("error"):
            s_info["error"] = db_info.get("error")

        s_status = s_info.get("status")

        # Download & validate
        val_stats = {"json_valid": False, "schema_valid": False, "valid_products": 0, "invalid_products": 0}
        resp_size = 0
        s_success = False

        endpoint_url = f"{service_url}{meta['endpoint']}"
        try:
            req_dl = urllib.request.Request(endpoint_url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req_dl, timeout=30) as resp_dl:
                raw_bytes = resp_dl.read()
                resp_size = len(raw_bytes)
                loaded_json = json.loads(raw_bytes.decode("utf-8"))
                prods_list = loaded_json.get("products", [])
                val_stats = validate_products(prods_list, s_name)
                val_stats["json_valid"] = True
                val_stats["schema_valid"] = True

                s_product_count = val_stats.get("valid_products", 0)
                if s_product_count >= args.min_products and (s_status == "completed" or (s_status is None and s_product_count > 0)):
                    s_success = True
                else:
                    s_success = False
        except Exception as e:
            s_success = False
            s_info["error"] = f"Failed to download/validate {meta['display_name']} data: {e}"

        if not s_success:
            all_success = False

        duration = s_info.get("duration_seconds", 0.0)

        result_data = {
            "scraper": s_name,
            "display_name": meta["display_name"],
            "status": "passed" if s_success else "failed",
            "duration_seconds": duration,
            "product_count": val_stats.get("valid_products", s_info.get("product_count", 0)),
            "variant_count": val_stats.get("total_variants_found", s_info.get("variant_count", 0)),
            "response_size_bytes": resp_size,
            "validation": val_stats,
            "error": None if s_success else (s_info.get("error") or ("Polling timed out" if is_timed_out else "Validation failed"))
        }
        (results_dir / meta["result_file"]).write_text(json.dumps(result_data, indent=2), encoding="utf-8")

    # Always generate CI summary
    generate_ci_summary(results_dir=str(results_dir))
    return all_success


def test_single_scraper(args) -> bool:
    """Legacy single scraper test for backwards compatibility."""
    overall_start_time = time.perf_counter()
    service_url = args.service_url.rstrip("/")
    source_name = args.source_name.lower()
    label = "TATA CLIQ" if "tata" in source_name else "COLUMBIA"

    endpoint_path = args.endpoint
    if not endpoint_path:
        endpoint_path = "/scrape/tata" if "tata" in source_name else "/scrape"

    scrape_endpoint = f"{service_url}{endpoint_path}"

    print("=" * 40)
    print(f"       {label} SCRAPER TEST")
    print("=" * 40)
    print(f"Service: {service_url}")
    print(f"Endpoint: {scrape_endpoint}")

    if not args.skip_wait:
        online, health_latency, wait_msg = wait_for_service(
            service_url,
            max_wait_seconds=args.deploy_wait_seconds,
            interval_seconds=args.health_check_interval
        )
        if not online:
            print(f"❌ SERVICE UNAVAILABLE: {wait_msg}")
            return False
    else:
        health_latency = 0.0

    print("Status:\n✅ API ONLINE\n")
    print(f"Calling scrape endpoint: {scrape_endpoint}")
    print(f"(Request timeout: {args.scrape_timeout_seconds}s)")

    scrape_start_dt = datetime.now(timezone.utc)
    started_str = scrape_start_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    t_scrape_start = time.perf_counter()

    http_status = 0
    raw_response_bytes = b""
    scrape_error = None
    max_retries = 3

    for attempt in range(1, max_retries + 1):
        scrape_error = None
        http_status = 0
        raw_response_bytes = b""
        t_req_start = time.perf_counter()

        try:
            req = urllib.request.Request(
                scrape_endpoint,
                headers={
                    "User-Agent": "GitHub-Actions-Scraper-Tester/2.0",
                    "Accept": "application/json"
                }
            )
            with urllib.request.urlopen(req, timeout=args.scrape_timeout_seconds) as resp:
                http_status = resp.status
                raw_response_bytes = resp.read()
                break
        except urllib.error.HTTPError as e:
            http_status = e.code
            raw_response_bytes = e.read()
            scrape_error = f"HTTP {e.code}: {e.reason}"
            call_dur = time.perf_counter() - t_req_start
            if e.code in (502, 503, 504) and call_dur < 20 and attempt < max_retries:
                retry_wait = 15
                print(f"  Attempt {attempt}: Received HTTP {e.code} in {call_dur:.1f}s (service deploying/restarting). Retrying in {retry_wait}s...")
                time.sleep(retry_wait)
                continue
            break
        except (urllib.error.URLError, ConnectionResetError) as e:
            call_dur = time.perf_counter() - t_req_start
            scrape_error = f"Network URL error: {e}"
            if call_dur < 20 and attempt < max_retries:
                retry_wait = 15
                print(f"  Attempt {attempt}: Connection reset/error in {call_dur:.1f}s. Retrying in {retry_wait}s...")
                time.sleep(retry_wait)
                continue
            break
        except TimeoutError:
            scrape_error = f"Request timed out after {args.scrape_timeout_seconds} seconds"
            break
        except Exception as e:
            scrape_error = f"Unexpected error during scrape request: {e}"
            break

    t_scrape_end = time.perf_counter()
    scrape_duration = t_scrape_end - t_scrape_start
    scrape_end_dt = datetime.now(timezone.utc)
    finished_str = scrape_end_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    response_size = len(raw_response_bytes)

    json_valid = False
    schema_valid = False
    parsed_json = None
    schema_errors = []

    if http_status == 200 and not scrape_error:
        try:
            parsed_json = json.loads(raw_response_bytes.decode("utf-8"))
            json_valid = True
        except Exception as e:
            scrape_error = f"Malformed JSON response: {e}"

    product_count = 0
    variant_count = 0
    avg_variants = 0.0
    val_stats = {}

    if json_valid and isinstance(parsed_json, dict):
        if "schema_version" not in parsed_json:
            schema_errors.append("Missing required key 'schema_version'")

        products = parsed_json.get("products")
        if not isinstance(products, list):
            schema_errors.append("'products' field is not a list")
            products = []
        product_count = len(products)

        if product_count < args.min_products:
            schema_errors.append(f"Product count ({product_count}) is below minimum threshold ({args.min_products})")

        if "tata" in source_name:
            val_stats = validate_tata_products(products)
            variant_count = val_stats.get("total_variants_found", 0)
        else:
            val_stats = validate_columbia_products(products)

        if not schema_errors:
            schema_valid = True

    is_success = (
        http_status == 200
        and json_valid
        and schema_valid
        and product_count >= args.min_products
        and not scrape_error
    )

    report_data = {
        "scraper": source_name,
        "status": "passed" if is_success else "failed",
        "duration_seconds": round(scrape_duration, 2),
        "http_status": http_status,
        "product_count": product_count,
        "variant_count": variant_count,
        "response_size_bytes": response_size,
        "validation": {
            "json_valid": json_valid,
            "schema_valid": schema_valid,
            "schema_errors": schema_errors,
            **val_stats
        }
    }

    if not is_success:
        report_data["error"] = scrape_error

    out_file = Path(args.output_file)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
    print(f"\nReport artifact saved to: {out_file.resolve()}\n")
    return is_success


def generate_ci_summary(results_dir: str = "test-results"):
    """
    Read all scraper test results in results_dir, format the final combined CI summary,
    and append to $GITHUB_STEP_SUMMARY.
    Dynamically renders rows for all tested scrapers.
    """
    r_dir = Path(results_dir)
    scrapers_run = []
    total_test_time = 0.0
    all_passed = True
    failed_scrapers = []

    print("\n" + "=" * 50)
    print("         SCRAPER CI TEST SUMMARY")
    print("=" * 50)

    for s_name, meta in SCRAPER_METADATA.items():
        res_file = r_dir / meta["result_file"]
        if not res_file.exists():
            continue

        try:
            data = json.loads(res_file.read_text(encoding="utf-8"))
        except Exception:
            data = {}

        passed = bool(data.get("status") == "passed")
        dur = float(data.get("duration_seconds", 0.0))
        total_test_time += dur
        if not passed:
            all_passed = False
            failed_scrapers.append(meta["display_name"])

        scrapers_run.append({
            "name": s_name,
            "display_name": meta["display_name"],
            "data": data,
            "passed": passed,
        })

        val = data.get("validation", {})
        print(f"\n{meta['display_name'].upper()}")
        print(f"Status: {'✅ PASSED' if passed else '❌ FAILED'}")
        print(f"Products: {data.get('product_count', 0):,}")
        if data.get("variant_count"):
            print(f"Variants: {data.get('variant_count', 0):,}")
        print(f"Execution time: {dur:.1f} sec")
        print(f"Response size: {format_bytes(data.get('response_size_bytes', 0))}")
        print(f"JSON: {'✅ Valid' if val.get('json_valid') else '❌ Invalid'}")
        print(f"Schema: {'✅ Valid' if val.get('schema_valid') else '❌ Invalid'}")
        print(f"Validation: {val.get('valid_products', 0):,} valid, {val.get('invalid_products', 0)} invalid")
        if not passed and data.get("error"):
            print(f"Error: {data.get('error')}")

    if not scrapers_run:
        print("\nNo scraper test result files found in test-results/")
        return False

    final_result = "✅ ALL REQUESTED SCRAPERS PASSED" if all_passed else "❌ SCRAPER TEST FAILED"

    print(f"\nTOTAL TEST TIME:\n{total_test_time:.2f} sec\n")
    print("FINAL RESULT:")
    print(final_result)
    if failed_scrapers:
        print(f"Failed Scrapers: ❌ {', '.join(failed_scrapers)}")
    print("=" * 50 + "\n")

    # Step Summary Markdown Table
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        table_rows = []
        for s in scrapers_run:
            s_status = "✅ PASSED" if s["passed"] else "❌ FAILED"
            d = s["data"]
            p_cnt = f"{d.get('product_count', 0):,}"
            v_cnt = f"{d.get('variant_count', 0):,}" if d.get("variant_count") else "-"
            s_time = f"{d.get('duration_seconds', 0.0):.1f}s"
            s_size = format_bytes(d.get("response_size_bytes", 0))
            s_val = "✅ Valid" if s["passed"] else "❌ Invalid"
            table_rows.append(
                f"| **{s['display_name']}** | {s_status} | {p_cnt} | {v_cnt} | {s_time} | {s_size} | {s_val} |"
            )

        rows_joined = "\n".join(table_rows)
        md = f"""# 🚀 Scraper Continuous Integration Pipeline

## 📊 Summary

| Scraper | Status | Products | Variants / SKUs | Execution Time | Response Size | Validation |
|---|:---:|---:|---:|---:|---:|:---:|
{rows_joined}

**Total Test Time**: `{total_test_time:.2f} seconds`
**Final Result**: **{final_result}**
"""
        if failed_scrapers:
            md += f"\n> [!CAUTION]\n> **Pipeline Failed**: The following scrapers failed: **{', '.join(failed_scrapers)}**.\n"

        try:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write("\n" + md + "\n")
        except Exception as e:
            print(f"Warning: Failed to write to GITHUB_STEP_SUMMARY: {e}", file=sys.stderr)

    return all_passed


def main():
    parser = argparse.ArgumentParser(description="Test deployed web scrapers on Render")
    parser.add_argument("--service-url", default=os.getenv("RENDER_SERVICE_URL", "https://columbia-4-0.onrender.com"))
    parser.add_argument("--source-name", default=os.getenv("SCRAPER_NAME", "columbia"))
    parser.add_argument("--scrapers", default=os.getenv("SCRAPERS", "columbia,adv,myntra,tata"), help="Comma-separated scrapers to trigger and test (e.g. columbia,adv)")
    parser.add_argument("--endpoint", default=None, help="Endpoint path e.g. /scrape or /scrape/tata (runs legacy test)")
    parser.add_argument("--min-products", type=int, default=int(os.getenv("MIN_PRODUCTS", "1")))
    parser.add_argument("--deploy-wait-seconds", type=int, default=int(os.getenv("RENDER_DEPLOY_WAIT_SECONDS", "600")))
    parser.add_argument("--health-check-interval", type=int, default=int(os.getenv("HEALTH_CHECK_INTERVAL_SECONDS", "30")))
    parser.add_argument("--scrape-timeout-seconds", type=int, default=int(os.getenv("SCRAPE_TIMEOUT_SECONDS", "3900")))
    parser.add_argument("--output-file", default=None)
    parser.add_argument("--skip-wait", action="store_true", help="Skip deployment wait if already checked")
    parser.add_argument("--wait-only", action="store_true", help="Only wait for Render deployment to become healthy")
    parser.add_argument("--generate-summary", action="store_true", help="Generate final CI summary from test-results/")
    parser.add_argument("--poll-job", action="store_true", help="Trigger POST /scrape and poll GET /scrape/status/{job_id}")
    parser.add_argument("--results-dir", default="test-results")
    parser.add_argument("--limit", type=int, default=None, help="Product limit for test mode")
    parser.add_argument("--force", action="store_true", default=False, help="Force re-run even if already completed today")

    args = parser.parse_args()

    if args.generate_summary:
        success = generate_ci_summary(args.results_dir)
        sys.exit(0 if success else 1)

    if args.wait_only:
        service_url = args.service_url.rstrip("/")
        online, latency, msg = wait_for_service(
            service_url,
            max_wait_seconds=args.deploy_wait_seconds,
            interval_seconds=args.health_check_interval
        )
        if not online:
            print(f"❌ Render service health check timed out: {msg}", file=sys.stderr)
            sys.exit(1)
        print("✅ Render service is healthy and online.")
        sys.exit(0)

    # If --endpoint is specified explicitly, run legacy single scraper test
    if args.endpoint:
        if not args.output_file:
            args.output_file = f"test-results/{args.source_name}-test-result.json"
        success = test_single_scraper(args)
        sys.exit(0 if success else 1)

    # Default mode: Run async job trigger and polling pipeline
    success = test_async_job_pipeline(args)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

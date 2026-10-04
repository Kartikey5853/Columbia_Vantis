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

        price = p.get("price")
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

        pid = p.get("product_id")
        if not pid or not str(pid).strip():
            stats["missing_product_id"] += 1
            item_invalid = True

        title = p.get("title")
        if not title or not str(title).strip():
            stats["missing_title"] += 1
            item_invalid = True

        price = p.get("price")
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


def test_async_job_pipeline(args) -> bool:
    """
    Triggers POST /scrape to start background pipeline, then polls
    GET /scrape/status/{job_id} until completed or failed.
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

    print("\n" + "=" * 50)
    print("      TRIGGERING ASYNC SCRAPER PIPELINE")
    print("=" * 50)
    trigger_url = f"{service_url}/scrape"
    print(f"Target: POST {trigger_url}")

    # Trigger background scrape job
    job_id = None
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
    poll_url = f"{service_url}/scrape/status/{job_id}"
    print(f"Polling job status every {args.health_check_interval}s ({args.health_check_interval // 60}m) (Timeout: {args.scrape_timeout_seconds}s)...")
    last_print = ""
    job_data = None

    while time.perf_counter() - t_start < args.scrape_timeout_seconds:
        try:
            p_req = urllib.request.Request(
                poll_url,
                headers={"User-Agent": "GitHub-Actions-Scraper-Tester/2.0", "Accept": "application/json"}
            )
            with urllib.request.urlopen(p_req, timeout=30) as p_resp:
                if p_resp.status == 200:
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
        except Exception as e:
            print(f"  [Poll Warning] Could not fetch job status: {e}. Retrying in {args.health_check_interval}s...", flush=True)

        time.sleep(args.health_check_interval)

    total_poll_time = time.perf_counter() - t_start

    if not job_data or job_data.get("status") not in ("completed", "failed"):
        print(f"\n❌ Scraper job polling timed out after {total_poll_time:.1f}s", file=sys.stderr)
        return False

    final_status = job_data.get("status")
    print(f"\nJob finished with status: {final_status.upper()} in {total_poll_time:.1f}s\n")

    # Step 3: Fetch results and validate both scrapers
    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)

    # Save complete raw job artifact
    (results_dir / f"job-{job_id}.json").write_text(json.dumps(job_data, indent=2), encoding="utf-8")

    scrapers_dict = job_data.get("scrapers", {})
    col_info = scrapers_dict.get("columbia", {})
    tata_info = scrapers_dict.get("tatacliq", {})

    col_success = col_info.get("status") == "completed" and col_info.get("product_count", 0) >= args.min_products
    tata_success = tata_info.get("status") == "completed" and tata_info.get("product_count", 0) >= args.min_products

    # Download & validate Columbia JSON
    col_val = {"json_valid": False, "schema_valid": False, "valid_products": 0, "invalid_products": 0}
    col_size = 0
    if col_success:
        try:
            c_req = urllib.request.Request(f"{service_url}/scrape", headers={"Accept": "application/json"})
            with urllib.request.urlopen(c_req, timeout=30) as c_resp:
                raw_c = c_resp.read()
                col_size = len(raw_c)
                col_json = json.loads(raw_c.decode("utf-8"))
                col_products = col_json.get("products", [])
                col_val = validate_columbia_products(col_products)
                col_val["json_valid"] = True
                col_val["schema_valid"] = True
        except Exception as e:
            col_success = False
            col_info["error"] = f"Failed to download/validate Columbia data: {e}"

    # Download & validate Tata JSON
    tata_val = {"json_valid": False, "schema_valid": False, "valid_products": 0, "invalid_products": 0}
    tata_size = 0
    if tata_success:
        try:
            t_req = urllib.request.Request(f"{service_url}/scrape/tata", headers={"Accept": "application/json"})
            with urllib.request.urlopen(t_req, timeout=30) as t_resp:
                raw_t = t_resp.read()
                tata_size = len(raw_t)
                tata_json = json.loads(raw_t.decode("utf-8"))
                tata_products = tata_json.get("products", [])
                tata_val = validate_tata_products(tata_products)
                tata_val["json_valid"] = True
                tata_val["schema_valid"] = True
        except Exception as e:
            tata_success = False
            tata_info["error"] = f"Failed to download/validate Tata CLiQ data: {e}"

    # Save columbia-test-result.json
    col_result_data = {
        "scraper": "columbia",
        "status": "passed" if col_success else "failed",
        "duration_seconds": col_info.get("duration_seconds", 0.0),
        "product_count": col_info.get("product_count", 0),
        "response_size_bytes": col_size,
        "validation": col_val,
        "error": col_info.get("error")
    }
    (results_dir / "columbia-test-result.json").write_text(json.dumps(col_result_data, indent=2), encoding="utf-8")

    # Save tata-test-result.json
    if col_info.get("status") == "completed":
        tata_result_data = {
            "scraper": "tatacliq",
            "status": "passed" if tata_success else "failed",
            "duration_seconds": tata_info.get("duration_seconds", 0.0),
            "product_count": tata_info.get("product_count", 0),
            "variant_count": tata_info.get("variant_count", 0),
            "response_size_bytes": tata_size,
            "validation": tata_val,
            "error": tata_info.get("error")
        }
        (results_dir / "tata-test-result.json").write_text(json.dumps(tata_result_data, indent=2), encoding="utf-8")

    # Output CI summary
    generate_ci_summary(results_dir=str(results_dir))
    return col_success and tata_success


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
    """
    r_dir = Path(results_dir)
    columbia_file = r_dir / "columbia-test-result.json"
    tata_file = r_dir / "tata-test-result.json"

    columbia_data = json.loads(columbia_file.read_text(encoding="utf-8")) if columbia_file.exists() else None
    tata_data = json.loads(tata_file.read_text(encoding="utf-8")) if tata_file.exists() else None

    columbia_passed = bool(columbia_data and columbia_data.get("status") == "passed")
    tata_passed = bool(tata_data and tata_data.get("status") == "passed")

    total_test_time = 0.0
    if columbia_data:
        total_test_time += columbia_data.get("duration_seconds", 0)
    if tata_data:
        total_test_time += tata_data.get("duration_seconds", 0)

    # Determine Overall Result
    if columbia_passed and tata_passed:
        final_result = "✅ ALL SCRAPERS PASSED"
        overall_success = True
        failed_scraper = None
    elif not columbia_passed:
        final_result = "❌ SCRAPER TEST FAILED"
        overall_success = False
        failed_scraper = "Columbia"
    else:
        final_result = "❌ SCRAPER TEST FAILED"
        overall_success = False
        failed_scraper = "Tata CLiQ"

    # Terminal Summary Output
    print("\n" + "=" * 40)
    print("       SCRAPER CI TEST")
    print("=" * 40)
    print("\nCOLUMBIA")
    if columbia_data:
        c_val = columbia_data.get("validation", {})
        print(f"Status: {'✅ PASSED' if columbia_passed else '❌ FAILED'}")
        print(f"Products/SKUs: {columbia_data.get('product_count', 0):,}")
        print(f"Execution time: {columbia_data.get('duration_seconds', 0):.1f} sec")
        print(f"Response size: {format_bytes(columbia_data.get('response_size_bytes', 0))}")
        print(f"JSON: {'✅ Valid' if c_val.get('json_valid') else '❌ Invalid'}")
        print(f"Schema: {'✅ Valid' if c_val.get('schema_valid') else '❌ Invalid'}")
        print(f"Validation: {c_val.get('valid_products', 0):,} valid, {c_val.get('invalid_products', 0)} invalid")
        if not columbia_passed:
            print(f"Error: {columbia_data.get('error', 'Unknown error')}")
    else:
        print("Status: ❌ NOT RUN")

    print("\nTATA CLIQ")
    if tata_data:
        t_val = tata_data.get("validation", {})
        print(f"Status: {'✅ PASSED' if tata_passed else '❌ FAILED'}")
        print(f"Products: {tata_data.get('product_count', 0):,}")
        print(f"Variants: {tata_data.get('variant_count', 0):,}")
        print(f"Execution time: {tata_data.get('duration_seconds', 0):.1f} sec")
        print(f"Response size: {format_bytes(tata_data.get('response_size_bytes', 0))}")
        print(f"JSON: {'✅ Valid' if t_val.get('json_valid') else '❌ Invalid'}")
        print(f"Schema: {'✅ Valid' if t_val.get('schema_valid') else '❌ Invalid'}")
        print(f"Validation: {t_val.get('valid_products', 0):,} valid, {t_val.get('invalid_products', 0)} invalid")
        if not tata_passed:
            print(f"Error: {tata_data.get('error', 'Unknown error')}")
    elif not columbia_passed:
        print("Status: ⏭️ SKIPPED (Fail-Fast: Columbia failed)")
    else:
        print("Status: ❌ NOT RUN")

    print(f"\nTOTAL TEST TIME:\n{total_test_time:.2f} sec\n")
    print("FINAL RESULT:")
    print(final_result)
    if failed_scraper:
        print(f"Failed Scraper: ❌ {failed_scraper}")
    print("=" * 40 + "\n")

    # Step Summary Markdown Table
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        c_status = "✅ PASSED" if columbia_passed else "❌ FAILED"
        c_count = f"{columbia_data.get('product_count', 0):,}" if columbia_data else "-"
        c_skus = c_count
        c_time = f"{columbia_data.get('duration_seconds', 0):.1f}s" if columbia_data else "-"
        c_size = format_bytes(columbia_data.get('response_size_bytes', 0)) if columbia_data else "-"
        c_val = "✅ Valid" if columbia_passed else "❌ Invalid"

        if tata_data:
            t_status = "✅ PASSED" if tata_passed else "❌ FAILED"
            t_count = f"{tata_data.get('product_count', 0):,}"
            t_skus = f"{tata_data.get('variant_count', 0):,}"
            t_time = f"{tata_data.get('duration_seconds', 0):.1f}s"
            t_size = format_bytes(tata_data.get('response_size_bytes', 0))
            t_val = "✅ Valid" if tata_passed else "❌ Invalid"
        else:
            t_status = "⏭️ SKIPPED" if not columbia_passed else "❌ NOT RUN"
            t_count = "-"
            t_skus = "-"
            t_time = "-"
            t_size = "-"
            t_val = "-"

        md = f"""# 🚀 Scraper Continuous Integration Pipeline

## 📊 Summary

| Scraper | Status | Products | Variants / SKUs | Execution Time | Response Size | Validation |
|---|:---:|---:|---:|---:|---:|:---:|
| **Columbia** | {c_status} | {c_count} | {c_skus} | {c_time} | {c_size} | {c_val} |
| **Tata CLiQ** | {t_status} | {t_count} | {t_skus} | {t_time} | {t_size} | {t_val} |

**Total Test Time**: `{total_test_time:.2f} seconds`
**Final Result**: **{final_result}**
"""
        if failed_scraper:
            md += f"\n> [!CAUTION]\n> **Pipeline Failed**: The **{failed_scraper}** scraper test failed. Execution halted.\n"

        try:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write("\n" + md + "\n")
        except Exception as e:
            print(f"Warning: Failed to write to GITHUB_STEP_SUMMARY: {e}", file=sys.stderr)

    return overall_success


def main():
    parser = argparse.ArgumentParser(description="Test deployed web scrapers on Render")
    parser.add_argument("--service-url", default=os.getenv("RENDER_SERVICE_URL", "https://columbia-4-0.onrender.com"))
    parser.add_argument("--source-name", default=os.getenv("SCRAPER_NAME", "columbia"))
    parser.add_argument("--endpoint", default=None, help="Endpoint path e.g. /scrape or /scrape/tata (runs legacy test)")
    parser.add_argument("--min-products", type=int, default=int(os.getenv("MIN_PRODUCTS", "1")))
    parser.add_argument("--deploy-wait-seconds", type=int, default=int(os.getenv("RENDER_DEPLOY_WAIT_SECONDS", "600")))
    parser.add_argument("--health-check-interval", type=int, default=int(os.getenv("HEALTH_CHECK_INTERVAL_SECONDS", "300")))
    parser.add_argument("--scrape-timeout-seconds", type=int, default=int(os.getenv("SCRAPE_TIMEOUT_SECONDS", "2400")))
    parser.add_argument("--output-file", default=None)
    parser.add_argument("--skip-wait", action="store_true", help="Skip deployment wait if already checked")
    parser.add_argument("--wait-only", action="store_true", help="Only wait for Render deployment to become healthy")
    parser.add_argument("--generate-summary", action="store_true", help="Generate final CI summary from test-results/")
    parser.add_argument("--poll-job", action="store_true", help="Trigger POST /scrape and poll GET /scrape/status/{job_id}")
    parser.add_argument("--results-dir", default="test-results")

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

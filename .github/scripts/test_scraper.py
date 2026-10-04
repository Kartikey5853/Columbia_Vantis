import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import urllib.request
import urllib.error

# Ensure UTF-8 output for emojis and special characters across platforms
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
    """
    Check if Render CPU and memory metrics can be retrieved.
    Render v1 REST API does not provide a public real-time CPU/memory utilization
    endpoint (only plan limits and service metadata). Unless a custom metrics endpoint
    is configured, return 'unavailable'.
    """
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
                headers={"User-Agent": "GitHub-Actions-Scraper-Tester/1.0", "Accept": "application/json"}
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
                if float(price) < 0:
                    stats["invalid_price"] += 1
                    item_invalid = True
            except (ValueError, TypeError):
                stats["invalid_price"] += 1
                item_invalid = True

        url = p.get("url")
        if not url or not isinstance(url, str) or not url.startswith("http"):
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
        "invalid_mrp": 0,
        "invalid_url": 0,
        "missing_variants": 0,
        "total_variants_counted": 0
    }

    for p in products:
        if not isinstance(p, dict):
            stats["invalid_products"] += 1
            continue

        item_invalid = False

        # product_id check
        pid = p.get("product_id")
        if not pid or not str(pid).strip():
            stats["missing_product_id"] += 1
            item_invalid = True

        # title check
        title = p.get("title")
        if not title or not str(title).strip():
            stats["missing_title"] += 1
            item_invalid = True

        # price check
        price = p.get("price")
        if price is None:
            stats["invalid_price"] += 1
            item_invalid = True
        else:
            try:
                if float(price) < 0:
                    stats["invalid_price"] += 1
                    item_invalid = True
            except (ValueError, TypeError):
                stats["invalid_price"] += 1
                item_invalid = True

        # mrp check
        mrp = p.get("mrp")
        if mrp is None:
            stats["invalid_mrp"] += 1
            item_invalid = True
        else:
            try:
                if float(mrp) < 0:
                    stats["invalid_mrp"] += 1
                    item_invalid = True
            except (ValueError, TypeError):
                stats["invalid_mrp"] += 1
                item_invalid = True

        # url check
        url = p.get("url")
        if not url or not isinstance(url, str) or not url.startswith("http"):
            stats["invalid_url"] += 1
            item_invalid = True

        # variants check
        variants = p.get("variants")
        if not isinstance(variants, list):
            stats["missing_variants"] += 1
            item_invalid = True
        else:
            stats["total_variants_counted"] += len(variants)

        if item_invalid:
            stats["invalid_products"] += 1
        else:
            stats["valid_products"] += 1

    return stats


def test_single_scraper(args) -> bool:
    """Execute test against one scraper endpoint and save results."""
    overall_start_time = time.perf_counter()
    service_url = args.service_url.rstrip("/")
    source_name = args.source_name.lower()
    endpoint = args.endpoint if args.endpoint else ("/scrape" if source_name == "columbia" else f"/scrape/{source_name}")
    scrape_endpoint = f"{service_url}{endpoint}"

    label = "TATA CLIQ" if "tata" in source_name else source_name.upper()

    print("=" * 40)
    print(f"       {label} SCRAPER TEST")
    print("=" * 40)
    print(f"Service: {service_url}")
    print(f"Endpoint: {scrape_endpoint}\n")

    # Step 1: Wait for service if not wait-only or already waited
    if not args.skip_wait:
        online, health_latency, health_msg = wait_for_service(
            service_url,
            max_wait_seconds=args.deploy_wait_seconds,
            interval_seconds=args.health_check_interval
        )
        if not online:
            total_duration = time.perf_counter() - overall_start_time
            print("\n❌ SERVICE HEALTH CHECK FAILED")
            print(f"Status: ❌ OFFLINE - {health_msg}")
            print(f"Execution Time: {total_duration:.1f} seconds")
            print("\n" + "=" * 40)
            print("       RESULT: ❌ FAIL")
            print("=" * 40)

            failure_report = {
                "status": "failed",
                "source": source_name,
                "service": service_url,
                "endpoint": endpoint,
                "api_online": False,
                "error": f"Health check failed: {health_msg}",
                "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "finished_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "duration_seconds": total_duration,
                "http_status": 0,
                "product_count": 0,
                "response_size_bytes": 0,
                "validation": {"json_valid": False, "schema_valid": False}
            }
            out_path = Path(args.output_file)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(failure_report, indent=2), encoding="utf-8")
            return False
    else:
        health_latency = 0.0

    print("Status:\n✅ API ONLINE\n")

    # Step 2: Trigger scrape endpoint
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
                    "User-Agent": "GitHub-Actions-Scraper-Tester/1.0",
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
            # If 502/503/504 happened quickly (< 20s), service is likely restarting/deploying
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

    # Step 3: Parse and Validate
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
        # Common checks
        if "schema_version" not in parsed_json:
            schema_errors.append("Missing required key 'schema_version'")

        actual_source = parsed_json.get("source")
        if "tata" in source_name and actual_source != "tatacliq":
            schema_errors.append(f"source '{actual_source}' does not match expected 'tatacliq'")
        elif "columbia" in source_name and actual_source != "columbia":
            schema_errors.append(f"source '{actual_source}' does not match expected 'columbia'")

        products = parsed_json.get("products")
        if not isinstance(products, list):
            schema_errors.append("'products' field is not a list")
            products = []
        product_count = len(products)

        if product_count < args.min_products:
            schema_errors.append(f"Product count ({product_count}) is below minimum threshold ({args.min_products})")

        # Specific Scraper Schema Checks
        if "tata" in source_name:
            total_p = parsed_json.get("total_products")
            if total_p != product_count:
                schema_errors.append(f"total_products ({total_p}) does not match products.length ({product_count})")

            total_v = parsed_json.get("total_variants")
            if total_v is None or not isinstance(total_v, (int, float)) or total_v < 0:
                schema_errors.append(f"total_variants is invalid or missing ({total_v})")
            else:
                variant_count = int(total_v)

            avg_v = parsed_json.get("average_variants_per_product")
            if avg_v is None or not isinstance(avg_v, (int, float)) or avg_v < 0:
                schema_errors.append(f"average_variants_per_product is invalid or missing ({avg_v})")
            else:
                avg_variants = float(avg_v)

            val_stats = validate_tata_products(products)
        else:
            # Columbia
            total_skus = parsed_json.get("total_skus")
            if total_skus != product_count:
                schema_errors.append(f"total_skus ({total_skus}) does not match products.length ({product_count})")
            val_stats = validate_columbia_products(products)

        if not schema_errors:
            schema_valid = True

    # Step 4: Metrics
    render_api_key = os.getenv("RENDER_API_KEY")
    render_service_id = os.getenv("RENDER_SERVICE_ID")
    render_cpu, render_memory = get_render_metrics(render_api_key, render_service_id)
    runner_cpu, runner_memory = get_runner_resources()

    total_test_duration = time.perf_counter() - overall_start_time

    is_success = (
        http_status == 200
        and json_valid
        and schema_valid
        and product_count >= args.min_products
        and not scrape_error
    )

    if not is_success and not scrape_error:
        if schema_errors:
            scrape_error = "; ".join(schema_errors)
        elif product_count == 0:
            scrape_error = "Scraper returned zero products"
        else:
            scrape_error = "Validation checks failed"

    # Step 5: Terminal Output for this scraper
    if is_success:
        print("Scrape:\n✅ COMPLETED\n")
        print(f"HTTP Status:\n{http_status}\n")
        print(f"Started:\n{started_str}\n")
        print(f"Finished:\n{finished_str}\n")
        print(f"Execution Time:\n{scrape_duration:.1f} seconds\n")
        print(f"Products: {product_count:,}")
        if "tata" in source_name:
            print(f"Variants: {variant_count:,}")
            print(f"Average Variants/Product: {avg_variants:.2f}")
        print(f"Response Size:\n{format_bytes(response_size)}\n")
        print("JSON:\n✅ VALID\n")
        print("Schema:\n✅ VALID\n")
        print(f"Render CPU:\n{render_cpu}\n")
        print(f"Render memory:\n{render_memory}\n")
        print(f"GitHub Actions runner CPU:\n{runner_cpu}\n")
        print(f"GitHub Actions runner memory:\n{runner_memory}\n")
        print("Validation Results:")
        print(f"  Valid products: {val_stats.get('valid_products', 0):,}")
        print(f"  Invalid products: {val_stats.get('invalid_products', 0)}")
        print("\n" + "=" * 40)
        print(f"       RESULT: ✅ PASS ({label})")
        print("=" * 40)
    else:
        print(f"❌ {label} SCRAPER FAILED\n")
        print(f"HTTP Status:\n{http_status}\n")
        print(f"Error:\n{scrape_error}\n")
        print(f"Execution Time:\n{scrape_duration:.1f} seconds\n")
        print(f"Products: {product_count:,}\n")
        print(f"Response Size:\n{format_bytes(response_size)}\n")
        print(f"JSON:\n{'✅ VALID' if json_valid else '❌ INVALID'}\n")
        print(f"Schema:\n{'✅ VALID' if schema_valid else '❌ INVALID'}\n")
        print("\n" + "=" * 40)
        print(f"       RESULT: ❌ FAIL ({label})")
        print("=" * 40)

    # Step 6: Save Result Artifact
    report_data = {
        "status": "passed" if is_success else "failed",
        "source": source_name,
        "service": service_url,
        "endpoint": endpoint,
        "api_online": True,
        "started_at": started_str,
        "finished_at": finished_str,
        "duration_seconds": round(scrape_duration, 2),
        "http_status": http_status,
        "product_count": product_count,
        "variant_count": variant_count,
        "average_variants_per_product": avg_variants,
        "response_size_bytes": response_size,
        "timings": {
            "health_check_seconds": round(health_latency, 3),
            "scrape_seconds": round(scrape_duration, 2),
            "total_test_seconds": round(total_test_duration, 2)
        },
        "resources": {
            "render_cpu": render_cpu,
            "render_memory": render_memory,
            "runner_cpu": runner_cpu,
            "runner_memory": runner_memory
        },
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

    sys.exit(0 if overall_success else 1)


def main():
    parser = argparse.ArgumentParser(description="Test deployed web scrapers on Render")
    parser.add_argument("--service-url", default=os.getenv("RENDER_SERVICE_URL", "https://columbia-4-0.onrender.com"))
    parser.add_argument("--source-name", default=os.getenv("SCRAPER_NAME", "columbia"))
    parser.add_argument("--endpoint", default=None, help="Endpoint path e.g. /scrape or /scrape/tata")
    parser.add_argument("--min-products", type=int, default=int(os.getenv("MIN_PRODUCTS", "1")))
    parser.add_argument("--deploy-wait-seconds", type=int, default=int(os.getenv("RENDER_DEPLOY_WAIT_SECONDS", "600")))
    parser.add_argument("--health-check-interval", type=int, default=int(os.getenv("HEALTH_CHECK_INTERVAL_SECONDS", "15")))
    parser.add_argument("--scrape-timeout-seconds", type=int, default=int(os.getenv("SCRAPE_TIMEOUT_SECONDS", "900")))
    parser.add_argument("--output-file", default=None)
    parser.add_argument("--skip-wait", action="store_true", help="Skip deployment wait if already checked")
    parser.add_argument("--wait-only", action="store_true", help="Only wait for Render deployment to become healthy")
    parser.add_argument("--generate-summary", action="store_true", help="Generate final CI summary from test-results/")
    parser.add_argument("--results-dir", default="test-results")

    args = parser.parse_args()

    if args.generate_summary:
        generate_ci_summary(args.results_dir)
        return

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

    if not args.output_file:
        args.output_file = f"test-results/{args.source_name}-test-result.json"

    success = test_single_scraper(args)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

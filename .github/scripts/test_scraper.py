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

    # Attempt to query Render API service endpoint if credentials provided
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
                        # Verify the response indicates the API is online
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


def validate_products(products: list) -> dict:
    """Validate item-level fields for all returned products."""
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

        # SKU check
        sku = p.get("sku")
        if not sku or not str(sku).strip():
            stats["missing_sku"] += 1
            item_invalid = True

        # Title check
        title = p.get("title")
        if not title or not str(title).strip():
            stats["missing_title"] += 1
            item_invalid = True

        # Price check
        price = p.get("price")
        if price is None:
            stats["invalid_price"] += 1
            item_invalid = True
        else:
            try:
                price_val = float(price)
                if price_val < 0:
                    stats["invalid_price"] += 1
                    item_invalid = True
            except (ValueError, TypeError):
                stats["invalid_price"] += 1
                item_invalid = True

        # URL check
        url = p.get("url")
        if not url or not isinstance(url, str) or not url.startswith("http"):
            stats["invalid_url"] += 1
            item_invalid = True

        if item_invalid:
            stats["invalid_products"] += 1
        else:
            stats["valid_products"] += 1

    return stats


def write_github_step_summary(report: dict, summary_path: str | None):
    """Write formatted markdown summary table to GITHUB_STEP_SUMMARY."""
    if not summary_path:
        return

    source = report.get("source", "Scraper").upper()
    is_pass = report.get("status") == "passed"
    result_icon = "✅ PASS" if is_pass else "❌ FAIL"
    api_icon = "✅ Online" if report.get("api_online") else "❌ Offline"
    json_icon = "✅ Valid" if report.get("validation", {}).get("json_valid") else "❌ Invalid"
    schema_icon = "✅ Valid" if report.get("validation", {}).get("schema_valid") else "❌ Invalid"

    p_count = report.get("product_count", 0)
    p_count_str = f"{p_count:,}" if isinstance(p_count, int) else "0"
    exec_time = f"{report.get('duration_seconds', 0):.2f} sec"
    resp_size = format_bytes(report.get("response_size_bytes", 0))

    md = f"""## 🚀 {source} Scraper Deployment Test

| Metric | Result |
|---|---:|
| **Service** | `{report.get("service")}` |
| **API** | {api_icon} |
| **HTTP Status** | `{report.get("http_status")}` |
| **Execution Time** | {exec_time} |
| **Products / SKUs** | {p_count_str} |
| **Response Size** | {resp_size} |
| **JSON** | {json_icon} |
| **Schema** | {schema_icon} |
| **Valid Products** | {report.get("validation", {}).get("valid_products", 0):,} |
| **Invalid Products** | {report.get("validation", {}).get("invalid_products", 0):,} |
| **Missing SKU** | {report.get("validation", {}).get("missing_sku", 0)} |
| **Missing Title** | {report.get("validation", {}).get("missing_title", 0)} |
| **Invalid Price** | {report.get("validation", {}).get("invalid_price", 0)} |
| **Invalid URL** | {report.get("validation", {}).get("invalid_url", 0)} |
| **Render CPU** | {report.get("resources", {}).get("render_cpu", "unavailable")} |
| **Render Memory** | {report.get("resources", {}).get("render_memory", "unavailable")} |
| **GitHub Actions Runner CPU** | {report.get("resources", {}).get("runner_cpu", "unavailable")} |
| **GitHub Actions Runner Memory** | {report.get("resources", {}).get("runner_memory", "unavailable")} |
| **Final Result** | **{result_icon}** |

### ⏱️ Latency Breakdown
* **Health Check**: `{report.get("timings", {}).get("health_check_seconds", 0):.3f} sec`
* **Scrape Request**: `{report.get("timings", {}).get("scrape_seconds", 0):.2f} sec`
* **Total Workflow Duration**: `{report.get("timings", {}).get("total_test_seconds", 0):.2f} sec`
"""
    if not is_pass:
        md += f"\n> [!CAUTION]\n> **Test Failed**: {report.get('error', 'Unknown failure')}\n"

    try:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n" + md + "\n")
    except Exception as e:
        print(f"Warning: Failed to write to GITHUB_STEP_SUMMARY: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Test deployed web scraper on Render")
    parser.add_argument("--service-url", default=os.getenv("RENDER_SERVICE_URL", "https://columbia-4-0.onrender.com"))
    parser.add_argument("--source-name", default=os.getenv("SCRAPER_NAME", "columbia"))
    parser.add_argument("--min-products", type=int, default=int(os.getenv("MIN_PRODUCTS", "1")))
    parser.add_argument("--deploy-wait-seconds", type=int, default=int(os.getenv("RENDER_DEPLOY_WAIT_SECONDS", "600")))
    parser.add_argument("--health-check-interval", type=int, default=int(os.getenv("HEALTH_CHECK_INTERVAL_SECONDS", "15")))
    parser.add_argument("--scrape-timeout-seconds", type=int, default=int(os.getenv("SCRAPE_TIMEOUT_SECONDS", "900")))
    parser.add_argument("--output-file", default=os.getenv("OUTPUT_FILE", "test-results/columbia-test-result.json"))

    args = parser.parse_args()

    overall_start_time = time.perf_counter()
    service_url = args.service_url.rstrip("/")
    source_name = args.source_name
    min_products = args.min_products
    scrape_endpoint = f"{service_url}/scrape"

    print("=" * 40)
    print(f"       {source_name.upper()} SCRAPER TEST")
    print("=" * 40)
    print(f"Service:\n{service_url}\n")

    # Step 1: Wait for Render Service Availability
    online, health_latency, health_msg = wait_for_service(
        service_url,
        max_wait_seconds=args.deploy_wait_seconds,
        interval_seconds=args.health_check_interval
    )

    if not online:
        total_duration = time.perf_counter() - overall_start_time
        print("\n❌ SERVICE HEALTH CHECK FAILED")
        print(f"Status:\n❌ OFFLINE - {health_msg}")
        print(f"Execution Time:\n{total_duration:.1f} seconds")
        print("\n" + "=" * 40)
        print("       RESULT: ❌ FAIL")
        print("=" * 40)

        failure_report = {
            "status": "failed",
            "source": source_name,
            "service": service_url,
            "api_online": False,
            "error": f"Health check failed: {health_msg}",
            "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "finished_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "duration_seconds": total_duration,
            "http_status": 0,
            "product_count": 0,
            "response_size_bytes": 0,
            "timings": {
                "health_check_seconds": health_latency,
                "scrape_seconds": 0.0,
                "total_test_seconds": total_duration
            },
            "resources": {
                "render_cpu": "unavailable",
                "render_memory": "unavailable",
                "runner_cpu": "unavailable",
                "runner_memory": "unavailable"
            },
            "validation": {
                "json_valid": False,
                "schema_valid": False,
                "valid_products": 0,
                "invalid_products": 0,
                "missing_sku": 0,
                "missing_title": 0,
                "invalid_price": 0,
                "invalid_url": 0
            }
        }
        out_path = Path(args.output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(failure_report, indent=2), encoding="utf-8")
        write_github_step_summary(failure_report, os.getenv("GITHUB_STEP_SUMMARY"))
        sys.exit(1)

    print("Status:\n✅ API ONLINE\n")

    # Step 2: Trigger /scrape endpoint
    print(f"Calling scrape endpoint: {scrape_endpoint}")
    print(f"(Request timeout: {args.scrape_timeout_seconds}s)")

    scrape_start_dt = datetime.now(timezone.utc)
    started_str = scrape_start_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    t_scrape_start = time.perf_counter()

    http_status = 0
    raw_response_bytes = b""
    scrape_error = None

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
    except urllib.error.HTTPError as e:
        http_status = e.code
        raw_response_bytes = e.read()
        scrape_error = f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        scrape_error = f"Network URL error: {e.reason}"
    except TimeoutError:
        scrape_error = f"Request timed out after {args.scrape_timeout_seconds} seconds"
    except Exception as e:
        scrape_error = f"Unexpected error during scrape request: {e}"

    t_scrape_end = time.perf_counter()
    scrape_duration = t_scrape_end - t_scrape_start
    scrape_end_dt = datetime.now(timezone.utc)
    finished_str = scrape_end_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    response_size = len(raw_response_bytes)

    # Step 3: Validate JSON and Schema
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

    if json_valid and isinstance(parsed_json, dict):
        # Validate High-Level Schema
        required_keys = ["schema_version", "source", "scraped_at", "total_skus", "products"]
        for key in required_keys:
            if key not in parsed_json:
                schema_errors.append(f"Missing required key '{key}'")

        products = parsed_json.get("products")
        if not isinstance(products, list):
            schema_errors.append("'products' field is not a list")
            product_count = 0
            val_stats = {"valid_products": 0, "invalid_products": 0, "missing_sku": 0, "missing_title": 0, "invalid_price": 0, "invalid_url": 0}
        else:
            product_count = len(products)
            expected_total = parsed_json.get("total_skus")
            if expected_total != product_count:
                schema_errors.append(f"total_skus ({expected_total}) does not match products.length ({product_count})")

            if product_count < min_products:
                schema_errors.append(f"Product count ({product_count}) is below minimum threshold ({min_products})")

            val_stats = validate_products(products)

        if not schema_errors:
            schema_valid = True
    else:
        product_count = 0
        val_stats = {"valid_products": 0, "invalid_products": 0, "missing_sku": 0, "missing_title": 0, "invalid_price": 0, "invalid_url": 0}

    # Step 4: Resources and Metrics
    render_api_key = os.getenv("RENDER_API_KEY")
    render_service_id = os.getenv("RENDER_SERVICE_ID")
    render_cpu, render_memory = get_render_metrics(render_api_key, render_service_id)
    runner_cpu, runner_memory = get_runner_resources()

    total_test_duration = time.perf_counter() - overall_start_time

    # Determine overall status
    is_success = (
        http_status == 200
        and json_valid
        and schema_valid
        and product_count >= min_products
        and not scrape_error
    )

    if not is_success and not scrape_error:
        if schema_errors:
            scrape_error = "; ".join(schema_errors)
        elif product_count == 0:
            scrape_error = "Scraper returned zero products"
        else:
            scrape_error = "Validation checks failed"

    # Step 5: Terminal Output
    if is_success:
        print("Scrape:\n✅ COMPLETED\n")
        print(f"HTTP Status:\n{http_status}\n")
        print(f"Started:\n{started_str}\n")
        print(f"Finished:\n{finished_str}\n")
        print(f"Execution Time:\n{scrape_duration:.1f} seconds\n")
        print(f"Products / SKUs:\n{product_count:,}\n")
        print(f"Response Size:\n{format_bytes(response_size)}\n")
        print("JSON:\n✅ VALID\n")
        print("Schema:\n✅ VALID\n")
        print(f"Render CPU:\n{render_cpu}\n")
        print(f"Render memory:\n{render_memory}\n")
        print(f"GitHub Actions runner CPU:\n{runner_cpu}\n")
        print(f"GitHub Actions runner memory:\n{runner_memory}\n")
        print("Valid products:\n" + f"{val_stats['valid_products']:,}\n")
        print(f"Invalid products:\n{val_stats['invalid_products']}\n")
        print(f"Missing SKU:\n{val_stats['missing_sku']}\n")
        print(f"Missing title:\n{val_stats['missing_title']}\n")
        print(f"Invalid price:\n{val_stats['invalid_price']}\n")
        print(f"Invalid URL:\n{val_stats['invalid_url']}\n")
        print("Timing Breakdown:")
        print(f"Health check:\n{health_latency:.2f} sec\n")
        print(f"Scrape:\n{scrape_duration:.2f} sec\n")
        print(f"Total test:\n{total_test_duration:.2f} sec\n")
        print("=" * 40)
        print("       RESULT: ✅ PASS")
        print("=" * 40)
    else:
        print("❌ SCRAPER FAILED\n")
        print(f"HTTP Status:\n{http_status}\n")
        print(f"Error:\n{scrape_error}\n")
        print(f"Started:\n{started_str}\n")
        print(f"Finished:\n{finished_str}\n")
        print(f"Execution Time:\n{scrape_duration:.1f} seconds\n")
        print(f"Products / SKUs:\n{product_count:,}\n")
        print(f"Response Size:\n{format_bytes(response_size)}\n")
        print(f"JSON:\n{'✅ VALID' if json_valid else '❌ INVALID'}\n")
        print(f"Schema:\n{'✅ VALID' if schema_valid else '❌ INVALID'}\n")
        print(f"Render CPU:\n{render_cpu}\n")
        print(f"Render memory:\n{render_memory}\n")
        print(f"GitHub Actions runner CPU:\n{runner_cpu}\n")
        print(f"GitHub Actions runner memory:\n{runner_memory}\n")
        print("Timing Breakdown:")
        print(f"Health check:\n{health_latency:.2f} sec\n")
        print(f"Scrape:\n{scrape_duration:.2f} sec\n")
        print(f"Total test:\n{total_test_duration:.2f} sec\n")
        print("=" * 40)
        print("       RESULT: ❌ FAIL")
        print("=" * 40)

    # Step 6: Save Result Artifact
    report_data = {
        "status": "passed" if is_success else "failed",
        "source": source_name,
        "service": service_url,
        "api_online": True,
        "started_at": started_str,
        "finished_at": finished_str,
        "duration_seconds": round(scrape_duration, 2),
        "http_status": http_status,
        "product_count": product_count,
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
            "valid_products": val_stats["valid_products"],
            "invalid_products": val_stats["invalid_products"],
            "missing_sku": val_stats["missing_sku"],
            "missing_title": val_stats["missing_title"],
            "invalid_price": val_stats["invalid_price"],
            "invalid_url": val_stats["invalid_url"]
        }
    }

    if not is_success:
        report_data["error"] = scrape_error

    out_file = Path(args.output_file)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
    print(f"\nReport artifact saved to: {out_file.resolve()}")

    # Step 7: Write GitHub Step Summary
    write_github_step_summary(report_data, os.getenv("GITHUB_STEP_SUMMARY"))

    # Exit code
    sys.exit(0 if is_success else 1)


if __name__ == "__main__":
    main()

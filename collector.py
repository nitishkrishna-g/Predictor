import os
import time
import json
import sqlite3
import argparse
from datetime import datetime, timedelta
import traceback

from extract_services import run_discovery
from multi_service_runner import scrape_seats_parallel
from import_multi_results import import_results
from verify_history import verify_database

DB = "abhibus.db"
LOG_FILE = "collector_log.txt"
CSV_LOG = "collector.log"

ROUTES = [
    {
        "name": "Coimbatore-Bangalore",
        "from_city": "Coimbatore",
        "from_id": "794",
        "to_city": "Bangalore",
        "to_id": "7"
    },
    {
        "name": "Bangalore-Coimbatore",
        "from_city": "Bangalore",
        "from_id": "7",
        "to_city": "Coimbatore",
        "to_id": "794"
    }
]

def append_csv_log(stats):
    # Create header if file doesn't exist
    if not os.path.exists(CSV_LOG):
        with open(CSV_LOG, "w", encoding="utf-8") as f:
            f.write("timestamp,route,journey_date,discovered,scraped,failed,scrapes_inserted,seats_inserted,cleanup_deleted,cycle_duration_sec,next_cycle_time\n")
            
    with open(CSV_LOG, "a", encoding="utf-8") as f:
        f.write(f"{stats['timestamp']},{stats['route']},{stats['journey_date']},{stats['discovered']},{stats['scraped']},{stats['failed']},{stats['scrapes_inserted']},{stats['seats_inserted']},{stats['cleanup_deleted']},{stats['duration']:.1f},{stats['next_cycle']}\n")

def cleanup_old_data():
    conn = sqlite3.connect(DB)
    deleted = 0
    try:
        print("Running 90-day cleanup based on journey_date...")
        # Get IDs of old services
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS old_services AS SELECT id FROM services WHERE journey_date < date('now', '-90 days')")
        
        seats_del = conn.execute("""
            DELETE FROM seats
            WHERE scrape_id IN (
                SELECT id FROM scrapes
                WHERE service_id IN old_services
            )
        """).rowcount
        
        scrapes_del = conn.execute("""
            DELETE FROM scrapes
            WHERE service_id IN old_services
        """).rowcount
        
        services_del = conn.execute("""
            DELETE FROM services
            WHERE id IN old_services
        """).rowcount
        
        conn.execute("DROP TABLE IF EXISTS old_services")
        
        conn.commit()
        deleted = seats_del + scrapes_del + services_del
        print(f"Cleanup successful. Deleted {deleted} rows (Seats: {seats_del}, Scrapes: {scrapes_del}, Services: {services_del}).")
    except Exception as e:
        print(f"Cleanup error: {e}")
        conn.rollback()
    finally:
        conn.close()
    return deleted

def run_cycle(next_cycle_str="Unknown", discovery_only=False, smoke_test=False, benchmark=False, num_workers=5, request_timeout=15, retries=2):
    start_time = time.time()
    now_ts = datetime.now()
    cycle_timestamp = now_ts.strftime('%d %b %Y %H:%M')
    
    print("\n" + "="*60)
    print(f"COLLECTION CYCLE")
    if smoke_test:
        print(f"*** SMOKE TEST MODE ***")
    if discovery_only:
        print(f"*** DISCOVERY ONLY MODE ***")
    if benchmark:
        print(f"*** BENCHMARK MODE (Workers: {num_workers}) ***")
    print(f"{cycle_timestamp}")
    print("="*60)
    
    # 8 days window (today to today + 7), but smoke test only uses today
    days_to_check = 1 if smoke_test else 8
    target_dates = [(now_ts.date() + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(days_to_check)]
    
    total_discovered = 0
    total_scraped = 0
    total_seats = 0
    
    cycle_matrix = []
    queued_services = []
    date_stats_map = {}
    
    from playwright.sync_api import sync_playwright
    
    print("\n--- PHASE 1: DISCOVERY ---")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1280, "height": 720})

        for route in ROUTES:
            r_name = route["name"]
            print(f"\n{r_name}")
            
            for date_str in target_dates:
                key = (r_name, date_str)
                date_stats_map[key] = {}
                try:
                    import os
                    output_dir = os.path.join("raw", date_str, r_name)
                    os.makedirs(output_dir, exist_ok=True)
                    
                    disc_res = run_discovery(page, route["from_city"], route["from_id"], route["to_city"], route["to_id"], date_str, output_dir=output_dir)
                    disc_file = disc_res.get("output_file")
                    disc_status = disc_res.get("status")
                    
                    if disc_status == "DISCOVERY_SUCCESS" and disc_file:
                        with open(disc_file, "r", encoding="utf-8") as f:
                            disc_data = json.load(f)
                        
                        for service in disc_data.get("services", []):
                            # Append extra metadata needed for queueing
                            service["_route_name"] = r_name
                            service["_date_str"] = date_str
                            service["_output_dir"] = output_dir
                            queued_services.append(service)
                            
                            op = service.get("travelerAgentName", "Unknown").lower()
                            if op not in date_stats_map[key]:
                                date_stats_map[key][op] = {"discovered": 0, "scraped": 0, "failed": 0, "seats": 0, "available_seats": 0}
                            date_stats_map[key][op]["discovered"] += 1
                            total_discovered += 1
                    else:
                        print(f"Discovery status: {disc_status}")
                    
                    # Sleep between date queries to prevent anti-bot blocking
                    time.sleep(5)
                except Exception as e:
                    print(f"Error on {r_name} for {date_str}: {e}")
        
        browser.close()
            
    print("\n--- PHASE 2: PARALLEL SEAT SCRAPING ---")
    results = []
    
    if os.path.exists("failed_queue.json"):
        try:
            with open("failed_queue.json", "r") as f:
                failed_queue = json.load(f)
            # Add to front of queued_services (if journey date is today or later to prevent stale infinite loops)
            valid_failed = []
            today_str = now_ts.strftime('%Y-%m-%d')
            for s in failed_queue:
                if s.get("_date_str") and s["_date_str"] >= today_str:
                    # check if it's already in queued_services to avoid duplicates if discovery found it again
                    if not any(q.get("serviceKey") == s.get("serviceKey") for q in queued_services):
                        valid_failed.append(s)
            
            if valid_failed:
                print(f"Loaded {len(valid_failed)} failed services from previous cycle to prioritize.")
                queued_services = valid_failed + queued_services
        except Exception as e:
            print(f"Error loading failed_queue.json: {e}")
            
    if not discovery_only and queued_services:
        results = scrape_seats_parallel(queued_services, num_workers=num_workers, output_dir="raw", request_timeout=request_timeout, max_retries=retries)
        
    print("\n--- PHASE 3: DATABASE INSERTION ---")
    
    successful_results = []
    failed_results = []
    
    for res in results:
        if res.get("status") == "SUCCESS":
            successful_results.append(res)
        else:
            failed_results.append(res)
            
    for res in successful_results:
        r_name = res.get("route")
        date_str = res.get("journeyDate")
        op = res.get("operator", "Unknown").lower()
        key = (r_name, date_str)
        
        # We need to map back to our stats structure
        # If route name in AbhiBus differs from our dict, we might have a mismatch,
        # but the queued_services metadata has the exact path. Wait, the result comes from `scrape_service`, 
        # which pulls from `captured.get("Route")`. Let's fallback to search by operator.
        # Actually it's safer to update stats based on what was inserted.
        
        # We'll write to a unified output file just for logging/history, though import_results expects a file
        # To maintain serialization, we create temporary files per result or one big file.
        # import_multi_results expects a JSON file with {"results": [...]}.
        pass
        
    # Serialize SQLite writes safely
    if successful_results:
        scrape_out = os.path.join("raw", f"cycle_scrape_results_{now_ts.strftime('%Y%m%d_%H%M%S')}.json")
        try:
            with open(scrape_out, "w", encoding="utf-8") as f:
                json.dump({"results": successful_results}, f, ensure_ascii=False, indent=2)
            
            # Update stats
            for service_res in successful_results:
                journey_date = service_res.get("originDateTime", "").split(" ")[0]
                if not journey_date: journey_date = service_res.get("journeyDate")
                
                op = service_res.get("operator", "Unknown").lower()
                route_str = service_res.get("route", "").lower()
                total_scraped += 1
                total_seats += service_res.get("totalSeats", 0)
                
                for k, stats_dict in date_stats_map.items():
                    r_name_lower = k[0].lower()
                    if k[1] == journey_date and op in stats_dict and (r_name_lower in route_str or route_str in r_name_lower or r_name_lower.replace("-", "") in route_str.replace("-", "")):
                        stats_dict[op]["scraped"] += 1
                        stats_dict[op]["seats"] += service_res.get("totalSeats", 0)
                        stats_dict[op]["available_seats"] += service_res.get("availableSeats", 0)
                        break

            print("Executing serialized SQLite insertion...")
            import_results(scrape_out, DB)
        except Exception as ex_import:
            print(f"Import error: {ex_import}")
            
    for key, stats_dict in date_stats_map.items():
        r_name, date_str = key
        fresh_d, fresh_s, fresh_f = 0, 0, 0
        zing_d, zing_s, zing_f = 0, 0, 0
        zingplus_d, zingplus_s, zingplus_f = 0, 0, 0
        neogo_d, neogo_s, neogo_f = 0, 0, 0
        
        for op, stats in stats_dict.items():
            stats["failed"] = stats["discovered"] - stats["scraped"]
            if op == "freshbus":
                fresh_d, fresh_s, fresh_f = stats["discovered"], stats["scraped"], stats["failed"]
            elif op == "zingbus":
                zing_d, zing_s, zing_f = stats["discovered"], stats["scraped"], stats["failed"]
            elif op == "zingbus plus":
                zingplus_d, zingplus_s, zingplus_f = stats["discovered"], stats["scraped"], stats["failed"]
            elif op == "neogo":
                neogo_d, neogo_s, neogo_f = stats["discovered"], stats["scraped"], stats["failed"]
                
        tot_d = fresh_d + zing_d + zingplus_d + neogo_d
        tot_s = fresh_s + zing_s + zingplus_s + neogo_s
        tot_f = fresh_f + zing_f + zingplus_f + neogo_f
        
        cycle_matrix.append({
            "route": r_name,
            "date": date_str,
            "freshbus": f"{fresh_d}/{fresh_s}/{fresh_f}",
            "zingbus": f"{zing_d}/{zing_s}/{zing_f}",
            "zingbus plus": f"{zingplus_d}/{zingplus_s}/{zingplus_f}",
            "neogo": f"{neogo_d}/{neogo_s}/{neogo_f}",
            "total": f"{tot_d}/{tot_s}/{tot_f}"
        })

    total_failed = len(failed_results) + (total_discovered - len(results))
    duration = time.time() - start_time
    
    print("\n" + "="*100)
    print("COLLECTION COMPLETENESS MATRIX (Discovered / Scraped / Failed)")
    print(f"{'Route':<22} | {'Date':<10} | {'Freshbus':<10} | {'Zingbus':<10} | {'Zingbus +':<10} | {'Neogo':<10} | {'Total':<10}")
    print("-" * 100)
    for row in cycle_matrix:
        print(f"{row['route']:<22} | {row['date']:<10} | {row['freshbus']:<10} | {row['zingbus']:<10} | {row['zingbus plus']:<10} | {row['neogo']:<10} | {row['total']:<10}")
    print("="*100 + "\n")
    
    # Save new failures to queue
    new_failures = []
    for fail in failed_results:
        if "_raw_service" in fail:
            new_failures.append(fail["_raw_service"])
    try:
        with open("failed_queue.json", "w") as f:
            json.dump(new_failures, f)
    except Exception as e:
        print(f"Error saving failed_queue.json: {e}")

    if failed_results:
        print("\n" + "="*85)
        print("FAILURE SUMMARY")
        print("="*85)
        for fail in failed_results:
            op = fail.get('operator') or "Unknown"
            print(f"[{fail.get('status', 'FAILED')}] {fail.get('route')} | {fail.get('journeyDate')} | {op.title()} | Key: {fail.get('serviceKey')}")
            print(f"  Reason: {fail.get('reason')} (Retries: {fail.get('retryCount', 0)})")
            print("-" * 85)
            
    succ_time = sum(res.get("processingDuration", 0) for res in successful_results)
    fail_time = sum(res.get("processingDuration", 0) for res in failed_results)

    print("\n" + "="*60)
    print(f"SERVICES DISCOVERED : {total_discovered}")
    print(f"SERVICES ATTEMPTED  : {len(results)}")
    print(f"SERVICES COLLECTED  : {total_scraped}")
    print(f"SERVICES FAILED     : {total_failed}")
    print(f"SEAT RECORDS        : {total_seats}")
    print(f"TOTAL DURATION      : {duration:.1f} sec")
    print(f"SUCCESS TIME SPENT  : {succ_time:.1f} sec (worker aggregate)")
    print(f"FAILED TIME SPENT   : {fail_time:.1f} sec (worker aggregate)")
    
    if total_scraped > 0:
        avg_duration = duration / total_scraped
        print(f"Avg Service Duration: {avg_duration:.1f} sec/service")
        spm = (total_scraped / duration) * 60
        print(f"Services/minute     : {spm:.1f}")
    
    print(f"\nNext collection: {next_cycle_str}")
    print("="*60 + "\n")
    
    cleanup_old_data()
    return duration
    
def get_sleep_seconds_to_next_boundary(minutes=10):
    now = datetime.now()
    next_boundary = now + timedelta(minutes=minutes - (now.minute % minutes))
    next_boundary = next_boundary.replace(second=0, microsecond=0)
    
    if (next_boundary - now).total_seconds() < 5:
        next_boundary += timedelta(minutes=minutes)
        
    return (next_boundary - now).total_seconds(), next_boundary.strftime('%H:%M:%S')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--smoke-test", action="store_true", help="Run 1 date per route and exit")
    parser.add_argument("--discovery-only", action="store_true", help="Run discovery only (skip scraping) and exit")
    parser.add_argument("--benchmark", action="store_true", help="Run one full cycle in benchmark mode")
    parser.add_argument("--interval", type=int, default=10, help="Interval in minutes (default 10)")
    parser.add_argument("--workers", type=int, default=5, help="Number of concurrent workers (default 5)")
    parser.add_argument("--request-timeout", type=int, default=15, help="Seconds to wait for API layout response (default 15)")
    parser.add_argument("--retries", type=int, default=2, help="Number of times to retry a failed service (default 2)")
    args = parser.parse_args()

    if args.run_once or args.smoke_test or args.discovery_only or args.benchmark:
        # Dummy next cycle
        run_cycle("N/A", discovery_only=args.discovery_only, smoke_test=args.smoke_test, benchmark=args.benchmark, num_workers=args.workers, request_timeout=args.request_timeout, retries=args.retries)
        if args.smoke_test:
            print("\nRunning Verification:")
            import verify_history
            verify_history.verify_database("abhibus.db")
        return

    interval = args.interval
    print(f"Starting Infinite Collector Loop ({interval}-minute boundaries)...")
    while True:
        # Calculate next boundary before cycle so we can log it
        _, next_run_str = get_sleep_seconds_to_next_boundary(interval)
        
        try:
            duration = run_cycle(next_run_str, num_workers=args.workers, request_timeout=args.request_timeout, retries=args.retries)
            if duration > interval * 60:
                print(f"\n[WARNING] COLLECTION_OVERRUN: Cycle took {duration:.1f}s, exceeding {interval}-minute interval.")
        except Exception as e:
            print(f"CRITICAL ERROR IN CYCLE: {e}")
            traceback.print_exc()
            
        sleep_sec, next_run_str = get_sleep_seconds_to_next_boundary(interval)
        print(f"\nCycle complete. Sleeping for {sleep_sec:.1f}s until {next_run_str}")
        time.sleep(sleep_sec)

if __name__ == "__main__":
    main()

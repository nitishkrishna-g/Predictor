import os
import time
import json
import sqlite3
import argparse
from datetime import datetime, timedelta
import traceback

from extract_services import run_discovery
from multi_service_runner import scrape_seats
from import_multi_results import import_results
from verify_history import verify_database

DB = "abhibus.db"
LOG_FILE = "collector_log.txt"
CSV_LOG = "collector.log"

ROUTES = [
    {
        "name": "Coimbatore -> Bengaluru",
        "from_city": "Coimbatore",
        "from_id": "794",
        "to_city": "Bengaluru",
        "to_id": "7"
    },
    {
        "name": "Bengaluru -> Coimbatore",
        "from_city": "Bengaluru",
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
        print("Running 90-day cleanup...")
        seats_del = conn.execute("""
            DELETE FROM seats
            WHERE scrape_id IN (
                SELECT id FROM scrapes
                WHERE scraped_at < datetime('now', '-90 days')
            )
        """).rowcount
        
        scrapes_del = conn.execute("""
            DELETE FROM scrapes
            WHERE scraped_at < datetime('now', '-90 days')
        """).rowcount
        
        conn.commit()
        deleted = seats_del + scrapes_del
        print(f"Cleanup successful. Deleted {deleted} rows.")
    except Exception as e:
        print(f"Cleanup error: {e}")
        conn.rollback()
    finally:
        conn.close()
    return deleted

def run_cycle(next_cycle_str="Unknown"):
    start_time = time.time()
    now_ts = datetime.now()
    cycle_timestamp = now_ts.strftime('%d %b %Y %H:%M')
    
    print("\n" + "="*60)
    print(f"COLLECTION CYCLE")
    print(f"{cycle_timestamp}")
    print("="*60)
    
    # 8 days window (T-0 to T-7)
    target_dates = [(now_ts + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(8)]
    
    total_discovered = 0
    total_scraped = 0
    total_seats = 0
    
    route_stats = {}
    
    for route in ROUTES:
        r_name = route["name"]
        print(f"\n{r_name}")
        route_stats[r_name] = {}
        
        for date_str in target_dates:
            try:
                run_discovery(route["from_city"], route["from_id"], route["to_city"], route["to_id"], date_str)
                success = scrape_seats("discovered_services.json", "seat_scrape_results.json")
                if success:
                    with open("discovered_services.json", "r", encoding="utf-8") as f:
                        disc_data = json.load(f)
                    
                    for service in disc_data.get("services", []):
                        op = service.get("travelerAgentName", "Unknown").lower()
                        if op not in route_stats[r_name]:
                            route_stats[r_name][op] = {"discovered": 0, "scraped": 0}
                        route_stats[r_name][op]["discovered"] += 1
                        total_discovered += 1
                        
                    with open("seat_scrape_results.json", "r", encoding="utf-8") as f:
                        res_data = json.load(f)
                        
                    for service_res in res_data.get("results", []):
                        op = service_res.get("operator", "Unknown").lower()
                        if op in route_stats[r_name]:
                            route_stats[r_name][op]["scraped"] += 1
                        total_scraped += 1
                        total_seats += len(service_res.get("seats", []))
                    
                    import_results("seat_scrape_results.json", DB)
                
                # Sleep between date queries to prevent anti-bot blocking
                time.sleep(5)
            except Exception as e:
                print(f"Error on {r_name} for {date_str}: {e}")
                
        for op, counts in route_stats[r_name].items():
            print(f"{op.title():<15} {counts['scraped']}/{counts['discovered']}")
            
    total_failed = total_discovered - total_scraped
    duration = time.time() - start_time
    
    print("\n" + "="*60)
    print(f"Services discovered : {total_discovered}")
    print(f"Services collected  : {total_scraped}")
    print(f"Services failed     : {total_failed}")
    print(f"Seat records        : {total_seats}")
    print(f"Duration            : {duration:.1f} sec")
    print(f"\nNext collection: {next_cycle_str}")
    print("="*60 + "\n")
    
    cleanup_old_data()
    
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
    args = parser.parse_args()

    if args.run_once:
        # Dummy next cycle for run-once
        run_cycle("N/A")
        return

    print("Starting Infinite Collector Loop (10-minute boundaries)...")
    while True:
        # Calculate next boundary before cycle so we can log it
        _, next_run_str = get_sleep_seconds_to_next_boundary(10)
        
        try:
            run_cycle(next_run_str)
        except Exception as e:
            print(f"CRITICAL ERROR IN CYCLE: {e}")
            traceback.print_exc()
            
        sleep_sec, next_run_str = get_sleep_seconds_to_next_boundary(10)
        print(f"\nCycle complete. Sleeping for {sleep_sec:.1f}s until {next_run_str}")
        time.sleep(sleep_sec)

if __name__ == "__main__":
    main()

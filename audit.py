import sqlite3
import json
import os
from datetime import datetime
from collections import defaultdict

print("=== PRODUCTION VERIFICATION AUDIT ===")

conn = sqlite3.connect('abhibus.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 1. Latest 20 scrapes
print("\n1. LATEST 20 SCRAPES:")
cur.execute("""
    SELECT 
        sc.scraped_at, s.service_key, s.journey_date, s.operator, s.route, sc.total_seats
    FROM scrapes sc
    JOIN services s ON sc.service_id = s.id
    ORDER BY sc.scraped_at DESC
    LIMIT 20
""")
for row in cur.fetchall():
    print(f"{row['scraped_at']} | Key: {row['service_key']} | Date: {row['journey_date']} | Op: {row['operator']} | Route: {row['route']} | Seats: {row['total_seats']}")

# 2 & 3. Cycle Cadence
print("\n2 & 3. CYCLE CADENCE:")
# Group scrapes by hour/minute string to identify cycles (since scraped_at includes seconds and microseconds, it might slightly differ if inserted in a loop, wait, let's check distinct scraped_at)
cur.execute("SELECT DISTINCT substr(scraped_at, 1, 16) as cycle_minute FROM scrapes ORDER BY cycle_minute DESC LIMIT 10")
cycles = [row['cycle_minute'] for row in cur.fetchall()]
print(f"Recent cycles (minute granularity): {cycles}")
if len(cycles) > 1:
    print("Time differences between cycles:")
    for i in range(len(cycles)-1):
        t1 = datetime.strptime(cycles[i], "%Y-%m-%dT%H:%M")
        t2 = datetime.strptime(cycles[i+1], "%Y-%m-%dT%H:%M")
        diff = (t1 - t2).total_seconds() / 60.0
        print(f"  {cycles[i]} - {cycles[i+1]} = {diff:.1f} minutes")

# 4. Latest Cycle Stats
if not cycles:
    print("No cycles found!")
else:
    latest_cycle = cycles[0]
    print(f"\n4. LATEST CYCLE STATS (Cycle starting around {latest_cycle}):")
    cur.execute("""
        SELECT 
            sc.id, s.operator, s.route, s.journey_date, sc.total_seats
        FROM scrapes sc
        JOIN services s ON sc.service_id = s.id
        WHERE substr(sc.scraped_at, 1, 16) = ?
    """, (latest_cycle,))
    cycle_scrapes = cur.fetchall()
    
    total_scrapes = len(cycle_scrapes)
    total_seats = sum(r['total_seats'] for r in cycle_scrapes)
    
    ops = defaultdict(int)
    routes = defaultdict(int)
    dates = defaultdict(int)
    
    for r in cycle_scrapes:
        ops[r['operator'].lower()] += 1
        routes[r['route'].lower()] += 1
        dates[r['journey_date']] += 1
        
    print(f"Total successful scrapes: {total_scrapes}")
    print(f"Total seats imported: {total_seats}")
    print("Operators:")
    for k, v in ops.items(): print(f"  {k}: {v}")
    print("Routes:")
    for k, v in routes.items(): print(f"  {k}: {v}")
    print("Dates:")
    for k, v in sorted(dates.items()): print(f"  {k}: {v}")
    
# 5. Check every successful scrape in the latest cycle
print("\n5. SUCCESSFUL SCRAPE INTEGRITY (Latest Cycle):")
cur.execute("""
    SELECT sc.id, sc.total_seats, sc.available_seats
    FROM scrapes sc
    WHERE substr(sc.scraped_at, 1, 16) = ?
""", (latest_cycle,))
bad_scrapes = 0
for row in cur.fetchall():
    if row['total_seats'] <= 0:
        print(f"ERROR: Scrape {row['id']} has zero seats")
        bad_scrapes += 1
    # Check if there are seats connected to this scrape
    cur.execute("SELECT COUNT(*) as c FROM seats WHERE scrape_id = ?", (row['id'],))
    seat_count = cur.fetchone()['c']
    if seat_count != row['total_seats']:
        print(f"ERROR: Scrape {row['id']} seat count mismatch: scrape says {row['total_seats']}, seats table has {seat_count}")
        bad_scrapes += 1
if bad_scrapes == 0:
    print("All latest cycle scrapes have valid seat mappings and counts.")

# 6. Duplicates
print("\n6. DUPLICATE SNAPSHOTS:")
cur.execute("""
    SELECT service_id, substr(scraped_at, 1, 16) as cycle, COUNT(*) as c 
    FROM scrapes 
    GROUP BY service_id, cycle 
    HAVING c > 1
""")
dupes = cur.fetchall()
if dupes:
    print(f"FOUND {len(dupes)} DUPLICATES!")
else:
    print("No duplicates found for same service within the same minute.")

# 7. Orphans
print("\n7. ORPHANS:")
cur.execute("SELECT COUNT(*) as c FROM scrapes WHERE service_id NOT IN (SELECT id FROM services)")
sc_orphans = cur.fetchone()['c']
cur.execute("SELECT COUNT(*) as c FROM seats WHERE scrape_id NOT IN (SELECT id FROM scrapes)")
se_orphans = cur.fetchone()['c']
print(f"Orphan scrapes: {sc_orphans}")
print(f"Orphan seats: {se_orphans}")

# 8. failed_queue.json
print("\n8. FAILED QUEUE:")
if os.path.exists('failed_queue.json'):
    try:
        with open('failed_queue.json', 'r') as f:
            fq = json.load(f)
        print(f"failed_queue.json exists and contains {len(fq)} elements.")
        if len(fq) > 0:
            print("Contents:", json.dumps(fq, indent=2))
    except Exception as e:
        print("Error reading failed_queue.json:", e)
else:
    print("failed_queue.json does not exist.")

print("\n=== END OF AUDIT ===")
conn.close()

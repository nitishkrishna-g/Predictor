import sqlite3

conn = sqlite3.connect('abhibus.db')

# Check the exact scrapes for CBE->BLR 18th 
print("=== SCRAPES FOR CBE->BLR 18 AUG ===")
rows = conn.execute("""
    SELECT sv.id, sv.operator, sv.departure, sv.service_key,
           sc.id as scrape_id, sc.cheapest_seater, sc.cheapest_sleeper, 
           sc.available_seats, sc.scraped_at
    FROM services sv
    JOIN scrapes sc ON sc.service_id = sv.id
    WHERE sv.journey_date = '2026-08-18'
    AND sv.route = 'Coimbatore-Bangalore'
    ORDER BY sv.departure, sc.scraped_at DESC
""").fetchall()

seen = set()
for r in rows:
    svc_key = (r[0], r[1])
    is_latest = svc_key not in seen
    seen.add(svc_key)
    flag = " <-- LATEST" if is_latest else ""
    print(f"  {r[2].split()[1] if ' ' in str(r[2]) else r[2]} | {r[1][:15]:15} | scrape_id={r[4]} | seater={r[5]} | scraped={str(r[8])[:16]}{flag}")

print()
print("=== FIRST 5 SEATS IN SCRAPE FOR SERVICE 189 ===")
scrape = conn.execute("SELECT id FROM scrapes WHERE service_id = 189 ORDER BY scraped_at DESC LIMIT 1").fetchone()
if scrape:
    seats = conn.execute("SELECT seat_number, seat_type, available, discounted_fare FROM seats WHERE scrape_id = ? LIMIT 10", (scrape[0],)).fetchall()
    for s in seats:
        print(f"  seat={s[0]} type={s[1]} avail={s[2]} fare={s[3]}")
conn.close()

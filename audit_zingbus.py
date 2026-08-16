import glob, json, os, sqlite3
from collections import defaultdict
from datetime import datetime

print("=== ZINGBUS DISCOVERY AUDIT ===")

today_date = "2026-08-17" 
raw_files = glob.glob(f"raw/2026-08-*/Bangalore-Coimbatore/discovery_raw.json") + \
            glob.glob(f"raw/2026-08-*/Coimbatore-Bangalore/discovery_raw.json")

date_routes_checked = set()
zing_mentions = defaultdict(int)
target_discovered = []

def get_op_key(name):
    n = name.lower().replace(" ", "")
    if "freshbus" in n: return "Freshbus"
    if n == "zingbus": return "Zingbus"
    if "zingbus" in n: return "Zingbus Plus" # everything else zingbus is plus
    if "neogo" in n or "nuego" in n: return "Neogo"
    return None

for rf in raw_files:
    parts = rf.split(os.sep)
    if len(parts) < 3: parts = rf.split('/')
    date_str, route = parts[-3], parts[-2]
    
    if date_str < today_date or date_str > "2026-08-24":
        continue
        
    date_routes_checked.add((date_str, route))
    with open(rf, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    services = data.get("services", [])
    for s in services:
        op_name = s.get("travelerAgentName", "")
        n = op_name.lower()
        if "zing" in n:
            zing_mentions[n] += 1
            
        op_key = get_op_key(op_name)
        if op_key:
            target_discovered.append({
                "key": s.get("serviceKey"),
                "op": op_key,
                "date": date_str,
                "route": route
            })

print("\n--- RAW DISCOVERY EVIDENCE (T0 to T+7 window) ---")
print(f"Total Date/Route combinations checked: {len(date_routes_checked)}")
print(f"Any operator containing 'zing':")
for k, v in zing_mentions.items():
    print(f"  '{k}': {v} services found in raw JSON")

if "zingbus" not in zing_mentions:
    print("CONCLUSION: 'zingbus' (exact match) is COMPLETELY ABSENT from the raw AbhiBus API response.")
    print("It is NOT being filtered by our code; it simply does not exist in the source JSON for these routes/dates.")

print("\n--- MATRIX: DISCOVERED TARGET SERVICES ---")
matrix = defaultdict(lambda: defaultdict(int))
for s in target_discovered:
    matrix[(s['date'], s['route'])][s['op']] += 1

print(f"{'Date':<12} | {'Direction':<22} | {'Freshbus':<8} | {'Zingbus':<7} | {'Zingbus +':<9} | {'Neogo':<5} | {'Total':<5}")
print("-" * 80)
for (d, r) in sorted(matrix.keys()):
    counts = matrix[(d, r)]
    tot = sum(counts.values())
    print(f"{d:<12} | {r:<22} | {counts['Freshbus']:<8} | {counts['Zingbus']:<7} | {counts['Zingbus Plus']:<9} | {counts['Neogo']:<5} | {tot:<5}")

total_discovered = len(target_discovered)

print("\n--- DATABASE VERIFICATION ---")
conn = sqlite3.connect('abhibus.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute('SELECT MAX(scraped_at) as m FROM scrapes')
max_time = cur.fetchone()['m']

cur.execute('''
    SELECT s.service_key, s.operator, s.route, s.journey_date
    FROM scrapes sc
    JOIN services s ON sc.service_id = s.id
    WHERE datetime(sc.scraped_at) >= datetime(?, "-15 minutes")
''')
db_scrapes = cur.fetchall()

db_keys = set([r['service_key'] for r in db_scrapes])
disc_keys = set([s['key'] for s in target_discovered])

print(f"Target Services Discovered in JSON : {total_discovered}")
print(f"Successful Scrapes in DB latest cycle: {len(db_scrapes)}")

if total_discovered == len(db_scrapes) and db_keys == disc_keys:
    print("VERIFIED: discovered target services = successful services.")
    print("VERIFIED: Every discovered service has exactly one successful scrape. No silent drops.")
else:
    print("MISMATCH DETECTED!")
    
ops = defaultdict(int)
for r in db_scrapes:
    ops[get_op_key(r['operator']) or r['operator']] += 1

print("\nLatest Cycle DB Operator breakdown:")
print(f"  Freshbus: {ops.get('Freshbus', 0)}")
print(f"  Zingbus: {ops.get('Zingbus', 0)}")
print(f"  Zingbus Plus: {ops.get('Zingbus Plus', 0)}")
print(f"  Neogo: {ops.get('Neogo', 0)}")

cur.execute("SELECT COUNT(*) as c FROM services WHERE LOWER(operator) = 'zingbus'")
hist_zing = cur.fetchone()['c']
if hist_zing > 0:
    print(f"\nHistorical Zingbus records found: {hist_zing}")
else:
    print("\nNo historical records of 'Zingbus' (exact match) found in the database either.")

conn.close()

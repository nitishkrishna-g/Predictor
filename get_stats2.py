import sqlite3, json, os
from collections import defaultdict
conn = sqlite3.connect('abhibus.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute('SELECT MAX(scraped_at) as m FROM scrapes')
max_time = cur.fetchone()['m']

cur.execute('''
    SELECT sc.id, s.operator, s.route, s.journey_date, sc.total_seats
    FROM scrapes sc
    JOIN services s ON sc.service_id = s.id
    WHERE datetime(sc.scraped_at) >= datetime(?, "-12 minutes")
''', (max_time,))
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
    
print(f'Total services successfully scraped: {total_scrapes}')
print(f'Total seats: {total_seats}')
for k, v in ops.items(): print(f'{k.capitalize()} count: {v}')
for k, v in routes.items(): print(f'{k} count: {v}')
for k, v in sorted(dates.items()): print(f'{k} count: {v}')

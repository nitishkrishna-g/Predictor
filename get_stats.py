import glob, json, os, sqlite3

print('Command: python collector.py --interval 10 --workers 5 --request-timeout 15 --retries 2')
print('Database: abhibus.db')

files = glob.glob('raw/cycle_scrape_results_*.json')
latest = max(files, key=os.path.getctime)
with open(latest, 'r', encoding='utf-8') as f:
    data = json.load(f)
results = data['results']

print(f'Services collected: {len(results)}')
print(f'Seats imported: {sum(r.get("totalSeats", 0) for r in results)}')

if os.path.exists('failed_queue.json'):
    with open('failed_queue.json', 'r') as f:
        fq = json.load(f)
    print(f'Failed queue size: {len(fq)}')
else:
    print('Failed queue size: 0')

import json, glob, os
files = glob.glob('raw/cycle_scrape_results_*.json')
latest = max(files, key=os.path.getctime)
with open(latest, 'r', encoding='utf-8') as f:
    data = json.load(f)
results = data['results']
succ_time = sum(r.get('processingDuration', 0) for r in results if r.get('status') == 'SUCCESS')
fail_time = sum(r.get('processingDuration', 0) for r in results if r.get('status') != 'SUCCESS')
print(f'Successful services: {len([r for r in results if r.get("status") == "SUCCESS"])}')
print(f'Failed services: {len([r for r in results if r.get("status") != "SUCCESS"])}')
print(f'SUCCESS TIME SPENT: {succ_time:.1f} sec')
print(f'FAILED TIME SPENT: {fail_time:.1f} sec')

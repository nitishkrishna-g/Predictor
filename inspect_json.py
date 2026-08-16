import glob, json
files = glob.glob('raw/seat_*.json')
if files:
    f = files[0]
    print(f'Checking {f}')
    with open(f, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
    print('Top-level keys:', list(data.keys()))
    if 'noOfSeats' in data: print('noOfSeats:', data['noOfSeats'])
    if 'TotalSeats' in data: print('TotalSeats:', data['TotalSeats'])
    if 'totalSeats' in data: print('totalSeats:', data['totalSeats'])
    
    tsl = data.get('TotalSeatList')
    print('TotalSeatList type:', type(tsl))
    if isinstance(tsl, dict):
        print('TotalSeatList keys:', list(tsl.keys()))
        for k, v in tsl.items():
            print(f'  {k} type: {type(v)} len: {len(v) if isinstance(v, list) else "N/A"}')

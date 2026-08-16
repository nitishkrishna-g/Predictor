import sqlite3, os, json
import py_compile

print('--- SANITY CHECKS ---')

# 1. DB exists and schema valid
if not os.path.exists('abhibus.db'):
    print('DB missing')
else:
    try:
        conn = sqlite3.connect('abhibus.db')
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [t[0] for t in cur.fetchall()]
        print('Tables:', tables)
        conn.close()
    except Exception as e:
        print('DB error:', e)

# 2. Compile
try:
    py_compile.compile('collector.py', doraise=True)
    print('collector.py compiled successfully')
except Exception as e:
    print('Compile error:', e)

# 3. failed_queue.json
if os.path.exists('failed_queue.json'):
    try:
        with open('failed_queue.json', 'r') as f:
            data = json.load(f)
        print('failed_queue.json is valid JSON with len:', len(data))
    except Exception as e:
        print('failed_queue.json error:', e)
else:
    print('failed_queue.json does not exist (OK)')

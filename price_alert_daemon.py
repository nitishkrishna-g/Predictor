import sqlite3
import time
import json
from datetime import datetime
import traceback

DB = "abhibus.db"
WATCHLIST_FILE = "watchlist.json"

def setup_db():
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            route TEXT,
            operator TEXT,
            departure TEXT,
            seat_type TEXT,
            alert_type TEXT, 
            message TEXT
        )
    """)
    conn.commit()
    conn.close()

def log_alert(conn, alert_type, route, operator, departure, seat_type, message):
    from notifier import send_notification
    print(f"[{datetime.now().isoformat()}] ALERT: {message}")
    conn.execute("""
        INSERT INTO alerts (created_at, route, operator, departure, seat_type, alert_type, message)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (datetime.now().isoformat(), route, operator, departure, seat_type, alert_type, message))
    conn.commit()
    
    title = f"{alert_type.replace('_', ' ')} - {operator} {route} ({departure})"
    send_notification(title, message)

def load_watchlist():
    try:
        with open(WATCHLIST_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to load watchlist: {e}")
        return []

def get_latest_two_scrapes(conn, route, operator, date, departure, seat_type):
    # Find the service
    sv = conn.execute("""
        SELECT id FROM services 
        WHERE route LIKE ? AND operator LIKE ? AND journey_date = ? AND departure = ?
    """, (f"%{route}%", f"%{operator}%", date, departure)).fetchone()
    
    if not sv: return None, None
    service_id = sv[0]
    
    # Get last two scrapes for this service
    scrapes = conn.execute("""
        SELECT id, scraped_at, available_seats, cheapest_seater, cheapest_sleeper
        FROM scrapes
        WHERE service_id = ?
        ORDER BY scraped_at DESC LIMIT 2
    """, (service_id,)).fetchall()
    
    if len(scrapes) < 2: return None, None
    
    curr = scrapes[0]
    prev = scrapes[1]
    
    cur_fare = curr["cheapest_seater"] if seat_type.lower() == "seater" else curr["cheapest_sleeper"]
    prev_fare = prev["cheapest_seater"] if seat_type.lower() == "seater" else prev["cheapest_sleeper"]
    
    return {
        "fare": cur_fare,
        "avail": curr["available_seats"],
        "time": curr["scraped_at"]
    }, {
        "fare": prev_fare,
        "avail": prev["available_seats"],
        "time": prev["scraped_at"]
    }

def check_for_alerts(last_max_id):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    
    # Check if new scrapes exist
    cur_max = conn.execute("SELECT MAX(id) FROM scrapes").fetchone()[0]
    if cur_max is None: cur_max = 0
    
    if cur_max <= last_max_id:
        conn.close()
        return last_max_id
        
    print(f"New scrapes detected (Max ID: {cur_max}). Analyzing watchlist...")
    
    watchlist = load_watchlist()
    for item in watchlist:
        route = item.get("route")
        op = item.get("operator")
        date = item.get("date")
        dep = item.get("departure")
        stype = item.get("seat_type")
        
        curr, prev = get_latest_two_scrapes(conn, route, op, date, dep, stype)
        if not curr or not prev: continue
        
        # We only alert if the 'curr' scrape is actually NEW (id > last_max_id)
        # But for simplicity, if curr vs prev is different, we can alert. 
        # Actually we need to make sure we don't alert multiple times for the same change.
        # So we only alert if the `curr` scrape ID > last_max_id.
        # We can just fetch the scrape ID in get_latest_two_scrapes, but let's assume if cur_max increased, this check is valid.
        # To be strict, let's fetch the scrape ID for curr.
        sv = conn.execute("SELECT id FROM services WHERE route LIKE ? AND operator LIKE ? AND journey_date = ? AND departure = ?", (f"%{route}%", f"%{op}%", date, dep)).fetchone()
        if sv:
            latest_id = conn.execute("SELECT id FROM scrapes WHERE service_id = ? ORDER BY id DESC LIMIT 1", (sv[0],)).fetchone()[0]
            if latest_id <= last_max_id:
                continue # This specific service wasn't scraped in the new batch
                
        # Compare
        c_fare, p_fare = curr["fare"], prev["fare"]
        c_avail, p_avail = curr["avail"], prev["avail"]
        
        if c_fare != p_fare or c_avail != p_avail:
            # We have a change, let's get intelligent context
            from analyze_history import get_seat_intelligence
            from booking_advisor import get_recommendation
            intel = get_seat_intelligence(route or "", date, op or "", stype)
            
            advisor_str = ""
            if "error" not in intel:
                rec, _, _, conf, _ = get_recommendation(intel)
                advisor_str = f"Advisor: {rec}\nHistorical low window: {intel['historical_low_window']}"
            else:
                advisor_str = f"Advisor: Unavailable ({intel['error']})"
                
            # Check Fares
            if c_fare is not None and p_fare is not None:
                if c_fare < p_fare:
                    drop = p_fare - c_fare
                    pct = (drop / p_fare) * 100
                    msg = f"₹{p_fare} → ₹{c_fare}\n↓ ₹{drop} (-{pct:.1f}%)\n{p_avail} → {c_avail} seats\n{advisor_str}"
                    log_alert(conn, "PRICE_DROP", route, op, dep, stype, msg)
                elif c_fare > p_fare:
                    inc = c_fare - p_fare
                    pct = (inc / p_fare) * 100
                    msg = f"₹{p_fare} → ₹{c_fare}\n↑ ₹{inc} (+{pct:.1f}%)\n{p_avail} → {c_avail} seats\n{advisor_str}"
                    log_alert(conn, "PRICE_INCREASE", route, op, dep, stype, msg)
                    
            # Check Availability (only if fare didn't trigger an alert, to avoid duplicate alerts for the same event)
            # Actually, if fare changes AND seat sells, we get both in the fare alert.
            # If ONLY seat changes, we alert here.
            if c_fare == p_fare:
                if c_avail == 0 and p_avail > 0:
                    msg = f"Only 0 eligible seats remain.\nCurrent fare: ₹{c_fare}\nAdvisor: BOOK NOW"
                    log_alert(conn, "SOLD_OUT", route, op, dep, stype, msg)
                elif c_avail < p_avail:
                    msg = f"Only {c_avail} eligible seats remain.\nCurrent fare: ₹{c_fare}\n{advisor_str}"
                    log_alert(conn, "SEAT_SOLD", route, op, dep, stype, msg)
            
    conn.close()
    return cur_max

def run_daemon():
    print("Starting Price Alert Daemon...")
    setup_db()
    
    # Initialize last_max_id
    conn = sqlite3.connect(DB)
    last_max_id = conn.execute("SELECT MAX(id) FROM scrapes").fetchone()[0]
    if last_max_id is None: last_max_id = 0
    conn.close()
    
    print(f"Initialized with Max Scrape ID: {last_max_id}")
    
    while True:
        try:
            last_max_id = check_for_alerts(last_max_id)
        except Exception as e:
            print(f"Error in alert check: {e}")
            traceback.print_exc()
            
        time.sleep(30) # Poll every 30 seconds

if __name__ == "__main__":
    run_daemon()

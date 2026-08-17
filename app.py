from flask import Flask, jsonify, send_from_directory, request
import json
import sqlite3
from datetime import datetime, timedelta
import traceback
from analyze_history import get_seat_intelligence, get_dataset_maturity
from booking_advisor import get_recommendation

app = Flask(__name__, static_folder='static', static_url_path='')
DB = "abhibus.db"

def get_db_connection():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def serve_index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/dashboard')
def get_dashboard():
    try:
        conn = get_db_connection()
        last_scrape = conn.execute("SELECT MAX(scraped_at) as last_time FROM scrapes").fetchone()["last_time"]
        
        yesterday = (datetime.now() - timedelta(days=1)).isoformat()
        scrapes_24h = conn.execute("SELECT COUNT(DISTINCT scraped_at) as cnt FROM scrapes WHERE scraped_at > ?", (yesterday,)).fetchone()["cnt"]
        
        today = datetime.now().strftime("%Y-%m-%d")
        services_today = conn.execute("SELECT COUNT(DISTINCT service_id) as cnt FROM scrapes WHERE scraped_at LIKE ?", (f"{today}%",)).fetchone()["cnt"]
        
        failed_count = 0
        try:
            with open("failed_queue.json", "r") as f:
                failed_q = json.load(f)
                failed_count = len(failed_q)
        except:
            pass
        
        dataset_days = get_dataset_maturity(conn)
        
        conn.close()
        
        # Check collector running via file modified time of db
        import os
        db_mtime = datetime.fromtimestamp(os.path.getmtime(DB))
        is_running = (datetime.now() - db_mtime).total_seconds() < 1200 # 20 mins
        
        return jsonify({
            "status": "RUNNING" if is_running else "STALE",
            "last_scrape": last_scrape,
            "scrapes_24h": scrapes_24h,
            "services_today": services_today,
            "failed_queue": failed_count,
            "dataset_maturity_days": dataset_days
        })
    except Exception as e:
        return jsonify({"status": "ERROR", "error": str(e)}), 500

@app.route('/api/health')
def get_health():
    # Backward compatibility
    return get_dashboard()

@app.route('/api/search_options')
def get_search_options():
    try:
        conn = get_db_connection()
        raw_routes = [r["route"].lower() for r in conn.execute("SELECT DISTINCT route FROM services").fetchall()]
        
        canonical_set = set()
        for raw in raw_routes:
            parts = [p.strip() for p in raw.replace('-', ' ').replace('>', ' ').split()]
            if 'bangalore' in parts or 'bengaluru' in parts:
                if 'coimbatore' in parts:
                    idx_blr = min([raw.find(x) for x in ['bangalore','bengaluru'] if x in raw] or [0])
                    idx_cbe = raw.find('coimbatore') if 'coimbatore' in raw else 999
                    if idx_blr < idx_cbe:
                        canonical_set.add('Bangalore-Coimbatore')
                    else:
                        canonical_set.add('Coimbatore-Bangalore')
        
        routes = sorted(list(canonical_set))
        if 'Bangalore-Coimbatore' not in routes: routes.append('Bangalore-Coimbatore')
        if 'Coimbatore-Bangalore' not in routes: routes.append('Coimbatore-Bangalore')
        
        today = datetime.now().strftime("%Y-%m-%d")
        dates_rows = conn.execute("SELECT DISTINCT journey_date FROM services WHERE journey_date >= ? ORDER BY journey_date LIMIT 8", (today,)).fetchall()
        dates = [r["journey_date"] for r in dates_rows]
        
        conn.close()
        return jsonify({"routes": routes, "dates": dates})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/services')
def search_services():
    route = request.args.get('route', '')
    date = request.args.get('date', '')
    try:
        conn = get_db_connection()
        
        route_lower = route.lower()
        blr_idx = min([route_lower.find(c) for c in ['bangalore','bengaluru'] if c in route_lower] or [9999])
        cbe_idx = route_lower.find('coimbatore') if 'coimbatore' in route_lower else 9999
        
        if blr_idx < cbe_idx:
            pattern1, pattern2 = 'bangalore%coimbatore', 'bengaluru%coimbatore'
        else:
            pattern1, pattern2 = 'coimbatore%bangalore', 'coimbatore%bengaluru'
        
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        services_raw = conn.execute("""
            SELECT id, operator, service_name, departure, bus_type, service_key, route, journey_date
            FROM services 
            WHERE (LOWER(route) LIKE ? OR LOWER(route) LIKE ?) AND journey_date = ?
            AND departure > ?
            AND LOWER(operator) IN ('freshbus', 'fresh bus electric', 'nuego', 'neogo', 'zingbus', 'zingbus plus')
            ORDER BY departure ASC
        """, (pattern1, pattern2, date, now_str)).fetchall()
        
        results = []
        for sv in services_raw:
            sid = sv["id"]
            scrape = conn.execute("""
                SELECT total_seats, available_seats, cheapest_seater, cheapest_sleeper
                FROM scrapes WHERE service_id = ? ORDER BY scraped_at DESC LIMIT 1
            """, (sid,)).fetchone()
            
            if scrape:
                # Get basic bus-level intelligence for the UI
                bus_intel = get_seat_intelligence(
                    route=sv["route"], 
                    journey_date=sv["journey_date"], 
                    operator=sv["operator"], 
                    seat_type='seater' if 'seater' in sv["bus_type"].lower() else 'sleeper', 
                    seat_number=None,
                    db_path=DB
                )
                
                rec = "INSUFFICIENT DATA"
                hist_min = None
                if "error" not in bus_intel:
                    rec_tuple = get_recommendation(bus_intel)
                    rec = rec_tuple[0]
                    hist_min = bus_intel.get("historical_min")

                results.append({
                    "service_id": sid,
                    "service_key": sv["service_key"],
                    "operator": sv["operator"],
                    "service_name": sv["service_name"],
                    "departure": sv["departure"],
                    "bus_type": sv["bus_type"],
                    "total_seats": scrape["total_seats"],
                    "available_seats": scrape["available_seats"],
                    "cheapest_seater": scrape["cheapest_seater"],
                    "cheapest_sleeper": scrape["cheapest_sleeper"],
                    "historical_min": hist_min,
                    "recommendation": rec
                })
        conn.close()
        return jsonify(results)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/api/seatmap/<int:service_id>')
def get_seatmap(service_id):
    try:
        conn = get_db_connection()
        sv = conn.execute("SELECT route, journey_date, operator, departure FROM services WHERE id = ?", (service_id,)).fetchone()
        if not sv: return jsonify({"error": "Service not found"}), 404
        
        latest_scrape = conn.execute("SELECT id, scraped_at FROM scrapes WHERE service_id = ? ORDER BY scraped_at DESC LIMIT 1", (service_id,)).fetchone()
        if not latest_scrape: return jsonify({"error": "No scrapes for service"}), 404
        
        seats = conn.execute("""
            SELECT seat_number, deck, seat_type, row_id, column_id, available, ladies_seat, seat_fare, discounted_fare 
            FROM seats WHERE scrape_id = ?
        """, (latest_scrape["id"],)).fetchall()
        conn.close()
        
        # We process column_id deterministically to calculate col_span for sleepers
        # By grouping seats into rows, we can calculate the col_span between adjacent columns.
        rows_map = {}
        for s in seats:
            key = f"{s['deck']}_{s['row_id']}"
            if key not in rows_map: rows_map[key] = []
            rows_map[key].append(dict(s))
            
        processed_seats = []
        for key, row_seats in rows_map.items():
            # sort by column
            row_seats.sort(key=lambda x: int(x['column_id'] or 1))
            
            for i in range(len(row_seats)):
                s = row_seats[i]
                col_span = 1
                if i < len(row_seats) - 1:
                    next_s = row_seats[i+1]
                    diff = int(next_s['column_id'] or 1) - int(s['column_id'] or 1)
                    if diff > 1 and diff < 4:  # typical sleeper span is 2 or 3 columns
                        col_span = diff
                # if it's the last seat in the row and it's a sleeper, we default it to span 2
                elif s['seat_type'] != 'SS':
                    col_span = 2
                    
                s['col_span'] = col_span
                processed_seats.append(s)
        
        return jsonify({
            "service": dict(sv),
            "scraped_at": latest_scrape["scraped_at"],
            "seats": processed_seats
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/api/intelligence')
def get_intelligence():
    service_id = request.args.get('service_id')
    seat_number = request.args.get('seat_number')
    if not service_id or not seat_number:
        return jsonify({"error": "Missing service_id or seat_number"}), 400
        
    try:
        conn = get_db_connection()
        sv = conn.execute("SELECT route, journey_date, operator FROM services WHERE id = ?", (service_id,)).fetchone()
        
        latest_scrape = conn.execute("SELECT id FROM scrapes WHERE service_id = ? ORDER BY scraped_at DESC LIMIT 1", (service_id,)).fetchone()
        seat = conn.execute("SELECT seat_type, seat_fare, discounted_fare FROM seats WHERE scrape_id = ? AND seat_number = ?", (latest_scrape["id"], seat_number)).fetchone()
        conn.close()
        
        if not sv or not seat:
            return jsonify({"error": "Service or seat not found"}), 404
            
        stype = "seater" if seat["seat_type"] == "SS" else "sleeper"
        
        intel = get_seat_intelligence(
            route=sv["route"], 
            journey_date=sv["journey_date"], 
            operator=sv["operator"], 
            seat_type=stype,
            seat_number=seat_number,
            db_path=DB
        )
        
        if "error" in intel:
            return jsonify({
                "status": "INSUFFICIENT_DATA",
                "message": intel["error"]
            })
            
        rec, next_check, risk, conf, why = get_recommendation(intel)
        
        current_fare = seat["discounted_fare"] or seat["seat_fare"]
        
        return jsonify({
            "status": "SUCCESS",
            "current_fare": current_fare,
            "historical_minimum": intel.get("historical_min", None),
            "observations_count": intel.get("total_snapshots", 0),
            "expected_lowest_fare": intel.get("expected_minimum", None),
            "price_drop_probability": intel.get("probability_of_price_drop", 0),
            "recommendation": rec,
            "confidence": conf,
            "best_booking_window": intel.get("historical_low_window", "Unknown"),
            "why_reason": why,
            "comparable_journeys": intel.get("comparable_journeys", 0),
            "chart_data": intel.get("current_journey_history", [])
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

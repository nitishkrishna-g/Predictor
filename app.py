from flask import Flask, jsonify, send_from_directory, request
import json
import sqlite3
from datetime import datetime, timedelta
import traceback
from analyze_history import get_seat_intelligence, build_dataset
from booking_advisor import get_recommendation

app = Flask(__name__, static_folder='static', static_url_path='')
DB = "abhibus.db"

# We cache the dataset globally to avoid reloading the huge history JSON on every click
# If we had 90 days of data, reloading it every click would be catastrophic.
GLOBAL_DATASET = None

def get_dataset():
    global GLOBAL_DATASET
    if GLOBAL_DATASET is None:
        GLOBAL_DATASET = build_dataset()
    return GLOBAL_DATASET

def get_db_connection():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def serve_index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/health')
def get_health():
    try:
        conn = get_db_connection()
        last_scrape = conn.execute("SELECT MAX(scraped_at) as last_time FROM scrapes").fetchone()["last_time"]
        
        yesterday = (datetime.now() - timedelta(days=1)).isoformat()
        scrapes_24h = conn.execute("SELECT COUNT(DISTINCT scraped_at) as cnt FROM scrapes WHERE scraped_at > ?", (yesterday,)).fetchone()["cnt"]
        
        today = datetime.now().strftime("%Y-%m-%d")
        services_today = conn.execute("SELECT COUNT(DISTINCT service_id) as cnt FROM scrapes WHERE scraped_at LIKE ?", (f"{today}%",)).fetchone()["cnt"]
        
        # Determine dataset maturity
        dates_with_data = conn.execute("SELECT COUNT(DISTINCT journey_date) as cnt FROM services").fetchone()["cnt"]
        
        conn.close()
        return jsonify({
            "status": "RUNNING",
            "last_scrape": last_scrape,
            "scrapes_24h": scrapes_24h,
            "services_today": services_today,
            "dataset_maturity_days": dates_with_data
        })
    except Exception as e:
        return jsonify({"status": "ERROR", "error": str(e)}), 500

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
        
        # Get up to 7 distinct upcoming dates (T0 to T+7)
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
        
        services_raw = conn.execute("""
            SELECT id, operator, service_name, departure, bus_type, service_key 
            FROM services 
            WHERE (LOWER(route) LIKE ? OR LOWER(route) LIKE ?) AND journey_date = ?
            AND LOWER(operator) IN ('freshbus', 'fresh bus electric', 'nuego', 'neogo', 'zingbus', 'zingbus plus')
            ORDER BY departure ASC
        """, (pattern1, pattern2, date)).fetchall()
        
        results = []
        for sv in services_raw:
            sid = sv["id"]
            scrape = conn.execute("""
                SELECT total_seats, available_seats, cheapest_seater, cheapest_sleeper
                FROM scrapes WHERE service_id = ? ORDER BY scraped_at DESC LIMIT 1
            """, (sid,)).fetchone()
            
            if scrape:
                # Calculate duration or arrival if possible
                # AbhiBus doesn't always provide arrival, we leave it as None for now
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
                    "cheapest_sleeper": scrape["cheapest_sleeper"]
                })
        conn.close()
        return jsonify(results)
    except Exception as e:
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
        
        return jsonify({
            "service": dict(sv),
            "scraped_at": latest_scrape["scraped_at"],
            "seats": [dict(s) for s in seats]
        })
    except Exception as e:
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
        dataset = get_dataset()
        
        intel = get_seat_intelligence(
            route=sv["route"], 
            journey_date=sv["journey_date"], 
            operator=sv["operator"], 
            seat_type=stype,
            seat_number=seat_number,
            dataset=dataset
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
            "historical_minimum": intel.get("historical_minimum", None),
            "observations_count": intel.get("observations_count", 0),
            "expected_lowest_fare": intel.get("expected_minimum", None),
            "price_drop_probability": intel.get("probability_of_price_drop", 0),
            "recommendation": rec,
            "confidence": conf,
            "best_booking_window": intel.get("historical_low_window", "Unknown"),
            "why_reason": why,
            "comparable_journeys": intel.get("comparable_journeys", 0)
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

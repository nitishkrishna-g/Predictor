from flask import Flask, jsonify, send_from_directory
import json
import sqlite3
from analyze_history import get_seat_intelligence

app = Flask(__name__, static_folder='static', static_url_path='')
DB = "abhibus.db"
WATCHLIST_FILE = "watchlist.json"

@app.route('/')
def serve_index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/watchlist')
def get_watchlist():
    try:
        with open(WATCHLIST_FILE, "r") as f:
            watchlist = json.load(f)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
        
    enriched = []
    for item in watchlist:
        try:
            intel = get_seat_intelligence(
                item["route"], 
                item["date"], 
                item["operator"], 
                item["seat_type"]
            )
            
            # Use logic to define recommendation string
            # Wait, we can import booking_advisor.get_recommendation
            # But let's just do it directly or import it
            from booking_advisor import get_recommendation
            
            if "error" not in intel:
                rec, next_check, risk, confidence, why = get_recommendation(intel)
                intel["recommendation"] = rec
                intel["next_check"] = next_check
                intel["availability_risk"] = risk
                intel["data_confidence"] = confidence
                intel["why_reason"] = why
                
            enriched.append({
                "config": item,
                "intelligence": intel
            })
        except Exception as e:
            enriched.append({
                "config": item,
                "error": str(e)
            })
            
    return jsonify(enriched)

@app.route('/api/alerts')
def get_alerts():
    try:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        
        # Make sure table exists (in case UI loads before daemon starts)
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
        
        alerts = conn.execute("""
            SELECT * FROM alerts 
            ORDER BY created_at DESC 
            LIMIT 50
        """).fetchall()
        conn.close()
        
        return jsonify([dict(a) for a in alerts])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/health')
def get_health():
    try:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        
        last_scrape = conn.execute("SELECT MAX(scraped_at) as last_time FROM scrapes").fetchone()["last_time"]
        
        from datetime import datetime, timedelta
        yesterday = (datetime.now() - timedelta(days=1)).isoformat()
        scrapes_24h = conn.execute("SELECT COUNT(DISTINCT scraped_at) as cnt FROM scrapes WHERE scraped_at > ?", (yesterday,)).fetchone()["cnt"]
        
        today = datetime.now().strftime("%Y-%m-%d")
        services_today = conn.execute("SELECT COUNT(DISTINCT service_id) as cnt FROM scrapes WHERE scraped_at LIKE ?", (f"{today}%",)).fetchone()["cnt"]
        
        conn.close()
        return jsonify({
            "status": "RUNNING",
            "last_scrape": last_scrape,
            "scrapes_24h": scrapes_24h,
            "services_today": services_today
        })
    except Exception as e:
        return jsonify({"status": "ERROR", "error": str(e)}), 500

from flask import request

@app.route('/api/seatmap')
def get_seatmap():
    route = request.args.get('route', '')
    op = request.args.get('operator', '')
    date = request.args.get('date', '')
    dep = request.args.get('departure', '')
    
    try:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        
        sv = conn.execute("""
            SELECT id FROM services 
            WHERE route LIKE ? AND operator LIKE ? AND journey_date = ? AND departure = ?
        """, (f"%{route}%", f"%{op}%", date, dep)).fetchone()
        
        if not sv: return jsonify({"error": "Service not found"})
            
        sid = sv["id"]
        latest_scrape = conn.execute("SELECT id FROM scrapes WHERE service_id = ? ORDER BY scraped_at DESC LIMIT 1", (sid,)).fetchone()
        if not latest_scrape: return jsonify({"error": "No scrapes for service"})
            
        scrape_id = latest_scrape["id"]
        seats = conn.execute("""
            SELECT seat_number, deck, seat_type, row_id, column_id, available, ladies_seat, discounted_fare 
            FROM seats WHERE scrape_id = ?
        """, (scrape_id,)).fetchall()
        conn.close()
        return jsonify([dict(s) for s in seats])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Canonical route names shown in UI
CANONICAL_ROUTES = {
    "Bangalore-Coimbatore": ["bangalore", "coimbatore"],   # BLR -> CBE pattern
    "Coimbatore-Bangalore": ["coimbatore", "bangalore"],   # CBE -> BLR pattern
}

@app.route('/api/search_options')
def get_search_options():
    try:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        raw_routes = [r["route"].lower() for r in conn.execute("SELECT DISTINCT route FROM services").fetchall()]
        
        # Map all route variants to canonical names
        canonical_set = set()
        for raw in raw_routes:
            parts = [p.strip() for p in raw.replace('-', ' ').replace('>', ' ').split()]
            if 'bangalore' in parts or 'bengaluru' in parts:
                if 'coimbatore' in parts:
                    # Figure out direction by which appears first
                    idx_blr = min([raw.find(x) for x in ['bangalore','bengaluru'] if x in raw] or [0])
                    idx_cbe = raw.find('coimbatore') if 'coimbatore' in raw else 999
                    if idx_blr < idx_cbe:
                        canonical_set.add('Bangalore-Coimbatore')
                    else:
                        canonical_set.add('Coimbatore-Bangalore')
        
        routes = sorted(list(canonical_set))
        # Always include both routes even if only one has data (avoids confusion)
        if 'Bangalore-Coimbatore' not in routes:
            routes.append('Bangalore-Coimbatore')
        if 'Coimbatore-Bangalore' not in routes:
            routes.append('Coimbatore-Bangalore')
        routes = sorted(routes)
        
        # Get dates that have data for any route
        dates = [r["journey_date"] for r in conn.execute(
            "SELECT DISTINCT journey_date FROM services ORDER BY journey_date"
        ).fetchall()]
        conn.close()
        return jsonify({"routes": routes, "dates": dates})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/services')
def search_services():
    route = request.args.get('route', '')
    date = request.args.get('date', '')
    try:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        
        # Determine direction from route name, then match loosely using city names
        route_lower = route.lower()
        
        # Detect direction: which city comes first?
        blr_idx = min([route_lower.find(c) for c in ['bangalore','bengaluru'] if c in route_lower] or [9999])
        cbe_idx = route_lower.find('coimbatore') if 'coimbatore' in route_lower else 9999
        
        if blr_idx < cbe_idx:
            # BLR -> CBE: route starts with Bangalore/Bengaluru
            pattern1 = 'bangalore%coimbatore'
            pattern2 = 'bengaluru%coimbatore'
        else:
            # CBE -> BLR: route starts with Coimbatore
            pattern1 = 'coimbatore%bangalore'
            pattern2 = 'coimbatore%bengaluru'
        
        services_raw = conn.execute("""
            SELECT id, operator, service_name, departure, bus_type 
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
                results.append({
                    "service_id": sid,
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

@app.route('/api/seatmap_intelligent')
def get_seatmap_intelligent():
    service_id = request.args.get('service_id')
    try:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        sv = conn.execute("SELECT route, journey_date, operator, departure FROM services WHERE id = ?", (service_id,)).fetchone()
        if not sv: return jsonify({"error": "Service not found"})
        
        latest_scrape = conn.execute("SELECT id FROM scrapes WHERE service_id = ? ORDER BY scraped_at DESC LIMIT 1", (service_id,)).fetchone()
        if not latest_scrape: return jsonify({"error": "No scrapes for service"})
        
        seats = conn.execute("""
            SELECT seat_number, deck, seat_type, row_id, column_id, available, ladies_seat, discounted_fare 
            FROM seats WHERE scrape_id = ?
        """, (latest_scrape["id"],)).fetchall()
        conn.close()
        
        from analyze_history import build_dataset, get_seat_intelligence
        from booking_advisor import get_recommendation
        
        dataset = build_dataset() # load once
        
        result_seats = []
        for row in seats:
            seat = dict(row)
            if seat["available"] and not seat["ladies_seat"]:
                stype = "seater" if seat["seat_type"] == "SS" else "sleeper"
                intel = get_seat_intelligence(
                    route=sv["route"], 
                    journey_date=sv["journey_date"], 
                    operator=sv["operator"], 
                    seat_type=stype,
                    seat_number=seat["seat_number"],
                    dataset=dataset
                )
                
                if "error" not in intel:
                    rec, next_check, risk, conf, why = get_recommendation(intel)
                    seat["intel"] = {
                        "recommendation": rec,
                        "expected_minimum": intel["expected_minimum"],
                        "probability_of_price_drop": intel["probability_of_price_drop"],
                        "data_confidence": conf,
                        "historical_low_window": intel["historical_low_window"],
                        "why_reason": why,
                        "comparable_journeys": intel.get("comparable_journeys", 0)
                    }
            result_seats.append(seat)
            
        return jsonify({
            "service": dict(sv),
            "seats": result_seats
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

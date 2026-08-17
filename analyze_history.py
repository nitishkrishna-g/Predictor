import sqlite3
import statistics
from datetime import datetime

DB = "abhibus.db"

def get_time_bucket(htd):
    if htd is None or htd < 0: return "Unknown"
    if htd <= 2: return "0-2h"
    if htd <= 4: return "2-4h"
    if htd <= 8: return "4-8h"
    if htd <= 12: return "8-12h"
    if htd <= 24: return "12-24h"
    if htd <= 36: return "24-36h"
    if htd <= 48: return "36-48h"
    if htd <= 72: return "48-72h"
    return "72h+"

def get_dataset_maturity(conn=None):
    close_conn = False
    if conn is None:
        conn = sqlite3.connect(DB)
        close_conn = True
        
    res = conn.execute("SELECT COUNT(DISTINCT date(scraped_at)) as days FROM scrapes").fetchone()
    days = res[0] if res else 0
    
    if close_conn:
        conn.close()
    return days

def get_seat_intelligence(route, journey_date, operator, seat_type, seat_number=None, db_path=DB, cutoff_time=None):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # 1. Get maturity
    maturity_days = get_dataset_maturity(conn)
    
    # 2. Get current state of the exact target service & seat
    # Determine direction/pattern for route matching
    route_lower = route.lower()
    blr_idx = min([route_lower.find(c) for c in ['bangalore','bengaluru'] if c in route_lower] or [9999])
    cbe_idx = route_lower.find('coimbatore') if 'coimbatore' in route_lower else 9999
    
    if blr_idx < cbe_idx:
        route_pattern = '%bangalore%coimbatore%'
    else:
        route_pattern = '%coimbatore%bangalore%'
        
    op_pattern = f"%{operator}%"
    
    # Find the target service for the specific journey_date
    target_sv = conn.execute("""
        SELECT id, departure FROM services 
        WHERE (LOWER(route) LIKE ? OR LOWER(route) LIKE ?) 
        AND LOWER(operator) LIKE ? 
        AND journey_date = ? LIMIT 1
    """, (route_pattern, route_pattern.replace('bangalore', 'bengaluru'), op_pattern, journey_date)).fetchone()
    
    if not target_sv:
        conn.close()
        return {"error": "Service not found in dataset."}
        
    service_id = target_sv["id"]
    departure_str = target_sv["departure"]
    
    # Current seat state
    seat_filter = "st.seat_number = ?" if seat_number else "st.seat_type = ?"
    seat_val = seat_number if seat_number else ("SS" if seat_type.lower() == "seater" else "LB") # roughly
    
    # If no seat number, we just want the cheapest available for that type
    if seat_number:
        current_state = conn.execute(f"""
            SELECT sc.scraped_at, st.discounted_fare, st.seat_fare, st.available
            FROM scrapes sc 
            JOIN seats st ON sc.id = st.scrape_id
            WHERE sc.service_id = ? AND st.seat_number = ?
            ORDER BY sc.scraped_at DESC LIMIT 1
        """, (service_id, seat_number)).fetchone()
    else:
        # Bus-level query (we can just look at scrapes)
        current_state = conn.execute("""
            SELECT scraped_at, cheapest_seater, cheapest_sleeper
            FROM scrapes WHERE service_id = ? ORDER BY scraped_at DESC LIMIT 1
        """, (service_id,)).fetchone()
        
    if not current_state:
        conn.close()
        return {"error": "Current seat/bus data not found."}
        
    # Parse departure and htd
    departure_dt = None
    if departure_str and "Unknown" not in departure_str:
        try:
            departure_dt = datetime.strptime(departure_str, "%Y-%m-%d %H:%M")
        except:
            pass
            
    current_fare = None
    available_now = False
    scraped_at_str = current_state["scraped_at"]
    
    if seat_number:
        current_fare = current_state["discounted_fare"] or current_state["seat_fare"]
        available_now = bool(current_state["available"])
    else:
        if seat_type.lower() == 'seater':
            current_fare = current_state["cheapest_seater"]
        else:
            current_fare = current_state["cheapest_sleeper"]
        available_now = current_fare is not None
        
    if not available_now or current_fare is None:
        conn.close()
        return {"error": "Seat is sold out or unavailable."}
        
    current_htd = None
    current_bucket = "Unknown"
    scraped_at_dt = None
    try:
        scraped_at_dt = datetime.fromisoformat(scraped_at_str).replace(tzinfo=None)
        if departure_dt:
            diff = departure_dt - scraped_at_dt
            current_htd = diff.total_seconds() / 3600.0
            current_bucket = get_time_bucket(current_htd)
    except:
        pass

    # 3. Targeted Historical Query for this exact route, operator, and seat configuration
    if seat_number:
        # Seat specific history
        hist_query = """
            SELECT sv.id as service_id, sc.scraped_at, sv.departure, st.discounted_fare, st.seat_fare, st.available
            FROM services sv
            JOIN scrapes sc ON sv.id = sc.service_id
            JOIN seats st ON sc.id = st.scrape_id
            WHERE (LOWER(sv.route) LIKE ? OR LOWER(sv.route) LIKE ?)
            AND LOWER(sv.operator) LIKE ?
            AND st.seat_number = ?
            AND (st.discounted_fare > 0 OR st.seat_fare > 0)
        """
        hist_params = (route_pattern, route_pattern.replace('bangalore', 'bengaluru'), op_pattern, seat_number)
    else:
        # Bus-level generic seat-type history
        hist_query = """
            SELECT sv.id as service_id, sc.scraped_at, sv.departure, sc.cheapest_seater, sc.cheapest_sleeper
            FROM services sv
            JOIN scrapes sc ON sv.id = sc.service_id
            WHERE (LOWER(sv.route) LIKE ? OR LOWER(sv.route) LIKE ?)
            AND LOWER(sv.operator) LIKE ?
        """
        hist_params = (route_pattern, route_pattern.replace('bangalore', 'bengaluru'), op_pattern)
        
    hist_rows = conn.execute(hist_query, hist_params).fetchall()
    
    # 4. Get journey history for the current specific service (for the chart)
    chart_query = """
        SELECT sc.scraped_at, st.discounted_fare, st.seat_fare
        FROM scrapes sc JOIN seats st ON sc.id = st.scrape_id
        WHERE sc.service_id = ? AND st.seat_number = ? AND st.available = 1
        ORDER BY sc.scraped_at ASC
    """
    if seat_number:
        chart_rows = conn.execute(chart_query, (service_id, seat_number)).fetchall()
    else:
        chart_rows = []
        
    conn.close()

    # Process Historical Data
    fares_history = []
    journeys = {}
    
    for r in hist_rows:
        fare = None
        if seat_number:
            fare = r["discounted_fare"] or r["seat_fare"]
        else:
            fare = r["cheapest_seater"] if seat_type.lower() == 'seater' else r["cheapest_sleeper"]
            
        if fare is None or fare <= 0: continue
        
        fares_history.append(fare)
        
        sid = r["service_id"]
        dep_str = r["departure"]
        scrap_str = r["scraped_at"]
        
        # calculate bucket
        htd = None
        bucket = "Unknown"
        try:
            scrap_dt = datetime.fromisoformat(scrap_str).replace(tzinfo=None)
            if dep_str and "Unknown" not in dep_str:
                dep_dt = datetime.strptime(dep_str, "%Y-%m-%d %H:%M")
                diff = dep_dt - scrap_dt
                htd = diff.total_seconds() / 3600.0
                bucket = get_time_bucket(htd)
        except:
            pass
            
        if sid not in journeys:
            journeys[sid] = []
        journeys[sid].append({"fare": fare, "scraped_at": scrap_str, "time_bucket": bucket, "htd": htd})

    if not fares_history:
        return {"error": "Insufficient historical data for this seat."}

    hist_min = min(fares_history)
    hist_max = max(fares_history)
    hist_med = statistics.median(fares_history)
    
    comparable_journeys = 0
    dropped_journeys = 0
    lowest_reached = []
    historical_best_buckets = {}
    
    for sid, obs_list in journeys.items():
        bucket_obs = [o for o in obs_list if o["time_bucket"] == current_bucket]
        if bucket_obs:
            comparable_journeys += 1
            first_bucket_obs_time = min(o["scraped_at"] for o in bucket_obs)
            future_obs = [o for o in obs_list if o["scraped_at"] > first_bucket_obs_time]
            
            if future_obs:
                min_future_fare = min(o["fare"] for o in future_obs)
                lowest_reached.append(min_future_fare)
                bucket_fare = max(o["fare"] for o in bucket_obs)
                if min_future_fare < bucket_fare:
                    dropped_journeys += 1
                    
        # historical low window
        if obs_list:
            journey_min = min(o["fare"] for o in obs_list)
            min_obs = [o for o in obs_list if o["fare"] == journey_min]
            for m in min_obs:
                b = m["time_bucket"]
                if b != "Unknown":
                    historical_best_buckets[b] = historical_best_buckets.get(b, 0) + 1
                    
    prob_drop = (dropped_journeys / comparable_journeys * 100) if comparable_journeys > 0 else 0.0
    expected_min = (sum(lowest_reached) / len(lowest_reached)) if lowest_reached else current_fare
    
    historical_low_window = "Unknown"
    if historical_best_buckets:
        best_bucket = max(historical_best_buckets, key=historical_best_buckets.get)
        historical_low_window = f"{best_bucket} before departure"
        
    current_journey_history = []
    for r in chart_rows:
        try:
            f = r["discounted_fare"] or r["seat_fare"]
            sdt = datetime.fromisoformat(r["scraped_at"]).replace(tzinfo=None)
            htd_val = (departure_dt - sdt).total_seconds() / 3600.0 if departure_dt else None
            if htd_val is not None:
                current_journey_history.append({"htd": htd_val, "fare": f, "scraped_at": r["scraped_at"]})
        except:
            pass
            
    # Confidence Level based on Maturity
    confidence = "INSUFFICIENT DATA"
    if maturity_days >= 60: confidence = "HIGH"
    elif maturity_days >= 30: confidence = "MEDIUM"
    elif maturity_days >= 7: confidence = "LOW"
    else: confidence = "INSUFFICIENT DATA"
    
    # We also consider comparable journeys as a secondary safety check
    if comparable_journeys < 3 and confidence != "INSUFFICIENT DATA":
        confidence = "LOW"

    return {
        "current_fare": current_fare,
        "historical_min": hist_min,
        "historical_max": hist_max,
        "historical_median": hist_med,
        "hours_to_departure": current_htd,
        "historical_low_window": historical_low_window,
        "probability_of_price_drop": prob_drop,
        "expected_minimum": expected_min,
        "available_seats_count": 1 if seat_number else 99, # roughly
        "comparable_journeys": comparable_journeys,
        "current_journey_history": current_journey_history,
        "dataset_maturity_days": maturity_days,
        "dataset_confidence": confidence
    }

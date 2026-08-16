import sqlite3
import statistics
import csv
from datetime import datetime

DB = "abhibus.db"

def get_time_bucket(htd):
    if htd is None or htd < 0:
        return "Unknown"
    if htd <= 2: return "0-2h"
    if htd <= 4: return "2-4h"
    if htd <= 8: return "4-8h"
    if htd <= 12: return "8-12h"
    if htd <= 24: return "12-24h"
    if htd <= 36: return "24-36h"
    if htd <= 48: return "36-48h"
    if htd <= 72: return "48-72h"
    return "72h+"

def build_dataset(db_path=DB, cutoff_time=None):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    where_clause = "WHERE st.discounted_fare IS NOT NULL AND st.discounted_fare > 0"
    params = []
    
    if cutoff_time:
        where_clause += " AND sc.scraped_at <= ?"
        params.append(cutoff_time)
        
    query = f"""
    SELECT 
      sv.id as service_id,
      sv.route, 
      sv.journey_date, 
      sv.operator, 
      sv.departure,
      sc.id as scrape_id,
      sc.scraped_at, 
      st.seat_type, 
      st.seat_number, 
      st.discounted_fare as fare, 
      st.available,
      st.ladies_seat
    FROM seats st
    JOIN scrapes sc ON st.scrape_id = sc.id
    JOIN services sv ON sc.service_id = sv.id
    {where_clause}
    ORDER BY sv.id, st.seat_number, sc.scraped_at
    """
    
    rows = conn.execute(query, params).fetchall()
    conn.close()
    
    dataset = []
    
    for r in rows:
        scraped_at = None
        departure = None
        hours_to_departure = None
        bucket = "Unknown"
        
        try:
            scraped_at = datetime.fromisoformat(r["scraped_at"])
        except:
            pass
            
        try:
            if r["departure"] and "Unknown" not in r["departure"]:
                departure = datetime.strptime(r["departure"], "%Y-%m-%d %H:%M")
        except:
            pass
            
        if scraped_at and departure:
            scraped_at_naive = scraped_at.replace(tzinfo=None)
            diff = departure - scraped_at_naive
            hours_to_departure = diff.total_seconds() / 3600.0
            bucket = get_time_bucket(hours_to_departure)
            
        dataset.append({
            "service_id": r["service_id"],
            "route": r["route"],
            "journey_date": r["journey_date"],
            "operator": r["operator"],
            "departure": r["departure"],
            "scraped_at": r["scraped_at"],
            "hours_to_departure": hours_to_departure,
            "time_bucket": bucket,
            "seat_type": r["seat_type"],
            "seat_number": r["seat_number"],
            "fare": r["fare"],
            "available": bool(r["available"]),
            "ladies_seat": bool(r["ladies_seat"])
        })
        
    return dataset

def export_csv(dataset, filename="historical_features.csv"):
    if not dataset:
        print("No data to export.")
        return
        
    keys = dataset[0].keys()
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(dataset)
    print(f"Exported {len(dataset)} records to {filename}")

def get_seat_intelligence(route, journey_date, operator, seat_type, seat_number=None, db_path=DB, cutoff_time=None, dataset=None):
    if dataset is None:
        dataset = build_dataset(db_path, cutoff_time)
    
    # 1. Filter for specific operator and route type
    service_obs = [
        d for d in dataset 
        if route.lower() in d["route"].lower() 
        and operator.lower() in (d["operator"] or "").lower()
    ]
    
    if not service_obs:
        return {"error": "Service not found in dataset."}
        
    # We find the exact target service for the specific journey date to get current stats
    target_service_obs = [d for d in service_obs if d["journey_date"] == journey_date]
    if not target_service_obs:
        return {"error": "Target journey date not found in dataset."}
        
    # 2. Filter by seat type/number
    seat_obs_all = []
    if seat_type.lower() == "seater":
        seat_obs_all = [d for d in service_obs if d["seat_type"] == "SS"]
    elif seat_type.lower() == "sleeper":
        seat_obs_all = [d for d in service_obs if d["seat_type"] in ("LB", "UB")]
    else:
        seat_obs_all = [d for d in service_obs if d["seat_type"].lower() == seat_type.lower()]
        
    if seat_number:
        seat_obs_all = [d for d in seat_obs_all if d["seat_number"].lower() == seat_number.lower()]
        
    if not seat_obs_all:
        return {"error": "No data for this seat criteria."}
        
    # The observations for the TARGET journey (for current state)
    target_seat_obs = [d for d in seat_obs_all if d["journey_date"] == journey_date]
    if not target_seat_obs:
        return {"error": "No data for this seat on the target date."}
        
    # 3. Identify current state (latest scrape on the target date)
    latest_scrape = max(d["scraped_at"] for d in target_seat_obs)
    current_obs = [d for d in target_seat_obs if d["scraped_at"] == latest_scrape]
    
    available_now = [d for d in current_obs if d["available"]]
    if not available_now:
        return {"error": "All matching seats are sold out."}
        
    current_fare = min([d["fare"] for d in available_now])
    current_htd = current_obs[0]["hours_to_departure"]
    current_bucket = current_obs[0]["time_bucket"]
    
    # 4. Global Historical Fares for this specific service+seat config across ALL journey dates
    fares_history = [d["fare"] for d in seat_obs_all if d["fare"] is not None]
    hist_min = min(fares_history)
    hist_max = max(fares_history)
    hist_med = statistics.median(fares_history)
    
    # 5. Forward-Looking Probability of Price Drop
    # Group observations by unique journey (service_id)
    journeys = {}
    for obs in seat_obs_all:
        sid = obs["service_id"]
        if sid not in journeys:
            journeys[sid] = []
        journeys[sid].append(obs)
        
    comparable_journeys = 0
    dropped_journeys = 0
    lowest_reached = []
    historical_best_buckets = {}
    
    for sid, obs_list in journeys.items():
        # Find if this journey had observations in the current time bucket
        bucket_obs = [o for o in obs_list if o["time_bucket"] == current_bucket]
        
        if bucket_obs:
            # We have a comparable journey!
            # Did the fare in this bucket resemble the current fare?
            # Or we can just ask: "Given this time bucket, did the fare drop in the future?"
            
            comparable_journeys += 1
            
            # Future observations are those with hours_to_departure < bucket start
            # But just ordering by scraped_at is easier. We look at all observations *after* the first bucket observation
            first_bucket_obs_time = min(o["scraped_at"] for o in bucket_obs)
            future_obs = [o for o in obs_list if o["scraped_at"] > first_bucket_obs_time]
            
            # The lowest fare reached in the future of this journey
            if future_obs:
                min_future_fare = min(o["fare"] for o in future_obs)
                lowest_reached.append(min_future_fare)
                
                # The minimum fare among the bucket observations (in case of multiple)
                bucket_fare = max(o["fare"] for o in bucket_obs)
                
                if min_future_fare < bucket_fare:
                    dropped_journeys += 1
            else:
                # No future observations means no drop
                pass
                
        # To find "historical low window", find when this specific journey reached its absolute minimum
        if obs_list:
            journey_min = min(o["fare"] for o in obs_list)
            min_obs = [o for o in obs_list if o["fare"] == journey_min]
            # When did it hit this minimum?
            for m in min_obs:
                b = m["time_bucket"]
                if b != "Unknown":
                    historical_best_buckets[b] = historical_best_buckets.get(b, 0) + 1
                    
    # Calculate probabilities
    prob_drop = (dropped_journeys / comparable_journeys * 100) if comparable_journeys > 0 else 0.0
    
    # Calculate Expected Minimum
    if lowest_reached:
        expected_min = sum(lowest_reached) / len(lowest_reached)
    else:
        expected_min = current_fare
        
    # Calculate best historical low window
    if historical_best_buckets:
        best_bucket = max(historical_best_buckets, key=historical_best_buckets.get)
        historical_low_window = f"{best_bucket} before departure"
    else:
        historical_low_window = "Unknown"
    
    # Build current journey history for the chart
    current_journey_history = []
    scrape_times = sorted(list(set(d["scraped_at"] for d in target_seat_obs)))
    for st in scrape_times:
        obs = [d for d in target_seat_obs if d["scraped_at"] == st and d["available"]]
        if obs:
            min_f = min(d["fare"] for d in obs)
            htd_val = obs[0]["hours_to_departure"]
            current_journey_history.append({"htd": htd_val, "fare": min_f})
            
    # Build detailed seat list
    available_seats_details = []
    for d in available_now:
        available_seats_details.append({
            "seat_number": d["seat_number"],
            "seat_type": d["seat_type"],
            "fare": d["fare"]
        })
    available_seats_details.sort(key=lambda x: x["fare"])
    
    return {
        "current_fare": current_fare,
        "historical_min": hist_min,
        "historical_max": hist_max,
        "historical_median": hist_med,
        "hours_to_departure": current_htd,
        "historical_low_window": historical_low_window,
        "probability_of_price_drop": prob_drop,
        "expected_minimum": expected_min,
        "available_seats_count": len(available_now),
        "total_matching_seats": len(current_obs),
        "departure": current_obs[0]["departure"],
        "operator": current_obs[0]["operator"],
        "comparable_journeys": comparable_journeys,
        "total_journeys_analyzed": len(journeys),
        "total_snapshots": len(seat_obs_all),
        "current_journey_history": current_journey_history,
        "available_seats_details": available_seats_details
    }

if __name__ == "__main__":
    print("Building historical dataset...")
    data = build_dataset()
    export_csv(data)

from analyze_history import build_dataset, get_seat_intelligence
from booking_advisor import get_recommendation

def run_backtest():
    print("Building full historical dataset...")
    full_dataset = build_dataset()
    
    # Group by journey = (route, operator, journey_date, departure, seat_type)
    journeys = {}
    for d in full_dataset:
        key = (d["route"], d["operator"], d["journey_date"], d["departure"], d["seat_type"])
        if key not in journeys:
            journeys[key] = []
        journeys[key].append(d)
        
    results = {
        "total_journeys": 0,
        "booked_journeys": 0,
        "sold_out_failures": 0,
        "total_savings": 0.0,
        "total_missed_savings": 0.0,
        "correct_waits": 0,
        "incorrect_waits": 0,
        "premature_books": 0
    }
    
    print(f"Starting backtest across {len(journeys)} unique journeys...")
    
    for key, obs_list in journeys.items():
        route, operator, journey_date, departure, seat_type = key
        results["total_journeys"] += 1
        
        # Sort by time
        obs_list.sort(key=lambda x: x["scraped_at"])
        
        # Unique scrape times (sorted chronologically)
        scrape_times = sorted(list(set(o["scraped_at"] for o in obs_list)))
        
        # Define meaningful decision checkpoints (hours before departure)
        checkpoints = [72, 48, 36, 24, 18, 12, 8, 6, 4, 2, 1]
        
        # Find the first observation that crossed each checkpoint
        checkpoint_times = []
        for c in checkpoints:
            # Find the first scrape where hours_to_departure <= c
            # (Since they are sorted chronologically, hours_to_departure is strictly decreasing)
            for t in scrape_times:
                # get the observation
                obs = [o for o in obs_list if o["scraped_at"] == t][0]
                htd = obs["hours_to_departure"]
                if htd is not None and htd <= c:
                    if t not in checkpoint_times:
                        checkpoint_times.append(t)
                    break
        
        booked = False
        
        for t in checkpoint_times:
            # Check availability at time t
            current_obs = [o for o in obs_list if o["scraped_at"] == t and o["available"]]
            if not current_obs:
                # Sold out!
                if not booked:
                    results["sold_out_failures"] += 1
                    booked = True # Treat as terminal state
                    break
            
            # To strictly prevent data leakage, filter the full dataset to only include data up to t
            blinded_dataset = [d for d in full_dataset if d["scraped_at"] <= t]
            
            intel = get_seat_intelligence(route or "", journey_date, operator or "", seat_type or "", cutoff_time=t, dataset=blinded_dataset)
            if "error" in intel:
                continue
                
            rec, _, _ = get_recommendation(intel)
            
            if "BOOK NOW" in rec:
                booked = True
                booked_fare = intel["current_fare"]
                
                # Check absolute minimum of future observations
                future_fares = [o["fare"] for o in obs_list if o["scraped_at"] > t and o["available"]]
                if future_fares:
                    future_min = min(future_fares)
                    if future_min < booked_fare:
                        results["premature_books"] += 1
                        results["total_missed_savings"] += (booked_fare - future_min)
                
                # Compare to first seen fare for savings calculation
                first_fares = [o["fare"] for o in obs_list if o["scraped_at"] == scrape_times[0] and o["available"]]
                if first_fares:
                    first_fare = min(first_fares)
                    results["total_savings"] += (first_fare - booked_fare)
                    
                results["booked_journeys"] += 1
                break
            else:
                # We WAITED
                # Check if wait was correct (did price drop later?)
                future_fares = [o["fare"] for o in obs_list if o["scraped_at"] > t and o["available"]]
                if future_fares:
                    future_min = min(future_fares)
                    if future_min < intel["current_fare"]:
                        results["correct_waits"] += 1
                    else:
                        results["incorrect_waits"] += 1
                        
    print("=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    print(f"Total Journeys Simulated : {results['total_journeys']}")
    print(f"Journeys Booked          : {results['booked_journeys']}")
    print(f"Availability Failures    : {results['sold_out_failures']}")
    print("-" * 60)
    
    avg_savings = results["total_savings"] / results["booked_journeys"] if results["booked_journeys"] > 0 else 0
    avg_missed = results["total_missed_savings"] / results["booked_journeys"] if results["booked_journeys"] > 0 else 0
    
    print(f"Average ₹ Saved          : ₹{avg_savings:.2f}")
    print(f"Average Missed Savings   : ₹{avg_missed:.2f}")
    print("-" * 60)
    
    total_waits = results["correct_waits"] + results["incorrect_waits"]
    wait_accuracy = (results["correct_waits"] / total_waits * 100) if total_waits > 0 else 0
    print(f"WAIT Accuracy (Drop)     : {wait_accuracy:.1f}%")
    print(f"Premature Books          : {results['premature_books']}")
    print("=" * 60)

if __name__ == "__main__":
    run_backtest()

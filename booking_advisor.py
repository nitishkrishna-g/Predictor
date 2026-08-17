import argparse
from analyze_history import get_seat_intelligence

def get_availability_risk(seats):
    if seats <= 5: return "CRITICAL"
    if seats <= 10: return "HIGH"
    if seats <= 20: return "MEDIUM"
    return "LOW"

def get_recommendation(intel):
    cur_fare = intel["current_fare"]
    expected_min = intel["expected_minimum"]
    prob_drop = intel["probability_of_price_drop"]
    avail = intel.get("available_seats_count", 99)
    comp_journeys = intel.get("comparable_journeys", 0)
    htd = intel.get("hours_to_departure", 0)
    low_window = intel.get("historical_low_window", "Unknown")
    confidence = intel.get("dataset_confidence", "INSUFFICIENT DATA")
    
    risk = get_availability_risk(avail)
    
    recommendation = "WAIT"
    next_check = "In 2-4 hours"
    
    if cur_fare <= expected_min or prob_drop < 15.0:
        recommendation = "BOOK NOW"
        next_check = "N/A"
    elif risk in ["CRITICAL", "HIGH"]:
        recommendation = "BOOK NOW"
        next_check = "N/A"
        
    if confidence == "INSUFFICIENT DATA":
        recommendation = "INSUFFICIENT DATA"
        next_check = "N/A"
        
    # Construct Why Reason
    why = f"Current fare is ₹{cur_fare:.0f}. "
    if confidence == "INSUFFICIENT DATA":
        why += "We need more days of historical data for this route to generate trustworthy predictions."
    elif confidence == "LOW":
        why += "Historical data is limited, prediction may be less reliable. "
    
    if confidence != "INSUFFICIENT DATA":
        if "BOOK" in recommendation:
            if risk in ["CRITICAL", "HIGH"]:
                why += f"Only {avail} seats remain (Risk: {risk}). Secure your seat now before it sells out. "
            else:
                why += f"The probability of the price dropping further is very low ({prob_drop:.0f}%). "
        else:
            why += f"Comparable historical journeys show the lowest fares typically occur {low_window}. "
            expected_savings = cur_fare - expected_min
            if expected_savings > 0:
                why += f"Expected potential saving: ₹{expected_savings:.0f}. "
    
    return recommendation, next_check, risk, confidence, why

def advise(route, date, service_name, seat_type, seat_number=None):
    intel = get_seat_intelligence(route, date, service_name, seat_type, seat_number)
    
    if "error" in intel:
        print(f"ERROR: {intel['error']}")
        return
        
    cur_fare = intel["current_fare"]
    hist_min = intel["historical_min"]
    hist_med = intel["historical_median"]
    htd = intel["hours_to_departure"]
    low_window = intel["historical_low_window"]
    expected_min = intel["expected_minimum"]
    prob_drop = intel["probability_of_price_drop"]
    
    recommendation, next_check, risk, confidence, why = get_recommendation(intel)
        
    print(f"{route}")
    if seat_number:
        print(f"Seat {seat_number} ({seat_type.title()})")
    else:
        print(f"{seat_type.title()}")
    print()
    print(f"Current fare: ₹{cur_fare:.0f}")
    print(f"Time to departure: {htd:.1f}h")
    print(f"Historical minimum: ₹{hist_min:.0f}")
    print(f"Probability of fare drop: {prob_drop:.0f}%")
    print(f"Expected minimum: ₹{expected_min:.0f}")
    print(f"Recommendation: {recommendation}")
    print(f"Confidence: {confidence}")
    print(f"Reason: {why}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--route", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--seat-type", choices=["seater", "sleeper"], required=True)
    parser.add_argument("--seat-number", required=False, help="Specific seat number (optional)")
    
    args = parser.parse_args()
    advise(args.route, args.date, args.service, args.seat_type, args.seat_number)

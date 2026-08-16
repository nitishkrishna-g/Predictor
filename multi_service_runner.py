import json
import os
import time
from datetime import datetime
from playwright.sync_api import sync_playwright

INPUT_FILE = "discovered_services.json"
OUTPUT_DIR = "multi_service_raw"

os.makedirs(OUTPUT_DIR, exist_ok=True)


def parse_seats(data):
    titles = data.get("titles", [])

    if not titles:
        return {"total": 0, "available": 0, "seaters": [], "sleepers": [], "all_seats": []}

    def safe_index(name):
        try:
            return titles.index(name)
        except ValueError:
            return -1

    idx_num = safe_index("Seat Number")
    idx_type = safe_index("Seat Type")
    idx_avail = safe_index("Availability")
    idx_ladies = safe_index("Is Ladies Seat")
    idx_fare = safe_index("Seat Fare")
    idx_disc = safe_index("price_filter")
    idx_row = safe_index("Row ID")
    idx_col = safe_index("Column ID")
    idx_gst = safe_index("GST Amount")
    idx_sc = safe_index("Service Charge")
    idx_toll = safe_index("Toll Fee")
    idx_sf = safe_index("Service Fee")

    all_seats = []
    
    raw_seat_list = data.get("TotalSeatList", {})
    
    if isinstance(raw_seat_list, list):
        # Fallback if list
        raw_seat_list = {"Lower": raw_seat_list}

    if isinstance(raw_seat_list, dict):
        for key, v in raw_seat_list.items():
            if not isinstance(v, list):
                continue
            deck_name = "Lower" if "lower" in key.lower() else "Upper"
            for raw_seat in v:
                if not isinstance(raw_seat, str):
                    continue
                parts = [x.strip() for x in raw_seat.split(",")]
                if len(parts) <= max(idx_num, idx_type, idx_avail, idx_ladies, idx_fare):
                    continue
                
                seat_number = parts[idx_num]
                seat_type = parts[idx_type]
                available = (parts[idx_avail] == "Y")
                ladies_seat = (parts[idx_ladies] == "F")
                
                try: fare_value = float(parts[idx_fare])
                except: fare_value = 0.0
                
                try: discounted_value = float(parts[idx_disc]) if idx_disc != -1 else float(parts[-1])
                except: discounted_value = 0.0
                if discounted_value == 0.0:
                    discounted_value = fare_value

                def get_int(idx):
                    if idx != -1 and len(parts) > idx:
                        try: return int(parts[idx])
                        except: return None
                    return None
                    
                def get_float(idx):
                    if idx != -1 and len(parts) > idx:
                        try: return float(parts[idx])
                        except: return None
                    return None
                
                all_seats.append({
                    "seat_number": seat_number,
                    "deck": deck_name,
                    "seat_type": seat_type,
                    "row_id": get_int(idx_row),
                    "column_id": get_int(idx_col),
                    "available": available,
                    "ladies_seat": ladies_seat,
                    "seat_fare": fare_value,
                    "discounted_fare": discounted_value,
                    "gst": get_float(idx_gst),
                    "service_charge": get_float(idx_sc),
                    "toll_fee": get_float(idx_toll),
                    "service_fee": get_float(idx_sf)
                })

    available_seats_list = [s for s in all_seats if s["available"]]

    seaters = [s for s in available_seats_list if s["seat_type"] == "SS" and not s["ladies_seat"]]
    sleepers = [s for s in available_seats_list if s["seat_type"] in ("LB", "UB") and not s["ladies_seat"]]

    return {
        "total": len(all_seats),
        "available": len(available_seats_list),
        "seaters": seaters,
        "sleepers": sleepers,
        "all_seats": all_seats
    }


def cheapest(seats):
    if not seats:
        return None

    return min(
        seats,
        key=lambda seat: seat["discounted_fare"]
    )


def scrape_service(page, service):
    service_key = service["serviceKey"]
    service_id = service["serviceId"]

    url = (
        "https://www.abhibus.com/"
        f"seat-layout-web/?serviceKey={service_id}"
    )

    captured = None

    def handle_response(response):
        nonlocal captured

        if captured is not None:
            return

        if response.status != 200:
            return

        if "/wap/GetSeatLayout" not in response.url:
            return

        print("FOUND API")
        print(f"URL    : {response.url}")
        print(f"STATUS : {response.status}")

        try:
            captured = response.json()
            print("JSON CAPTURED")
        except Exception as e:
            print(f"JSON ERROR: {e}")

    page.on("response", handle_response)

    print()
    print("=" * 70)
    print("SCRAPING SERVICE")
    print("=" * 70)
    print(f"Operator       : {service['travelerAgentName']}")
    print(f"Service Key    : {service_key}")
    print(f"Service ID     : {service['serviceId']}")
    print(f"Bus Type       : {service['busTypeName']}")
    print(f"Departure      : {service['originDateTime']}")
    print(f"URL            : {url}")

    print()
    print("Opening seat layout...")

    try:
        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000
        )
    except Exception as e:
        print(f"PAGE LOAD WARNING: {e}")

    print("Waiting for GetSeatLayout...")
    start_wait = time.time()
    while captured is None and time.time() - start_wait < 30:
        page.wait_for_timeout(1000)

    if captured is None:
        print("ERROR: GetSeatLayout was not captured")
        return None

    raw_filename = (
        f"seat_{service_key.replace('/', '_')}.json"
    )

    raw_path = os.path.join(
        OUTPUT_DIR,
        raw_filename
    )

    with open(
        raw_path,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            captured,
            f,
            ensure_ascii=False,
            indent=2
        )

    parsed = parse_seats(captured)

    cheapest_seater = cheapest(parsed["seaters"])
    cheapest_sleeper = cheapest(parsed["sleepers"])

    result = {
        "scrapedAt": datetime.now().astimezone().isoformat(),
        "serviceKey": service_key,
        "serviceId": service["serviceId"],
        "operatorId": service["operatorId"],
        "operator": service["travelerAgentName"],
        "serviceName": service["serviceName"],
        "serviceNumber": service["serviceNumber"],
        "busType": service["busTypeName"],
        "originDateTime": service["originDateTime"],
        "route": captured.get("Route"),
        "journeyDate": captured.get("JourneyDate"),
        "totalSeats": parsed["total"],
        "availableSeats": parsed["available"],
        "availableSeaters": len(parsed["seaters"]),
        "availableSleepers": len(parsed["sleepers"]),
        "cheapestSeater": cheapest_seater,
        "cheapestSleeper": cheapest_sleeper,
        "seats": parsed["all_seats"],
        "rawFile": raw_path
    }

    print()
    print("=" * 70)
    print("ABHIBUS RESULT")
    print("=" * 70)

    print(f"Service Key       : {service_key}")
    print(f"Operator          : {service['travelerAgentName']}")
    print(f"Route             : {captured.get('Route')}")
    print(f"Journey Date      : {captured.get('JourneyDate')}")
    print(f"Service No        : {captured.get('serviceNo')}")
    print(f"Bus Type          : {captured.get('busTypeName')}")
    print(f"Total seats       : {parsed['total']}")
    print(f"Available seats   : {parsed['available']}")
    print(f"Available seaters : {len(parsed['seaters'])}")
    print(f"Available sleepers: {len(parsed['sleepers'])}")

    print()
    print("CHEAPEST SEATER")

    if cheapest_seater:
        print(
            f"{cheapest_seater['seat_number']} "
            f"Rs.{cheapest_seater['discounted_fare']:.0f}"
        )
    else:
        print("None")

    print()
    print("CHEAPEST SLEEPER")

    if cheapest_sleeper:
        print(
            f"{cheapest_sleeper['seat_number']} "
            f"Rs.{cheapest_sleeper['discounted_fare']:.0f}"
        )
    else:
        print("None")

    print()
    print(f"RAW JSON SAVED: {raw_path}")

    page.remove_listener("response", handle_response)

    return result


def scrape_seats(input_file="discovered_services.json", output_file="seat_scrape_results.json"):
    try:
        with open(
            input_file,
            "r",
            encoding="utf-8"
        ) as f:
            discovery = json.load(f)
    except Exception as e:
        print(f"Failed to read {input_file}: {e}")
        return False

    services = discovery.get("services", [])

    print("=" * 70)
    print("MULTI-SERVICE SEAT SCRAPER")
    print("=" * 70)
    print(f"Route       : {discovery.get('route')}")
    print(f"Journey Date: {discovery.get('journeyDate')}")
    print(f"Services    : {len(services)}")

    if not services:
        print("No services found.")
        return

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False
        )

        for service in services:
            try:
                # Use a FRESH page for each service to avoid listener cross-contamination
                page = browser.new_page(
                    viewport={
                        "width": 1280,
                        "height": 720
                    }
                )
                result = scrape_service(
                    page,
                    service
                )
                page.close()

                if result:
                    results.append(result)
                
                # Prevent AbhiBus rate-limiting
                import time
                time.sleep(10)
            except Exception as e:
                print(f"Error scraping service {service.get('serviceKey', 'UNKNOWN')}: {e}")

        browser.close()

    output = {
        "scrapedAt": datetime.now().astimezone().isoformat(),
        "route": discovery.get("route"),
        "journeyDate": discovery.get("journeyDate"),
        "successfulServices": len(results),
        "totalServices": len(services),
        "results": results
    }

    with open(
        output_file,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2
        )

    print()
    print("=" * 70)
    print("MULTI-SERVICE SCRAPE COMPLETE")
    print("=" * 70)
    print(
        f"Successful services: "
        f"{len(results)}/{len(services)}"
    )
    print(f"Results: {output_file}")
    
    return True


if __name__ == "__main__":
    scrape_seats(INPUT_FILE, "seat_scrape_results.json")

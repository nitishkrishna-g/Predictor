import json
import os
import time
from datetime import datetime
import queue
import threading
from playwright.sync_api import sync_playwright



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
                if idx_num == -1 or idx_type == -1 or idx_avail == -1:
                    continue
                if len(parts) <= max(idx_num, idx_type, idx_avail):
                    continue
                
                seat_number = parts[idx_num]
                seat_type = parts[idx_type]
                available = (parts[idx_avail] == "Y")
                ladies_seat = (parts[idx_ladies] == "F") if idx_ladies != -1 and len(parts) > idx_ladies else False
                
                try: fare_value = float(parts[idx_fare]) if idx_fare != -1 and len(parts) > idx_fare else 0.0
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


def scrape_service(page, service, output_dir=".", request_timeout=15):
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
            timeout=request_timeout * 1000
        )
    except Exception as e:
        print(f"PAGE LOAD WARNING: {e}")

    print("Waiting for GetSeatLayout...")
    start_wait = time.time()
    while captured is None and time.time() - start_wait < request_timeout:
        page.wait_for_timeout(1000)

    if captured is None:
        print("ERROR: GetSeatLayout was not captured")
        return {
            "status": "FAILED", 
            "reason": "GET_SEAT_LAYOUT_TIMEOUT",
            "serviceKey": service_key,
            "operator": service["travelerAgentName"],
            "route": service.get("_route_name", "Unknown"),
            "journeyDate": service.get("_date_str", "Unknown")
        }

    raw_filename = (
        f"seat_{service_key.replace('/', '_')}.json"
    )

    raw_path = os.path.join(
        output_dir,
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
    
    # Validation: SEAT COMPLETENESS
    # Calculate API's stated total seats directly from TotalSeatList elements
    api_total_seats = 0
    raw_seat_list = captured.get("TotalSeatList", {})
    if isinstance(raw_seat_list, list):
        api_total_seats = len(raw_seat_list)
    elif isinstance(raw_seat_list, dict):
        for k, v in raw_seat_list.items():
            if isinstance(v, list):
                api_total_seats += len(v)
                
    if api_total_seats > 0 and api_total_seats != parsed["total"]:
        print(f"INCOMPLETE: API expects {api_total_seats} seats but parsed {parsed['total']}")
        return {
            "status": "INCOMPLETE",
            "reason": f"SEAT_COUNT_MISMATCH: API declared {api_total_seats}, Parsed {parsed['total']}",
            "serviceKey": service_key,
            "operator": service["travelerAgentName"],
            "route": service.get("_route_name", "Unknown"),
            "journeyDate": service.get("_date_str", "Unknown")
        }

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
        "rawFile": raw_path,
        "status": "SUCCESS"
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


def worker_task(worker_id, service_queue, results_list, output_dir, lock, request_timeout=15, max_retries=2):
    # Each thread gets its own playwright instance (and thus its own browser)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            while True:
                try:
                    service = service_queue.get(block=False)
                except queue.Empty:
                    break
                
                start_proc = time.time()
                try:
                    result = None
                    last_error_reason = "Unknown Error"
                    
                    # Convert to max attempts (retries + 1)
                    max_attempts = max_retries + 1
                    
                    for attempt in range(max_attempts):
                        try:
                            page = browser.new_page(viewport={"width": 1280, "height": 720})
                            result = scrape_service(page, service, output_dir, request_timeout)
                            page.close()
                            
                            if result:
                                if result.get("status") == "SUCCESS":
                                    if result.get("totalSeats", 0) > 0:
                                        break
                                    else:
                                        with lock:
                                            print(f"[Worker {worker_id}] Attempt {attempt+1}: 0 seats found. Retrying...")
                                        result = {"status": "FAILED", "reason": "0_SEATS_PARSED"}
                                        if attempt < max_attempts - 1:
                                            time.sleep(2)
                                else:
                                    # It's an explicit FAILED or INCOMPLETE dictionary returned
                                    last_error_reason = result.get("reason", "Unknown Failure")
                                    with lock:
                                        print(f"[Worker {worker_id}] Attempt {attempt+1}: {last_error_reason}. Retrying...")
                                    
                                    # Short-circuit logic: Don't retry if INCOMPLETE (parsing mismatch)
                                    if result.get("status") == "INCOMPLETE":
                                        break
                                        
                                    if attempt < max_attempts - 1:
                                        time.sleep(2)
                            else:
                                last_error_reason = "Scrape returned None"
                                with lock:
                                    print(f"[Worker {worker_id}] Attempt {attempt+1}: Scrape failed. Retrying...")
                                if attempt < max_attempts - 1:
                                    time.sleep(2)
                        except Exception as ex:
                            last_error_reason = f"BROWSER_ERROR: {str(ex)[:50]}"
                            with lock:
                                print(f"[Worker {worker_id}] Attempt {attempt+1} error: {ex}")
                            try: page.close()
                            except: pass
                            if attempt < max_attempts - 1:
                                time.sleep(2)
                            
                    proc_dur = time.time() - start_proc
                    
                    if result and result.get("status") == "SUCCESS" and result.get("totalSeats", 0) > 0:
                        result["processingDuration"] = proc_dur
                        with lock:
                            results_list.append(result)
                        # Standard safety delay for successful pulls to avoid rate limit
                        time.sleep(10)
                    else:
                        # Append the failure record for reporting
                        fail_rec = result if (result and result.get("status") != "SUCCESS") else {
                            "status": "FAILED",
                            "reason": last_error_reason,
                            "serviceKey": service.get("serviceKey"),
                            "operator": service.get("travelerAgentName", "Unknown"),
                            "route": service.get("_route_name", "Unknown"),
                            "journeyDate": service.get("_date_str", "Unknown")
                        }
                        # Add retry count to failure record
                        fail_rec["retryCount"] = max_attempts
                        fail_rec["processingDuration"] = proc_dur
                        
                        # We also keep raw service dict so collector.py can push it to failed_queue.json
                        fail_rec["_raw_service"] = service
                        
                        with lock:
                            results_list.append(fail_rec)
                            
                        # SHORT-CIRCUIT WAIT
                        # Do NOT sleep for 10 seconds if it failed to save time. 
                        # Immediate take Service B
                        time.sleep(1)
                        
                except Exception as e:
                    with lock:
                        print(f"[Worker {worker_id}] Error scraping service {service.get('serviceKey', 'UNKNOWN')}: {e}")
                finally:
                    service_queue.task_done()
                    
            browser.close()
    except Exception as e:
        with lock:
            print(f"[Worker {worker_id}] Fatal Playwright Error: {e}")

def scrape_seats_parallel(services, num_workers=5, output_dir=".", output_file="seat_scrape_results.json", request_timeout=15, max_retries=2):
    print("=" * 70)
    print("MULTI-SERVICE PARALLEL SEAT SCRAPER")
    print("=" * 70)
    print(f"Services to scrape: {len(services)}")
    print(f"Workers           : {num_workers}")
    print(f"Request Timeout   : {request_timeout}s")
    print(f"Max Retries       : {max_retries}")

    if not services:
        print("No services found.")
        return []

    service_queue = queue.Queue()
    for s in services:
        service_queue.put(s)
        
    results_list = []
    lock = threading.Lock()
    
    threads = []
    for i in range(num_workers):
        t = threading.Thread(target=worker_task, args=(i+1, service_queue, results_list, output_dir, lock, request_timeout, max_retries))
        t.start()
        threads.append(t)
        
    for t in threads:
        t.join()

    # We will let collector.py write the final JSON so it can group by route properly,
    # or just return the results.
    print()
    print("=" * 70)
    print("PARALLEL SCRAPE COMPLETE")
    print("=" * 70)
    print(f"Successful services: {len(results_list)}/{len(services)}")
    
    return results_list


if __name__ == "__main__":
    # Test stub
    pass

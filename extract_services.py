import json
import argparse
from datetime import datetime
from playwright.sync_api import sync_playwright

TARGET_OPERATORS = {
    "fresh bus",
    "freshbus",
    "nuego",
    "neogo",
    "zingbus"
}

RAW_FILE = "services_discovery_raw.json"
OUTPUT_FILE = "discovered_services.json"

def is_target_operator(service):
    operator = str(service.get("travelerAgentName", "")).strip().lower()
    service_name = str(service.get("serviceName", "")).strip().lower()
    service_number = str(service.get("serviceNumber", "")).strip().lower()

    for target in TARGET_OPERATORS:
        if target in operator:
            return True
        if target in service_name:
            return True
        if target in service_number:
            return True

    return False

def extract_service(service):
    # Parse real departure time from timings object (e.g. 2026-08-16T22:45:00+05:30)
    dt_str = service.get("timings", {}).get("startTimeDateFormat")
    real_time = dt_str[:16].replace("T", " ") if dt_str else service.get("originDateTime")
    
    return {
        "serviceKey": service.get("serviceKey"),
        "serviceId": service.get("serviceId"),
        "operatorId": service.get("operatorId"),
        "travelerAgentName": service.get("travelerAgentName"),
        "serviceName": service.get("serviceName"),
        "serviceNumber": service.get("serviceNumber"),
        "busTypeName": service.get("busTypeName"),
        "busServiceTypeName": service.get("busServiceTypeName"),
        "originDateTime": real_time
    }

def run_discovery(from_city, from_id, to_city, to_id, journey_date):
    SOURCE_CITY = from_city
    SOURCE_ID = from_id
    DEST_CITY = to_city
    DEST_ID = to_id
    JOURNEY_DATE = journey_date
    
    SEARCH_URL = (
        f"https://www.abhibus.com/bus_search/"
        f"{SOURCE_CITY}/{SOURCE_ID}/"
        f"{DEST_CITY}/{DEST_ID}/"
        f"{datetime.strptime(JOURNEY_DATE, '%Y-%m-%d').strftime('%d-%m-%Y')}/O"
    )
    
    captured_data = None
    captured_url = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        page = browser.new_page(viewport={"width": 1280, "height": 720})

        def handle_response(response):
            nonlocal captured_data, captured_url
            if captured_data is not None:
                return
            if response.status != 200:
                return
            if "/buslist/v3/services" not in response.url:
                return
            if "/buslist/v3/services/meta/" in response.url:
                return

            print()
            print("SERVICES API FOUND")
            print(f"URL    : {response.url}")
            print(f"STATUS : {response.status}")

            try:
                captured_data = response.json()
                captured_url = response.url
                print("JSON CAPTURED")
            except Exception as e:
                print(f"JSON ERROR: {e}")

        page.on("response", handle_response)

        print("=" * 70)
        print("ABHIBUS SERVICE DISCOVERY")
        print("=" * 70)
        print(f"Route       : {SOURCE_CITY} -> {DEST_CITY}")
        print(f"Journey Date: {JOURNEY_DATE}")
        print(f"URL         : {SEARCH_URL}")
        print()
        print("Opening search page...")

        try:
            page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"PAGE LOAD WARNING: {e}")

        print("Page loaded.")
        print(f"Current URL: {page.url}")

        print()
        print("Waiting for services API...")

        for second in range(60):
            if captured_data is not None:
                break
            page.wait_for_timeout(1000)
            if second % 5 == 4:
                print(f"Still waiting... {second + 1}/60 seconds")

        if captured_data is None:
            print()
            print("=" * 70)
            print("SERVICES API NOT CAPTURED")
            print("=" * 70)
            browser.close()
            return

        with open(RAW_FILE, "w", encoding="utf-8") as f:
            json.dump(captured_data, f, ensure_ascii=False, indent=2)

        services = captured_data.get("services", [])
        selected = []

        for service in services:
            if not is_target_operator(service):
                continue
                
            extracted = extract_service(service)
            
            # Required fields validation
            required = [
                extracted.get("serviceKey"),
                extracted.get("serviceId"),
                extracted.get("operatorId"),
                extracted.get("travelerAgentName"),
                extracted.get("serviceName"),
                extracted.get("serviceNumber"),
                extracted.get("busTypeName"),
                extracted.get("originDateTime")
            ]
            
            if any(val is None or str(val).strip() == "" for val in required):
                print(f"WARNING: Skipping incomplete service {extracted.get('serviceKey', 'UNKNOWN')}")
                continue
                
            selected.append(extracted)

        output = {
            "route": f"{SOURCE_CITY}-{DEST_CITY}",
            "source": SOURCE_CITY,
            "sourceId": SOURCE_ID,
            "destination": DEST_CITY,
            "destinationId": DEST_ID,
            "journeyDate": JOURNEY_DATE,
            "scrapedAt": datetime.now().astimezone().isoformat(),
            "apiUrl": captured_url,
            "totalServicesReturned": len(services),
            "targetServicesFound": len(selected),
            "services": selected
        }

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        print()
        print("=" * 70)
        print("SERVICES API RESULT")
        print("=" * 70)
        print(f"Total services returned : {len(services)}")
        print(f"Target services found   : {len(selected)}")

        print()
        print("=" * 70)
        print("TARGET SERVICES")
        print("=" * 70)

        if not selected:
            print("NO FRESHBUS / NEOG0 / ZINGBUS SERVICES FOUND")
        else:
            for index, service in enumerate(selected, 1):
                print()
                print(f"SERVICE {index}")
                print("-" * 70)
                print(f"Operator       : {service['travelerAgentName']}")
                print(f"Service Key    : {service['serviceKey']}")
                print(f"Service ID     : {service['serviceId']}")
                print(f"Operator ID    : {service['operatorId']}")
                print(f"Service Name   : {service['serviceName']}")
                print(f"Service Number : {service['serviceNumber']}")
                print(f"Bus Type       : {service['busTypeName']}")
                print(f"Departure      : {service['originDateTime']}")

        print()
        print("=" * 70)
        print("DISCOVERY COMPLETE")
        print("=" * 70)
        print(f"RAW API : {RAW_FILE}")
        print(f"OUTPUT  : {OUTPUT_FILE}")

        browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="from_city", required=True)
    parser.add_argument("--from-id", required=True)
    parser.add_argument("--to", dest="to_city", required=True)
    parser.add_argument("--to-id", required=True)
    parser.add_argument("--date", required=True)
    
    args = parser.parse_args()
    run_discovery(args.from_city, args.from_id, args.to_city, args.to_id, args.date)

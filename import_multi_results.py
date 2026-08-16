import json
import sqlite3

DB = "abhibus.db"
RESULTS = "seat_scrape_results.json"


def normalize_route(route):
    """Normalize route name to canonical form: Bangalore-Coimbatore or Coimbatore-Bangalore"""
    if not route:
        return route
    r = route.lower().replace(' ', '')
    blr_first = any(r.startswith(x) for x in ['bangalore', 'bengaluru'])
    cbe_first = r.startswith('coimbatore')
    if blr_first:
        return 'Bangalore-Coimbatore'
    elif cbe_first:
        return 'Coimbatore-Bangalore'
    return route


def get_or_create_service(conn, service):
    row = conn.execute(
        """
        SELECT id
        FROM services
        WHERE service_key = ?
        AND journey_date = ?
        """,
        (
            service["serviceKey"],
            service["journeyDate"]
        )
    ).fetchone()

    canonical_route = normalize_route(service.get("route", ""))

    if row:
        service_db_id = row[0]

        conn.execute(
            """
            UPDATE services
            SET
                route = ?,
                service_no = ?,
                bus_type = ?,
                abhibus_service_id = ?,
                operator_id = ?,
                operator = ?,
                service_name = ?,
                departure = ?
            WHERE id = ?
            """,
            (
                canonical_route,
                service["serviceNumber"],
                service["busType"],
                service["serviceId"],
                service["operatorId"],
                service["operator"],
                service["serviceName"],
                service["originDateTime"],
                service_db_id
            )
        )

        return service_db_id

    cursor = conn.execute(
        """
        INSERT INTO services (
            service_key,
            route,
            journey_date,
            service_no,
            bus_type,
            abhibus_service_id,
            operator_id,
            operator,
            service_name,
            departure
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            service["serviceKey"],
            canonical_route,
            service["journeyDate"],
            service["serviceNumber"],
            service["busType"],
            service["serviceId"],
            service["operatorId"],
            service["operator"],
            service["serviceName"],
            service["originDateTime"]
        )
    )

    return cursor.lastrowid


def import_service(conn, service):
    service_db_id = get_or_create_service(conn, service)

    seats = service.get("seats", [])

    available_seats = [
        seat for seat in seats
        if seat.get("available") is True
    ]

    available_seaters = [
        seat for seat in available_seats
        if seat.get("seat_type") == "SS"
    ]

    available_sleepers = [
        seat for seat in available_seats
        if seat.get("seat_type") in ("LB", "UB")
    ]

    seater_fares = [
        seat.get("discounted_fare")
        for seat in available_seaters
        if seat.get("discounted_fare") is not None
    ]

    sleeper_fares = [
        seat.get("discounted_fare")
        for seat in available_sleepers
        if seat.get("discounted_fare") is not None
    ]

    cheapest_seater = min(seater_fares) if seater_fares else None
    cheapest_sleeper = min(sleeper_fares) if sleeper_fares else None

    cursor = conn.execute(
        """
        INSERT INTO scrapes (
            service_id,
            scraped_at,
            total_seats,
            available_seats,
            available_seaters,
            available_sleepers,
            cheapest_seater,
            cheapest_sleeper
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            service_db_id,
            service["scrapedAt"],
            len(seats),
            len(available_seats),
            len(available_seaters),
            len(available_sleepers),
            cheapest_seater,
            cheapest_sleeper
        )
    )

    scrape_id = cursor.lastrowid

    for seat in seats:
        conn.execute(
            """
            INSERT INTO seats (
                scrape_id,
                seat_number,
                deck,
                seat_type,
                row_id,
                column_id,
                available,
                ladies_seat,
                seat_fare,
                discounted_fare,
                gst,
                service_charge,
                toll_fee,
                service_fee
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scrape_id,
                seat.get("seat_number"),
                seat.get("deck"),
                seat.get("seat_type"),
                seat.get("row_id"),
                seat.get("column_id"),
                1 if seat.get("available") else 0,
                1 if seat.get("ladies_seat") else 0,
                seat.get("seat_fare"),
                seat.get("discounted_fare"),
                seat.get("gst"),
                seat.get("service_charge"),
                seat.get("toll_fee"),
                seat.get("service_fee")
            )
        )

    print("=" * 70)
    print("SNAPSHOT IMPORTED")
    print("=" * 70)
    print(f"Service DB ID      : {service_db_id}")
    print(f"Service Key        : {service['serviceKey']}")
    print(f"AbhiBus Service ID : {service['serviceId']}")
    print(f"Operator           : {service['operator']}")
    print(f"Route              : {service['route']}")
    print(f"Journey Date       : {service['journeyDate']}")
    print(f"Service No         : {service['serviceNumber']}")
    print(f"Bus Type           : {service['busType']}")
    print(f"Departure          : {service['originDateTime']}")
    print(f"Scrape ID          : {scrape_id}")
    print(f"Total seats        : {len(seats)}")
    print(f"Available seats    : {len(available_seats)}")
    print(f"Available seaters  : {len(available_seaters)}")
    print(f"Available sleepers : {len(available_sleepers)}")
    print(f"Cheapest seater    : {cheapest_seater}")
    print(f"Cheapest sleeper   : {cheapest_sleeper}")
    print(f"Seats inserted     : {len(seats)}")
    print()


def import_results(results_file="seat_scrape_results.json", db_path="abhibus.db"):
    try:
        with open(results_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Failed to read {results_file}: {e}")
        return False

    results = data.get("results", [])

    if not results:
        print("No service results found.")
        return

    conn = sqlite3.connect(db_path)

    try:
        conn.execute("PRAGMA foreign_keys = ON")

        for service in results:
            try:
                import_service(conn, service)
            except Exception as e:
                print(f"Error importing service {service.get('serviceKey', 'UNKNOWN')}: {e}")
                # Continue importing other services
                
        conn.commit()

        print("=" * 70)
        print("MULTI-SERVICE SQLITE IMPORT COMPLETE")
        print("=" * 70)
        print(f"Services imported : {len(results)}")
        print(f"Database          : {db_path}")

        return True

    except Exception:
        conn.rollback()
        print("IMPORT FAILED - TRANSACTION ROLLED BACK")
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    import_results(RESULTS, DB)

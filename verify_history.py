import sqlite3
import sys
import io
from collections import defaultdict

DB = "abhibus.db"

def verify_database(db_path="abhibus.db", log_file=None):
    conn = sqlite3.connect(db_path)
    
    # Capture output if a log file is provided
    output = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = output if log_file else sys.stdout
    
    # Basic counts
    services_count = conn.execute("SELECT COUNT(*) FROM services").fetchone()[0]
    scrapes_count = conn.execute("SELECT COUNT(*) FROM scrapes").fetchone()[0]
    seats_count = conn.execute("SELECT COUNT(*) FROM seats").fetchone()[0]
    
    # Operators
    operators = conn.execute("SELECT operator, COUNT(*) FROM services GROUP BY operator").fetchall()
    
    # Scrape timeline
    # We want to see Service (Operator + Departure), Scrapes, First, Last
    timeline = conn.execute("""
        SELECT 
            s.operator || ' ' || substr(s.departure, 12, 5) as service_name,
            COUNT(sc.id) as scrape_count,
            MIN(sc.scraped_at) as first_scrape,
            MAX(sc.scraped_at) as last_scrape
        FROM services s
        JOIN scrapes sc ON s.id = sc.service_id
        GROUP BY s.id
        ORDER BY s.operator, s.departure
    """).fetchall()
    
    # Fare history
    fares = conn.execute("""
        SELECT 
            s.operator || ' ' || substr(s.departure, 12, 5) as service_name,
            MIN(sc.cheapest_seater) as min_seater,
            MAX(sc.cheapest_seater) as max_seater,
            MIN(sc.cheapest_sleeper) as min_sleeper,
            MAX(sc.cheapest_sleeper) as max_sleeper
        FROM services s
        JOIN scrapes sc ON s.id = sc.service_id
        GROUP BY s.id
        ORDER BY s.operator, s.departure
    """).fetchall()
    
    print("=" * 70)
    print("HISTORY VERIFICATION")
    print("=" * 70)
    print(f"Database       : {DB}")
    print(f"Services       : {services_count}")
    print(f"Scrapes        : {scrapes_count}")
    print(f"Seats          : {seats_count}")
    print()
    print("Operators")
    print("-" * 70)
    for op, count in operators:
        print(f"{op or 'Unknown':<15}: {count}")
        
    print()
    print("SCRAPE TIMELINE")
    print("-" * 70)
    print(f"{'Service':<30} {'Scrapes':<10} {'First':<25} {'Last':<25}")
    for name, count, first, last in timeline:
        # truncate time for display if needed
        first_short = first[11:16] if first and len(first) > 16 else str(first)
        last_short = last[11:16] if last and len(last) > 16 else str(last)
        safe_name = name if name else "Unknown Service"
        print(f"{safe_name:<30} {count:<10} {first_short:<25} {last_short:<25}")

    print()
    print("FARE HISTORY")
    print("-" * 70)
    print(f"{'Service':<30} {'Min (Seat/Sleep)':<20} {'Max (Seat/Sleep)'}")
    for name, min_seat, max_seat, min_sleep, max_sleep in fares:
        min_s = f"Rs.{min_seat:.0f}" if min_seat is not None else "N/A"
        max_s = f"Rs.{max_seat:.0f}" if max_seat is not None else "N/A"
        min_sl = f"Rs.{min_sleep:.0f}" if min_sleep is not None else "N/A"
        max_sl = f"Rs.{max_sleep:.0f}" if max_sleep is not None else "N/A"
        safe_name = name if name else "Unknown Service"
        print(f"{safe_name:<30} {min_s}/{min_sl:<15} {max_s}/{max_sl}")

    # Integrity
    print()
    print("DATABASE INTEGRITY")
    print("-" * 70)
    
    # Check foreign keys
    fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    
    # Orphans
    orphan_seats = conn.execute("SELECT COUNT(*) FROM seats WHERE scrape_id NOT IN (SELECT id FROM scrapes)").fetchone()[0]
    orphan_scrapes = conn.execute("SELECT COUNT(*) FROM scrapes WHERE service_id NOT IN (SELECT id FROM services)").fetchone()[0]
    
    # Duplicates (same service, same scrape time)
    duplicates = conn.execute("SELECT service_id, scraped_at, COUNT(*) FROM scrapes GROUP BY service_id, scraped_at HAVING COUNT(*) > 1").fetchall()
    
    # Zero seats in scrapes
    zero_seats = conn.execute("SELECT COUNT(*) FROM scrapes WHERE total_seats = 0").fetchone()[0]
    
    # Invalid operators
    valid_ops = ["freshbus", "zingbus", "zingbus plus", "neogo"]
    invalid_ops = conn.execute(f"SELECT COUNT(*) FROM services WHERE LOWER(operator) NOT IN ({','.join(['?']*len(valid_ops))})", valid_ops).fetchone()[0]
    
    # Invalid routes
    valid_routes = ["Bangalore-Coimbatore", "Coimbatore-Bangalore"]
    invalid_routes = conn.execute(f"SELECT COUNT(*) FROM services WHERE route NOT IN ({','.join(['?']*len(valid_routes))})", valid_routes).fetchone()[0]
    
    # Negative fares
    negative_fares = conn.execute("SELECT COUNT(*) FROM seats WHERE seat_fare < 0 OR discounted_fare < 0").fetchone()[0]
    
    # Invalid boolean flags
    invalid_flags = conn.execute("SELECT COUNT(*) FROM seats WHERE available NOT IN (0, 1) OR ladies_seat NOT IN (0, 1)").fetchone()[0]
    
    print(f"Services            : {'OK' if services_count > 0 else 'EMPTY'}")
    print(f"Scrapes             : {'OK' if scrapes_count > 0 else 'EMPTY'}")
    print(f"Seats               : {'OK' if seats_count > 0 else 'EMPTY'}")
    print(f"Foreign references  : {'OK' if len(fk_errors) == 0 else 'FAILED'}")
    print(f"Orphan seats        : {'OK' if orphan_seats == 0 else orphan_seats}")
    print(f"Orphan scrapes      : {'OK' if orphan_scrapes == 0 else orphan_scrapes}")
    print(f"Duplicate snapshots : {'OK' if len(duplicates) == 0 else len(duplicates)}")
    print(f"0-seat scrapes      : {'OK' if zero_seats == 0 else zero_seats}")
    print(f"Invalid operators   : {'OK' if invalid_ops == 0 else invalid_ops}")
    print(f"Invalid routes      : {'OK' if invalid_routes == 0 else invalid_routes}")
    print(f"Negative fares      : {'OK' if negative_fares == 0 else negative_fares}")
    print(f"Invalid bool flags  : {'OK' if invalid_flags == 0 else invalid_flags}")
    
    print()
    all_ok = len(fk_errors) == 0 and services_count > 0 and orphan_seats == 0 and orphan_scrapes == 0 and len(duplicates) == 0 and invalid_ops == 0 and invalid_routes == 0 and negative_fares == 0 and invalid_flags == 0
    if all_ok:
        print("STATUS: HEALTHY")
    else:
        print("STATUS: ISSUES FOUND")

    if log_file:
        sys.stdout = old_stdout
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(output.getvalue())
        print(output.getvalue(), end="") # Also print to console
        
    conn.close()
    return all_ok

if __name__ == "__main__":
    verify_database(DB)

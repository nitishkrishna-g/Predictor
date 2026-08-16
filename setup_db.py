import sqlite3

def setup_db(db_path="abhibus.db"):
    conn = sqlite3.connect(db_path)
    
    conn.execute("""
    CREATE TABLE IF NOT EXISTS services (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service_key TEXT,
        route TEXT,
        journey_date TEXT,
        service_no TEXT,
        bus_type TEXT,
        abhibus_service_id TEXT,
        operator_id TEXT,
        operator TEXT,
        service_name TEXT,
        departure TEXT,
        UNIQUE(service_key, journey_date)
    )
    """)
    
    conn.execute("""
    CREATE TABLE IF NOT EXISTS scrapes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service_id INTEGER,
        scraped_at TEXT,
        total_seats INTEGER,
        available_seats INTEGER,
        available_seaters INTEGER,
        available_sleepers INTEGER,
        cheapest_seater REAL,
        cheapest_sleeper REAL,
        FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE CASCADE,
        UNIQUE(service_id, scraped_at)
    )
    """)
    
    conn.execute("""
    CREATE TABLE IF NOT EXISTS seats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scrape_id INTEGER,
        seat_number TEXT,
        deck TEXT,
        seat_type TEXT,
        row_id INTEGER,
        column_id INTEGER,
        available INTEGER,
        ladies_seat INTEGER,
        seat_fare REAL,
        discounted_fare REAL,
        gst REAL,
        service_charge REAL,
        toll_fee REAL,
        service_fee REAL,
        FOREIGN KEY (scrape_id) REFERENCES scrapes(id) ON DELETE CASCADE
    )
    """)
    
    conn.commit()
    conn.close()
    print("Database initialized.")

if __name__ == "__main__":
    setup_db()

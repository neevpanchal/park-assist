"""
database.py
------------
Sets up our SQLite database: creates tables and adds starter data.

CHANGE IN THIS VERSION:
Booking is now HOURLY. Instead of a slot being simply "Available/Booked"
forever, each slot can be booked for a specific date + specific 1-hour
time range (e.g. "2026-09-15", "08:00" to "09:00"). So the same physical
slot (e.g. A1) can have many different bookings on many different days
and hours, as long as they don't clash.

Because of this, we removed the old 'status' column from the slots
table (it doesn't make sense anymore - a slot isn't just "Available" or
"Booked", it depends on WHICH hour you're asking about).
"""

import os
import shutil
import sqlite3
import tempfile

# In Vercel serverless environment, the root filesystem is read-only.
# We store the SQLite database in the system temporary directory (e.g. /tmp on Vercel/Linux).
if os.environ.get("VERCEL"):
    DATABASE_NAME = os.path.join(tempfile.gettempdir(), "parking.db")
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATABASE_NAME = os.path.join(BASE_DIR, "parking.db")


def get_connection():
    if not os.path.exists(DATABASE_NAME):
        initialize_database()
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database():
    # If running on Vercel and local starter parking.db exists, copy it over if needed
    if os.environ.get("VERCEL"):
        local_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "parking.db")
        if not os.path.exists(DATABASE_NAME) and os.path.exists(local_db):
            try:
                shutil.copyfile(local_db, DATABASE_NAME)
            except Exception:
                pass

    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # ---------- USERS TABLE ----------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            vehicle_number TEXT,
            role TEXT NOT NULL DEFAULT 'student'
        )
    """)

    # ---------- SLOTS TABLE ----------
    # Just describes the physical parking spot. No "status" column anymore -
    # availability now depends on date + hour, which lives in "bookings".
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_number TEXT UNIQUE NOT NULL,
            slot_type TEXT NOT NULL DEFAULT 'Car',
            location TEXT NOT NULL DEFAULT 'Main Campus'
        )
    """)

    # ---------- BOOKINGS TABLE ----------
    # booking_date : which day, e.g. "2026-09-15"
    # start_time   : e.g. "08:00"
    # end_time     : e.g. "09:00"   (always exactly 1 hour after start_time)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            slot_id INTEGER NOT NULL,
            vehicle_number TEXT,
            booking_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Active',
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (slot_id) REFERENCES slots (id)
        )
    """)
    conn.commit()

    # ---------- SIMPLE MIGRATION ----------
    # If someone is upgrading from the OLD version of this project (where
    # bookings did not have booking_date/start_time/end_time), the old
    # 'bookings' table won't have those columns. We detect that and rebuild
    # the table fresh, since old bookings without a date/time don't fit the
    # new design anyway.
    cursor.execute("PRAGMA table_info(bookings)")
    existing_columns = [row["name"] for row in cursor.fetchall()]
    if "start_time" not in existing_columns:
        cursor.execute("DROP TABLE bookings")
        conn.commit()
        cursor.execute("""
            CREATE TABLE bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                slot_id INTEGER NOT NULL,
                vehicle_number TEXT,
                booking_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Active',
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (slot_id) REFERENCES slots (id)
            )
        """)
        conn.commit()
        print("Old 'bookings' table upgraded to support date + hourly time slots.")

    # ---------- DEFAULT ADMIN ----------
    cursor.execute("SELECT * FROM users WHERE role = 'admin'")
    if not cursor.fetchone():
        from werkzeug.security import generate_password_hash
        cursor.execute("""
            INSERT INTO users (full_name, email, password, vehicle_number, role)
            VALUES (?, ?, ?, ?, ?)
        """, ("Admin", "admin@university.edu",
              generate_password_hash("admin123"), "N/A", "admin"))
        conn.commit()
        print("Default admin created -> email: admin@university.edu | password: admin123")

    # ---------- STARTER SLOTS ----------
    cursor.execute("SELECT COUNT(*) as count FROM slots")
    if cursor.fetchone()["count"] == 0:
        starter_slots = [
            ("A1", "Car", "Block A"), ("A2", "Car", "Block A"),
            ("A3", "Car", "Block A"), ("A4", "Bike", "Block A"),
            ("B1", "Car", "Block B"), ("B2", "Car", "Block B"),
            ("B3", "Bike", "Block B"), ("B4", "Bike", "Block B"),
        ]
        cursor.executemany("""
            INSERT INTO slots (slot_number, slot_type, location)
            VALUES (?, ?, ?)
        """, starter_slots)
        conn.commit()
        print(f"{len(starter_slots)} starter parking slots created.")

    conn.close()


if __name__ == "__main__":
    initialize_database()
    print("Database setup complete. File created: parking.db")

"""
database.py
-----------
Sets up SQLite database: creates tables, runs migrations, and populates 50 starter slots.

UPGRADES IN THIS VERSION:
- 50 physical parking slots (A01 - A50) in a structured square garage layout with 4 corner exits.
- Multi-hour duration support in bookings (start_time, end_time, duration_hours, arrival_deadline).
- Automated check-in and no-show strike tracking (check_in_time, actual_exit_time, status: Active, Checked-In, Completed, Cancelled, No-Show).
- Student account security: email_verified, strike_count, account_status ('Active' / 'Suspended'), vehicle_banned.
- Secure OTP verification table (otps) with expiration and attempt limiting.
- Violations table for No-Show strikes and Overstay penalty records.
- Audit log table for admin activity tracking.
"""

import os
import shutil
import sqlite3
import tempfile
from datetime import datetime

# In Vercel serverless environment, the root filesystem is read-only.
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
    # Enable foreign key support in SQLite
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database():
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
            role TEXT NOT NULL DEFAULT 'student',
            email_verified INTEGER NOT NULL DEFAULT 1,
            strike_count INTEGER NOT NULL DEFAULT 0,
            account_status TEXT NOT NULL DEFAULT 'Active',
            vehicle_banned INTEGER NOT NULL DEFAULT 0,
            created_at TEXT
        )
    """)
    conn.commit()

    # Migrate users columns if table existed previously without them
    cursor.execute("PRAGMA table_info(users)")
    existing_user_cols = [row["name"] for row in cursor.fetchall()]

    new_user_cols = {
        "email_verified": "INTEGER NOT NULL DEFAULT 0",
        "strike_count": "INTEGER NOT NULL DEFAULT 0",
        "account_status": "TEXT NOT NULL DEFAULT 'Active'",
        "vehicle_banned": "INTEGER NOT NULL DEFAULT 0",
        "created_at": "TEXT"
    }
    for col, col_type in new_user_cols.items():
        if col not in existing_user_cols:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
    conn.commit()

    # Ensure all users have email_verified = 1 for simple direct access
    cursor.execute("UPDATE users SET email_verified = 1 WHERE email_verified = 0")
    conn.commit()

    # ---------- OTPS TABLE ----------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS otps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            otp_hash TEXT NOT NULL,
            purpose TEXT NOT NULL DEFAULT 'registration',
            expires_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            verified INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_otps_email ON otps(email)")
    conn.commit()

    # ---------- SLOTS TABLE ----------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_number TEXT UNIQUE NOT NULL,
            slot_type TEXT NOT NULL DEFAULT 'Car',
            location TEXT NOT NULL DEFAULT 'Main Campus'
        )
    """)
    conn.commit()

    # ---------- BOOKINGS TABLE ----------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            slot_id INTEGER NOT NULL,
            vehicle_number TEXT,
            booking_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            duration_hours INTEGER NOT NULL DEFAULT 1,
            arrival_deadline TEXT NOT NULL DEFAULT '',
            check_in_time TEXT,
            actual_exit_time TEXT,
            status TEXT NOT NULL DEFAULT 'Active',
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (slot_id) REFERENCES slots (id)
        )
    """)
    conn.commit()

    # Migrate bookings columns if missing
    cursor.execute("PRAGMA table_info(bookings)")
    existing_booking_cols = [row["name"] for row in cursor.fetchall()]

    new_booking_cols = {
        "duration_hours": "INTEGER NOT NULL DEFAULT 1",
        "arrival_deadline": "TEXT NOT NULL DEFAULT ''",
        "check_in_time": "TEXT",
        "actual_exit_time": "TEXT"
    }
    for col, col_type in new_booking_cols.items():
        if col not in existing_booking_cols:
            cursor.execute(f"ALTER TABLE bookings ADD COLUMN {col} {col_type}")
    conn.commit()

    # ---------- VIOLATIONS TABLE ----------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            booking_id INTEGER,
            violation_type TEXT NOT NULL,
            vehicle_number TEXT,
            description TEXT,
            penalty_amount REAL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            resolved_by TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (booking_id) REFERENCES bookings (id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_violations_user ON violations(user_id)")
    conn.commit()

    # ---------- AUDIT LOGS TABLE ----------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()

    # ---------- DEFAULT ADMIN ----------
    cursor.execute("SELECT * FROM users WHERE role = 'admin'")
    admin_user = cursor.fetchone()
    from werkzeug.security import generate_password_hash
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not admin_user:
        cursor.execute("""
            INSERT INTO users (full_name, email, password, vehicle_number, role,
                               email_verified, strike_count, account_status, vehicle_banned, created_at)
            VALUES (?, ?, ?, ?, ?, 1, 0, 'Active', 0, ?)
        """, ("Admin", "admin@university.edu",
              generate_password_hash("admin123"), "CAMPUS-01", "admin", now_str))
        conn.commit()
        print("Default admin created -> email: admin@university.edu | password: admin123")
    else:
        # Ensure existing admin is marked as verified & active
        cursor.execute("""
            UPDATE users SET email_verified = 1, account_status = 'Active' WHERE role = 'admin'
        """)
        conn.commit()

    # ---------- EXACTLY 50 PARKING SLOTS (A01 TO A50) ----------
    cursor.execute("SELECT COUNT(*) as count FROM slots")
    slot_count = cursor.fetchone()["count"]

    # If slots do not equal 50 or have old naming (like A1 instead of A01), re-seed 50 slots
    cursor.execute("SELECT slot_number FROM slots WHERE slot_number = 'A01'")
    has_a01 = cursor.fetchone() is not None

    if slot_count != 50 or not has_a01:
        # Check if there are active bookings pointing to old slots
        cursor.execute("SELECT COUNT(*) as bcount FROM bookings")
        has_bookings = cursor.fetchone()["bcount"] > 0

        if not has_bookings:
            cursor.execute("DELETE FROM slots")
            try:
                cursor.execute("DELETE FROM sqlite_sequence WHERE name = 'slots'")
            except Exception:
                pass
            conn.commit()

            fifty_slots = []
            for i in range(1, 51):
                slot_num = f"A{i:02d}"
                # Zone allocation for clean square garage layout
                if 1 <= i <= 10:
                    location = "North Row (Gate A/B)"
                    stype = "Car"
                elif 11 <= i <= 20:
                    location = "Central North Bay"
                    stype = "Car"
                elif 21 <= i <= 30:
                    location = "Central Mid Bay"
                    stype = "Car" if i not in (29, 30) else "Bike"
                elif 31 <= i <= 40:
                    location = "Central South Bay"
                    stype = "Car" if i not in (39, 40) else "Bike"
                else:
                    location = "South Row (Gate C/D)"
                    stype = "Car" if i not in (47, 48, 49, 50) else "Bike"

                fifty_slots.append((slot_num, stype, location))

            cursor.executemany("""
                INSERT INTO slots (slot_number, slot_type, location)
                VALUES (?, ?, ?)
            """, fifty_slots)
            conn.commit()
            print("Successfully populated exactly 50 parking spaces: A01 to A50.")
        else:
            # If bookings exist, populate missing slots up to A50
            cursor.execute("SELECT slot_number FROM slots")
            existing_numbers = {row["slot_number"] for row in cursor.fetchall()}
            new_slots = []
            for i in range(1, 51):
                slot_num = f"A{i:02d}"
                if slot_num not in existing_numbers:
                    stype = "Bike" if i in (29, 30, 39, 40, 47, 48, 49, 50) else "Car"
                    loc = "Block A" if i <= 12 else ("Block B" if i <= 24 else ("Block C" if i <= 36 else "Block D"))
                    new_slots.append((slot_num, stype, loc))
            if new_slots:
                cursor.executemany("""
                    INSERT INTO slots (slot_number, slot_type, location)
                    VALUES (?, ?, ?)
                """, new_slots)
                conn.commit()

    conn.close()


if __name__ == "__main__":
    initialize_database()

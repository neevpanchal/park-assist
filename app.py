"""
app.py
------
Main Flask backend for the Smart Parking Management System.

CHANGE IN THIS VERSION - HOURLY BOOKING:
Booking is now done by picking a DATE and a 1-HOUR TIME SLOT, from
7:00 AM to 9:00 PM (14 one-hour slots per day):
    7-8, 8-9, 9-10, 10-11, 11-12, 12-13, 13-14, 14-15,
    15-16, 16-17, 17-18, 18-19, 19-20, 20-21

Flow for a student:
    1. Go to Dashboard -> pick a date -> see all parking slots
    2. Click "View Time Slots" on a slot -> see all 14 hourly slots for
       that parking spot on that date, marked Available / Booked / Expired
    3. Click "Book" on an available hour -> enter vehicle number -> done
"""

import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta

from database import get_connection, initialize_database

base_dir = os.path.abspath(os.path.dirname(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(base_dir, "templates"),
    static_folder=os.path.join(base_dir, "static")
)
app.secret_key = os.environ.get("SECRET_KEY", "smart_parking_secret_key")

initialize_database()

# Parking operates from 7 AM to 9 PM -> hours 7,8,9...20 as START hours
OPENING_HOUR = 7
CLOSING_HOUR = 21  # last slot ENDS at 21:00 (9 PM)


# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------
def is_logged_in():
    return "user_id" in session


def is_admin():
    return session.get("role") == "admin"


def get_time_slots():
    """
    Builds the list of 1-hour time slots for a day, from 7:00 to 21:00.
    Returns a list of dicts like:
        {"start": "07:00", "end": "08:00", "display": "07:00 AM - 08:00 AM"}
    """
    slots = []
    for hour in range(OPENING_HOUR, CLOSING_HOUR):
        start_str = f"{hour:02d}:00"
        end_str = f"{(hour + 1):02d}:00"
        start_display = datetime.strptime(start_str, "%H:%M").strftime("%I:%M %p")
        end_display = datetime.strptime(end_str, "%H:%M").strftime("%I:%M %p")
        slots.append({
            "start": start_str,
            "end": end_str,
            "display": f"{start_display} - {end_display}"
        })
    return slots


def get_valid_date(date_str):
    """
    Makes sure the date the user asked for is valid and not in the past.
    If it's missing, badly formatted, or in the past, we fall back to today.
    """
    today_str = date.today().strftime("%Y-%m-%d")

    if not date_str:
        return today_str
    try:
        parsed_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return today_str

    if parsed_date < date.today():
        return today_str
    return date_str


# ---------------------------------------------------------
# HOME
# ---------------------------------------------------------
@app.route("/")
def home():
    if is_logged_in():
        if is_admin():
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


# ---------------------------------------------------------
# REGISTER
# ---------------------------------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form["full_name"]
        email = request.form["email"]
        password = request.form["password"]
        vehicle_number = request.form["vehicle_number"]
        hashed_password = generate_password_hash(password)

        conn = get_connection()
        try:
            conn.execute("""
                INSERT INTO users (full_name, email, password, vehicle_number, role)
                VALUES (?, ?, ?, ?, 'student')
            """, (full_name, email, hashed_password, vehicle_number))
            conn.commit()
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))
        except Exception:
            flash("An account with this email already exists.", "error")
        finally:
            conn.close()

    return render_template("register.html")


# ---------------------------------------------------------
# LOGIN / LOGOUT
# ---------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn = get_connection()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["full_name"] = user["full_name"]
            session["role"] = user["role"]
            flash(f"Welcome back, {user['full_name']}!", "success")
            if user["role"] == "admin":
                return redirect(url_for("admin_dashboard"))
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid email or password.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------
# STUDENT DASHBOARD -> list of parking slots for a chosen date
# ---------------------------------------------------------
@app.route("/dashboard")
def dashboard():
    if not is_logged_in():
        return redirect(url_for("login"))

    selected_date = get_valid_date(request.args.get("date"))
    today_str = date.today().strftime("%Y-%m-%d")
    tomorrow_str = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")

    conn = get_connection()
    slots = conn.execute("SELECT * FROM slots ORDER BY slot_number").fetchall()

    # Count how many ACTIVE bookings each slot already has on this date,
    # so we can show "3 / 14 hours booked" on each slot card.
    rows = conn.execute("""
        SELECT slot_id, COUNT(*) as booked_count
        FROM bookings
        WHERE booking_date = ? AND status = 'Active'
        GROUP BY slot_id
    """, (selected_date,)).fetchall()
    conn.close()

    booked_counts = {row["slot_id"]: row["booked_count"] for row in rows}
    total_hours = len(get_time_slots())

    return render_template(
        "dashboard.html",
        slots=slots,
        selected_date=selected_date,
        today=today_str,
        tomorrow=tomorrow_str,
        booked_counts=booked_counts,
        total_hours=total_hours
    )


# ---------------------------------------------------------
# SLOT DETAIL -> the 14 hourly time slots for ONE parking slot
# ---------------------------------------------------------
@app.route("/slot/<int:slot_id>")
def slot_detail(slot_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    selected_date = get_valid_date(request.args.get("date"))

    conn = get_connection()
    slot = conn.execute("SELECT * FROM slots WHERE id = ?", (slot_id,)).fetchone()
    if slot is None:
        conn.close()
        flash("Slot not found.", "error")
        return redirect(url_for("dashboard"))

    booked_rows = conn.execute("""
        SELECT start_time FROM bookings
        WHERE slot_id = ? AND booking_date = ? AND status = 'Active'
    """, (slot_id, selected_date)).fetchall()
    conn.close()

    booked_start_times = {row["start_time"] for row in booked_rows}

    # Figure out if the chosen date is today, so we can mark past hours "Expired"
    is_today = (selected_date == date.today().strftime("%Y-%m-%d"))
    current_hour = datetime.now().hour

    cells = []
    for slot_time in get_time_slots():
        hour = int(slot_time["start"].split(":")[0])
        if is_today and hour <= current_hour:
            status = "Expired"
        elif slot_time["start"] in booked_start_times:
            status = "Booked"
        else:
            status = "Available"

        cells.append({**slot_time, "status": status})

    return render_template(
        "slot_detail.html",
        slot=slot,
        cells=cells,
        selected_date=selected_date
    )


# ---------------------------------------------------------
# BOOK A TIME SLOT
# ---------------------------------------------------------
@app.route("/book", methods=["POST"])
def book_slot():
    if not is_logged_in():
        return redirect(url_for("login"))

    slot_id = request.form["slot_id"]
    booking_date = get_valid_date(request.form["booking_date"])
    start_time = request.form["start_time"]
    end_time = request.form["end_time"]
    vehicle_number = request.form["vehicle_number"]

    # Make sure the submitted start_time is actually one of our real time slots
    valid_start_times = {slot["start"] for slot in get_time_slots()}
    if start_time not in valid_start_times:
        flash("Invalid time slot selected.", "error")
        return redirect(url_for("slot_detail", slot_id=slot_id, date=booking_date))

    # Block booking an hour that has already passed today
    is_today = (booking_date == date.today().strftime("%Y-%m-%d"))
    if is_today and int(start_time.split(":")[0]) <= datetime.now().hour:
        flash("You cannot book a time slot that has already passed.", "error")
        return redirect(url_for("slot_detail", slot_id=slot_id, date=booking_date))

    conn = get_connection()

    # Double-booking check: is this slot already booked for this exact hour?
    clash = conn.execute("""
        SELECT * FROM bookings
        WHERE slot_id = ? AND booking_date = ? AND start_time = ? AND status = 'Active'
    """, (slot_id, booking_date, start_time)).fetchone()

    if clash:
        flash("Sorry, this time slot was just booked by someone else.", "error")
    else:
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("""
            INSERT INTO bookings (user_id, slot_id, vehicle_number, booking_date,
                                   start_time, end_time, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'Active', ?)
        """, (session["user_id"], slot_id, vehicle_number, booking_date,
              start_time, end_time, created_at))
        conn.commit()
        flash(f"Booked {start_time} - {end_time} on {booking_date} successfully!", "success")

    conn.close()
    return redirect(url_for("slot_detail", slot_id=slot_id, date=booking_date))


# ---------------------------------------------------------
# MY BOOKINGS
# ---------------------------------------------------------
@app.route("/my-bookings")
def my_bookings():
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_connection()
    bookings = conn.execute("""
        SELECT bookings.id, bookings.vehicle_number, bookings.booking_date,
               bookings.start_time, bookings.end_time, bookings.status,
               slots.slot_number, slots.slot_type, slots.location
        FROM bookings
        JOIN slots ON bookings.slot_id = slots.id
        WHERE bookings.user_id = ?
        ORDER BY bookings.booking_date DESC, bookings.start_time DESC
    """, (session["user_id"],)).fetchall()
    conn.close()

    return render_template("my_bookings.html", bookings=bookings)


# ---------------------------------------------------------
# CANCEL A BOOKING
# ---------------------------------------------------------
@app.route("/cancel/<int:booking_id>", methods=["POST"])
def cancel_booking(booking_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_connection()
    booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()

    if booking and booking["user_id"] == session["user_id"]:
        conn.execute("UPDATE bookings SET status = 'Cancelled' WHERE id = ?", (booking_id,))
        conn.commit()
        flash("Booking cancelled successfully.", "success")
    else:
        flash("Booking not found.", "error")

    conn.close()
    return redirect(url_for("my_bookings"))


# ---------------------------------------------------------
# ADMIN DASHBOARD
# ---------------------------------------------------------
@app.route("/admin")
def admin_dashboard():
    if not is_logged_in() or not is_admin():
        flash("Access denied. Admins only.", "error")
        return redirect(url_for("login"))

    conn = get_connection()
    slots = conn.execute("SELECT * FROM slots ORDER BY slot_number").fetchall()
    bookings = conn.execute("""
        SELECT bookings.id, users.full_name, users.email, slots.slot_number,
               bookings.vehicle_number, bookings.booking_date, bookings.start_time,
               bookings.end_time, bookings.status
        FROM bookings
        JOIN users ON bookings.user_id = users.id
        JOIN slots ON bookings.slot_id = slots.id
        ORDER BY bookings.booking_date DESC, bookings.start_time DESC
    """).fetchall()

    active_now = len([b for b in bookings if b["status"] == "Active"])
    conn.close()

    return render_template(
        "admin.html",
        slots=slots,
        bookings=bookings,
        total_slots=len(slots),
        active_bookings=active_now
    )


@app.route("/admin/add-slot", methods=["POST"])
def add_slot():
    if not is_logged_in() or not is_admin():
        return redirect(url_for("login"))

    slot_number = request.form["slot_number"]
    slot_type = request.form["slot_type"]
    location = request.form["location"]

    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO slots (slot_number, slot_type, location)
            VALUES (?, ?, ?)
        """, (slot_number, slot_type, location))
        conn.commit()
        flash(f"Slot {slot_number} added successfully.", "success")
    except Exception:
        flash("A slot with this number already exists.", "error")
    finally:
        conn.close()

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/delete-slot/<int:slot_id>", methods=["POST"])
def delete_slot(slot_id):
    if not is_logged_in() or not is_admin():
        return redirect(url_for("login"))

    conn = get_connection()
    conn.execute("DELETE FROM slots WHERE id = ?", (slot_id,))
    conn.commit()
    conn.close()

    flash("Slot deleted.", "success")
    return redirect(url_for("admin_dashboard"))


if __name__ == "__main__":
    app.run(debug=True)

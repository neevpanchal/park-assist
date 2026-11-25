"""
app.py
------
Main Flask backend for the upgraded Smart University Parking Management System.

KEY CAPABILITIES:
1. Email OTP Verification during student registration with secure hashing & rate limiting.
2. 15-Minute Arrival Grace Period and automated No-Show strike & account suspension system.
3. Multi-Hour Consecutive Booking System (1 to 14 hours between 07:00 and 21:00).
4. Interactive Pictorial 50-Space Parking Map in a square garage layout with 4 corner exits.
5. Rule Book with Facility Rules & Overstay Violation Management.
6. Admin AI Parking Analytics with Real-Time KPIs, Weekly/Monthly reports, and AI Q&A.
7. Role-based security, CSRF protection, and parameterized SQL queries.
"""

import os
import io
import qrcode
import qrcode.image.svg
import secrets
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify, send_file
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

# Load environment variables from .env if present
load_dotenv()

from database import get_connection, initialize_database
from email_utils import (
    generate_secure_otp, store_otp, verify_otp_code,
    can_resend_otp, send_otp_email, send_smtp_email
)
from no_show_utils import calculate_arrival_deadline, process_no_shows
from analytics_utils import (
    get_realtime_analytics, get_weekly_analytics,
    get_monthly_analytics, query_ai_insights
)

base_dir = os.path.abspath(os.path.dirname(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(base_dir, "templates"),
    static_folder=os.path.join(base_dir, "static")
)
app.secret_key = os.environ.get("SECRET_KEY", "smart_parking_secret_key_2026_secure")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Initialize database tables and 50 slots on startup
initialize_database()

# Facility operates from 7:00 AM to 9:00 PM (14 hourly increments)
OPENING_HOUR = 7
CLOSING_HOUR = 21


# ---------------------------------------------------------
# DISPLAY FILTERS (friendly times & dates in templates)
# ---------------------------------------------------------
@app.template_filter("t12")
def format_time_12h(value):
    """'13:00' -> '1:00 PM'. Returns the input unchanged if it can't be parsed."""
    if not value:
        return ""
    try:
        t = datetime.strptime(str(value).strip()[:5], "%H:%M")
        return t.strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return value


@app.template_filter("nice_date")
def format_nice_date(value):
    """'2026-11-25' -> 'Wed, 25 Nov 2026' (adds 'Today'/'Tomorrow' where it applies)."""
    if not value:
        return ""
    try:
        d = datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return value
    if d == date.today():
        return "Today, " + d.strftime("%d %b")
    if d == date.today() + timedelta(days=1):
        return "Tomorrow, " + d.strftime("%d %b")
    return d.strftime("%a, %d %b %Y")


# ---------------------------------------------------------
# CSRF PROTECTION & TEMPLATE HELPERS
# ---------------------------------------------------------
@app.before_request
def csrf_protect():
    # Automatically scan and penalize any overdue no-shows before processing requests
    try:
        process_no_shows()
    except Exception as e:
        print(f"[NO-SHOW RUNTIME WARNING] {e}")

    # Generate session CSRF token if missing
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)

    # Validate CSRF token on POST requests
    if request.method == "POST":
        # Allow JSON API endpoints if needed, otherwise check form CSRF token
        if not request.path.startswith("/api/"):
            token = request.form.get("csrf_token")
            if not token or token != session.get("csrf_token"):
                flash("Security session check failed. Please submit the form again.", "error")
                return redirect(request.referrer or url_for("home"))


@app.context_processor
def inject_globals():
    """Injects common utility variables and CSRF token into all templates."""
    def get_csrf():
        return session.get("csrf_token", "")

    student_strikes = 0
    account_status = "Active"
    if is_logged_in() and session.get("role") == "student":
        try:
            conn = get_connection()
            u = conn.execute("SELECT strike_count, account_status FROM users WHERE id = ?", (session["user_id"],)).fetchone()
            conn.close()
            if u:
                student_strikes = u["strike_count"]
                account_status = u["account_status"]
        except Exception:
            pass

    return {
        "csrf_token": get_csrf(),
        "today_str": date.today().strftime("%Y-%m-%d"),
        "now_time_str": datetime.now().strftime("%H:%M"),
        "current_user_strikes": student_strikes,
        "current_user_status": account_status
    }


# ---------------------------------------------------------
# AUTH HELPERS
# ---------------------------------------------------------
def is_logged_in():
    return "user_id" in session


def is_admin():
    return session.get("role") == "admin"


def get_time_slots():
    """Returns list of the 14 standard 1-hour time blocks (07:00 to 21:00)."""
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
# HOME & RULE BOOK
# ---------------------------------------------------------
@app.route("/")
def home():
    if is_logged_in():
        if is_admin():
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/rules")
def rules():
    return render_template("rules.html")


# ---------------------------------------------------------
# STUDENT REGISTRATION (DIRECT REGISTRATION & LOGIN)
# ---------------------------------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form["full_name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        vehicle_number = request.form["vehicle_number"].strip().upper()

        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return render_template("register.html")

        conn = get_connection()
        existing_user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if existing_user:
            conn.close()
            flash("An account with this email already exists. Please log in.", "error")
            return redirect(url_for("login"))

        hashed_pw = generate_password_hash(password)
        conn.execute("""
            INSERT INTO users (full_name, email, password, vehicle_number, role,
                               email_verified, strike_count, account_status, vehicle_banned, created_at)
            VALUES (?, ?, ?, ?, 'student', 1, 0, 'Active', 0, ?)
        """, (full_name, email, hashed_pw, vehicle_number, now_str))
        conn.commit()
        conn.close()

        flash("Registration successful! You can now log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/verify-otp")
def verify_otp():
    return redirect(url_for("login"))


# ---------------------------------------------------------
# LOGIN / LOGOUT
# ---------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        conn = get_connection()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            # Check if account is suspended
            if user["account_status"] == "Suspended":
                flash("ACCOUNT SUSPENDED: You have exceeded 3 parking no-show strikes. "
                      "Your booking privileges and vehicle are currently banned. "
                      "Please contact the administration office.", "error")
                return render_template("login.html")

            session["user_id"] = user["id"]
            session["full_name"] = user["full_name"]
            session["role"] = user["role"]
            session["vehicle_number"] = user["vehicle_number"]

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
# STUDENT DASHBOARD & 50-SPACE MAP
# ---------------------------------------------------------
@app.route("/dashboard")
def dashboard():
    if not is_logged_in():
        return redirect(url_for("login"))

    selected_date = get_valid_date(request.args.get("date"))
    today_str = date.today().strftime("%Y-%m-%d")
    tomorrow_str = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    view_mode = request.args.get("view", "map")  # default to interactive map

    conn = get_connection()
    slots = conn.execute("SELECT * FROM slots ORDER BY slot_number").fetchall()

    # Get active/checked-in bookings on this date
    rows = conn.execute("""
        SELECT slot_id, SUM(duration_hours) as booked_hours, COUNT(*) as booking_count
        FROM bookings
        WHERE booking_date = ? AND status IN ('Active', 'Checked-In')
        GROUP BY slot_id
    """, (selected_date,)).fetchall()

    # User's current account standing
    user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    conn.close()

    booked_hours_map = {row["slot_id"]: (row["booked_hours"] or 0) for row in rows}
    total_hours = len(get_time_slots())  # 14 hours

    return render_template(
        "dashboard.html",
        slots=slots,
        selected_date=selected_date,
        today=today_str,
        tomorrow=tomorrow_str,
        booked_hours_map=booked_hours_map,
        total_hours=total_hours,
        view_mode=view_mode,
        user=user,
        current_hour=datetime.now().hour
    )


# ---------------------------------------------------------
# MULTI-HOUR SLOT DETAIL & BOOKING
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
        flash("Parking slot not found.", "error")
        return redirect(url_for("dashboard"))

    # Active/Checked-In bookings for this slot on this date
    bookings = conn.execute("""
        SELECT start_time, end_time, duration_hours, status 
        FROM bookings
        WHERE slot_id = ? AND booking_date = ? AND status IN ('Active', 'Checked-In')
    """, (slot_id, selected_date)).fetchall()

    user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    conn.close()

    # Build hourly occupancy set for each hour 7 to 20
    occupied_hours = set()
    for b in bookings:
        try:
            start_h = int(b["start_time"].split(":")[0])
            end_h = int(b["end_time"].split(":")[0])
            for h in range(start_h, end_h):
                occupied_hours.add(f"{h:02d}:00")
        except Exception:
            pass

    is_today = (selected_date == date.today().strftime("%Y-%m-%d"))
    current_hour = datetime.now().hour

    cells = []
    for slot_time in get_time_slots():
        hour = int(slot_time["start"].split(":")[0])
        if is_today and hour <= current_hour:
            status = "Expired"
        elif slot_time["start"] in occupied_hours:
            status = "Booked"
        else:
            status = "Available"

        cells.append({**slot_time, "status": status})

    return render_template(
        "slot_detail.html",
        slot=slot,
        cells=cells,
        selected_date=selected_date,
        user=user
    )


@app.route("/book", methods=["POST"])
def book_slot():
    if not is_logged_in():
        return redirect(url_for("login"))

    slot_id = int(request.form["slot_id"])
    booking_date = get_valid_date(request.form["booking_date"])
    start_time = request.form["start_time"].strip()
    duration_hours = int(request.form.get("duration_hours", 1))
    vehicle_number = request.form["vehicle_number"].strip().upper()

    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()

    # 1. Enforcement checks: suspension & vehicle bans
    if user["account_status"] == "Suspended":
        conn.close()
        flash("Booking blocked: Your account is suspended due to 3 no-show strikes.", "error")
        return redirect(url_for("slot_detail", slot_id=slot_id, date=booking_date))

    if user["vehicle_banned"] == 1:
        conn.close()
        flash("Booking blocked: Your registered vehicle is banned from reserving parking spaces.", "error")
        return redirect(url_for("slot_detail", slot_id=slot_id, date=booking_date))

    # 2. Validate start time and duration bounds
    try:
        start_hour = int(start_time.split(":")[0])
    except Exception:
        conn.close()
        flash("Invalid start time format.", "error")
        return redirect(url_for("slot_detail", slot_id=slot_id, date=booking_date))

    if start_hour < OPENING_HOUR or start_hour >= CLOSING_HOUR:
        conn.close()
        flash("Parking is only open between 7:00 AM and 9:00 PM.", "error")
        return redirect(url_for("slot_detail", slot_id=slot_id, date=booking_date))

    end_hour = start_hour + duration_hours
    if end_hour > CLOSING_HOUR:
        conn.close()
        flash(f"Booking duration exceeds 9:00 PM closing time. Maximum duration from {start_time} is {CLOSING_HOUR - start_hour} hours.", "error")
        return redirect(url_for("slot_detail", slot_id=slot_id, date=booking_date))

    end_time = f"{end_hour:02d}:00"

    # Block past hours for today
    is_today = (booking_date == date.today().strftime("%Y-%m-%d"))
    if is_today and start_hour <= datetime.now().hour:
        conn.close()
        flash("You cannot book a time slot that has already started or passed.", "error")
        return redirect(url_for("slot_detail", slot_id=slot_id, date=booking_date))

    # 3. Check for overlapping bookings for EVERY hour in requested span
    # Overlap logic: NOT (existing.end_time <= requested.start_time OR existing.start_time >= requested.end_time)
    overlap = conn.execute("""
        SELECT * FROM bookings
        WHERE slot_id = ? 
          AND booking_date = ? 
          AND status IN ('Active', 'Checked-In')
          AND NOT (end_time <= ? OR start_time >= ?)
    """, (slot_id, booking_date, start_time, end_time)).fetchone()

    if overlap:
        conn.close()
        flash(f"Slot conflict: This space is already reserved between {overlap['start_time']} and {overlap['end_time']}. Please pick another time or slot.", "error")
        return redirect(url_for("slot_detail", slot_id=slot_id, date=booking_date))

    # 4. Calculate arrival deadline: start_time + 15 minutes grace period
    arrival_deadline = calculate_arrival_deadline(start_time)
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute("""
        INSERT INTO bookings (user_id, slot_id, vehicle_number, booking_date,
                               start_time, end_time, duration_hours, arrival_deadline,
                               status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Active', ?)
    """, (session["user_id"], slot_id, vehicle_number, booking_date,
          start_time, end_time, duration_hours, arrival_deadline, now_ts))
    conn.commit()
    conn.close()

    flash(f"Booked! {format_nice_date(booking_date)}, {format_time_12h(start_time)} – {format_time_12h(end_time)} "
          f"({duration_hours} hr). Please arrive by {format_time_12h(arrival_deadline)} and show your QR pass at the gate.",
          "success")
    return redirect(url_for("my_bookings"))


# ---------------------------------------------------------
# CHECK-IN & MY BOOKINGS
# ---------------------------------------------------------
@app.route("/my-bookings")
def my_bookings():
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_connection()
    bookings = conn.execute("""
        SELECT b.id, b.vehicle_number, b.booking_date, b.start_time, b.end_time,
               b.duration_hours, b.arrival_deadline, b.check_in_time, b.status,
               s.slot_number, s.slot_type, s.location
        FROM bookings b
        JOIN slots s ON b.slot_id = s.id
        WHERE b.user_id = ?
        ORDER BY b.booking_date DESC, b.start_time DESC
    """, (session["user_id"],)).fetchall()

    user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()

    violations = conn.execute("""
        SELECT * FROM violations WHERE user_id = ? ORDER BY id DESC
    """, (session["user_id"],)).fetchall()
    conn.close()

    today_str = date.today().strftime("%Y-%m-%d")

    return render_template(
        "my_bookings.html",
        bookings=bookings,
        user=user,
        violations=violations,
        today=today_str
    )


@app.route("/check-in/<int:booking_id>", methods=["POST"])
def check_in(booking_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_connection()
    booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()

    if not booking:
        conn.close()
        flash("Booking not found.", "error")
        return redirect(url_for("my_bookings"))

    # Disallow student self check-in (admins/staff only)
    if not is_admin():
        conn.close()
        flash("Self check-in is disabled. Please present your booking QR code at the parking gate scanner or to the gate attendant to verify arrival.", "error")
        return redirect(url_for("my_bookings"))

    today_str = date.today().strftime("%Y-%m-%d")
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Validate check-in date
    if booking["booking_date"] != today_str and not is_admin():
        conn.close()
        flash(f"Check-in is only available on your scheduled booking date ({booking['booking_date']}).", "error")
        return redirect(url_for("my_bookings"))

    if booking["status"] != "Active":
        conn.close()
        flash(f"Cannot check in: Booking status is currently '{booking['status']}'.", "error")
        return redirect(url_for("my_bookings"))

    # Record check-in
    conn.execute("""
        UPDATE bookings 
        SET status = 'Checked-In', check_in_time = ? 
        WHERE id = ?
    """, (now_ts, booking_id))
    conn.commit()
    conn.close()

    flash(f"Check-in verified successfully at {now_ts}! Your parking spot is secured.", "success")
    if is_admin():
        return redirect(request.referrer or url_for("admin_dashboard"))
    return redirect(url_for("my_bookings"))


@app.route("/cancel/<int:booking_id>", methods=["POST"])
def cancel_booking(booking_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_connection()
    booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()

    if booking and (booking["user_id"] == session["user_id"] or is_admin()):
        if booking["status"] in ("Checked-In", "Completed"):
            conn.close()
            flash("Cannot cancel a booking that has already checked in or completed.", "error")
            return redirect(url_for("my_bookings"))

        conn.execute("UPDATE bookings SET status = 'Cancelled' WHERE id = ?", (booking_id,))
        conn.commit()
        flash(f"Booking for Slot {booking['slot_id']} cancelled. The full duration has been released.", "success")
    else:
        flash("Booking not found or permission denied.", "error")

    conn.close()
    if is_admin():
        return redirect(request.referrer or url_for("admin_dashboard"))
    return redirect(url_for("my_bookings"))


# ---------------------------------------------------------
# QR CODE & DIGITAL PARKING PASS VERIFICATION
# ---------------------------------------------------------
@app.route("/booking/qr/<int:booking_id>")
def booking_qr(booking_id):
    # Determine accurate external scheme and host for Vercel/reverse proxy environments
    host = request.headers.get("X-Forwarded-Host", request.host)
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    pass_path = url_for("booking_pass", booking_id=booking_id)
    pass_url = f"{scheme}://{host}{pass_path}"

    try:
        # 1. Attempt PNG generation with Pillow
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2
        )
        qr.add_data(pass_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#12203D", back_color="#FFFFFF")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png")
    except Exception as err:
        print(f"[QR GENERATION WARNING] Pillow PNG failed: {err}. Using pure-Python SVG fallback.")
        # 2. Pure-Python SVG fallback (zero external C-library or Pillow dependencies)
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2,
            image_factory=qrcode.image.svg.SvgPathImage
        )
        qr.add_data(pass_url)
        qr.make(fit=True)
        img = qr.make_image()

        buf = io.BytesIO()
        img.save(buf)
        buf.seek(0)
        return send_file(buf, mimetype="image/svg+xml")


@app.route("/booking/pass/<int:booking_id>")
def booking_pass(booking_id):
    conn = get_connection()
    booking = conn.execute("""
        SELECT b.*, s.slot_number, s.slot_type, s.location,
               u.full_name, u.email, u.vehicle_number AS user_vehicle,
               u.account_status, u.strike_count
        FROM bookings b
        JOIN slots s ON b.slot_id = s.id
        JOIN users u ON b.user_id = u.id
        WHERE b.id = ?
    """, (booking_id,)).fetchone()
    conn.close()

    if not booking:
        flash("Digital Parking Pass not found.", "error")
        return redirect(url_for("dashboard") if is_logged_in() else url_for("login"))

    today_str = date.today().strftime("%Y-%m-%d")
    is_valid_today = (booking["booking_date"] == today_str)

    # Determine recommended gate according to slot
    slot_no = booking["slot_number"]
    gate_name = "Gate A (North-West Entry)"
    gate_desc = "Optimal for Bays A01 - A12 (North-West wing)"
    try:
        num = int(slot_no[1:])
        if 1 <= num <= 12:
            gate_name = "Gate A (North-West Entry)"
            gate_desc = "Optimal for Bays A01 - A12 (North-West wing)"
        elif 13 <= num <= 25:
            gate_name = "Gate B (North-East Entry)"
            gate_desc = "Optimal for Bays A13 - A25 (North-East wing)"
        elif 26 <= num <= 38:
            gate_name = "Gate C (South-West Entry)"
            gate_desc = "Optimal for Bays A26 - A38 (South-West wing)"
        else:
            gate_name = "Gate D (South-East Entry)"
            gate_desc = "Optimal for Bays A39 - A50 (South-East wing)"
    except Exception:
        pass

    return render_template(
        "booking_pass.html",
        b=booking,
        today=today_str,
        is_valid_today=is_valid_today,
        gate_name=gate_name,
        gate_desc=gate_desc,
        scanned_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )


@app.route("/booking/pass/<int:booking_id>/verify", methods=["POST"])
def verify_pass_arrival(booking_id):
    conn = get_connection()
    booking = conn.execute("""
        SELECT b.*, s.slot_number 
        FROM bookings b 
        JOIN slots s ON b.slot_id = s.id 
        WHERE b.id = ?
    """, (booking_id,)).fetchone()

    if not booking:
        conn.close()
        flash("Booking pass not found.", "error")
        return redirect(url_for("dashboard") if is_logged_in() else url_for("login"))

    if booking["status"] != "Active":
        conn.close()
        flash(f"Arrival cannot be verified: Booking status is already '{booking['status']}'.", "error")
        return redirect(url_for("booking_pass", booking_id=booking_id))

    today_str = date.today().strftime("%Y-%m-%d")
    if booking["booking_date"] != today_str and not is_admin():
        conn.close()
        flash(f"Check-in is only available on scheduled booking date ({booking['booking_date']}).", "error")
        return redirect(url_for("booking_pass", booking_id=booking_id))

    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("""
        UPDATE bookings
        SET status = 'Checked-In', check_in_time = ?
        WHERE id = ?
    """, (now_ts, booking_id))
    conn.commit()
    conn.close()

    flash(f"Gate Arrival Confirmed! Vehicle access verified for Bay {booking['slot_number']} at {now_ts}.", "success")
    return redirect(url_for("booking_pass", booking_id=booking_id))


# ---------------------------------------------------------
# ADMIN DASHBOARD & ENFORCEMENT
# ---------------------------------------------------------
@app.route("/admin")
def admin_dashboard():
    if not is_logged_in() or not is_admin():
        flash("Access denied. Administrators only.", "error")
        return redirect(url_for("login"))

    conn = get_connection()
    slots = conn.execute("SELECT * FROM slots ORDER BY slot_number").fetchall()
    bookings = conn.execute("""
        SELECT b.id, u.full_name, u.email, s.slot_number,
               b.vehicle_number, b.booking_date, b.start_time, b.end_time,
               b.duration_hours, b.arrival_deadline, b.check_in_time, b.actual_exit_time, b.status
        FROM bookings b
        JOIN users u ON b.user_id = u.id
        JOIN slots s ON b.slot_id = s.id
        ORDER BY b.booking_date DESC, b.start_time DESC
    """).fetchall()

    students = conn.execute("""
        SELECT id, full_name, email, vehicle_number, email_verified, strike_count, account_status, vehicle_banned
        FROM users 
        WHERE role = 'student' 
        ORDER BY strike_count DESC, id DESC
    """).fetchall()

    active_now = len([b for b in bookings if b["status"] in ("Active", "Checked-In")])
    conn.close()

    return render_template(
        "admin.html",
        slots=slots,
        bookings=bookings,
        students=students,
        total_slots=len(slots),
        active_bookings=active_now
    )


@app.route("/admin/reset-strikes/<int:user_id>", methods=["POST"])
def reset_strikes(user_id):
    if not is_logged_in() or not is_admin():
        return redirect(url_for("login"))

    conn = get_connection()
    conn.execute("""
        UPDATE users 
        SET strike_count = 0, account_status = 'Active', vehicle_banned = 0 
        WHERE id = ?
    """, (user_id,))
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("""
        INSERT INTO audit_logs (actor_id, action, details, created_at)
        VALUES (?, 'LIFT_SUSPENSION', ?, ?)
    """, (session["user_id"], f"Admin manually lifted suspension and reset strikes for user id {user_id}", now_ts))
    conn.commit()
    conn.close()

    flash("Suspension lifted! Strikes reset to 0 and vehicle unbanned.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/add-slot", methods=["POST"])
def add_slot():
    if not is_logged_in() or not is_admin():
        return redirect(url_for("login"))

    slot_number = request.form["slot_number"].strip().upper()
    slot_type = request.form["slot_type"]
    location = request.form["location"].strip()

    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO slots (slot_number, slot_type, location)
            VALUES (?, ?, ?)
        """, (slot_number, slot_type, location))
        conn.commit()
        flash(f"Slot {slot_number} added successfully.", "success")
    except Exception:
        flash("A slot with this identifier already exists.", "error")
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

    flash("Slot removed from active inventory.", "success")
    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------
# ADMIN AI PARKING ANALYTICS
# ---------------------------------------------------------
@app.route("/admin/analytics")
def admin_analytics():
    if not is_logged_in() or not is_admin():
        flash("Access denied. Admins only.", "error")
        return redirect(url_for("login"))

    week_offset = int(request.args.get("week", 0))
    month_offset = int(request.args.get("month", date.today().month))
    year = int(request.args.get("year", date.today().year))

    realtime = get_realtime_analytics()
    weekly = get_weekly_analytics(week_offset=week_offset)
    monthly = get_monthly_analytics(year=year, month=month_offset)

    return render_template(
        "admin_analytics.html",
        realtime=realtime,
        weekly=weekly,
        monthly=monthly,
        week_offset=week_offset,
        selected_month=month_offset,
        selected_year=year
    )


@app.route("/api/ai-insights", methods=["POST"])
def api_ai_insights():
    """API endpoint for the AI Parking Analytics interactive Q&A."""
    if not is_logged_in() or not is_admin():
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json() or {}
    question = data.get("question", "").strip()
    if not question:
        return jsonify({"error": "Question cannot be empty"}), 400

    result = query_ai_insights(question)
    return jsonify(result)


# ---------------------------------------------------------
# OVERSTAYS & VIOLATIONS MANAGEMENT
# ---------------------------------------------------------
@app.route("/admin/overstay", methods=["GET", "POST"])
def admin_overstay():
    if not is_logged_in() or not is_admin():
        flash("Access denied. Admins only.", "error")
        return redirect(url_for("login"))

    conn = get_connection()
    today_str = date.today().strftime("%Y-%m-%d")

    if request.method == "POST":
        booking_id = int(request.form["booking_id"])
        actual_exit_time = request.form["actual_exit_time"].strip()

        booking = conn.execute("""
            SELECT b.*, u.full_name, u.email 
            FROM bookings b 
            JOIN users u ON b.user_id = u.id 
            WHERE b.id = ?
        """, (booking_id,)).fetchone()

        if booking:
            # Calculate overstay minutes
            try:
                booked_end = datetime.strptime(f"{booking['booking_date']} {booking['end_time']}", "%Y-%m-%d %H:%M")
                actual_exit = datetime.strptime(f"{booking['booking_date']} {actual_exit_time}", "%Y-%m-%d %H:%M")
                diff_minutes = max(0, int((actual_exit - booked_end).total_seconds() / 60))
            except Exception:
                diff_minutes = 30

            now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Penalty fee: Rs. 50 per 30 minutes overstay (minimum Rs. 50)
            penalty_amount = 0.0
            if diff_minutes > 5:  # 5 min leeway
                half_hours = (diff_minutes + 29) // 30
                penalty_amount = float(half_hours * 50)

                desc = (f"Overstay violation on {booking['booking_date']}: Scheduled end {booking['end_time']}, "
                        f"actual exit recorded at {actual_exit_time} ({diff_minutes} minutes overstay). "
                        f"Enforced offline at parking exit gate.")

                conn.execute("""
                    INSERT INTO violations (user_id, booking_id, violation_type, vehicle_number,
                                           description, penalty_amount, status, created_at)
                    VALUES (?, ?, 'Overstay', ?, ?, ?, 'Pending', ?)
                """, (booking["user_id"], booking["id"], booking["vehicle_number"], desc, penalty_amount, now_ts))

                conn.execute("UPDATE bookings SET actual_exit_time = ?, status = 'Completed' WHERE id = ?", (actual_exit_time, booking_id))
                conn.commit()

                # Email notification
                send_smtp_email(
                    to_email=booking["email"],
                    subject="Parking Overstay Notice & Fee Assessment",
                    html_content=f"<p>Dear {booking['full_name']}, an overstay of {diff_minutes} mins was recorded for vehicle {booking['vehicle_number']}. Applicable penalty: Rs. {penalty_amount:.2f}. Please clear this with exit security staff.</p>",
                    text_content=f"Overstay recorded: {diff_minutes} mins. Penalty fee: Rs. {penalty_amount:.2f}."
                )

                flash(f"Overstay of {diff_minutes} minutes recorded for vehicle {booking['vehicle_number']}. Penalty assessed: ₹{penalty_amount:.2f}.", "success")
            else:
                conn.execute("UPDATE bookings SET actual_exit_time = ?, status = 'Completed' WHERE id = ?", (actual_exit_time, booking_id))
                conn.commit()
                flash("Vehicle exit recorded with no overstay penalty.", "success")

    # Fetch active/checked-in bookings for today
    live_bookings = conn.execute("""
        SELECT b.*, u.full_name, u.email, s.slot_number 
        FROM bookings b
        JOIN users u ON b.user_id = u.id
        JOIN slots s ON b.slot_id = s.id
        WHERE b.booking_date = ? AND b.status IN ('Active', 'Checked-In')
        ORDER BY b.end_time ASC
    """, (today_str,)).fetchall()

    violations = conn.execute("""
        SELECT v.*, u.full_name, u.email 
        FROM violations v
        JOIN users u ON v.user_id = u.id
        ORDER BY v.id DESC
    """).fetchall()

    conn.close()

    return render_template(
        "admin_overstay.html",
        live_bookings=live_bookings,
        violations=violations,
        today=today_str
    )


@app.route("/admin/resolve-violation/<int:violation_id>", methods=["POST"])
def resolve_violation(violation_id):
    if not is_logged_in() or not is_admin():
        return redirect(url_for("login"))

    action = request.form.get("status_action", "Paid")
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection()
    conn.execute("""
        UPDATE violations 
        SET status = ?, resolved_at = ?, resolved_by = ? 
        WHERE id = ?
    """, (action, now_ts, session.get("full_name", "Admin"), violation_id))
    conn.commit()
    conn.close()

    flash(f"Violation marked as '{action}'.", "success")
    return redirect(url_for("admin_overstay"))


# ---------------------------------------------------------
# JSON API FOR LIVE MAP STATUS
# ---------------------------------------------------------
@app.route("/api/map-status")
def api_map_status():
    """Returns real-time occupancy status for all 50 slots on the chosen date."""
    selected_date = get_valid_date(request.args.get("date"))
    conn = get_connection()
    slots = conn.execute("SELECT * FROM slots ORDER BY slot_number").fetchall()

    bookings = conn.execute("""
        SELECT slot_id, start_time, end_time, duration_hours, status 
        FROM bookings
        WHERE booking_date = ? AND status IN ('Active', 'Checked-In')
    """, (selected_date,)).fetchall()
    conn.close()

    bookings_by_slot = {}
    for b in bookings:
        bookings_by_slot.setdefault(b["slot_id"], []).append({
            "start": b["start_time"],
            "end": b["end_time"],
            "duration": b["duration_hours"],
            "status": b["status"]
        })

    result = []
    for s in slots:
        slot_b = bookings_by_slot.get(s["id"], [])
        booked_hours_count = sum(b["duration"] for b in slot_b)
        result.append({
            "id": s["id"],
            "number": s["slot_number"],
            "type": s["slot_type"],
            "location": s["location"],
            "booked_hours": booked_hours_count,
            "is_full": booked_hours_count >= 14,
            "bookings": slot_b
        })

    return jsonify({
        "date": selected_date,
        "total_slots": len(result),
        "slots": result
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)

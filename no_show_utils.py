"""
no_show_utils.py
----------------
Automated 15-minute arrival grace period and strike/penalty management.
Guarantees consistent, database-backed status tracking so slots are freed and
violations are logged even if users don't have the site open.
"""

from datetime import datetime, date, timedelta
from database import get_connection
from email_utils import send_strike_alert_email


def calculate_arrival_deadline(start_time_str):
    """
    Given a start time like '08:00', adds 15 minutes of grace period -> '08:15'.
    """
    try:
        t = datetime.strptime(start_time_str, "%H:%M")
        deadline = t + timedelta(minutes=15)
        return deadline.strftime("%H:%M")
    except Exception:
        return start_time_str


def is_past_arrival_deadline(booking_date_str, arrival_deadline_str):
    """
    Checks if current local time is past the arrival deadline for a given booking.
    """
    today_str = date.today().strftime("%Y-%m-%d")
    now_time_str = datetime.now().strftime("%H:%M")

    if booking_date_str < today_str:
        return True
    if booking_date_str == today_str and now_time_str > arrival_deadline_str:
        return True
    return False


def process_no_shows():
    """
    Scans for active, un-checked-in bookings whose 15-minute grace period has passed.
    - Updates booking status to 'No-Show' (which immediately frees the slot for others).
    - Issues exactly 1 strike to the student.
    - Records the violation in the violations table.
    - If student hits 3 strikes, suspends account and bans vehicle.
    - Sends email notification to student.
    - Records audit log.
    """
    conn = get_connection()
    today_str = date.today().strftime("%Y-%m-%d")
    now_time_str = datetime.now().strftime("%H:%M")
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Find active bookings without check-in that are past deadline
    query = """
        SELECT b.id, b.user_id, b.slot_id, b.vehicle_number, b.booking_date,
               b.start_time, b.end_time, b.arrival_deadline,
               u.full_name, u.email, u.strike_count, u.account_status,
               s.slot_number
        FROM bookings b
        JOIN users u ON b.user_id = u.id
        JOIN slots s ON b.slot_id = s.id
        WHERE b.status = 'Active' 
          AND (b.check_in_time IS NULL OR b.check_in_time = '')
          AND (b.booking_date < ? OR (b.booking_date = ? AND b.arrival_deadline < ?))
    """
    overdue_bookings = conn.execute(query, (today_str, today_str, now_time_str)).fetchall()

    if not overdue_bookings:
        conn.close()
        return 0

    processed_count = 0
    for b in overdue_bookings:
        # Check if violation was already logged for this specific booking
        existing_violation = conn.execute("""
            SELECT id FROM violations WHERE booking_id = ? AND violation_type = 'No-Show'
        """, (b["id"],)).fetchone()

        if existing_violation:
            # Already penalized, just ensure status is set to No-Show
            conn.execute("UPDATE bookings SET status = 'No-Show' WHERE id = ?", (b["id"],))
            continue

        # 1. Update booking status to 'No-Show'
        conn.execute("UPDATE bookings SET status = 'No-Show' WHERE id = ?", (b["id"],))

        # 2. Increment student strike count
        new_strikes = b["strike_count"] + 1
        is_suspended = (new_strikes >= 3)
        new_status = "Suspended" if is_suspended else b["account_status"]
        vehicle_banned = 1 if is_suspended else 0

        conn.execute("""
            UPDATE users 
            SET strike_count = ?, account_status = ?, vehicle_banned = ?
            WHERE id = ?
        """, (new_strikes, new_status, vehicle_banned, b["user_id"]))

        # 3. Record violation in database
        desc = (f"No-show on {b['booking_date']}: Failed to check in for slot {b['slot_number']} "
                f"({b['start_time']}-{b['end_time']}) by arrival deadline {b['arrival_deadline']}.")
        conn.execute("""
            INSERT INTO violations (user_id, booking_id, violation_type, vehicle_number,
                                   description, penalty_amount, status, created_at)
            VALUES (?, ?, 'No-Show', ?, ?, 0.0, 'Pending', ?)
        """, (b["user_id"], b["id"], b["vehicle_number"], desc, now_ts))

        # 4. Record audit log
        conn.execute("""
            INSERT INTO audit_logs (actor_id, action, details, created_at)
            VALUES (?, 'NO_SHOW_PENALTY', ?, ?)
        """, (b["user_id"], f"Issued strike {new_strikes}/3 to {b['email']} ({b['vehicle_number']}). Suspended: {is_suspended}", now_ts))

        # 5. Send notification email
        send_strike_alert_email(
            email=b["email"],
            full_name=b["full_name"],
            vehicle_number=b["vehicle_number"],
            strike_count=new_strikes,
            reason=desc,
            is_suspended=is_suspended
        )

        processed_count += 1

    conn.commit()
    conn.close()
    return processed_count

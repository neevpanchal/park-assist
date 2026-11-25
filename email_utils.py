"""
email_utils.py
--------------
Handles email OTP generation, verification, and notification delivery via SMTP.
Includes a robust local Demo Mode fallback so testing and vivas work seamlessly
even without live email credentials.
"""

import os
import secrets
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_connection


def is_smtp_configured():
    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    placeholders = (
        "your_university_email@gmail.com",
        "your_actual_email@gmail.com",
        "your_16_char_app_password",
        "your_app_specific_password",
        "example@gmail.com"
    )
    if not username or not password:
        return False
    if username in placeholders or password in placeholders:
        return False
    return True


def generate_secure_otp():
    """Generates a cryptographically secure 6-digit numeric OTP."""
    return f"{secrets.randbelow(900000) + 100000}"


def store_otp(email, otp_code, purpose="registration"):
    """
    Hashes and stores a 6-digit OTP with a 5-minute expiration.
    Invalidates any previous unverified OTPs for the same email and purpose.
    """
    otp_hash = generate_password_hash(otp_code)
    now = datetime.now()
    expires_at = (now + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection()
    # Invalidate previous unverified OTPs for this email and purpose
    conn.execute("""
        UPDATE otps SET verified = -1 
        WHERE email = ? AND purpose = ? AND verified = 0
    """, (email, purpose))

    conn.execute("""
        INSERT INTO otps (email, otp_hash, purpose, expires_at, attempts, verified, created_at)
        VALUES (?, ?, ?, ?, 0, 0, ?)
    """, (email, otp_hash, purpose, expires_at, now_str))
    conn.commit()
    conn.close()


def verify_otp_code(email, submitted_code, purpose="registration"):
    """
    Verifies the submitted 6-digit OTP against the active hash in database.
    Enforces 5-minute expiration and max 5 attempts limit.
    Returns (success: bool, message: str)
    """
    conn = get_connection()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    otp_record = conn.execute("""
        SELECT * FROM otps 
        WHERE email = ? AND purpose = ? AND verified = 0 
        ORDER BY id DESC LIMIT 1
    """, (email, purpose)).fetchone()

    if not otp_record:
        conn.close()
        return False, "No active verification code found. Please request a new code."

    # Check expiration
    if otp_record["expires_at"] < now_str:
        conn.execute("UPDATE otps SET verified = -1 WHERE id = ?", (otp_record["id"],))
        conn.commit()
        conn.close()
        return False, "Verification code has expired (5-minute limit). Please request a new code."

    # Check rate limit (max 5 attempts)
    current_attempts = otp_record["attempts"] + 1
    if current_attempts > 5:
        conn.execute("UPDATE otps SET verified = -1, attempts = ? WHERE id = ?", (current_attempts, otp_record["id"]))
        conn.commit()
        conn.close()
        return False, "Too many failed attempts. Code locked. Please request a new code."

    # Verify code
    is_valid = check_password_hash(otp_record["otp_hash"], submitted_code.strip())
    if is_valid:
        conn.execute("UPDATE otps SET verified = 1, attempts = ? WHERE id = ?", (current_attempts, otp_record["id"]))
        # Mark user as verified
        conn.execute("UPDATE users SET email_verified = 1 WHERE email = ?", (email,))
        conn.commit()
        conn.close()
        return True, "Email verified successfully!"
    else:
        conn.execute("UPDATE otps SET attempts = ? WHERE id = ?", (current_attempts, otp_record["id"]))
        conn.commit()
        conn.close()
        remaining = 5 - current_attempts
        return False, f"Invalid verification code. {remaining} attempt(s) remaining."


def can_resend_otp(email, purpose="registration", cooldown_seconds=60):
    """Checks if cooldown period has elapsed since last OTP generation."""
    conn = get_connection()
    last_otp = conn.execute("""
        SELECT created_at FROM otps 
        WHERE email = ? AND purpose = ? 
        ORDER BY id DESC LIMIT 1
    """, (email, purpose)).fetchone()
    conn.close()

    if not last_otp:
        return True, 0

    try:
        created_time = datetime.strptime(last_otp["created_at"], "%Y-%m-%d %H:%M:%S")
        elapsed = (datetime.now() - created_time).total_seconds()
        if elapsed < cooldown_seconds:
            return False, int(cooldown_seconds - elapsed)
    except Exception:
        pass
    return True, 0


def send_smtp_email(to_email, subject, html_content, text_content=None):
    """
    Sends an email using standard Python smtplib.
    If SMTP credentials are not configured, prints to console and returns demo indicator.
    """
    if not is_smtp_configured():
        print(f"\n[DEMO MODE / NO LIVE SMTP] Sending to: {to_email}")
        print(f"Subject: {subject}")
        print(f"Content Summary: {text_content or html_content[:200]}")
        print("-" * 50 + "\n")
        return True, "demo"

    server_host = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    server_port = int(os.environ.get("SMTP_PORT", 587))
    use_tls = os.environ.get("SMTP_USE_TLS", "True").lower() in ("true", "1", "yes")
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    sender = os.environ.get("SMTP_SENDER", f"Smart Parking <{username}>")

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to_email

        if text_content:
            msg.attach(MIMEText(text_content, "plain"))
        if html_content:
            msg.attach(MIMEText(html_content, "html"))

        server = smtplib.SMTP(server_host, server_port, timeout=10)
        if use_tls:
            server.starttls()
        server.login(username, password)
        server.sendmail(username, [to_email], msg.as_string())
        server.quit()
        return True, "sent"
    except Exception as e:
        print(f"[SMTP ERROR] Could not send email: {e}")
        return False, str(e)


def send_otp_email(email, otp_code, student_name="Student"):
    """Sends 6-digit OTP code in university navy/amber branded email."""
    subject = f"{otp_code} is your Smart Parking Verification Code"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background: #F2F4F9; margin: 0; padding: 24px; color: #16213A; }}
            .container {{ max-width: 520px; margin: 0 auto; background: #FFFFFF; border-radius: 8px; border: 1px solid rgba(18, 32, 61, 0.12); overflow: hidden; }}
            .header {{ background: #12203D; padding: 24px; border-bottom: 3px solid #FFB627; color: #FFFFFF; }}
            .header h1 {{ margin: 0; font-size: 20px; font-weight: 800; }}
            .content {{ padding: 32px 24px; text-align: center; }}
            .otp-box {{ background: #12203D; color: #FFB627; font-family: monospace; font-size: 36px; font-weight: bold; letter-spacing: 8px; padding: 18px; border-radius: 6px; display: inline-block; margin: 24px 0; }}
            .footer {{ background: #F2F4F9; padding: 16px; font-size: 12px; color: #5B6478; text-align: center; border-top: 1px solid #E2E6EF; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Smart University Parking</h1>
            </div>
            <div class="content">
                <p style="font-size: 16px; text-align: left;">Hello <strong>{student_name}</strong>,</p>
                <p style="font-size: 14px; color: #5B6478; text-align: left;">
                    Thank you for registering. Use the 6-digit verification code below to verify your email and activate your parking booking account:
                </p>
                <div class="otp-box">{otp_code}</div>
                <p style="font-size: 13px; color: #E1484D; font-weight: bold;">
                    ⚠️ This code expires in 5 minutes. Do not share it with anyone.
                </p>
            </div>
            <div class="footer">
                Automated message from Campus Parking Authority. If you did not register, please ignore this email.
            </div>
        </div>
    </body>
    </html>
    """
    text = f"Smart Parking Verification Code: {otp_code}\nExpires in 5 minutes. Enter this code to verify your account."
    return send_smtp_email(email, subject, html, text)


def send_strike_alert_email(email, full_name, vehicle_number, strike_count, reason, is_suspended=False):
    """Sends formal notification when a student receives a no-show strike."""
    if is_suspended:
        subject = "URGENT: Smart Parking Account Suspended (3 Strikes Exceeded)"
        status_line = "<strong style='color: #E1484D;'>YOUR PARKING ACCOUNT AND REGISTERED VEHICLE HAVE BEEN SUSPENDED.</strong>"
        action_line = "You are currently blocked from making any new parking reservations. Please visit the Campus Parking Administration Office to review your violation history and request reinstatement."
    else:
        subject = f"Warning: Parking Violation Strike {strike_count}/3 Recorded"
        status_line = f"<strong style='color: #FFB627;'>You have accumulated {strike_count} of 3 allowable strikes.</strong>"
        action_line = "Please ensure you check in within the 15-minute grace period on future bookings. Accumulating 3 strikes results in automated account suspension."

    html = f"""
    <div style="font-family: sans-serif; max-width: 520px; margin: 0 auto; background: #fff; border: 1px solid #ddd; border-radius: 8px; overflow: hidden;">
        <div style="background: #12203D; padding: 20px; color: #fff; border-bottom: 3px solid #E1484D;">
            <h2 style="margin: 0; font-size: 18px;">Smart Parking Violation Notice</h2>
        </div>
        <div style="padding: 24px; color: #16213A;">
            <p>Dear <strong>{full_name}</strong>,</p>
            <p>A parking facility violation has been recorded for your account:</p>
            <div style="background: #F2F4F9; padding: 14px; border-left: 4px solid #E1484D; margin: 16px 0; font-size: 13px;">
                <strong>Violation:</strong> {reason}<br>
                <strong>Registered Vehicle:</strong> {vehicle_number}<br>
                <strong>Current Strike Count:</strong> {strike_count} / 3
            </div>
            <p>{status_line}</p>
            <p style="font-size: 13px; color: #5B6478;">{action_line}</p>
        </div>
    </div>
    """
    text = f"Parking Violation Notice for {full_name} ({vehicle_number}). Reason: {reason}. Current strikes: {strike_count}/3."
    return send_smtp_email(email, subject, html, text)

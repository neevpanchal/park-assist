# Smart Parking Management System (University Project)

A web-based system that lets students view parking slots, book a specific
**1-hour time slot** (7:00 AM to 9:00 PM) on a chosen date, cancel a booking,
and lets an admin manage slots and see all booking history.

---

## 1. Tech Stack (keep this simple when explaining)

| Layer          | Technology                          |
|----------------|--------------------------------------|
| Backend        | Python + Flask (a lightweight web framework) |
| Database       | SQLite (a single-file database, built into Python) |
| Frontend       | HTML, CSS, Jinja2 templates (no JavaScript frameworks) |
| Password Security | Werkzeug's `generate_password_hash` / `check_password_hash` |

**Why these choices?**
- Flask is simple enough to explain route-by-route to a teacher.
- SQLite needs no separate installation or server — the whole database is one file (`parking.db`).
- Jinja2 templating lets Python data (like the list of slots) be displayed directly in HTML using `{{ }}` and `{% %}`.

---

## 2. Project Structure

```
parking_system/
│
├── app.py                 # Main Flask app - all routes/URLs live here
├── database.py             # Creates tables + adds starter data
├── requirements.txt         # Python packages needed
├── parking.db               # Auto-created SQLite database (after first run)
│
├── templates/               # HTML pages (Jinja2 templates)
│   ├── base.html             # Shared layout (navbar, flash messages)
│   ├── login.html
│   ├── register.html
│   ├── dashboard.html        # Student: pick a date, see all slots
│   ├── slot_detail.html      # Student: hourly time-grid for one slot, book an hour
│   ├── my_bookings.html      # Student: view + cancel own bookings
│   └── admin.html            # Admin: manage slots + view all bookings
│
└── static/
    └── style.css             # All CSS styling
```

---

## 3. Database Design (Explain this as your ER diagram)

**users**
| Column | Type | Notes |
|---|---|---|
| id | INTEGER (PK) | auto-increment |
| full_name | TEXT | |
| email | TEXT | must be unique |
| password | TEXT | stored as a hash, never plain text |
| vehicle_number | TEXT | |
| role | TEXT | `student` or `admin` |

**slots**
| Column | Type | Notes |
|---|---|---|
| id | INTEGER (PK) | |
| slot_number | TEXT | e.g. "A1" |
| slot_type | TEXT | Car / Bike |
| location | TEXT | e.g. "Block A" |

**bookings**
| Column | Type | Notes |
|---|---|---|
| id | INTEGER (PK) | |
| user_id | INTEGER (FK → users.id) | who booked |
| slot_id | INTEGER (FK → slots.id) | which physical slot |
| vehicle_number | TEXT | |
| booking_date | TEXT | e.g. "2026-09-15" |
| start_time | TEXT | e.g. "08:00" |
| end_time | TEXT | e.g. "09:00" (always 1 hour after start_time) |
| status | TEXT | Active / Cancelled |
| created_at | TEXT | when the booking was made |

Relationship: One **user** can have many **bookings**. One **slot** can have many
**bookings**, but never two *Active* bookings with the same `booking_date` +
`start_time` (that combination is what prevents double-booking).

Notice `slots` no longer has a "status" column — a slot isn't simply
Available/Booked anymore, because that now depends on WHICH date and WHICH
hour you're asking about. Availability is worked out on the fly by checking
the `bookings` table for that date + hour.

---

## 4. Core Features

1. **Student Registration & Login** — passwords hashed with Werkzeug, session-based login.
2. **Hourly Time Slots** — parking is divided into 14 fixed 1-hour slots per day, from
   7:00 AM to 9:00 PM (7-8, 8-9, 9-10 ... 20-21).
3. **Date-based Availability** — student picks a date on the dashboard, then opens a
   parking slot to see all 14 hours for that date marked **Available**, **Booked**,
   or **Expired** (an hour that has already passed today).
4. **Book a Time Slot** — student picks an available hour, enters a vehicle number,
   and a booking record is created for that exact date + hour.
5. **My Bookings** — student sees their own booking history (with date and time) and
   can cancel an active booking, freeing that hour back up.
6. **Admin Dashboard** — add new physical slots, delete slots, and view every booking
   (with date + time) ever made by every student.
7. **Access Control** — students can't reach `/admin`; a student can't cancel someone
   else's booking (checked using `session['user_id']`).

---

## 5. How the Booking Flow Works (good to explain in viva)

1. On the dashboard, the student picks a **date** (defaults to today; past dates are blocked).
2. Clicking a slot opens `/slot/<slot_id>?date=...`, which builds a list of the 14
   fixed hourly ranges and checks the `bookings` table to mark each one Available,
   Booked, or Expired (if the date is today and that hour has already gone by).
3. Clicking "Book" on an available hour sends a `POST` to `/book` with the slot id,
   date, start time, and end time (all in hidden form fields) plus the vehicle number.
4. `app.py` re-checks that no *Active* booking already exists for that exact
   slot + date + hour (this guards against two students booking the same hour
   at the same time — a race condition).
5. If it's free, a new row is inserted into `bookings` with status `Active`.
6. If the student cancels later, that row's status simply changes to `Cancelled`,
   which frees the hour up again for anyone (since availability is calculated live
   from `Active` bookings only).

---

## 6. How to Run the Project

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the app (this also auto-creates the database on first run)
python app.py

# 3. Open your browser
http://127.0.0.1:5000
```

**Default admin login (auto-created on first run):**
- Email: `admin@university.edu`
- Password: `admin123`

Students register their own accounts using the "Register" page.

---

## 7. Possible Future Improvements (mention these if asked "what's next?")

- Allow booking multiple consecutive hours in one go (e.g. 9-12).
- Send email/SMS confirmation on booking.
- QR-code based slot check-in/check-out.
- Payment/fee integration (intentionally left out of this version).
- Real-time slot status updates using WebSockets.
- A calendar-style weekly view instead of picking one date at a time.

---

## 8. Visual Design

The interface is themed around real parking garage signage rather than a
generic dashboard look:

- **Navy + amber palette** — navy is used for structural surfaces (navbar,
  table headers, the "board bar" summary strip), amber for primary actions,
  echoing the black-and-yellow of parking barriers and caution markings.
- **LED-style status dots** — green / red / grey circular indicators next to
  each slot and each hourly time range, similar to the indicator lights used
  above real parking bays.
- **Two fonts** — Manrope for all body text and labels, and Space Mono
  (a monospace font) specifically for slot codes, dates, and times, so they
  read like a digital reader-board display.
- **"Board bar"** — the navy summary strip at the top of the Dashboard and
  Admin pages mimics the reader boards seen at parking garage entrances
  ("X spaces available").

This is easy to point out if a teacher asks about design choices: the theme
was chosen to match the subject matter, not applied as generic decoration.

---

## 9. Why SQLite + raw SQL instead of an ORM (e.g. SQLAlchemy)?

For a first project, writing plain SQL (`SELECT`, `INSERT`, `UPDATE`) makes it much
easier to explain exactly what the database is doing at each step, rather than
hiding it behind ORM abstractions. This keeps the project at an
easy-to-defend, intermediate level.

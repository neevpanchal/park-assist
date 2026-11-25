# Smart University Parking Management System (Upgraded Edition)

A full-stack, enterprise-grade university parking reservation and analytics platform built with Python, Flask, SQLite, and Jinja2. The system features a realistic garage-themed navy blue and amber reader-board design, an interactive 50-bay pictorial square parking map with 4 corner exits, email OTP verification, automated 15-minute arrival grace period enforcement with a 3-strike penalty system, multi-hour consecutive booking, and an Admin AI Parking Analytics dashboard.

---

## 1. Tech Stack & Architecture

| Layer | Technology | Purpose |
|---|---|---|
| **Backend** | Python + Flask | Lightweight WSGI web backend with clean, viva-defensible modular design |
| **Database** | SQLite (`parking.db`) | Zero-configuration single-file relational database with strict foreign keys |
| **Frontend** | HTML5, CSS3, Jinja2 | Semantic responsive UI styled with parking garage signage design (no bloated heavy JS frameworks) |
| **Security & Auth** | Werkzeug Hashing + CSRF | Password and OTP hashing (`generate_password_hash`), session CSRF verification |
| **Email Service** | Python `smtplib` + MIME | Real SMTP verification with automatic fallback Demo Mode |
| **AI Analytics** | Gemini API + Built-in Heuristic | Live LLM insight synthesis with offline SQLite statistical heuristic fallback |

---

## 2. Key Upgraded Features

### 1. Email OTP Verification During Registration
- Multi-step registration flow: Student enters Name, University Email, Password, and Vehicle Plate Number.
- Secure 6-digit cryptographically generated OTP (`secrets.randbelow`).
- OTPs are hashed before saving to SQLite with a **5-minute expiration** window.
- Rate-limited: Maximum 5 verification attempts per code; 60-second cooldown on OTP resend requests.
- **Offline / Viva Demo Mode**: If live SMTP credentials are not configured, OTP is automatically printed in server logs and displayed in a demo flash banner.

### 2. 15-Minute Arrival Grace Period & Strike Enforcement
- Every reservation automatically calculates an arrival deadline: **Start Time + 15 minutes** (e.g. 09:00 booking &rarr; 09:15 deadline).
- Students verify their physical arrival via the **Check In** button on their "My Bookings" page (or gate security can verify them).
- **Automated No-Show Detection**: Whenever reservations are queried, overdue un-checked-in bookings are marked as `No-Show` and the slot is immediately released for other patrons.
- **Three-Strike Penalty Escalation**:
  - Each no-show adds **1 strike** to the student's account.
  - Striking is accompanied by automated email alert notification.
  - At **3 strikes**, the student's booking privileges are suspended and their vehicle plate is banned from future reservations.
  - Administrators can review the permanent violation log and manually lift suspensions/reset strikes.

### 3. Multi-Hour Consecutive Booking System
- Students can book between **1 and 14 consecutive hours** in a single unified reservation (operating hours: 7:00 AM to 9:00 PM).
- Dynamic client-side and server-side preview calculates total hours, end time, and arrival deadline.
- Server performs interval collision detection to prevent double-booking across any hour in the duration.
- Cancellation releases the entire multi-hour duration back into public inventory.

### 4. Interactive Pictorial 50-Space Parking Map
- **Layout**: Square-shaped parking garage facility containing **exactly 50 physical parking bays** (`A01` to `A50`).
- **4 Corner Exits**:
  - Exit 1 (Gate A &bull; North-West)
  - Exit 2 (Gate B &bull; North-East)
  - Exit 3 (Gate C &bull; South-West)
  - Exit 4 (Gate D &bull; South-East)
- **Driving Aisles**: One-way perimeter lanes and central driving aisles with directional arrows and road markings clearly separating traffic from bays.
- **Live LED Indicators**:
  - 🟢 **Green LED**: Fully available.
  - 🟡 **Amber LED**: Partially booked today.
  - 🔴 **Red LED**: Fully occupied (14 hours booked).
- Clicking any space opens an interactive multi-hour reservation drawer.
- Supports both **Square Map View** and **Grid Cards View** with a one-click toggle.

### 5. Rule Book & Overstay Management
- Prominently placed **RULE BOOK** button in the top navigation bar opens an interactive modal or dedicated `/rules` page.
- Lists the **12 Official Facility Regulations**.
- **Overstay Policy**:
  - Vehicles must vacate the facility before their booked period ends.
  - Campus security interface at `/admin/overstay` records actual vehicle exit timestamps.
  - Overstays are assessed at **₹50 per 30 minutes** of excess occupancy.
  - Offline gate staff collect payment before opening the exit barrier.
  - Overstay violations are maintained separately from no-show attendance strikes.

### 6. Admin AI Parking Analytics Dashboard
- Dedicated `/admin/analytics` dashboard providing:
  - **A. Real-Time Fleet KPIs**: 10 live metrics including total bays, occupied now, free bays, utilization rate, active bookings, cancellations, no-shows, registered students, suspensions, and banned vehicles.
  - **B. Weekly Reports**: Total reservations, total hours, average duration, weekly utilization %, cancellation %, no-show %, strikes issued, top-booked bays, day-of-week demand breakdown, and 14-hour distribution bar chart. Filterable across past weeks.
  - **C. Monthly Reports & MoM Comparison**: Longitudinal monthly performance with month-over-month percentage changes.
  - **D. Interactive AI Terminal ("Ask AI Analytics")**:
    - Pre-populated prompt buttons for standard operational questions (busiest hours, most used spaces, capacity utilization, no-show trends, peak demand days, and optimization advice).
    - Free-form analytical question input field.
    - Powered by Google Gemini API if `GEMINI_API_KEY` is provided; seamlessly falls back to a built-in SQLite data-driven heuristic reasoning engine if no key is set.

---

## 3. Project File Structure

```
python project/
│
├── app.py                     # Main Flask application and API routes
├── database.py                # Database setup, migrations, and 50-slot seeder
├── email_utils.py             # Secure OTP hashing, SMTP emailer & demo fallback
├── no_show_utils.py           # 15-minute grace period & automated strike engine
├── analytics_utils.py         # Real-time, weekly, monthly & AI analytics engine
├── requirements.txt           # Python package requirements
├── .env.example               # Template environment configuration file
├── parking.db                 # Auto-created SQLite relational database
│
├── templates/                 # Jinja2 HTML templates
│   ├── base.html              # Layout, navbar, Rule Book modal, strike pill
│   ├── dashboard.html         # Reader board, 50-bay square map, booking drawer
│   ├── slot_detail.html       # Multi-hour duration booking & 14-hour timeline
│   ├── my_bookings.html       # Reservations, check-in button, violation log
│   ├── verify_otp.html        # 6-digit OTP verification & resend cooldown
│   ├── login.html             # Secure login screen
│   ├── register.html          # Registration form
│   ├── rules.html             # 12 Facility Rules and Overstay Policy document
│   ├── admin.html             # Slot manager, active bookings, suspension lift
│   ├── admin_analytics.html   # AI Parking Analytics dashboard & Q&A terminal
│   └── admin_overstay.html    # Security gate departure logger & fine assessment
│
└── static/
    └── style.css              # Theme CSS: Navy Blue + Amber parking garage styling
```

---

## 4. Setup & Running Instructions

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Environment Configuration (Optional)
Copy `.env.example` to `.env` to configure custom SMTP or AI keys:
```bash
cp .env.example .env
```
*(If `.env` is omitted, the system runs with local defaults and full Demo Mode fallback).*

### 3. Run the Application
```bash
python app.py
```
Open your browser and navigate to:
**[http://localhost:5000](http://localhost:5000)** (or [http://127.0.0.1:5000](http://127.0.0.1:5000))

### Default Administrator Credentials
- **Email:** `admin@university.edu`
- **Password:** `admin123`
- **Role:** `admin`

---

## 5. Automated Verification Results

All 20 required system capabilities were verified via automated integration tests:
1. Database migration: Exactly 50 slots (`A01` to `A50`) created with zone mapping.
2. Email OTP generation: 6-digit code, securely hashed, with attempt limits and expiration.
3. 15-minute grace period: Arrival deadline correctly calculated (`start_time + 15m`).
4. Multi-hour booking: Consecutive durations from 1 to 14 hours successfully reserved.
5. Overlap collision prevention: Clashing multi-hour interval bookings strictly rejected.
6. Check-in mechanism: Arrival confirmation updates status and logs check-in timestamp.
7. Automated No-Show detection: Overdue bookings marked `No-Show` and slots freed immediately.
8. Strike escalation: 1 strike per violation; 3 strikes automatically trigger suspension and vehicle ban.
9. Admin discipline management: Administrators can lift suspensions and reset strikes.
10. AI Analytics engine: Real-time KPIs, weekly distribution, monthly comparisons, and heuristic Q&A verified.
11. Gate overstay logging: Actual exit recording and fine calculation (₹50 / 30m) verified.
12. All web routes loaded with HTTP 200 OK.

---

## 6. Author & Maintainer
- **Developer / GitHub:** [@chhandtyagi1-byte](https://github.com/chhandtyagi1-byte)
- **Contact Email:** [chhandtyagi1@gmail.com](mailto:chhandtyagi1@gmail.com)

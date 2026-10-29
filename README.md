# EduMate — Smart Study Planner for Students

EduMate is a full-stack academic study planning web application developed with Python (Flask), SQLite (SQLAlchemy), and a modern, responsive design system. It empowers college students to track syllabus progress, manage daily revision tasks, view upcoming exam milestones, and stay organized throughout their semester.

---

## 🚀 Key Features

* **Real Database Metrics (No Fake Data):** Every percentage, subject count, task counter, and exam countdown is dynamically calculated from actual database records.
* **Authentication & Role-Based Authorization:** Secure student registration, password hashing (`werkzeug.security`), session handling (`Flask-Login`), and strict server-side role separation (`student` vs `admin`).
* **Standalone Centered Authentication Pages:** Clean, dedicated auth layout for login and registration without rendering authenticated dashboard elements.
* **Syllabus-to-Study-Roadmap Generator:** Deterministic algorithm that transforms syllabus units, topics, and target exam deadlines into a day-by-day study schedule with built-in revision buffers, workload capacity warnings, and database persistence.
* **Explore Verified Competitive Exams:** Direct access to verified official portals (GATE, CAT, UPSC, JEE Advanced, UGC NET, ISRO) with category filters, eligibility overviews, and transparent official authority links.
* **Interactive Light-Theme Dashboard:** Clean, professional UI with deep navy sidebar navigation, metric stat cards, subject progress bars, upcoming exams countdown, and today's schedule.
* **Live Task & Roadmap Checklists:** Asynchronous completion toggling (via `fetch` API) with real-time UI counters updating without page refresh.
* **Protected Admin Panel:** Real-time statistics across all users, account status toggling (active/deactivated), and SQLite database diagnostics.
* **Honest AI Study Assistant:** Transparent status indicator showing "Online" only when a real API key is configured; clearly explains status and provides guidance when offline.
* **Isolated Demo / Evaluation Data:** Reproducible CLI seed command (`python seed.py`) with isolated test accounts that can be refreshed without touching personal student accounts.

---

## 🛠️ Technology Stack

| Layer | Technologies |
| :--- | :--- |
| **Backend** | Python 3, Flask 3.1, Werkzeug |
| **Database & ORM** | SQLite 3, Flask-SQLAlchemy |
| **Authentication** | Flask-Login, Werkzeug Password Hashing |
| **Frontend** | Semantic HTML5, Custom CSS3 Design System, Vanilla JavaScript (ES6) |
| **Testing** | Python `unittest` framework |

---

## 🔑 Demo & Evaluation Accounts

For college project viva and examiner evaluation, pre-seeded database accounts are available:

| Account Type | Email / Username | Password | Role & Purpose |
| :--- | :--- | :--- | :--- |
| **Student Demo** | `student@edumate.local` (or `demo_student`) | `student123` | Demonstrates syllabus progress, roadmap timeline, timetable, and interactive tasks |
| **Admin Demo** | `admin@edumate.local` (or `demo_admin`) | `admin123` | Demonstrates user oversight, account activation, and health metrics |

> **Note:** Demo data is isolated in the SQLite database and does not overwrite or expose personal student accounts.

---

## ⚡ Quick Start & Running Locally

### 1. Initialize & Seed Database
```bash
python3 seed.py
```

### 2. Start Flask Server
```bash
python3 app.py
```
Open your browser and navigate to:
```
http://127.0.0.1:5000
```

### 3. Run Automated Tests
```bash
python3 test_app.py
```

---

## 📊 Database Schema Overview

```
User (id, username, email, password_hash, role, is_active, created_at)
  ├── Subject (id, name, code, color, icon, user_id)
  │     ├── Topic (id, title, is_completed, subject_id)
  │     ├── Task (id, title, due_date, is_completed, user_id, subject_id)
  │     ├── Exam (id, subject_id, exam_date, is_important, user_id)
  │     ├── TimetableEntry (id, day_of_week, start_time, end_time, subject_id, topic, status, user_id)
  │     └── RoadmapPlan (id, user_id, subject_id, title, exam_date, daily_hours, workload_warning)
  │           └── RoadmapItem (id, plan_id, day_number, scheduled_date, unit_name, topic_title, is_completed, is_revision)
  │
  └── OfficialExamDirectory (id, exam_code, exam_name, authority, category, eligibility, official_url)
```

---

## 🎓 College Viva Preparation Guide

### Frequently Asked Viva Questions & Answers

1. **Why did you use SQLite and Flask-SQLAlchemy?**
   * *Answer:* SQLite is a serverless, zero-configuration relational database ideal for desktop and self-contained web applications. Flask-SQLAlchemy provides an Object-Relational Mapper (ORM) that enables writing clean Python model classes instead of raw SQL queries, while protecting against SQL injection vulnerabilities.

2. **How does user authentication and password security work?**
   * *Answer:* We never store plaintext passwords. We use `werkzeug.security.generate_password_hash` which generates a cryptographically salted SHA-256 hash. During login, `check_password_hash` compares the input against the stored hash. Sessions are managed using signed session cookies via `Flask-Login`.

3. **How does the Syllabus-to-Study-Roadmap Generator distribute topics?**
   * *Answer:* The algorithm in `app.py` computes total days until the exam (`(exam_date - today).days`). It allocates the final 15-20% of available days exclusively as revision and mock question buffers. The remaining days are study days where syllabus topics are distributed sequentially. If total estimated topic hours exceed available hours, it triggers a non-blocking workload warning.

4. **Why are external exams linked directly to official authority portals rather than relying solely on scraping?**
   * *Answer:* Exam dates, fees, and syllabus patterns change between cycles. Web scraping can break or display stale information. EduMate maintains a verified directory of official authority portals (IITs for GATE/JEE, IIMs for CAT, UPSC, NTA) to guarantee authentic, official information.

5. **How are the dashboard statistics calculated?**
   * *Answer:* Statistics are computed dynamically during each request in `app.py`:
     * Total Subjects: Query count for the logged-in user (`user_id`).
     * Syllabus Progress: Count of completed topics (`is_completed = True`) divided by total topics for that student's subjects multiplied by 100.
     * Next Exam: Earliest exam where `exam_date >= date.today()`.
     * If a student has no subjects, it safely displays 0% and empty state cards.

from datetime import datetime, date, timezone
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='student')  # 'student' or 'admin'
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    subjects = db.relationship('Subject', backref='student', lazy=True, cascade='all, delete-orphan')
    tasks = db.relationship('Task', backref='student', lazy=True, cascade='all, delete-orphan')
    exams = db.relationship('Exam', backref='student', lazy=True, cascade='all, delete-orphan')
    timetable_entries = db.relationship('TimetableEntry', backref='student', lazy=True, cascade='all, delete-orphan')
    roadmaps = db.relationship('RoadmapPlan', backref='student', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'admin'

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'


class Subject(db.Model):
    __tablename__ = 'subjects'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), nullable=True)  # e.g. "DS", "COA", "OS", "DBMS"
    color = db.Column(db.String(20), default='#3b82f6')  # Hex code for progress bar and badges
    icon = db.Column(db.String(30), default='book')  # 'book', 'cpu', 'gear', 'database', 'pi'
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    topics = db.relationship('Topic', backref='subject', lazy=True, cascade='all, delete-orphan')
    tasks = db.relationship('Task', backref='subject', lazy=True)
    exams = db.relationship('Exam', backref='subject', lazy=True, cascade='all, delete-orphan')
    timetable_entries = db.relationship('TimetableEntry', backref='subject', lazy=True)

    @property
    def total_topics(self):
        return len(self.topics)

    @property
    def completed_topics(self):
        return sum(1 for t in self.topics if t.is_completed)

    @property
    def progress_percentage(self):
        if not self.topics:
            return 0
        return int(round((self.completed_topics / self.total_topics) * 100))

    def __repr__(self):
        return f'<Subject {self.name}>'


class Topic(db.Model):
    __tablename__ = 'topics'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    is_completed = db.Column(db.Boolean, default=False, nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<Topic {self.title} (completed={self.is_completed})>'


class Task(db.Model):
    __tablename__ = 'tasks'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    due_date = db.Column(db.Date, default=date.today, nullable=False)
    is_completed = db.Column(db.Boolean, default=False, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<Task {self.title} (done={self.is_completed})>'


class Exam(db.Model):
    __tablename__ = 'exams'

    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    exam_date = db.Column(db.Date, nullable=False)
    is_important = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def days_left(self):
        delta = (self.exam_date - date.today()).days
        return delta

    def __repr__(self):
        return f'<Exam {self.subject_id} on {self.exam_date}>'


class TimetableEntry(db.Model):
    __tablename__ = 'timetable_entries'

    id = db.Column(db.Integer, primary_key=True)
    day_of_week = db.Column(db.String(20), nullable=False)  # 'Monday', 'Tuesday', ...
    start_time = db.Column(db.String(20), nullable=False)   # e.g. '09:00 AM'
    end_time = db.Column(db.String(20), nullable=False)     # e.g. '10:00 AM'
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    topic = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(20), default='Pending')    # 'Completed', 'In Progress', 'Pending'
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<TimetableEntry {self.day_of_week} {self.start_time}-{self.end_time}>'


class RoadmapPlan(db.Model):
    __tablename__ = 'roadmap_plans'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    title = db.Column(db.String(150), default='Semester Exam Roadmap')
    exam_date = db.Column(db.Date, nullable=False)
    daily_study_hours = db.Column(db.Float, default=2.0, nullable=False)
    total_topics_count = db.Column(db.Integer, default=0)
    completed_topics_count = db.Column(db.Integer, default=0)
    has_workload_warning = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    subject = db.relationship('Subject', backref=db.backref('roadmap_plans', lazy=True, cascade='all, delete-orphan'))
    items = db.relationship('RoadmapItem', backref='plan', lazy=True, cascade='all, delete-orphan', order_by='RoadmapItem.day_number.asc()')

    @property
    def progress_percentage(self):
        if self.total_topics_count <= 0:
            return 0
        return int(round((self.completed_topics_count / self.total_topics_count) * 100))

    @property
    def days_remaining(self):
        return (self.exam_date - date.today()).days

    def __repr__(self):
        return f'<RoadmapPlan {self.title} for Subject {self.subject_id}>'


class RoadmapItem(db.Model):
    __tablename__ = 'roadmap_items'

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('roadmap_plans.id'), nullable=False)
    day_number = db.Column(db.Integer, nullable=False)
    scheduled_date = db.Column(db.Date, nullable=False)
    unit_name = db.Column(db.String(100), default='Unit 1')
    topic_title = db.Column(db.String(250), nullable=False)
    estimated_hours = db.Column(db.Float, default=1.5)
    is_revision = db.Column(db.Boolean, default=False)
    is_completed = db.Column(db.Boolean, default=False, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<RoadmapItem Day {self.day_number}: {self.topic_title} (done={self.is_completed})>'


class OfficialExamDirectory(db.Model):
    __tablename__ = 'official_exam_directory'

    id = db.Column(db.Integer, primary_key=True)
    exam_code = db.Column(db.String(30), unique=True, nullable=False)
    exam_name = db.Column(db.String(150), nullable=False)
    conducting_authority = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(60), nullable=False)  # 'Engineering', 'Management', 'Civil Services', etc.
    eligibility_summary = db.Column(db.String(255), nullable=False)
    official_portal_url = db.Column(db.String(255), nullable=False)
    verification_status = db.Column(db.String(50), default='Verified Official Source')
    last_verified_date = db.Column(db.String(30), default='October 2026')
    official_notification_note = db.Column(db.String(255), nullable=False)

    def __repr__(self):
        return f'<OfficialExamDirectory {self.exam_code}>'

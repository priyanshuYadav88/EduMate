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

    # Relationships
    subjects = db.relationship('Subject', backref='student', lazy=True, cascade='all, delete-orphan')
    tasks = db.relationship('Task', backref='student', lazy=True, cascade='all, delete-orphan')
    exams = db.relationship('Exam', backref='student', lazy=True, cascade='all, delete-orphan')
    timetable_entries = db.relationship('TimetableEntry', backref='student', lazy=True, cascade='all, delete-orphan')

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

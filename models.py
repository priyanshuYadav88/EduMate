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
    quizzes = db.relationship('QuizAttempt', backref='student', lazy=True, cascade='all, delete-orphan')
    chat_messages = db.relationship('ChatMessage', backref='student', lazy=True, cascade='all, delete-orphan')

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
    unit_name = db.Column(db.String(100), default='Unit 1')
    subtopics = db.Column(db.Text, nullable=True)  # JSON-encoded array of subtopics
    source_pages = db.Column(db.String(100), nullable=True)  # e.g. "2, 3"
    notes_content = db.Column(db.Text, nullable=True)  # AI-generated notes
    summary_content = db.Column(db.Text, nullable=True)  # AI-generated revision summary
    is_completed = db.Column(db.Boolean, default=False, nullable=False)
    status = db.Column(db.String(20), default='pending')  # 'pending', 'in_progress', 'completed'
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    quizzes = db.relationship('QuizAttempt', backref='topic', lazy=True, cascade='all, delete-orphan')

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
    status = db.Column(db.String(20), default='pending')  # 'pending', 'in_progress', 'completed'
    topic_id = db.Column(db.Integer, db.ForeignKey('topics.id'), nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    topic = db.relationship('Topic', backref=db.backref('roadmap_items', lazy=True))

    def __repr__(self):
        return f'<RoadmapItem Day {self.day_number}: {self.topic_title} (status={self.status})>'


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


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    admin_username = db.Column(db.String(64), nullable=False)
    action = db.Column(db.String(80), nullable=False)  # 'USER_CREATE', 'ROLE_CHANGE', 'PASSWORD_RESET', 'USER_DELETE', 'SETTINGS_UPDATE', etc.
    target_type = db.Column(db.String(50), nullable=True)  # 'user', 'subject', 'exam', 'system'
    target_id = db.Column(db.String(50), nullable=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    admin = db.relationship('User', backref=db.backref('performed_audits', lazy=True))

    def __repr__(self):
        return f'<AuditLog {self.action} by {self.admin_username}>'


class UploadedPdfDocument(db.Model):
    __tablename__ = 'uploaded_pdf_documents'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=True)
    filename = db.Column(db.String(255), nullable=False)
    file_size_bytes = db.Column(db.Integer, default=0)
    page_count = db.Column(db.Integer, default=0)
    ocr_applied = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(30), default='Uploaded')  # 'Uploaded', 'Extracting', 'OCR Required', 'Processing', 'AI Analysis Completed', 'Needs Review', 'Approved', 'Failed'
    extracted_text = db.Column(db.Text, nullable=True)
    structured_json = db.Column(db.Text, nullable=True)  # Validated hierarchical JSON of units & topics
    error_message = db.Column(db.Text, nullable=True)
    topics_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = db.relationship('User', backref=db.backref('uploaded_pdfs', lazy=True, cascade='all, delete-orphan'))
    subject = db.relationship('Subject', backref=db.backref('syllabus_pdfs', lazy=True))

    def __repr__(self):
        return f'<UploadedPdfDocument {self.filename} ({self.status})>'


class QuizAttempt(db.Model):
    __tablename__ = 'quiz_attempts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=True)
    topic_id = db.Column(db.Integer, db.ForeignKey('topics.id'), nullable=True)
    quiz_type = db.Column(db.String(50), default='mcq')  # 'mcq', 'short_questions'
    title = db.Column(db.String(200), nullable=False)
    score = db.Column(db.Integer, default=0)
    total_questions = db.Column(db.Integer, default=0)
    questions_data = db.Column(db.Text, nullable=True)  # JSON-encoded array of questions, options, user answers
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    subject = db.relationship('Subject', backref=db.backref('quizzes', lazy=True, cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<QuizAttempt {self.title}: {self.score}/{self.total_questions}>'


class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=True)
    role = db.Column(db.String(20), nullable=False)  # 'user' or 'assistant'
    content = db.Column(db.Text, nullable=False)
    provider = db.Column(db.String(30), nullable=True)  # 'gemini' or 'ollama'
    model = db.Column(db.String(60), nullable=True)
    fallback_used = db.Column(db.Boolean, default=False)
    source_pages = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    subject = db.relationship('Subject', backref=db.backref('chat_messages', lazy=True))

    def __repr__(self):
        return f'<ChatMessage {self.role} by User {self.user_id}>'


class SystemSetting(db.Model):
    __tablename__ = 'system_settings'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(60), unique=True, nullable=False, index=True)
    value = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    @staticmethod
    def get_val(key, default=None):
        setting = SystemSetting.query.filter_by(key=key).first()
        return setting.value if setting else default

    @staticmethod
    def set_val(key, value, description=None):
        setting = SystemSetting.query.filter_by(key=key).first()
        if not setting:
            setting = SystemSetting(key=key, value=str(value), description=description)
            db.session.add(setting)
        else:
            setting.value = str(value)
            if description:
                setting.description = description
        db.session.commit()
        return setting

    def __repr__(self):
        return f'<SystemSetting {self.key}={self.value}>'

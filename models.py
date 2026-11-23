import os
import base64
import hashlib
from datetime import datetime, date, timezone
from typing import Optional, Dict, Any
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.orm import validates
from cryptography.fernet import Fernet

db = SQLAlchemy()

def get_encryption_cipher(secret_key: Optional[str] = None) -> Fernet:
    """Derives a deterministic 32-byte Fernet key from SECRET_KEY or ENCRYPTION_SECRET_KEY."""
    raw = secret_key or os.getenv('ENCRYPTION_SECRET_KEY') or os.getenv('SECRET_KEY', 'edumate-btech-secret-key-2026')
    derived = hashlib.sha256(raw.encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(derived))

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='student')  # 'student' or 'admin'
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    @validates('role')
    def validate_role(self, key, role):
        if not role or role not in ('student', 'admin'):
            raise ValueError(f"Invalid user role '{role}'. Permitted roles: 'student', 'admin'.")
        return role

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

    @property
    def display_name(self) -> str:
        if self.profile and self.profile.full_name:
            return self.profile.full_name
        return self.username

    def get_or_create_profile(self):
        if not self.profile:
            prof = UserProfile(user_id=self.id)
            db.session.add(prof)
            db.session.commit()
            return prof
        return self.profile

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'


class UserProfile(db.Model):
    __tablename__ = 'user_profiles'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False, index=True)

    # Personal Information
    full_name = db.Column(db.String(100), nullable=True)
    phone_number = db.Column(db.String(25), nullable=True)
    avatar_url = db.Column(db.String(255), nullable=True)

    # Academic Information
    college_name = db.Column(db.String(150), nullable=True)
    university_name = db.Column(db.String(150), nullable=True)
    degree_course = db.Column(db.String(100), nullable=True)
    branch_department = db.Column(db.String(100), nullable=True)
    current_semester = db.Column(db.String(20), nullable=True)
    academic_session = db.Column(db.String(30), nullable=True)
    roll_number = db.Column(db.String(50), nullable=True)

    # Study Preferences
    daily_study_hours = db.Column(db.Float, default=3.0, nullable=True)
    preferred_study_time = db.Column(db.String(30), default='Evening', nullable=True)  # 'Early Morning', 'Afternoon', 'Evening', 'Night'
    preferred_language = db.Column(db.String(30), default='English', nullable=True)   # 'English', 'Hindi', 'Hinglish'
    target_exam = db.Column(db.String(100), nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    user = db.relationship('User', backref=db.backref('profile', uselist=False, cascade='all, delete-orphan'))

    @property
    def completion_percentage(self) -> int:
        """Calculates profile completion percentage across all sections."""
        tracked_fields = [
            bool(self.full_name and self.full_name.strip()),
            bool(self.phone_number and self.phone_number.strip()),
            bool(self.avatar_url and self.avatar_url.strip()),
            bool(self.college_name and self.college_name.strip()),
            bool(self.university_name and self.university_name.strip()),
            bool(self.degree_course and self.degree_course.strip()),
            bool(self.branch_department and self.branch_department.strip()),
            bool(self.current_semester and self.current_semester.strip()),
            bool(self.academic_session and self.academic_session.strip()),
            bool(self.roll_number and self.roll_number.strip()),
            bool(self.daily_study_hours and self.daily_study_hours > 0),
            bool(self.preferred_study_time and self.preferred_study_time.strip()),
            bool(self.preferred_language and self.preferred_language.strip()),
            bool(self.target_exam and self.target_exam.strip())
        ]
        # Base credit of 2 for username and email from the parent User account
        filled = sum(1 for f in tracked_fields if f) + 2
        total = len(tracked_fields) + 2
        return int(round((filled / total) * 100))

    def to_dict(self) -> Dict[str, Any]:
        return {
            'full_name': self.full_name or '',
            'phone_number': self.phone_number or '',
            'avatar_url': self.avatar_url or '',
            'college_name': self.college_name or '',
            'university_name': self.university_name or '',
            'degree_course': self.degree_course or '',
            'branch_department': self.branch_department or '',
            'current_semester': self.current_semester or '',
            'academic_session': self.academic_session or '',
            'roll_number': self.roll_number or '',
            'daily_study_hours': self.daily_study_hours if self.daily_study_hours is not None else 3.0,
            'preferred_study_time': self.preferred_study_time or 'Evening',
            'preferred_language': self.preferred_language or 'English',
            'target_exam': self.target_exam or '',
            'completion_percentage': self.completion_percentage
        }

    def __repr__(self):
        return f'<UserProfile for User {self.user_id} ({self.full_name or "Unnamed"})>'


def cleanup_verified_demo_accounts() -> Dict[str, Any]:
    """
    Safely identifies and removes ONLY verified seed/demo accounts.
    Explicit safety checks:
      1. Must match BOTH a known demo username ('demo_student', 'demo_admin')
         AND an '@edumate.local' email domain.
      2. Legitimate user accounts and real academic records are never touched.
    """
    demo_specs = [
        ('demo_student', 'student@edumate.local'),
        ('demo_admin', 'admin@edumate.local')
    ]
    deleted_accounts = []
    for uname, uemail in demo_specs:
        user = User.query.filter(
            User.username == uname,
            User.email == uemail
        ).first()
        if user:
            deleted_accounts.append({'id': user.id, 'username': user.username, 'email': user.email, 'role': user.role})
            db.session.delete(user)
    if deleted_accounts:
        db.session.commit()
    return {
        'success': True,
        'count': len(deleted_accounts),
        'deleted': deleted_accounts
    }


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


class AIProviderConfig(db.Model):
    __tablename__ = 'ai_provider_configs'

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.String(30), unique=True, nullable=False, index=True)  # 'gemini', 'groq', 'ollama'
    display_name = db.Column(db.String(60), nullable=False)  # 'Google Gemini', 'Groq API', 'Ollama (Local AI)'
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    is_primary = db.Column(db.Boolean, default=False, nullable=False)
    priority = db.Column(db.Integer, default=1, nullable=False)  # 1 = primary, 2 = fallback 1, 3 = fallback 2
    api_key_encrypted = db.Column(db.Text, nullable=True)  # Fernet encrypted at rest
    api_base_url = db.Column(db.String(255), nullable=True)
    model_name = db.Column(db.String(100), nullable=False)
    timeout_sec = db.Column(db.Float, default=15.0, nullable=False)
    last_status = db.Column(db.String(30), default='untested')  # 'active', 'error', 'disabled', 'untested'
    last_tested_at = db.Column(db.DateTime, nullable=True)
    last_test_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    def set_api_key(self, raw_key: Optional[str], secret_key: Optional[str] = None):
        """Encrypts and stores API key at rest using Fernet."""
        if raw_key is None or not raw_key.strip():
            self.api_key_encrypted = None
            return
        clean_key = raw_key.strip()
        cipher = get_encryption_cipher(secret_key)
        self.api_key_encrypted = cipher.encrypt(clean_key.encode('utf-8')).decode('utf-8')

    def get_api_key(self, secret_key: Optional[str] = None) -> Optional[str]:
        """Decrypts and returns the raw API key for outbound server-side requests."""
        if not self.api_key_encrypted:
            return None
        try:
            cipher = get_encryption_cipher(secret_key)
            return cipher.decrypt(self.api_key_encrypted.encode('utf-8')).decode('utf-8')
        except Exception:
            return None

    def get_masked_key(self) -> str:
        """Returns masked API key safe for UI presentation without leaking the secret."""
        raw_key = self.get_api_key()
        if not raw_key:
            return ""
        if len(raw_key) <= 8:
            return "••••••••"
        return f"{raw_key[:4]}••••••••{raw_key[-4:]}"

    def to_safe_dict(self) -> Dict[str, Any]:
        """Returns safe dictionary representation for templates and API responses."""
        return {
            'id': self.id,
            'provider_id': self.provider_id,
            'display_name': self.display_name,
            'is_enabled': self.is_enabled,
            'is_primary': self.is_primary,
            'priority': self.priority,
            'has_api_key': bool(self.api_key_encrypted),
            'masked_key': self.get_masked_key(),
            'api_base_url': self.api_base_url,
            'model_name': self.model_name,
            'timeout_sec': self.timeout_sec,
            'last_status': self.last_status,
            'last_tested_at': self.last_tested_at.strftime('%d %b %Y, %H:%M:%S') if self.last_tested_at else None,
            'last_test_message': self.last_test_message
        }

    def __repr__(self):
        return f'<AIProviderConfig {self.provider_id} (enabled={self.is_enabled}, priority={self.priority})>'


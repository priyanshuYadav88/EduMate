import os
import sqlite3
import shutil
from datetime import datetime, timezone, date
from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    current_app, abort, jsonify, send_file, Response
)
from flask_login import login_required, current_user
from auth import admin_required
from models import (
    db, User, Subject, Topic, Task, Exam, TimetableEntry,
    RoadmapPlan, RoadmapItem, OfficialExamDirectory,
    AuditLog, UploadedPdfDocument, SystemSetting
)
from ai_service import ai_service, InvalidInputException

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def log_admin_action(action, target_type=None, target_id=None, details=None):
    """Utility helper to record sensitive admin actions in AuditLog."""
    try:
        ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        if ip and ',' in ip:
            ip = ip.split(',')[0].strip()
        log = AuditLog(
            admin_id=current_user.id if current_user.is_authenticated else None,
            admin_username=current_user.username if current_user.is_authenticated else 'system',
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id else None,
            details=details,
            ip_address=ip
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Audit log failure: {e}")


# ==============================================================================
# PHASE 1 — Admin Overview Dashboard
# ==============================================================================
@admin_bp.route('/')
@login_required
@admin_required
def dashboard():
    # Database-backed stats strictly from SQLite
    total_users = User.query.count()
    active_users = User.query.filter_by(is_active=True).count()
    inactive_users = User.query.filter_by(is_active=False).count()
    total_students = User.query.filter_by(role='student').count()
    total_admins = User.query.filter_by(role='admin').count()

    total_subjects = Subject.query.count()
    total_topics = Topic.query.count()
    total_tasks = Task.query.count()
    total_exams = Exam.query.count()
    total_roadmaps = RoadmapPlan.query.count()
    total_pdfs = UploadedPdfDocument.query.count()

    # Recent Registrations
    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()

    # Recent System Activities / Audit Logs
    recent_activities = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(8).all()

    # System & Database Diagnostics
    db_path = current_app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
    db_size_kb = 0
    if os.path.exists(db_path):
        db_size_kb = round(os.path.getsize(db_path) / 1024, 2)

    maintenance_mode = SystemSetting.get_val('maintenance_mode', 'false') == 'true'

    health_info = {
        'database_type': 'SQLite 3 Relational DB',
        'database_size_kb': db_size_kb,
        'sqlite_version': sqlite3.sqlite_version,
        'maintenance_mode': maintenance_mode,
        'status': 'Operational & Healthy'
    }

    return render_template(
        'admin/dashboard.html',
        total_users=total_users,
        active_users=active_users,
        inactive_users=inactive_users,
        total_students=total_students,
        total_admins=total_admins,
        total_subjects=total_subjects,
        total_topics=total_topics,
        total_tasks=total_tasks,
        total_exams=total_exams,
        total_roadmaps=total_roadmaps,
        total_pdfs=total_pdfs,
        recent_users=recent_users,
        recent_activities=recent_activities,
        health_info=health_info,
        ai_status=ai_service.get_provider_status()
    )


# ==============================================================================
# PHASE 2 — User Management
# ==============================================================================
@admin_bp.route('/users')
@login_required
@admin_required
def users_list():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('q', '').strip()
    role_filter = request.args.get('role', '').strip()
    status_filter = request.args.get('status', '').strip()

    query = User.query

    if search:
        search_like = f"%{search}%"
        query = query.filter(
            db.or_(
                User.username.ilike(search_like),
                User.email.ilike(search_like)
            )
        )

    if role_filter in ['student', 'admin']:
        query = query.filter_by(role=role_filter)

    if status_filter == 'active':
        query = query.filter_by(is_active=True)
    elif status_filter == 'inactive':
        query = query.filter_by(is_active=False)

    pagination = query.order_by(User.created_at.desc()).paginate(page=page, per_page=10, error_out=False)

    return render_template(
        'admin/users.html',
        pagination=pagination,
        search=search,
        role_filter=role_filter,
        status_filter=status_filter
    )


@admin_bp.route('/users/create', methods=['POST'])
@login_required
@admin_required
def create_user():
    username = request.form.get('username', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    role = request.form.get('role', 'student').strip()
    is_active = request.form.get('is_active') == 'true'

    if not username or not email or not password:
        flash('All required fields (Username, Email, Password) must be filled.', 'danger')
        return redirect(url_for('admin.users_list'))

    if len(username) < 3 or len(password) < 6:
        flash('Username must be >= 3 characters and Password must be >= 6 characters.', 'danger')
        return redirect(url_for('admin.users_list'))

    if role not in ['student', 'admin']:
        role = 'student'

    if User.query.filter_by(username=username).first():
        flash(f"Username '{username}' is already in use.", 'warning')
        return redirect(url_for('admin.users_list'))

    if User.query.filter_by(email=email).first():
        flash(f"Email '{email}' is already registered.", 'warning')
        return redirect(url_for('admin.users_list'))

    new_user = User(
        username=username,
        email=email,
        role=role,
        is_active=is_active
    )
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()

    log_admin_action(
        action='USER_CREATE',
        target_type='user',
        target_id=new_user.id,
        details=f"Created user '{username}' with role '{role}'"
    )

    flash(f"User '{username}' created successfully as {role.capitalize()}.", 'success')
    return redirect(url_for('admin.users_list'))


@admin_bp.route('/users/<int:user_id>')
@login_required
@admin_required
def user_detail(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)

    subjects = Subject.query.filter_by(user_id=user.id).all()
    tasks = Task.query.filter_by(user_id=user.id).order_by(Task.due_date.desc()).limit(15).all()
    exams = Exam.query.filter_by(user_id=user.id).order_by(Exam.exam_date.asc()).all()
    roadmaps = RoadmapPlan.query.filter_by(user_id=user.id).order_by(RoadmapPlan.created_at.desc()).all()
    pdfs = UploadedPdfDocument.query.filter_by(user_id=user.id).order_by(UploadedPdfDocument.created_at.desc()).all()

    return render_template(
        'admin/user_detail.html',
        target_user=user,
        subjects=subjects,
        tasks=tasks,
        exams=exams,
        roadmaps=roadmaps,
        pdfs=pdfs
    )


@admin_bp.route('/users/<int:user_id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)

    username = request.form.get('username', '').strip()
    email = request.form.get('email', '').strip().lower()
    role = request.form.get('role', user.role).strip()
    is_active = request.form.get('is_active') == 'true'

    if not username or not email:
        flash('Username and Email cannot be empty.', 'danger')
        return redirect(url_for('admin.user_detail', user_id=user.id))

    # Check unique username/email collision with other users
    existing_u = User.query.filter(User.username == username, User.id != user.id).first()
    if existing_u:
        flash(f"Username '{username}' is already taken by another account.", 'warning')
        return redirect(url_for('admin.user_detail', user_id=user.id))

    existing_e = User.query.filter(User.email == email, User.id != user.id).first()
    if existing_e:
        flash(f"Email '{email}' is already registered to another account.", 'warning')
        return redirect(url_for('admin.user_detail', user_id=user.id))

    # Guard: Cannot remove last admin or demote self if only admin
    if user.role == 'admin' and role != 'admin':
        admin_count = User.query.filter_by(role='admin', is_active=True).count()
        if admin_count <= 1:
            flash('Operation rejected: You cannot remove the last active administrator.', 'danger')
            return redirect(url_for('admin.user_detail', user_id=user.id))

    # Guard: Cannot deactivate self
    if user.id == current_user.id and not is_active:
        flash('You cannot deactivate your own logged-in administrator account.', 'warning')
        is_active = True

    old_role = user.role
    user.username = username
    user.email = email
    user.role = role if role in ['student', 'admin'] else 'student'
    user.is_active = is_active
    db.session.commit()

    log_admin_action(
        action='USER_EDIT',
        target_type='user',
        target_id=user.id,
        details=f"Updated profile for '{username}'. Role: {old_role} -> {user.role}, Active: {is_active}"
    )

    flash(f"User account '{username}' updated successfully.", 'success')
    return redirect(url_for('admin.user_detail', user_id=user.id))


@admin_bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@login_required
@admin_required
def reset_user_password(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)

    new_password = request.form.get('new_password', '')
    if len(new_password) < 6:
        flash('New password must be at least 6 characters.', 'danger')
        return redirect(url_for('admin.user_detail', user_id=user.id))

    user.set_password(new_password)
    db.session.commit()

    log_admin_action(
        action='PASSWORD_RESET',
        target_type='user',
        target_id=user.id,
        details=f"Admin reset password for user '{user.username}'"
    )

    flash(f"Password for user '{user.username}' has been successfully reset.", 'success')
    return redirect(url_for('admin.user_detail', user_id=user.id))


@admin_bp.route('/toggle-user/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def toggle_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)

    # Protect against self-deactivation
    if user.id == current_user.id:
        flash('You cannot deactivate your own administrative account.', 'warning')
        return redirect(request.referrer or url_for('admin.users_list'))

    # Protect against deactivating the last active admin
    if user.role == 'admin' and user.is_active:
        admin_count = User.query.filter_by(role='admin', is_active=True).count()
        if admin_count <= 1:
            flash('Operation rejected: You cannot deactivate the last active administrator.', 'danger')
            return redirect(request.referrer or url_for('admin.users_list'))

    user.is_active = not user.is_active
    db.session.commit()

    action = 'activated' if user.is_active else 'deactivated'
    log_admin_action(
        action='USER_STATUS_TOGGLE',
        target_type='user',
        target_id=user.id,
        details=f"User '{user.username}' was {action}"
    )

    flash(f"User '{user.username}' has been {action}.", 'success')
    return redirect(request.referrer or url_for('admin.users_list'))


@admin_bp.route('/delete-user/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)

    # Protect against self-deletion
    if user.id == current_user.id:
        flash('You cannot delete your own administrative account.', 'danger')
        return redirect(url_for('admin.users_list'))

    # Protect against deleting the last admin
    if user.role == 'admin':
        admin_count = User.query.filter_by(role='admin').count()
        if admin_count <= 1:
            flash('Operation rejected: You cannot delete the last administrator.', 'danger')
            return redirect(url_for('admin.users_list'))

    username = user.username
    user_id_val = user.id
    db.session.delete(user)
    db.session.commit()

    log_admin_action(
        action='USER_DELETE',
        target_type='user',
        target_id=user_id_val,
        details=f"Permanently removed user account '{username}'"
    )

    flash(f"User account '{username}' and all associated records have been removed.", 'success')
    return redirect(url_for('admin.users_list'))


# ==============================================================================
# PHASE 3 — Academic Management
# ==============================================================================
@admin_bp.route('/academics')
@login_required
@admin_required
def academics_list():
    student_id = request.args.get('student_id', type=int)
    search = request.args.get('q', '').strip()

    subject_query = Subject.query
    if student_id:
        subject_query = subject_query.filter_by(user_id=student_id)
    if search:
        subject_query = subject_query.filter(Subject.name.ilike(f"%{search}%"))

    subjects = subject_query.order_by(Subject.created_at.desc()).all()
    students = User.query.filter_by(role='student').order_by(User.username.asc()).all()

    # Academic counters
    exams = Exam.query.order_by(Exam.exam_date.asc()).limit(10).all()
    roadmaps = RoadmapPlan.query.order_by(RoadmapPlan.created_at.desc()).limit(10).all()
    official_exams = OfficialExamDirectory.query.order_by(OfficialExamDirectory.exam_code.asc()).all()

    return render_template(
        'admin/academics.html',
        subjects=subjects,
        students=students,
        student_id=student_id,
        search=search,
        exams=exams,
        roadmaps=roadmaps,
        official_exams=official_exams
    )


@admin_bp.route('/academics/subjects/create', methods=['POST'])
@login_required
@admin_required
def create_academic_subject():
    student_id = request.form.get('student_id', type=int)
    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip().upper()
    color = request.form.get('color', '#2563eb')
    icon = request.form.get('icon', 'book')

    student = db.session.get(User, student_id)
    if not student:
        flash('Invalid student selected.', 'danger')
        return redirect(url_for('admin.academics_list'))

    if not name or not code:
        flash('Subject Name and Code are required.', 'danger')
        return redirect(url_for('admin.academics_list'))

    new_sub = Subject(
        name=name,
        code=code,
        color=color,
        icon=icon,
        user_id=student.id
    )
    db.session.add(new_sub)
    db.session.commit()

    log_admin_action(
        action='SUBJECT_CREATE',
        target_type='subject',
        target_id=new_sub.id,
        details=f"Created subject '{name}' ({code}) for student '{student.username}'"
    )

    flash(f"Subject '{name}' created for student {student.username}.", 'success')
    return redirect(url_for('admin.academics_list'))


@admin_bp.route('/academics/subjects/<int:subject_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_academic_subject(subject_id):
    subject = db.session.get(Subject, subject_id)
    if not subject:
        abort(404)

    name = subject.name
    student_name = subject.student.username
    db.session.delete(subject)
    db.session.commit()

    log_admin_action(
        action='SUBJECT_DELETE',
        target_type='subject',
        target_id=subject_id,
        details=f"Deleted subject '{name}' belonging to student '{student_name}'"
    )

    flash(f"Subject '{name}' and all its topics/roadmaps were removed.", 'success')
    return redirect(url_for('admin.academics_list'))


@admin_bp.route('/academics/subjects/<int:subject_id>/topics')
@login_required
@admin_required
def subject_topics_view(subject_id):
    subject = db.session.get(Subject, subject_id)
    if not subject:
        abort(404)

    return render_template('admin/subject_topics.html', subject=subject)


@admin_bp.route('/academics/subjects/<int:subject_id>/topics/add', methods=['POST'])
@login_required
@admin_required
def add_subject_topic(subject_id):
    subject = db.session.get(Subject, subject_id)
    if not subject:
        abort(404)

    title = request.form.get('title', '').strip()
    is_completed = request.form.get('is_completed') == 'true'

    if not title:
        flash('Topic title cannot be empty.', 'danger')
        return redirect(url_for('admin.subject_topics_view', subject_id=subject.id))

    new_t = Topic(
        title=title,
        is_completed=is_completed,
        subject_id=subject.id
    )
    db.session.add(new_t)
    db.session.commit()

    log_admin_action(
        action='TOPIC_ADD',
        target_type='topic',
        target_id=new_t.id,
        details=f"Added topic '{title}' to subject '{subject.name}'"
    )

    flash(f"Topic '{title}' added to {subject.name}.", 'success')
    return redirect(url_for('admin.subject_topics_view', subject_id=subject.id))


@admin_bp.route('/academics/topics/<int:topic_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_subject_topic(topic_id):
    topic = db.session.get(Topic, topic_id)
    if not topic:
        abort(404)

    subject_id = topic.subject_id
    title = topic.title
    db.session.delete(topic)
    db.session.commit()

    log_admin_action(
        action='TOPIC_DELETE',
        target_type='topic',
        target_id=topic_id,
        details=f"Deleted topic '{title}'"
    )

    flash(f"Topic '{title}' deleted.", 'success')
    return redirect(url_for('admin.subject_topics_view', subject_id=subject_id))


@admin_bp.route('/academics/official-exams/create', methods=['POST'])
@login_required
@admin_required
def create_official_exam():
    exam_code = request.form.get('exam_code', '').strip().upper()
    exam_name = request.form.get('exam_name', '').strip()
    conducting_authority = request.form.get('conducting_authority', '').strip()
    category = request.form.get('category', 'Engineering & Technology').strip()
    eligibility_summary = request.form.get('eligibility_summary', '').strip()
    official_portal_url = request.form.get('official_portal_url', '').strip()
    official_notification_note = request.form.get('official_notification_note', '').strip()

    if not exam_code or not exam_name or not official_portal_url:
        flash('Exam Code, Name, and Official URL are required.', 'danger')
        return redirect(url_for('admin.academics_list'))

    existing = OfficialExamDirectory.query.filter_by(exam_code=exam_code).first()
    if existing:
        flash(f"Exam code '{exam_code}' already exists in directory.", 'warning')
        return redirect(url_for('admin.academics_list'))

    new_exam = OfficialExamDirectory(
        exam_code=exam_code,
        exam_name=exam_name,
        conducting_authority=conducting_authority,
        category=category,
        eligibility_summary=eligibility_summary,
        official_portal_url=official_portal_url,
        official_notification_note=official_notification_note,
        last_verified_date=datetime.now().strftime('%B %Y')
    )
    db.session.add(new_exam)
    db.session.commit()

    log_admin_action(
        action='OFFICIAL_EXAM_ADD',
        target_type='exam_directory',
        target_id=new_exam.id,
        details=f"Added official exam '{exam_code}' - {exam_name}"
    )

    flash(f"Official exam entry '{exam_code}' added successfully.", 'success')
    return redirect(url_for('admin.academics_list'))


# ==============================================================================
# PHASE 4 — PDF and Study Material Management
# ==============================================================================
@admin_bp.route('/pdfs')
@login_required
@admin_required
def pdf_management_view():
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status', '').strip()

    query = UploadedPdfDocument.query
    if status_filter in ['processed', 'ocr_required', 'encrypted', 'failed']:
        query = query.filter_by(status=status_filter)

    pagination = query.order_by(UploadedPdfDocument.created_at.desc()).paginate(page=page, per_page=12, error_out=False)

    total_uploaded = UploadedPdfDocument.query.count()
    successful_processed = UploadedPdfDocument.query.filter_by(status='processed').count()
    ocr_required_count = UploadedPdfDocument.query.filter_by(status='ocr_required').count()
    failed_count = UploadedPdfDocument.query.filter(UploadedPdfDocument.status.in_(['failed', 'encrypted'])).count()

    return render_template(
        'admin/pdfs.html',
        pagination=pagination,
        status_filter=status_filter,
        total_uploaded=total_uploaded,
        successful_processed=successful_processed,
        ocr_required_count=ocr_required_count,
        failed_count=failed_count
    )


@admin_bp.route('/pdfs/<int:pdf_id>')
@login_required
@admin_required
def pdf_detail_view(pdf_id):
    pdf_doc = db.session.get(UploadedPdfDocument, pdf_id)
    if not pdf_doc:
        abort(404)

    return render_template('admin/pdf_detail.html', doc=pdf_doc)


@admin_bp.route('/pdfs/<int:pdf_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_pdf_record(pdf_id):
    pdf_doc = db.session.get(UploadedPdfDocument, pdf_id)
    if not pdf_doc:
        abort(404)

    filename = pdf_doc.filename
    db.session.delete(pdf_doc)
    db.session.commit()

    log_admin_action(
        action='PDF_RECORD_DELETE',
        target_type='pdf_document',
        target_id=pdf_id,
        details=f"Deleted PDF document log for '{filename}'"
    )

    flash(f"PDF record for '{filename}' was removed.", 'success')
    return redirect(url_for('admin.pdf_management_view'))


# ==============================================================================
# PHASE 5 — System Control & Database Backups
# ==============================================================================
@admin_bp.route('/system')
@login_required
@admin_required
def system_control_view():
    db_path = current_app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
    db_size_kb = round(os.path.getsize(db_path) / 1024, 2) if os.path.exists(db_path) else 0

    maintenance_mode = SystemSetting.get_val('maintenance_mode', 'false') == 'true'
    allow_registrations = SystemSetting.get_val('allow_registrations', 'true') == 'true'

    settings = {
        'maintenance_mode': maintenance_mode,
        'allow_registrations': allow_registrations
    }

    # Backup files listing
    backup_dir = os.path.join(os.path.dirname(db_path), 'backups')
    backup_files = []
    if os.path.exists(backup_dir):
        for f in os.listdir(backup_dir):
            if f.endswith('.sqlite') or f.endswith('.db'):
                fp = os.path.join(backup_dir, f)
                backup_files.append({
                    'name': f,
                    'size_kb': round(os.path.getsize(fp) / 1024, 2),
                    'created_at': datetime.fromtimestamp(os.path.getmtime(fp)).strftime('%d %b %Y %H:%M:%S')
                })

    backup_files.sort(key=lambda x: x['name'], reverse=True)

    # Get live provider status from Hybrid AI service
    ai_status = ai_service.get_provider_status()

    return render_template(
        'admin/system.html',
        db_size_kb=db_size_kb,
        settings=settings,
        backup_files=backup_files,
        sqlite_version=sqlite3.sqlite_version,
        ai_status=ai_status
    )


@admin_bp.route('/ai/status', methods=['GET'])
@login_required
@admin_required
def admin_ai_status():
    """Returns real-time configuration and health of Gemini and Ollama providers."""
    status = ai_service.get_provider_status()
    return jsonify({'success': True, 'status': status})


@admin_bp.route('/ai/test', methods=['POST'])
@login_required
@admin_required
def admin_ai_test():
    """
    Admin-only diagnostic test endpoint.
    Tests hybrid AI execution, returns the actual provider utilized,
    and logs the action in the audit trail.
    """
    data = request.get_json() if request.is_json else request.form
    prompt = (data.get('prompt') or 'Hello! Briefly introduce yourself in one sentence.').strip()

    try:
        result = ai_service.generate_response(
            prompt=prompt,
            system_instruction="You are EduMate AI Study Assistant. Be concise and precise."
        )

        log_admin_action(
            action='AI_PROVIDER_TEST',
            target_type='ai_service',
            details=f"Test executed. Provider: {result.get('provider')}, Fallback used: {result.get('fallback_used')}"
        )

        return jsonify(result), (200 if result.get('success') else 503)
    except InvalidInputException as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': f"Unexpected system error: {str(e)}"}), 500


@admin_bp.route('/system/settings/update', methods=['POST'])
@login_required
@admin_required
def update_system_settings():
    maintenance_mode = request.form.get('maintenance_mode') == 'true'
    allow_registrations = request.form.get('allow_registrations') == 'true'

    SystemSetting.set_val('maintenance_mode', 'true' if maintenance_mode else 'false', 'Maintenance Mode Flag')
    SystemSetting.set_val('allow_registrations', 'true' if allow_registrations else 'false', 'Allow Public Registrations')

    log_admin_action(
        action='SETTINGS_UPDATE',
        target_type='system',
        details=f"Maintenance mode: {maintenance_mode}, Allow registrations: {allow_registrations}"
    )

    flash('System settings updated successfully.', 'success')
    return redirect(url_for('admin.system_control_view'))


@admin_bp.route('/system/backup/create', methods=['POST'])
@login_required
@admin_required
def create_database_backup():
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    db_path = db_uri.replace('sqlite:///', '')

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_filename = f"edumate_backup_{timestamp}.sqlite"

    if db_path == ':memory:' or not db_path:
        # In-memory test environment backup
        backup_dir = os.path.join(current_app.root_path, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, backup_filename)
        try:
            raw_conn = db.engine.raw_connection()
            dst_conn = sqlite3.connect(backup_path)
            raw_conn.driver_connection.backup(dst_conn)
            dst_conn.close()

            log_admin_action(
                action='DATABASE_BACKUP_CREATE',
                target_type='database',
                details=f"Created backup file '{backup_filename}'"
            )
            flash(f"Database backup '{backup_filename}' created successfully.", 'success')
        except Exception as e:
            flash(f"Backup creation failed: {str(e)}", 'danger')
        return redirect(url_for('admin.system_control_view'))

    if not os.path.exists(db_path):
        flash('Database file not found.', 'danger')
        return redirect(url_for('admin.system_control_view'))

    backup_dir = os.path.join(os.path.dirname(db_path), 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    backup_path = os.path.join(backup_dir, backup_filename)

    try:
        # Use SQLite online backup API to ensure safety even if database is active
        src_conn = sqlite3.connect(db_path)
        dst_conn = sqlite3.connect(backup_path)
        src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()

        log_admin_action(
            action='DATABASE_BACKUP_CREATE',
            target_type='database',
            details=f"Created backup file '{backup_filename}'"
        )
        flash(f"Database backup '{backup_filename}' created successfully.", 'success')
    except Exception as e:
        flash(f"Backup creation failed: {str(e)}", 'danger')

    return redirect(url_for('admin.system_control_view'))


@admin_bp.route('/system/backup/download/<filename>')
@login_required
@admin_required
def download_backup_file(filename):
    # Prevent directory traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        abort(400)

    db_path = current_app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
    backup_path = os.path.join(os.path.dirname(db_path), 'backups', filename)

    if not os.path.exists(backup_path):
        abort(404)

    log_admin_action(
        action='DATABASE_BACKUP_DOWNLOAD',
        target_type='database',
        details=f"Downloaded backup '{filename}'"
    )

    return send_file(backup_path, as_attachment=True, download_name=filename)


# ==============================================================================
# PHASE 6 — Audit Logs Viewer
# ==============================================================================
@admin_bp.route('/audit-logs')
@login_required
@admin_required
def audit_logs_view():
    page = request.args.get('page', 1, type=int)
    action_filter = request.args.get('action', '').strip()

    query = AuditLog.query
    if action_filter:
        query = query.filter_by(action=action_filter)

    pagination = query.order_by(AuditLog.created_at.desc()).paginate(page=page, per_page=20, error_out=False)

    # Distinct actions for filter
    available_actions = [r[0] for r in db.session.query(AuditLog.action).distinct().all()]

    return render_template(
        'admin/audit_logs.html',
        pagination=pagination,
        action_filter=action_filter,
        available_actions=available_actions
    )

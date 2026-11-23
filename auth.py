import re
from functools import wraps
from datetime import timedelta
from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    abort, session, current_app
)
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User, UserProfile, SystemSetting

auth_bp = Blueprint('auth', __name__)

def admin_required(f):
    """
    Decorator to restrict route access strictly to admin users.
    Returns 403 Forbidden if current_user is not an admin.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login', next=request.url))
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


RESERVED_USERNAMES = {
    'admin', 'administrator', 'root', 'system', 'superuser',
    'demo_admin', 'test_admin', 'edumate_admin', 'manager', 'staff'
}

EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    # Check if public registration is enabled by administrator
    if SystemSetting.get_val('allow_registrations', 'true') == 'false':
        flash('Public registration is currently closed by the administrator.', 'warning')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        # Personal Information
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        full_name = request.form.get('full_name', '').strip() or username
        phone_number = request.form.get('phone_number', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        # Academic Information (optional fields)
        college_name = request.form.get('college_name', '').strip()
        university_name = request.form.get('university_name', '').strip()
        degree_course = request.form.get('degree_course', '').strip()
        branch_department = request.form.get('branch_department', '').strip()
        current_semester = request.form.get('current_semester', '').strip()
        academic_session = request.form.get('academic_session', '').strip()
        roll_number = request.form.get('roll_number', '').strip()

        form_data = {
            'full_name': full_name,
            'username': username,
            'email': email,
            'phone_number': phone_number,
            'college_name': college_name,
            'university_name': university_name,
            'degree_course': degree_course,
            'branch_department': branch_department,
            'current_semester': current_semester,
            'academic_session': academic_session,
            'roll_number': roll_number
        }

        # Server-side validation
        if not username or not email or not password:
            flash('Full Name, Username, Email, and Password are required.', 'danger')
            return render_template('auth/register.html', **form_data)

        if len(username) < 3:
            flash('Username must be at least 3 characters long.', 'danger')
            return render_template('auth/register.html', **form_data)

        if not re.match(r'^[a-zA-Z0-9_.-]+$', username):
            flash('Username may only contain letters, numbers, periods, hyphens, and underscores.', 'danger')
            return render_template('auth/register.html', **form_data)

        if not EMAIL_REGEX.match(email):
            flash('Please enter a valid email address (e.g., student@college.edu).', 'danger')
            return render_template('auth/register.html', **form_data)

        if len(password) < 6:
            flash('Password must be at least 6 characters long.', 'danger')
            return render_template('auth/register.html', **form_data)

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('auth/register.html', **form_data)

        # Safeguard: Prevent registration of reserved administrative usernames
        if username.lower() in RESERVED_USERNAMES:
            flash(f"Username '{username}' is reserved. Please choose another username.", 'danger')
            return render_template('auth/register.html', **form_data)

        # Case-insensitive uniqueness check for username
        if User.query.filter(db.func.lower(User.username) == username.lower()).first():
            flash('Username is already taken. Please choose another.', 'danger')
            return render_template('auth/register.html', **form_data)

        # Case-insensitive uniqueness check for email
        if User.query.filter(db.func.lower(User.email) == email.lower()).first():
            flash('Email is already registered. Please log in.', 'danger')
            return render_template('auth/register.html', **form_data)

        # Strict security constraint: Public registration MUST ALWAYS assign 'student' role.
        # Any attempt to pass role='admin' in form data or headers is strictly disregarded.
        new_user = User(
            username=username,
            email=email,
            role='student',
            is_active=True
        )
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.flush()  # Generates new_user.id

        # Step 3: Study Preferences
        daily_study_hours_raw = request.form.get('daily_study_hours', '3.0')
        try:
            daily_study_hours = max(0.5, min(16.0, float(daily_study_hours_raw)))
        except (ValueError, TypeError):
            daily_study_hours = 3.0
        preferred_study_time = request.form.get('preferred_study_time', 'Evening').strip()
        if preferred_study_time not in ('Early Morning', 'Morning', 'Afternoon', 'Evening', 'Night'):
            preferred_study_time = 'Evening'
        preferred_language = request.form.get('preferred_language', 'English').strip()
        if preferred_language not in ('English', 'Hindi', 'Hinglish'):
            preferred_language = 'English'
        target_exam = request.form.get('target_exam', '').strip()

        # Initialize student profile with personal, academic & preference data
        profile = UserProfile(
            user_id=new_user.id,
            full_name=full_name,
            phone_number=phone_number,
            college_name=college_name,
            university_name=university_name,
            degree_course=degree_course,
            branch_department=branch_department,
            current_semester=current_semester,
            academic_session=academic_session,
            roll_number=roll_number,
            daily_study_hours=daily_study_hours,
            preferred_study_time=preferred_study_time,
            preferred_language=preferred_language,
            target_exam=target_exam
        )
        db.session.add(profile)
        db.session.commit()

        flash('Registration successful! You can now log in with your credentials.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        password = request.form.get('password', '')
        remember = bool(request.form.get('remember'))

        if not identifier or not password:
            flash('Please enter both your username/email and password.', 'danger')
            return render_template('auth/login.html', identifier=identifier)

        # Allow case-insensitive login by either username or email
        ident_lower = identifier.lower()
        user = User.query.filter(
            (db.func.lower(User.username) == ident_lower) | (db.func.lower(User.email) == ident_lower)
        ).first()

        if not user or not user.check_password(password):
            flash('Invalid username/email or password. Please try again.', 'danger')
            return render_template('auth/login.html', identifier=identifier)

        if not user.is_active:
            flash('Your account has been deactivated. Please contact an administrator.', 'danger')
            return render_template('auth/login.html', identifier=identifier)

        # Configure session persistence based on Remember Me checkbox
        if remember:
            session.permanent = True
            current_app.permanent_session_lifetime = timedelta(days=30)
        else:
            session.permanent = False

        login_user(user, remember=remember)
        flash(f'Welcome back, {user.display_name}!', 'success')

        next_page = request.args.get('next')
        if next_page and next_page.startswith('/'):
            return redirect(next_page)

        if user.is_admin:
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('dashboard'))

    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('auth.login'))

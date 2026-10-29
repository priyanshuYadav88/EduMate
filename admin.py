import os
import sqlite3
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, abort
from flask_login import login_required, current_user
from auth import admin_required
from models import db, User, Subject, Task, Exam, TimetableEntry

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/')
@login_required
@admin_required
def dashboard():
    # Database-backed stats
    total_users = User.query.count()
    total_students = User.query.filter_by(role='student').count()
    total_admins = User.query.filter_by(role='admin').count()
    active_users = User.query.filter_by(is_active=True).count()
    total_subjects = Subject.query.count()
    total_tasks = Task.query.count()
    total_exams = Exam.query.count()

    # User list
    users = User.query.order_by(User.created_at.desc()).all()

    # System health metrics
    db_path = current_app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
    db_size_kb = 0
    if os.path.exists(db_path):
        db_size_kb = round(os.path.getsize(db_path) / 1024, 2)

    health_info = {
        'database_type': 'SQLite 3',
        'database_size_kb': db_size_kb,
        'sqlite_version': sqlite3.sqlite_version,
        'status': 'Healthy'
    }

    return render_template(
        'admin/dashboard.html',
        total_users=total_users,
        total_students=total_students,
        total_admins=total_admins,
        active_users=active_users,
        total_subjects=total_subjects,
        total_tasks=total_tasks,
        total_exams=total_exams,
        users=users,
        health_info=health_info
    )


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
        return redirect(url_for('admin.dashboard'))

    user.is_active = not user.is_active
    db.session.commit()

    action = 'activated' if user.is_active else 'deactivated'
    flash(f"User '{user.username}' has been {action}.", 'success')
    return redirect(url_for('admin.dashboard'))


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
        return redirect(url_for('admin.dashboard'))

    username = user.username
    db.session.delete(user)
    db.session.commit()

    flash(f"User account '{username}' and all associated records have been removed.", 'success')
    return redirect(url_for('admin.dashboard'))

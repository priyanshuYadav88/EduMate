import os
from datetime import date, datetime
from flask import Flask, render_template, redirect, url_for, request, jsonify, flash
from flask_login import LoginManager, login_required, current_user
from models import db, User, Subject, Topic, Task, Exam, TimetableEntry
from auth import auth_bp
from admin import admin_bp

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'edumate-btech-secret-key-2026')
    db_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'edumate.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Initialize extensions
    db.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'warning'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Register Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)

    @app.context_processor
    def inject_global_vars():
        return {
            'now': datetime.now(),
            'current_date_formatted': datetime.now().strftime('%a, %d %b %Y')
        }

    # Core Routes
    @app.route('/')
    def index():
        if current_user.is_authenticated:
            if current_user.is_admin:
                return redirect(url_for('admin.dashboard'))
            return redirect(url_for('dashboard'))
        return redirect(url_for('auth.login'))

    @app.route('/dashboard')
    @login_required
    def dashboard():
        today = date.today()
        day_name = today.strftime('%A')

        # 1. Total Subjects (Database query for current user)
        subjects = Subject.query.filter_by(user_id=current_user.id).all()
        total_subjects = len(subjects)

        # 2. Syllabus Completion Percentage (Calculated strictly from database topics)
        total_topics = 0
        completed_topics = 0
        for subj in subjects:
            total_topics += len(subj.topics)
            completed_topics += sum(1 for t in subj.topics if t.is_completed)

        overall_progress = int(round((completed_topics / total_topics) * 100)) if total_topics > 0 else 0

        # 3. Next Exam (Earliest upcoming exam for current user)
        upcoming_exams = Exam.query.filter(
            Exam.user_id == current_user.id,
            Exam.exam_date >= today
        ).order_by(Exam.exam_date.asc()).all()

        next_exam = upcoming_exams[0] if upcoming_exams else None

        # 4. Today's Tasks
        today_tasks = Task.query.filter_by(
            user_id=current_user.id,
            due_date=today
        ).order_by(Task.is_completed.asc(), Task.id.asc()).all()

        completed_tasks_count = sum(1 for t in today_tasks if t.is_completed)
        total_tasks_count = len(today_tasks)

        # 5. Today's Timetable / Schedule
        today_schedule = TimetableEntry.query.filter_by(
            user_id=current_user.id,
            day_of_week=day_name
        ).order_by(TimetableEntry.id.asc()).all()

        # Check AI Service Status
        gemini_api_key = os.environ.get('GEMINI_API_KEY')
        ai_online = bool(gemini_api_key and len(gemini_api_key.strip()) > 5)

        return render_template(
            'index.html',
            total_subjects=total_subjects,
            overall_progress=overall_progress,
            next_exam=next_exam,
            today_tasks=today_tasks,
            completed_tasks_count=completed_tasks_count,
            total_tasks_count=total_tasks_count,
            subjects=subjects,
            upcoming_exams=upcoming_exams,
            today_schedule=today_schedule,
            ai_online=ai_online,
            today=today
        )

    # API Endpoints for interactive dashboard actions
    @app.route('/api/tasks/toggle/<int:task_id>', methods=['POST'])
    @login_required
    def toggle_task(task_id):
        task = Task.query.filter_by(id=task_id, user_id=current_user.id).first_or_404()
        task.is_completed = not task.is_completed
        db.session.commit()

        # Recalculate today's counts for immediate UI update
        today = date.today()
        today_tasks = Task.query.filter_by(user_id=current_user.id, due_date=today).all()
        completed_count = sum(1 for t in today_tasks if t.is_completed)
        total_count = len(today_tasks)

        return jsonify({
            'success': True,
            'task_id': task.id,
            'is_completed': task.is_completed,
            'completed_count': completed_count,
            'total_count': total_count
        })

    @app.route('/api/tasks/add', methods=['POST'])
    @login_required
    def add_task():
        data = request.get_json() if request.is_json else request.form
        title = data.get('title', '').strip()
        subject_id = data.get('subject_id')

        if not title:
            return jsonify({'success': False, 'error': 'Task title cannot be empty'}), 400

        task = Task(
            title=title,
            due_date=date.today(),
            is_completed=False,
            user_id=current_user.id,
            subject_id=int(subject_id) if subject_id else None
        )
        db.session.add(task)
        db.session.commit()

        return jsonify({
            'success': True,
            'task': {
                'id': task.id,
                'title': task.title,
                'subject_code': task.subject.code if task.subject else 'General',
                'is_completed': False
            }
        })

    @app.route('/api/ai/chat', methods=['POST'])
    @login_required
    def ai_chat():
        data = request.get_json() or {}
        user_message = data.get('message', '').strip()

        if not user_message:
            return jsonify({'reply': 'Please enter a valid study query.'})

        gemini_api_key = os.environ.get('GEMINI_API_KEY')
        if not gemini_api_key:
            return jsonify({
                'reply': (
                    "⚠️ EduMate AI Service is currently offline. "
                    "To enable the real AI assistant, set the GEMINI_API_KEY environment variable. "
                    "In compliance with project specifications, no fake responses are generated."
                ),
                'online': False
            })

        # If API key is present, execute via Gemini API
        try:
            import urllib.request
            import json

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_api_key}"
            headers = {'Content-Type': 'application/json'}
            payload = {
                "contents": [{
                    "parts": [{
                        "text": f"You are EduMate AI Study Assistant for college students. Answer this concisely and clearly:\n\n{user_message}"
                    }]
                }]
            }
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                reply = res_data['candidates'][0]['content']['parts'][0]['text']
                return jsonify({'reply': reply, 'online': True})
        except Exception as e:
            return jsonify({
                'reply': f"Error communicating with AI service: {str(e)}",
                'online': False
            })

    # Additional standard section views
    @app.route('/subjects')
    @login_required
    def subjects_view():
        subjects = Subject.query.filter_by(user_id=current_user.id).all()
        return render_template('subjects.html', subjects=subjects)

    @app.route('/timetable')
    @login_required
    def timetable_view():
        entries = TimetableEntry.query.filter_by(user_id=current_user.id).all()
        return render_template('timetable.html', entries=entries)

    @app.route('/quizzes')
    @login_required
    def quizzes_view():
        subjects = Subject.query.filter_by(user_id=current_user.id).all()
        return render_template('quizzes.html', subjects=subjects)

    @app.route('/revision')
    @login_required
    def revision_view():
        subjects = Subject.query.filter_by(user_id=current_user.id).all()
        return render_template('revision.html', subjects=subjects)

    @app.route('/progress')
    @login_required
    def progress_view():
        subjects = Subject.query.filter_by(user_id=current_user.id).all()
        return render_template('progress.html', subjects=subjects)

    @app.route('/settings')
    @login_required
    def settings_view():
        return render_template('settings.html')

    return app

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)

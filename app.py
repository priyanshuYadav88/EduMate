import os
import re
from datetime import date, datetime, timedelta, timezone
from flask import Flask, render_template, redirect, url_for, request, jsonify, flash
from flask_login import LoginManager, login_required, current_user
from models import db, User, Subject, Topic, Task, Exam, TimetableEntry, RoadmapPlan, RoadmapItem, OfficialExamDirectory
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

    # Study Roadmap Routes
    @app.route('/roadmap')
    @login_required
    def roadmap_view():
        subjects = Subject.query.filter_by(user_id=current_user.id).all()
        plans = RoadmapPlan.query.filter_by(user_id=current_user.id).order_by(RoadmapPlan.created_at.desc()).all()

        plan_id = request.args.get('plan_id', type=int)
        selected_plan = None
        if plan_id:
            selected_plan = db.session.get(RoadmapPlan, plan_id)
            if selected_plan and selected_plan.user_id != current_user.id:
                selected_plan = None
        if not selected_plan and plans:
            selected_plan = plans[0]

        return render_template('roadmap.html', subjects=subjects, plans=plans, selected_plan=selected_plan, today=date.today())

    @app.route('/roadmap/generate', methods=['POST'])
    @login_required
    def generate_roadmap():
        subject_id = request.form.get('subject_id', type=int)
        exam_date_str = request.form.get('exam_date', '').strip()
        daily_hours = request.form.get('daily_hours', type=float, default=2.0)
        syllabus_text = request.form.get('syllabus_text', '').strip()
        custom_title = request.form.get('title', '').strip()
        reset_existing = request.form.get('reset_existing') == 'true'

        # Validation 1: Subject verification and ownership
        subject = db.session.get(Subject, subject_id) if subject_id else None
        if not subject or subject.user_id != current_user.id:
            flash('Please select a valid subject from your coursework.', 'danger')
            return redirect(url_for('roadmap_view'))

        # Validation 2: Exam date verification (must be in future)
        if not exam_date_str:
            flash('Please specify a target exam date.', 'danger')
            return redirect(url_for('roadmap_view'))

        try:
            exam_date = date.fromisoformat(exam_date_str)
        except ValueError:
            flash('Invalid date format. Please select a valid date.', 'danger')
            return redirect(url_for('roadmap_view'))

        today = date.today()
        available_days = (exam_date - today).days
        if available_days <= 0:
            flash('Exam date must be in the future (at least 1 day away).', 'danger')
            return redirect(url_for('roadmap_view'))

        # Validation 3: Syllabus parsing
        topics_raw = []
        if not syllabus_text:
            if subject.topics:
                topics_raw = [(f"Unit {idx // 3 + 1}", t.title) for idx, t in enumerate(subject.topics)]
            else:
                flash('Please enter syllabus units and topics, or add topics to this subject first.', 'danger')
                return redirect(url_for('roadmap_view'))
        else:
            current_unit = "Unit 1: Overview"
            for line in syllabus_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                lower_line = line.lower()
                if lower_line.startswith(('unit', 'module', 'chapter', 'section', 'part')):
                    current_unit = line
                else:
                    clean_title = re.sub(r'^[0-9]+[\.\-\)]\s*|^[\*\-\•]\s*', '', line).strip()
                    if clean_title:
                        topics_raw.append((current_unit, clean_title))

        if not topics_raw:
            flash('Could not identify topics in the provided syllabus. Please enter one topic per line.', 'danger')
            return redirect(url_for('roadmap_view'))

        # Workload & Capacity Analysis
        est_hours_per_topic = 1.5
        total_required_hours = len(topics_raw) * est_hours_per_topic
        total_available_hours = available_days * daily_hours
        has_warning = total_required_hours > total_available_hours

        # Plan Distribution Algorithm:
        revision_days = max(1, min(4, int(available_days * 0.18)))
        if available_days <= 3:
            revision_days = 1
        study_days = max(1, available_days - revision_days)

        # Check existing plan for this subject to preserve progress if requested
        existing_plan = RoadmapPlan.query.filter_by(user_id=current_user.id, subject_id=subject.id).first()
        preserved_completions = {}
        if existing_plan:
            if not reset_existing:
                for item in existing_plan.items:
                    if item.is_completed:
                        preserved_completions[item.topic_title.lower().strip()] = True
            db.session.delete(existing_plan)
            db.session.flush()

        # Create new RoadmapPlan
        plan_title = custom_title if custom_title else f"{subject.name} Exam Roadmap"
        new_plan = RoadmapPlan(
            user_id=current_user.id,
            subject_id=subject.id,
            title=plan_title,
            exam_date=exam_date,
            daily_study_hours=daily_hours,
            total_topics_count=len(topics_raw) + revision_days,
            completed_topics_count=0,
            has_workload_warning=has_warning
        )
        db.session.add(new_plan)
        db.session.flush()

        # Distribute topics across study days
        num_topics = len(topics_raw)
        topics_per_day = max(1, int(round(num_topics / study_days)))

        for idx, (unit_n, t_title) in enumerate(topics_raw):
            day_offset = min(study_days - 1, idx // topics_per_day)
            scheduled_date = today + timedelta(days=day_offset + 1)
            is_comp = preserved_completions.get(t_title.lower().strip(), False)

            item = RoadmapItem(
                plan_id=new_plan.id,
                day_number=day_offset + 1,
                scheduled_date=scheduled_date,
                unit_name=unit_n,
                topic_title=t_title,
                estimated_hours=est_hours_per_topic,
                is_revision=False,
                is_completed=is_comp
            )
            db.session.add(item)

        # Add revision milestone days
        for r_idx in range(revision_days):
            rev_day_num = study_days + r_idx + 1
            rev_date = today + timedelta(days=study_days + r_idx + 1)
            rev_title = f"Comprehensive Revision & Mock Questions (Phase {r_idx + 1})" if revision_days > 1 else "Final Formula Review & Exam Rehearsal"
            rev_item = RoadmapItem(
                plan_id=new_plan.id,
                day_number=rev_day_num,
                scheduled_date=rev_date,
                unit_name="Revision & Recall",
                topic_title=rev_title,
                estimated_hours=daily_hours,
                is_revision=True,
                is_completed=False
            )
            db.session.add(rev_item)

        db.session.flush()
        new_plan.completed_topics_count = sum(1 for i in new_plan.items if i.is_completed)
        db.session.commit()

        if has_warning:
            flash(
                f"Workload Warning: Syllabus requires ~{total_required_hours:.1f} hours, but you have ~{total_available_hours:.1f} available hours ({available_days} days @ {daily_hours}h/day). Plan generated with compressed pacing.",
                'warning'
            )
        else:
            flash(f"Study roadmap successfully generated for {subject.name}! {available_days} days allocated with {revision_days} revision days.", 'success')

        return redirect(url_for('roadmap_view', plan_id=new_plan.id))

    @app.route('/api/roadmap/toggle/<int:item_id>', methods=['POST'])
    @login_required
    def toggle_roadmap_item(item_id):
        item = db.session.get(RoadmapItem, item_id)
        if not item or item.plan.user_id != current_user.id:
            return jsonify({'success': False, 'error': 'Item not found'}), 404

        item.is_completed = not item.is_completed
        item.completed_at = datetime.now(timezone.utc) if item.is_completed else None

        plan = item.plan
        plan.completed_topics_count = sum(1 for i in plan.items if i.is_completed)
        db.session.commit()

        return jsonify({
            'success': True,
            'item_id': item.id,
            'is_completed': item.is_completed,
            'completed_count': plan.completed_topics_count,
            'total_count': plan.total_topics_count,
            'progress_percentage': plan.progress_percentage
        })

    # Explore External Exams Directory Route
    @app.route('/explore-exams')
    @login_required
    def explore_exams_view():
        query = request.args.get('q', '').strip()
        category = request.args.get('category', '').strip()

        exam_query = OfficialExamDirectory.query
        if category and category != 'All':
            exam_query = exam_query.filter(OfficialExamDirectory.category == category)
        if query:
            search_pattern = f"%{query}%"
            exam_query = exam_query.filter(
                (OfficialExamDirectory.exam_name.ilike(search_pattern)) |
                (OfficialExamDirectory.exam_code.ilike(search_pattern)) |
                (OfficialExamDirectory.conducting_authority.ilike(search_pattern)) |
                (OfficialExamDirectory.eligibility_summary.ilike(search_pattern))
            )

        exams = exam_query.all()
        categories = db.session.query(OfficialExamDirectory.category).distinct().all()
        categories_list = [c[0] for c in categories if c[0]]

        # Live external search API status check
        exam_api_key = os.environ.get('EXAM_SEARCH_API_KEY')
        search_api_configured = bool(exam_api_key and len(exam_api_key.strip()) > 5)

        return render_template(
            'explore_exams.html',
            exams=exams,
            categories=categories_list,
            selected_category=category,
            search_query=query,
            search_api_configured=search_api_configured
        )

    return app

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)

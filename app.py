import os
import re
import io
import json
from datetime import date, datetime, timedelta, timezone
from flask import Flask, render_template, redirect, url_for, request, jsonify, flash
from flask_login import LoginManager, login_required, current_user
from dotenv import load_dotenv
from models import (
    db, User, Subject, Topic, Task, Exam, TimetableEntry,
    RoadmapPlan, RoadmapItem, OfficialExamDirectory, AuditLog,
    UploadedPdfDocument, SystemSetting, QuizAttempt, ChatMessage
)
from auth import auth_bp
from admin import admin_bp
from ai_service import ai_service, InvalidInputException
from pdf_service import validate_pdf_upload, extract_pdf_content, PDFProcessingException

load_dotenv()

def create_app(test_config=None):
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'edumate-btech-secret-key-2026')
    db_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'edumate.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    if test_config:
        app.config.update(test_config)

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
        return render_template('landing.html')

    @app.route('/dashboard')
    @login_required
    def dashboard():
        if current_user.is_admin and request.args.get('preview_student') != '1':
            return redirect(url_for('admin.dashboard'))

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

        # Test compatibility & status check:
        # If GEMINI_API_KEY is missing/empty and Ollama fallback is unreachable, honestly report offline
        gemini_api_key = os.environ.get('GEMINI_API_KEY')
        status = ai_service.get_provider_status()
        ollama_ready = status['fallback']['reachable'] and status['fallback']['model_ready']
        if not gemini_api_key and not ollama_ready:
            return jsonify({
                'reply': (
                    "⚠️ EduMate AI Service is currently offline. "
                    "To enable the real AI assistant, set the GEMINI_API_KEY environment variable or start local Ollama. "
                    "In compliance with project specifications, no fake responses are generated."
                ),
                'online': False
            })

        # Assemble student's approved syllabus context for grounded Q&A
        user_subjects = Subject.query.filter_by(user_id=current_user.id).all()
        syllabus_ctx = []
        for s in user_subjects:
            units_dict = {}
            for t in s.topics:
                u_name = t.unit_name or "General Curriculum"
                if u_name not in units_dict:
                    units_dict[u_name] = []
                units_dict[u_name].append({
                    'title': t.title,
                    'source_pages': t.source_pages
                })
            syllabus_ctx.append({
                'subject_name': s.name,
                'units': [{'unit_title': u_k, 'topics': u_v} for u_k, u_v in units_dict.items()]
            })

        try:
            res = ai_service.chat_study_assistant(
                user_message=user_message,
                approved_syllabus_context=syllabus_ctx
            )

            if not res.get('success'):
                return jsonify({
                    'reply': res.get('reply') or "EduMate AI service is currently unavailable.",
                    'online': False
                })

            # Record chat interaction in database for student history
            try:
                chat_msg = ChatMessage(
                    user_id=current_user.id,
                    role='assistant',
                    content=res['reply'],
                    provider=res.get('provider'),
                    model=res.get('model'),
                    fallback_used=res.get('fallback_used', False),
                    source_pages=res.get('source_pages')
                )
                db.session.add(chat_msg)
                db.session.commit()
            except Exception:
                db.session.rollback()

            return jsonify({
                'reply': res['reply'],
                'online': True,
                'provider': res.get('provider'),
                'model': res.get('model'),
                'fallback_used': res.get('fallback_used', False),
                'source_pages': res.get('source_pages')
            })
        except Exception as e:
            return jsonify({
                'reply': f"EduMate AI service is currently offline or unreachable: {str(e)}",
                'online': False
            })

    @app.route('/api/ai/chat/history', methods=['GET'])
    @login_required
    def api_chat_history():
        msgs = ChatMessage.query.filter_by(user_id=current_user.id).order_by(ChatMessage.created_at.desc()).limit(15).all()
        msgs.reverse()
        return jsonify({
            'success': True,
            'messages': [
                {
                    'id': m.id,
                    'role': m.role,
                    'content': m.content,
                    'provider': m.provider,
                    'source_pages': m.source_pages,
                    'created_at': m.created_at.strftime('%H:%M')
                } for m in msgs
            ]
        })

    @app.route('/api/ai/academic-content', methods=['POST'])
    @login_required
    def api_academic_content():
        """
        Module 6: Generates Notes, Summary, MCQs, Short Questions, or Long Questions
        for a specific approved topic.
        """
        data = request.get_json() or {}
        topic_id = data.get('topic_id')
        content_type = data.get('content_type', 'notes')

        if not topic_id:
            return jsonify({'success': False, 'error': 'Topic ID is required.'}), 400

        topic = db.session.get(Topic, int(topic_id))
        if not topic or topic.subject.user_id != current_user.id:
            return jsonify({'success': False, 'error': 'Topic not found or access denied.'}), 404

        subtopics_list = []
        if topic.subtopics:
            try:
                subtopics_list = json.loads(topic.subtopics)
            except Exception:
                subtopics_list = []

        try:
            res = ai_service.generate_academic_content(
                content_type=content_type,
                topic_name=topic.title,
                unit_name=topic.unit_name or "Unit 1",
                subject_name=topic.subject.name,
                subtopics=subtopics_list
            )

            # Persist notes or summary cache
            if content_type == 'notes' and res.get('content'):
                topic.notes_content = res['content']
                db.session.commit()
            elif content_type == 'summary' and res.get('content'):
                topic.summary_content = res['content']
                db.session.commit()

            return jsonify(res)
        except Exception as e:
            return jsonify({'success': False, 'error': f"Failed to generate academic content: {str(e)}"}), 500

    @app.route('/api/quiz/submit', methods=['POST'])
    @login_required
    def api_submit_quiz():
        """
        Module 6: Scores student's submitted MCQ quiz, calculates actual percentage,
        saves results in QuizAttempt table, and returns explanations.
        """
        data = request.get_json() or {}
        topic_id = data.get('topic_id')
        subject_id = data.get('subject_id')
        title = data.get('title') or "Practice MCQ Quiz"
        questions = data.get('questions', [])
        user_answers = data.get('answers', [])

        if not questions:
            return jsonify({'success': False, 'error': 'No questions submitted.'}), 400

        total = len(questions)
        score = 0
        scored_questions = []

        for idx, q in enumerate(questions):
            user_ans = user_answers[idx] if idx < len(user_answers) else None
            correct_ans = q.get('correct_answer')
            is_correct = (user_ans == correct_ans)
            if is_correct:
                score += 1
            scored_questions.append({
                'question': q.get('question'),
                'options': q.get('options', []),
                'user_answer': user_ans,
                'correct_answer': correct_ans,
                'is_correct': is_correct,
                'explanation': q.get('explanation', '')
            })

        attempt = QuizAttempt(
            user_id=current_user.id,
            subject_id=subject_id,
            topic_id=topic_id,
            quiz_type='mcq',
            title=title,
            score=score,
            total_questions=total,
            questions_data=json.dumps(scored_questions)
        )
        db.session.add(attempt)
        db.session.commit()

        percentage = int(round((score / total) * 100)) if total > 0 else 0
        return jsonify({
            'success': True,
            'score': score,
            'total_questions': total,
            'percentage': percentage,
            'attempt_id': attempt.id,
            'results': scored_questions
        })

    def extract_text_from_pdf(file_stream):
        """
        Extract text from uploaded PDF file stream.
        Checks for password encryption, corrupt headers, empty/scanned documents,
        and provides honest feedback regarding OCR availability.
        """
        import pypdf
        try:
            reader = pypdf.PdfReader(file_stream)
        except Exception as e:
            return None, f"Invalid or corrupted PDF file: {str(e)}"

        if reader.is_encrypted:
            return None, "This PDF is password-protected. Please remove the password and upload again."

        total_pages = len(reader.pages)
        if total_pages == 0:
            return None, "The uploaded PDF contains no pages."

        extracted_text_chunks = []
        for page_idx, page in enumerate(reader.pages):
            try:
                page_text = page.extract_text() or ''
                if page_text.strip():
                    extracted_text_chunks.append(page_text.strip())
            except Exception as e:
                continue

        full_text = "\n\n".join(extracted_text_chunks).strip()

        # Check if PDF is scanned or image-only without selectable text layer
        if not full_text or len(full_text) < 15:
            return None, (
                "No selectable text could be extracted from this PDF. "
                "It appears to be a scanned document or image-only PDF. "
                "Note: OCR (Optical Character Recognition) engine is currently not installed on this server. "
                "Please upload a standard text PDF or type/paste topics manually."
            )

        return full_text, None

    def parse_syllabus_topics(text):
        """
        Intelligently identifies syllabus units and individual topics from raw text.
        Returns list of (unit_name, topic_title) tuples.
        """
        units_and_topics = []
        current_unit = "Unit 1: Overview"

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            lower_line = line.lower()
            # Detect unit / module / chapter headers
            if lower_line.startswith(('unit', 'module', 'chapter', 'section', 'part', 'course objective', 'prerequisite')):
                # Filter out pure non-syllabus meta headers
                if not lower_line.startswith(('course objective', 'prerequisite')):
                    current_unit = line
                continue

            # Topic line: clean leading bullets, numbering, or checkboxes
            clean_title = re.sub(r'^[0-9]+[\.\-\)]\s*|^[\*\-\•\u2022\u25E6]\s*', '', line).strip()
            # Ignore headers or lines that are too short/pure punctuation
            if len(clean_title) >= 3 and not clean_title.startswith(('http://', 'https://', 'page ')):
                # If a line contains comma-separated subtopics and is long, split or keep concise
                units_and_topics.append((current_unit, clean_title))

        return units_and_topics

    # Additional standard section views
    @app.route('/subjects', methods=['GET', 'POST'])
    @login_required
    def subjects_view():
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            code = request.form.get('code', '').strip().upper()
            color = request.form.get('color', '#2563eb').strip()
            icon = request.form.get('icon', 'book').strip()

            # Validation 1: Required fields
            if not name:
                flash('Subject name is required and cannot be empty.', 'danger')
                return redirect(url_for('subjects_view'))

            if not code:
                # Generate a reasonable code if not provided
                code = "".join([part[0] for part in name.split() if part])[:6].upper()

            # Validation 2: Duplicate check for current student
            existing = Subject.query.filter(
                Subject.user_id == current_user.id,
                db.or_(
                    db.func.lower(Subject.name) == name.lower(),
                    db.func.lower(Subject.code) == code.lower()
                )
            ).first()

            if existing:
                flash(f'A subject with name "{name}" or code "{code}" already exists in your coursework.', 'warning')
                return redirect(url_for('subjects_view'))

            # Allowed icons and colors whitelist for UI consistency
            allowed_icons = {'book', 'cpu', 'gear', 'database', 'pi'}
            if icon not in allowed_icons:
                icon = 'book'

            new_subject = Subject(
                name=name,
                code=code,
                color=color if color.startswith('#') and len(color) in (4, 7) else '#2563eb',
                icon=icon,
                user_id=current_user.id
            )
            db.session.add(new_subject)
            db.session.commit()

            flash(f'Subject "{name}" ({code}) has been added successfully.', 'success')
            return redirect(url_for('subjects_view'))

        subjects = Subject.query.filter_by(user_id=current_user.id).all()
        return render_template('subjects.html', subjects=subjects)

    # API: Dynamically retrieve current user's enrolled subjects for dropdowns
    @app.route('/api/subjects', methods=['GET'])
    @login_required
    def get_user_subjects():
        subjects = Subject.query.filter_by(user_id=current_user.id).all()
        return jsonify({
            'success': True,
            'subjects': [
                {
                    'id': s.id,
                    'name': s.name,
                    'code': s.code,
                    'color': s.color,
                    'total_topics': len(s.topics),
                    'completed_topics': s.completed_topics,
                    'progress_percentage': s.progress_percentage
                } for s in subjects
            ]
        })

    # API: Extract syllabus topics from uploaded PDF file using PyMuPDF and AI
    @app.route('/api/syllabus/extract-pdf', methods=['POST'])
    @login_required
    def api_extract_syllabus_pdf():
        if 'pdf_file' not in request.files:
            return jsonify({'success': False, 'error': 'No file part found in upload request.'}), 400

        file = request.files['pdf_file']
        if not file or file.filename == '':
            return jsonify({'success': False, 'error': 'Please select a PDF file to upload.'}), 400

        filename = file.filename
        subject_id_val = request.form.get('subject_id', type=int)

        # 1. Validate file extension, size, and header magic bytes
        try:
            file_length = validate_pdf_upload(file, filename)
        except PDFProcessingException as pe:
            return jsonify({'success': False, 'error': pe.message}), 400
        except Exception as e:
            return jsonify({'success': False, 'error': f"File validation failed: {str(e)}"}), 400

        # 2. Read bytes and extract content page-by-page (PyMuPDF + OCR fallback)
        file.seek(0)
        file_bytes = file.read()

        try:
            pdf_data = extract_pdf_content(file_bytes)
        except PDFProcessingException as pe:
            # Record failed or password-protected upload in database for administrative oversight
            try:
                pdf_doc = UploadedPdfDocument(
                    user_id=current_user.id,
                    subject_id=subject_id_val,
                    filename=filename,
                    file_size_bytes=file_length,
                    status=pe.status_code.lower() if hasattr(pe, 'status_code') else 'failed',
                    error_message=pe.message,
                    topics_count=0
                )
                db.session.add(pdf_doc)
                db.session.commit()
            except Exception:
                db.session.rollback()
            return jsonify({'success': False, 'error': pe.message}), 400
        except Exception as e:
            return jsonify({'success': False, 'error': f"Document extraction error: {str(e)}"}), 400

        # Resolve subject name if subject_id was selected
        subject_name = None
        if subject_id_val:
            s_obj = db.session.get(Subject, subject_id_val)
            if s_obj and s_obj.user_id == current_user.id:
                subject_name = s_obj.name

        # 3. AI Syllabus Understanding (Gemini Primary + Ollama Fallback + Heuristic Engine)
        structure = ai_service.extract_syllabus_structure(pdf_data['pages'], subject_name=subject_name)

        # Check if the document actually contains an academic syllabus
        if not structure.get('is_syllabus') or (not structure.get('units') and not structure.get('unassigned_topics')):
            err_msg = structure.get('error_message') or (
                "No academic syllabus detected in the uploaded PDF. "
                "The file appears to contain unrelated content (such as an administrative notice, "
                "examination rules, fee details, or certificate) rather than course units and topics."
            )
            # Record failed extraction for administrative oversight
            try:
                pdf_doc = UploadedPdfDocument(
                    user_id=current_user.id,
                    subject_id=subject_id_val,
                    filename=filename,
                    file_size_bytes=file_length,
                    page_count=pdf_data['total_pages'],
                    ocr_applied=pdf_data['ocr_applied'],
                    status='No Syllabus Detected',
                    error_message=err_msg,
                    extracted_text=pdf_data['full_text'],
                    topics_count=0
                )
                db.session.add(pdf_doc)
                db.session.commit()
            except Exception:
                db.session.rollback()

            return jsonify({
                'success': False,
                'is_syllabus': False,
                'error': err_msg
            }), 400

        # 4. Save processed document into SQLite
        try:
            pdf_doc = UploadedPdfDocument(
                user_id=current_user.id,
                subject_id=subject_id_val,
                filename=filename,
                file_size_bytes=file_length,
                page_count=pdf_data['total_pages'],
                ocr_applied=pdf_data['ocr_applied'],
                status='Needs Review',
                extracted_text=pdf_data['full_text'],
                structured_json=json.dumps(structure),
                topics_count=structure.get('total_topics', 0)
            )
            db.session.add(pdf_doc)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            pdf_doc = None

        # Build flat list for backward compatibility with frontend modal
        flat_topics = []
        for u in structure.get('units', []):
            for t in u.get('topics', []):
                flat_topics.append({
                    'unit': u.get('title'),
                    'title': t.get('name'),
                    'subtopics': t.get('subtopics', []),
                    'source_pages': t.get('source_pages', [])
                })

        doc_id = pdf_doc.id if pdf_doc else None
        review_url = url_for('syllabus_review_view', doc_id=doc_id) if doc_id else None

        return jsonify({
            'success': True,
            'is_syllabus': True,
            'doc_id': doc_id,
            'review_url': review_url,
            'filename': filename,
            'subject': structure.get('subject'),
            'detected_subject': structure.get('detected_subject') or structure.get('subject'),
            'course_code': structure.get('course_code'),
            'units': structure.get('units', []),
            'unassigned_topics': structure.get('unassigned_topics', []),
            'topics': flat_topics,
            'total_topics': len(flat_topics),
            'ocr_applied': pdf_data['ocr_applied'],
            'provider': structure.get('provider'),
            'raw_text_preview': pdf_data['full_text'][:400] + ('...' if len(pdf_data['full_text']) > 400 else '')
        })

    # Student Syllabus Review & Hierarchy Inspection View
    @app.route('/syllabus/review/<int:doc_id>', methods=['GET'])
    @login_required
    def syllabus_review_view(doc_id):
        doc = db.session.get(UploadedPdfDocument, doc_id)
        if not doc or (doc.user_id != current_user.id and current_user.role != 'admin'):
            flash('Syllabus document not found or access denied.', 'danger')
            return redirect(url_for('subjects_view'))

        subjects = Subject.query.filter_by(user_id=current_user.id).all()
        detected_subject_name = ''
        detected_course_code = ''
        units_json = '[]'
        unassigned_topics_json = '[]'

        if doc.structured_json:
            try:
                data = json.loads(doc.structured_json)
                detected_subject_name = data.get('detected_subject') or data.get('subject', '')
                detected_course_code = data.get('course_code', '')
                units_json = json.dumps(data.get('units', []))
                unassigned_topics_json = json.dumps(data.get('unassigned_topics', []))
            except Exception:
                units_json = '[]'
                unassigned_topics_json = '[]'

        return render_template(
            'syllabus_review.html',
            doc=doc,
            subjects=subjects,
            selected_subject_id=doc.subject_id,
            detected_subject_name=detected_subject_name,
            detected_course_code=detected_course_code,
            units_json=units_json,
            unassigned_topics_json=unassigned_topics_json
        )

    # API: Approve and commit reviewed syllabus topics to Subject and Topic models
    @app.route('/api/syllabus/approve', methods=['POST'])
    @login_required
    def api_approve_syllabus():
        data = request.get_json() or {}
        doc_id = data.get('doc_id')
        subject_id = data.get('subject_id')
        new_subject_name = (data.get('new_subject_name') or '').strip()
        flat_topics = data.get('flat_topics', [])
        units = data.get('units', [])

        if not doc_id:
            return jsonify({'success': False, 'error': 'Document ID is required.'}), 400

        doc = db.session.get(UploadedPdfDocument, int(doc_id))
        if not doc or (doc.user_id != current_user.id and current_user.role != 'admin'):
            return jsonify({'success': False, 'error': 'Document not found or access denied.'}), 404

        if not flat_topics:
            return jsonify({'success': False, 'error': 'No topics provided to approve.'}), 400

        course_code = (data.get('course_code') or '').strip().upper()

        # Resolve or create target subject
        target_subject = None
        if str(subject_id) == '__NEW__':
            if not new_subject_name:
                return jsonify({'success': False, 'error': 'New subject name is required.'}), 400

            code_parts = [p[0] for p in new_subject_name.split() if p]
            gen_code = course_code or ("".join(code_parts)[:6].upper() or "SUBJ")

            target_subject = Subject(
                name=new_subject_name,
                code=gen_code,
                color='#2563eb',
                user_id=current_user.id
            )
            db.session.add(target_subject)
            db.session.flush()
        else:
            try:
                s_id = int(subject_id)
                target_subject = db.session.get(Subject, s_id)
            except (ValueError, TypeError):
                target_subject = None

            if not target_subject or target_subject.user_id != current_user.id:
                return jsonify({'success': False, 'error': 'Valid enrolled subject required.'}), 400

            if course_code and (not target_subject.code or target_subject.code == 'SUBJ'):
                target_subject.code = course_code

        # Link document with target subject
        doc.subject_id = target_subject.id

        # Insert approved topics with unit, subtopics, and source pages
        existing_titles = {t.title.lower().strip() for t in target_subject.topics}
        saved_count = 0

        for item in flat_topics:
            t_title = (item.get('title') or '').strip()
            if not t_title or t_title.lower() in existing_titles:
                continue

            subtopics_val = item.get('subtopics')
            subtopics_json = json.dumps(subtopics_val) if isinstance(subtopics_val, list) and subtopics_val else None

            source_pages_val = item.get('source_pages')
            if isinstance(source_pages_val, list):
                source_pages_str = ", ".join(map(str, source_pages_val))
            else:
                source_pages_str = str(source_pages_val) if source_pages_val else None

            topic_record = Topic(
                subject_id=target_subject.id,
                unit_name=(item.get('unit_name') or 'Unit 1').strip(),
                title=t_title,
                subtopics=subtopics_json,
                source_pages=source_pages_str,
                is_completed=False
            )
            db.session.add(topic_record)
            existing_titles.add(t_title.lower())
            saved_count += 1

        # Mark document approved
        doc.status = 'Approved'
        if units:
            doc.structured_json = json.dumps({
                'subject': target_subject.name,
                'units': units
            })
        doc.topics_count = len(target_subject.topics) + saved_count
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Successfully approved and saved {saved_count} topics for {target_subject.name}.',
            'redirect_url': url_for('roadmap_view', subject_id=target_subject.id)
        })

    # API: Save reviewed/edited topics for a subject
    @app.route('/api/syllabus/save-topics', methods=['POST'])
    @login_required
    def api_save_syllabus_topics():
        data = request.get_json() or {}
        subject_id = data.get('subject_id')
        topics = data.get('topics', [])
        replace_existing = data.get('replace_existing', False)

        if not subject_id:
            return jsonify({'success': False, 'error': 'Please select a valid subject.'}), 400

        subject = db.session.get(Subject, int(subject_id))
        if not subject or subject.user_id != current_user.id:
            return jsonify({'success': False, 'error': 'Selected subject not found in your account.'}), 404

        if not topics or not isinstance(topics, list):
            return jsonify({'success': False, 'error': 'No topics provided to save.'}), 400

        if replace_existing:
            # Delete existing topics for this subject
            Topic.query.filter_by(subject_id=subject.id).delete()
            db.session.flush()

        saved_count = 0
        existing_titles = {t.title.lower().strip() for t in subject.topics} if not replace_existing else set()

        for item in topics:
            if isinstance(item, dict):
                title = item.get('title', '').strip()
            else:
                title = str(item).strip()

            if title and title.lower() not in existing_titles:
                new_topic = Topic(
                    title=title,
                    is_completed=False,
                    subject_id=subject.id
                )
                db.session.add(new_topic)
                existing_titles.add(title.lower())
                saved_count += 1

        db.session.commit()

        return jsonify({
            'success': True,
            'saved_count': saved_count,
            'total_topics': len(subject.topics),
            'message': f'Successfully saved {saved_count} syllabus topics for {subject.name}.'
        })

    @app.route('/timetable')
    @login_required
    def timetable_view():
        entries = TimetableEntry.query.filter_by(user_id=current_user.id).all()
        return render_template('timetable.html', entries=entries)

    @app.route('/quizzes')
    @login_required
    def quizzes_view():
        subjects = Subject.query.filter_by(user_id=current_user.id).all()
        recent_attempts = QuizAttempt.query.filter_by(user_id=current_user.id).order_by(QuizAttempt.created_at.desc()).limit(10).all()
        return render_template('quizzes.html', subjects=subjects, recent_attempts=recent_attempts)

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

        today = date.today()
        today_items = []
        upcoming_items = []
        pending_items = []
        in_progress_items = []
        completed_items = []
        today_completed_count = 0
        today_total_count = 0
        next_topic = None

        if selected_plan:
            # Auto-link unlinked items to topics if possible
            topic_map = {t.title.lower().strip(): t for t in selected_plan.subject.topics}
            for it in selected_plan.items:
                if not it.topic_id and it.topic_title.lower().strip() in topic_map:
                    it.topic_id = topic_map[it.topic_title.lower().strip()].id

                # Ensure status consistency
                if not it.status:
                    it.status = 'completed' if it.is_completed else 'pending'

                if it.scheduled_date == today:
                    today_items.append(it)
                    today_total_count += 1
                    if it.is_completed or it.status == 'completed':
                        today_completed_count += 1
                elif it.scheduled_date > today:
                    upcoming_items.append(it)

                if it.is_completed or it.status == 'completed':
                    completed_items.append(it)
                elif it.status == 'in_progress':
                    in_progress_items.append(it)
                else:
                    pending_items.append(it)

            # Determine next active topic to study
            if in_progress_items:
                next_topic = in_progress_items[0]
            elif [it for it in today_items if not it.is_completed and it.status != 'completed']:
                next_topic = [it for it in today_items if not it.is_completed and it.status != 'completed'][0]
            elif pending_items:
                next_topic = pending_items[0]

        return render_template(
            'roadmap.html',
            subjects=subjects,
            plans=plans,
            selected_plan=selected_plan,
            today=today,
            today_items=today_items,
            upcoming_items=upcoming_items,
            pending_items=pending_items,
            in_progress_items=in_progress_items,
            completed_items=completed_items,
            today_completed_count=today_completed_count,
            today_total_count=today_total_count,
            next_topic=next_topic
        )

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

        # Validation 3: Syllabus parsing & formatting for AI study roadmap
        topics_input = []
        if syllabus_text:
            parsed_tuples = parse_syllabus_topics(syllabus_text)
            topics_input = [{"unit_name": u, "topic_title": t, "is_completed": False} for u, t in parsed_tuples]
        else:
            if subject.topics:
                for idx, t in enumerate(subject.topics):
                    u_name = t.unit_name or f"Unit {idx // 3 + 1}"
                    topics_input.append({
                        "unit_name": u_name,
                        "topic_title": t.title,
                        "is_completed": t.is_completed
                    })
            else:
                flash('Please enter syllabus units and topics, or add topics to this subject first.', 'danger')
                return redirect(url_for('roadmap_view'))

        if not topics_input:
            flash('Could not identify topics in the provided syllabus. Please enter one topic per line.', 'danger')
            return redirect(url_for('roadmap_view'))

        # Generate intelligent balanced schedule via AI roadmap algorithm
        roadmap_data = ai_service.generate_study_roadmap(
            subject_name=subject.name,
            exam_date=exam_date,
            daily_hours=daily_hours,
            topics_input=topics_input,
            today=today
        )

        has_warning = roadmap_data['has_workload_warning']
        total_required_hours = roadmap_data['total_required_hours']
        total_available_hours = roadmap_data['total_available_hours']
        revision_days = roadmap_data['revision_days']

        # Check existing plan for this subject to preserve progress if requested
        existing_plan = RoadmapPlan.query.filter_by(user_id=current_user.id, subject_id=subject.id).first()
        preserved_completions = {}
        preserved_statuses = {}
        if existing_plan:
            if not reset_existing:
                for item in existing_plan.items:
                    k = item.topic_title.lower().strip()
                    if item.is_completed:
                        preserved_completions[k] = True
                    if item.status:
                        preserved_statuses[k] = item.status
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
            total_topics_count=len(roadmap_data['items']),
            completed_topics_count=0,
            has_workload_warning=has_warning
        )
        db.session.add(new_plan)
        db.session.flush()

        # Build topic lookup from subject
        topic_lookup = {t.title.lower().strip(): t for t in subject.topics}

        # Populate schedule items
        for item_data in roadmap_data['items']:
            t_title = item_data['topic_title']
            t_key = t_title.lower().strip()
            matched_topic = topic_lookup.get(t_key)

            is_comp = item_data['is_completed'] or preserved_completions.get(t_key, False)
            if not is_comp and matched_topic and matched_topic.is_completed:
                is_comp = True

            stored_status = preserved_statuses.get(t_key)
            if is_comp:
                init_status = 'completed'
            elif stored_status in ('in_progress', 'completed'):
                init_status = stored_status
            elif matched_topic and matched_topic.status in ('in_progress', 'completed'):
                init_status = matched_topic.status
            else:
                init_status = 'pending'

            item = RoadmapItem(
                plan_id=new_plan.id,
                day_number=item_data['day_number'],
                scheduled_date=item_data['scheduled_date'],
                unit_name=item_data['unit_name'],
                topic_title=t_title,
                estimated_hours=item_data['estimated_hours'],
                is_revision=item_data['is_revision'],
                is_completed=is_comp,
                status=init_status,
                topic_id=matched_topic.id if matched_topic else None,
                completed_at=datetime.now(timezone.utc) if is_comp else None
            )
            db.session.add(item)

            if matched_topic and is_comp:
                matched_topic.is_completed = True
                matched_topic.status = 'completed'

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

    def _sync_roadmap_item_status(item, new_status):
        """Helper to sync RoadmapItem with corresponding Topic record and update plan counters."""
        item.status = new_status
        item.is_completed = (new_status == 'completed')
        item.completed_at = datetime.now(timezone.utc) if item.is_completed else None

        # Synchronize linked topic or locate matching topic
        matched_topic = item.topic
        if not matched_topic and item.plan.subject:
            t_key = item.topic_title.lower().strip()
            for t in item.plan.subject.topics:
                if t.title.lower().strip() == t_key:
                    matched_topic = t
                    item.topic_id = t.id
                    break

        if matched_topic:
            matched_topic.is_completed = item.is_completed
            matched_topic.status = item.status

        plan = item.plan
        plan.completed_topics_count = sum(1 for i in plan.items if i.is_completed)
        return plan

    def _find_next_pending_item(plan, current_item=None):
        """Helper to find the next sequential pending study topic in a plan."""
        # Check subsequent day items
        if current_item:
            for it in plan.items:
                if not it.is_completed and it.status != 'completed' and it.day_number >= current_item.day_number and it.id != current_item.id:
                    return {
                        'id': it.id,
                        'day_number': it.day_number,
                        'topic_title': it.topic_title,
                        'unit_name': it.unit_name,
                        'scheduled_date': it.scheduled_date.strftime('%d %b %Y')
                    }
        # Fallback to any pending item in the plan
        for it in plan.items:
            if not it.is_completed and it.status != 'completed' and (current_item is None or it.id != current_item.id):
                return {
                    'id': it.id,
                    'day_number': it.day_number,
                    'topic_title': it.topic_title,
                    'unit_name': it.unit_name,
                    'scheduled_date': it.scheduled_date.strftime('%d %b %Y')
                }
        return None

    @app.route('/api/roadmap/toggle/<int:item_id>', methods=['POST'])
    @login_required
    def toggle_roadmap_item(item_id):
        item = db.session.get(RoadmapItem, item_id)
        if not item or item.plan.user_id != current_user.id:
            return jsonify({'success': False, 'error': 'Item not found or access denied.'}), 404

        new_status = 'pending' if (item.is_completed or item.status == 'completed') else 'completed'
        plan = _sync_roadmap_item_status(item, new_status)
        db.session.commit()

        next_item = _find_next_pending_item(plan, item) if new_status == 'completed' else None
        today_items = [i for i in plan.items if i.scheduled_date == item.scheduled_date]
        all_today_completed = bool(today_items and all(i.is_completed for i in today_items))

        return jsonify({
            'success': True,
            'item_id': item.id,
            'is_completed': item.is_completed,
            'status': item.status,
            'completed_count': plan.completed_topics_count,
            'total_count': plan.total_topics_count,
            'progress_percentage': plan.progress_percentage,
            'next_item': next_item,
            'all_today_completed': all_today_completed
        })

    @app.route('/api/roadmap/item/<int:item_id>/status', methods=['POST'])
    @login_required
    def update_roadmap_item_status(item_id):
        item = db.session.get(RoadmapItem, item_id)
        if not item or item.plan.user_id != current_user.id:
            return jsonify({'success': False, 'error': 'Item not found or access denied.'}), 404

        data = request.get_json() or {}
        new_status = data.get('status', '').strip().lower()
        if new_status not in ('pending', 'in_progress', 'completed'):
            return jsonify({'success': False, 'error': f"Invalid status '{new_status}'. Allowed: pending, in_progress, completed."}), 400

        plan = _sync_roadmap_item_status(item, new_status)
        db.session.commit()

        next_item = _find_next_pending_item(plan, item) if new_status == 'completed' else None
        today_items = [i for i in plan.items if i.scheduled_date == item.scheduled_date]
        all_today_completed = bool(today_items and all(i.is_completed for i in today_items))

        return jsonify({
            'success': True,
            'item_id': item.id,
            'is_completed': item.is_completed,
            'status': item.status,
            'completed_count': plan.completed_topics_count,
            'total_count': plan.total_topics_count,
            'progress_percentage': plan.progress_percentage,
            'next_item': next_item,
            'all_today_completed': all_today_completed
        })

    @app.route('/api/roadmap/item/<int:item_id>/details', methods=['GET'])
    @login_required
    def get_roadmap_item_details(item_id):
        item = db.session.get(RoadmapItem, item_id)
        if not item or item.plan.user_id != current_user.id:
            return jsonify({'success': False, 'error': 'Roadmap item not found or access denied.'}), 404

        # Locate linked topic
        matched_topic = item.topic
        if not matched_topic and item.plan.subject:
            t_key = item.topic_title.lower().strip()
            for t in item.plan.subject.topics:
                if t.title.lower().strip() == t_key:
                    matched_topic = t
                    item.topic_id = t.id
                    db.session.commit()
                    break

        subtopics_list = []
        if matched_topic and matched_topic.subtopics:
            try:
                subtopics_list = json.loads(matched_topic.subtopics)
            except Exception:
                subtopics_list = []

        return jsonify({
            'success': True,
            'item': {
                'id': item.id,
                'topic_title': item.topic_title,
                'unit_name': item.unit_name,
                'day_number': item.day_number,
                'scheduled_date': item.scheduled_date.strftime('%a, %d %b %Y'),
                'scheduled_date_iso': item.scheduled_date.isoformat(),
                'estimated_hours': item.estimated_hours,
                'is_revision': item.is_revision,
                'status': item.status or ('completed' if item.is_completed else 'pending'),
                'is_completed': item.is_completed,
                'notes': item.notes
            },
            'subject': {
                'id': item.plan.subject.id,
                'name': item.plan.subject.name,
                'code': item.plan.subject.code
            },
            'topic': {
                'id': matched_topic.id if matched_topic else None,
                'subtopics': subtopics_list,
                'source_pages': matched_topic.source_pages if matched_topic else None,
                'has_notes': bool(matched_topic and matched_topic.notes_content),
                'notes_preview': matched_topic.notes_content[:300] if (matched_topic and matched_topic.notes_content) else None,
                'has_summary': bool(matched_topic and matched_topic.summary_content)
            }
        })

    @app.route('/api/topic/status/<int:topic_id>', methods=['POST'])
    @login_required
    def update_topic_status(topic_id):
        topic = db.session.get(Topic, topic_id)
        if not topic or topic.subject.user_id != current_user.id:
            return jsonify({'success': False, 'error': 'Topic not found or access denied.'}), 404

        data = request.get_json() or {}
        new_status = (data.get('status') or '').strip().lower()
        if not new_status:
            new_status = 'pending' if topic.is_completed else 'completed'

        if new_status not in ('pending', 'in_progress', 'completed'):
            return jsonify({'success': False, 'error': f"Invalid status '{new_status}'."}), 400

        topic.status = new_status
        topic.is_completed = (new_status == 'completed')

        # Synchronize linked roadmap items
        for r_item in topic.roadmap_items:
            r_item.status = topic.status
            r_item.is_completed = topic.is_completed
            r_item.completed_at = datetime.now(timezone.utc) if r_item.is_completed else None
            plan = r_item.plan
            plan.completed_topics_count = sum(1 for i in plan.items if i.is_completed)

        db.session.commit()
        return jsonify({
            'success': True,
            'topic_id': topic.id,
            'status': topic.status,
            'is_completed': topic.is_completed
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

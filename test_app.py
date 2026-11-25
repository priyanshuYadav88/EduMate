import os
import sys
import types
import unittest
from unittest.mock import patch, MagicMock
from datetime import date, timedelta

# Fallback mock for google.genai if not present in test environment
if 'google' not in sys.modules:
    try:
        import google.genai
    except ImportError:
        _g = types.ModuleType('google')
        _genai = types.ModuleType('google.genai')
        _errors = types.ModuleType('google.genai.errors')
        _types_mod = types.ModuleType('google.genai.types')

        class _MockClientError(Exception):
            def __init__(self, code, message):
                self.code = code
                self.message = str(message)
                super().__init__(self.message)

        class _MockServerError(Exception):
            def __init__(self, code, message):
                self.code = code
                self.message = str(message)
                super().__init__(self.message)

        _errors.ClientError = _MockClientError
        _errors.ServerError = _MockServerError

        class _MockClient:
            def __init__(self, **kwargs):
                self.models = types.SimpleNamespace()

        class _MockGenerateContentConfig:
            def __init__(self, **kwargs):
                pass

        _types_mod.GenerateContentConfig = _MockGenerateContentConfig
        _genai.Client = _MockClient
        _genai.errors = _errors
        _genai.types = _types_mod
        _g.genai = _genai

        sys.modules['google'] = _g
        sys.modules['google.genai'] = _genai
        sys.modules['google.genai.errors'] = _errors
        sys.modules['google.genai.types'] = _types_mod

from app import create_app
from models import (
    db, User, UserProfile, Subject, Topic, Task, Exam, TimetableEntry,
    RoadmapPlan, RoadmapItem, OfficialExamDirectory, AuditLog,
    UploadedPdfDocument, SystemSetting, QuizAttempt, ChatMessage,
    cleanup_verified_demo_accounts
)

class EduMateTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'WTF_CSRF_ENABLED': False
        })
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

            # Create test student
            self.student = User(username='test_student', email='student@test.com', role='student')
            self.student.set_password('pass123')

            # Create test admin
            self.admin = User(username='test_admin', email='admin@test.com', role='admin')
            self.admin.set_password('admin123')

            # Create second student for data isolation test
            self.other_student = User(username='other_student', email='other@test.com', role='student')
            self.other_student.set_password('pass123')

            db.session.add_all([self.student, self.admin, self.other_student])
            db.session.commit()

            # Add subjects and topics for test student
            sub = Subject(name='Data Structures', code='DS', color='#3b82f6', user_id=self.student.id)
            db.session.add(sub)
            db.session.flush()

            t1 = Topic(title='Arrays', is_completed=True, subject_id=sub.id)
            t2 = Topic(title='Trees', is_completed=False, subject_id=sub.id)
            db.session.add_all([t1, t2])

            # Add task for test student
            task = Task(title='Study arrays', is_completed=False, user_id=self.student.id, subject_id=sub.id, due_date=date.today())
            db.session.add(task)

            # Add task for other student
            other_task = Task(title='Private task', is_completed=False, user_id=self.other_student.id, due_date=date.today())
            db.session.add(other_task)

            db.session.commit()
            self.student_id = self.student.id
            self.admin_id = self.admin.id
            self.other_student_id = self.other_student.id
            self.subject_id = sub.id
            self.task_id = task.id
            self.other_task_id = other_task.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_student_registration_and_login(self):
        """Test registration and password hashing validation"""
        # Register new student
        response = self.client.post('/register', data={
            'username': 'newuser',
            'email': 'newuser@college.edu',
            'password': 'password123',
            'confirm_password': 'password123'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            u = User.query.filter_by(username='newuser').first()
            self.assertIsNotNone(u)
            self.assertNotEqual(u.password_hash, 'password123')
            self.assertTrue(u.check_password('password123'))
            self.assertEqual(u.role, 'student')

        # Test Login
        login_res = self.client.post('/login', data={
            'identifier': 'newuser',
            'password': 'password123'
        }, follow_redirects=True)
        self.assertIn(b'Welcome back, newuser!', login_res.data)

    def test_role_based_access_control(self):
        """Test that students cannot access /admin (403 Forbidden) and admins can (200 OK)"""
        # Login as student
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})
        res = self.client.get('/admin/')
        self.assertEqual(res.status_code, 403)

        # Logout and login as admin
        self.client.get('/logout')
        self.client.post('/login', data={'identifier': 'test_admin', 'password': 'admin123'})
        admin_res = self.client.get('/admin/')
        self.assertEqual(admin_res.status_code, 200)
        self.assertIn(b'Admin Control Center', admin_res.data)

    def test_user_data_isolation(self):
        """Test that students cannot see or modify other students' tasks"""
        # Login as test_student
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        # Try to toggle other student's task (should return 404 Not Found)
        res = self.client.post(f'/api/tasks/toggle/{self.other_task_id}')
        self.assertEqual(res.status_code, 404)

        # Toggle own task (should succeed)
        res_own = self.client.post(f'/api/tasks/toggle/{self.task_id}')
        self.assertEqual(res_own.status_code, 200)
        data = res_own.get_json()
        self.assertTrue(data['success'])
        self.assertTrue(data['is_completed'])

    def test_dynamic_statistics_calculation(self):
        """Test that syllabus % and stats are strictly calculated from database"""
        # Login as test_student
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})
        res = self.client.get('/dashboard')
        self.assertEqual(res.status_code, 200)

        # 1 completed out of 2 topics = 50%
        self.assertIn(b'50%', res.data)
        # 1 active subject
        self.assertIn(b'Active subjects', res.data)

    def test_ai_honesty_when_offline(self):
        """Test that AI assistant honestly reports offline when no key is set"""
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})
        with patch.dict(os.environ, {'GEMINI_API_KEY': ''}):
            res = self.client.post('/api/ai/chat', json={'message': 'Explain binary search'})
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertFalse(data.get('online', True))
            self.assertIn('offline', data['reply'].lower())

    def test_standalone_auth_layout_without_sidebar(self):
        """Verify login and register pages render standalone layout without sidebar/searchbar"""
        login_page = self.client.get('/login')
        self.assertEqual(login_page.status_code, 200)
        self.assertNotIn(b'<aside class="sidebar">', login_page.data)
        self.assertNotIn(b'id="globalSearchInput"', login_page.data)
        self.assertNotIn(b'notification-btn', login_page.data)
        self.assertIn(b'Welcome Back to EduMate', login_page.data)

        register_page = self.client.get('/register')
        self.assertEqual(register_page.status_code, 200)
        self.assertNotIn(b'<aside class="sidebar">', register_page.data)
        self.assertNotIn(b'id="globalSearchInput"', register_page.data)
        self.assertIn(b'Create Student Account', register_page.data)

    def test_roadmap_generation_success(self):
        """Test generating a day-by-day roadmap with real topic distribution"""
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})
        future_date = (date.today() + timedelta(days=14)).isoformat()

        with self.app.app_context():
            sub = Subject.query.filter_by(user_id=self.student_id).first()
            sub_id = sub.id

        response = self.client.post('/roadmap/generate', data={
            'subject_id': sub_id,
            'exam_date': future_date,
            'daily_hours': '2.0',
            'syllabus_text': 'Unit 1: Fundamentals\nArrays\nLinked Lists\nUnit 2: Non-Linear\nBinary Trees\nGraphs',
            'title': 'Test DSA Roadmap'
        }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Test DSA Roadmap', response.data)
        self.assertIn(b'Arrays', response.data)
        self.assertIn(b'Comprehensive Revision', response.data)

        # Check in DB
        with self.app.app_context():
            plan = RoadmapPlan.query.filter_by(user_id=self.student_id).first()
            self.assertIsNotNone(plan)
            self.assertEqual(plan.title, 'Test DSA Roadmap')
            self.assertFalse(plan.has_workload_warning)
            self.assertGreater(len(plan.items), 4)

    def test_roadmap_validation_past_date(self):
        """Test that past exam date is rejected with clean error message"""
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})
        past_date = (date.today() - timedelta(days=5)).isoformat()

        with self.app.app_context():
            sub = Subject.query.filter_by(user_id=self.student_id).first()
            sub_id = sub.id

        response = self.client.post('/roadmap/generate', data={
            'subject_id': sub_id,
            'exam_date': past_date,
            'daily_hours': '2.0',
            'syllabus_text': 'Topic 1\nTopic 2'
        }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Exam date must be in the future', response.data)

    def test_roadmap_workload_warning(self):
        """Test that excessive syllabus volume triggers a workload warning"""
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})
        # Exam is in 2 days, but student provides 20 topics with only 1 hr/day
        near_date = (date.today() + timedelta(days=2)).isoformat()

        with self.app.app_context():
            sub = Subject.query.filter_by(user_id=self.student_id).first()
            sub_id = sub.id

        heavy_syllabus = "\n".join([f"Topic {i}" for i in range(1, 21)])

        response = self.client.post('/roadmap/generate', data={
            'subject_id': sub_id,
            'exam_date': near_date,
            'daily_hours': '1.0',
            'syllabus_text': heavy_syllabus
        }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Workload Warning', response.data)

    def test_roadmap_item_toggle_persistence(self):
        """Test toggling a roadmap milestone and recalculating plan progress in DB"""
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        with self.app.app_context():
            sub = Subject.query.filter_by(user_id=self.student_id).first()
            plan = RoadmapPlan(
                user_id=self.student_id,
                subject_id=sub.id,
                exam_date=date.today() + timedelta(days=10),
                total_topics_count=2,
                completed_topics_count=0
            )
            db.session.add(plan)
            db.session.flush()

            item = RoadmapItem(
                plan_id=plan.id,
                day_number=1,
                scheduled_date=date.today() + timedelta(days=1),
                topic_title='Pointers in C',
                is_completed=False
            )
            db.session.add(item)
            db.session.commit()
            item_id = item.id

        # Toggle via API
        toggle_res = self.client.post(f'/api/roadmap/toggle/{item_id}')
        self.assertEqual(toggle_res.status_code, 200)
        data = toggle_res.get_json()
        self.assertTrue(data['success'])
        self.assertTrue(data['is_completed'])
        self.assertEqual(data['completed_count'], 1)
        self.assertEqual(data['progress_percentage'], 50)

        # Verify persistence in DB
        with self.app.app_context():
            updated_item = db.session.get(RoadmapItem, item_id)
            self.assertTrue(updated_item.is_completed)
            self.assertIsNotNone(updated_item.completed_at)

    def test_explore_exams_search_and_filter(self):
        """Test exploring verified national competitive and entrance exams"""
        with self.app.app_context():
            exam = OfficialExamDirectory(
                exam_code='GATE',
                exam_name='Graduate Aptitude Test in Engineering',
                conducting_authority='IIT / IISc',
                category='Engineering & Technology',
                eligibility_summary='B.Tech or equivalent',
                official_portal_url='https://gate2025.iitr.ac.in',
                official_notification_note='Official brochure available on portal'
            )
            db.session.add(exam)
            db.session.commit()

        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        # 1. Search by keyword
        res = self.client.get('/explore-exams?q=GATE')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Graduate Aptitude Test in Engineering', res.data)
        self.assertIn(b'https://gate2025.iitr.ac.in', res.data)
        self.assertIn(b'Verified Official Source', res.data)

        # 2. Search nonexistent keyword
        res_empty = self.client.get('/explore-exams?q=NonExistentExamXYZ')
        self.assertEqual(res_empty.status_code, 200)
        self.assertIn(b'No exams found matching', res_empty.data)

    def test_add_subject_success_and_duplicate_prevention(self):
        """Test adding a subject via POST and verify duplicate name/code rejection"""
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        # 1. Add valid new subject
        res = self.client.post('/subjects', data={
            'name': 'Operating Systems',
            'code': 'OS',
            'color': '#10b981',
            'icon': 'gear'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Operating Systems', res.data)
        self.assertIn(b'OS', res.data)

        # Verify record in SQLite database
        with self.app.app_context():
            saved_subj = Subject.query.filter_by(user_id=self.student_id, name='Operating Systems').first()
            self.assertIsNotNone(saved_subj)
            self.assertEqual(saved_subj.code, 'OS')
            self.assertEqual(saved_subj.color, '#10b981')
            self.assertEqual(saved_subj.icon, 'gear')

        # 2. Attempt adding duplicate name
        res_dup = self.client.post('/subjects', data={
            'name': 'Operating Systems',
            'code': 'OS2',
            'color': '#2563eb',
            'icon': 'book'
        }, follow_redirects=True)
        self.assertEqual(res_dup.status_code, 200)
        self.assertIn(b'already exists in your coursework', res_dup.data)

        # 3. Attempt adding empty name
        res_empty = self.client.post('/subjects', data={
            'name': '   ',
            'code': 'EMPTY'
        }, follow_redirects=True)
        self.assertEqual(res_empty.status_code, 200)
        self.assertIn(b'Subject name is required', res_empty.data)

    def test_get_user_subjects_dropdown_api(self):
        """Test GET /api/subjects returns only current user's enrolled subjects for dynamic dropdowns"""
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        res = self.client.get('/api/subjects')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertIsInstance(data['subjects'], list)
        self.assertGreaterEqual(len(data['subjects']), 1)

        # Verify structure
        subj = data['subjects'][0]
        self.assertIn('id', subj)
        self.assertIn('name', subj)
        self.assertIn('code', subj)
        self.assertIn('progress_percentage', subj)
        self.assertEqual(subj['name'], 'Data Structures')

    def test_syllabus_pdf_upload_and_topic_extraction(self):
        """Test uploading a text PDF, extracting syllabus topics, handling scanned/password errors"""
        import io
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        # 1. Test standard text PDF
        pdf_bytes = (
            b"%PDF-1.4\n"
            b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
            b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
            b"4 0 obj << /Length 135 >> stream\n"
            b"BT\n"
            b"/F1 12 Tf\n"
            b"72 712 Td\n"
            b"(Unit 1: Foundations of Algorithms) Tj\n"
            b"0 -20 Td\n"
            b"(- Asymptotic Analysis) Tj\n"
            b"0 -20 Td\n"
            b"(- Divide and Conquer Strategy) Tj\n"
            b"ET\n"
            b"endstream endobj\n"
            b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
            b"xref\n"
            b"0 6\n"
            b"0000000000 65535 f \n"
            b"0000000009 00000 n \n"
            b"0000000058 00000 n \n"
            b"0000000115 00000 n \n"
            b"0000000244 00000 n \n"
            b"0000000429 00000 n \n"
            b"trailer << /Size 6 /Root 1 0 R >>\n"
            b"startxref\n"
            b"500\n"
            b"%%EOF\n"
        )
        pdf_stream = io.BytesIO(pdf_bytes)
        res = self.client.post(
            '/api/syllabus/extract-pdf',
            data={'pdf_file': (pdf_stream, 'algorithms_syllabus.pdf')},
            content_type='multipart/form-data'
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['filename'], 'algorithms_syllabus.pdf')
        self.assertGreaterEqual(len(data['topics']), 2)
        topic_titles = [t['title'] for t in data['topics']]
        self.assertIn('Asymptotic Analysis', topic_titles)
        self.assertIn('Divide and Conquer Strategy', topic_titles)

        # 2. Test invalid non-PDF file extension
        text_stream = io.BytesIO(b"Hello syllabus")
        res_invalid = self.client.post(
            '/api/syllabus/extract-pdf',
            data={'pdf_file': (text_stream, 'syllabus.docx')},
            content_type='multipart/form-data'
        )
        self.assertEqual(res_invalid.status_code, 400)
        self.assertIn('Invalid file format', res_invalid.get_json()['error'])

        # 3. Test scanned / empty text PDF with OCR notice
        import pypdf
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=300, height=300)
        blank_stream = io.BytesIO()
        writer.write(blank_stream)
        blank_stream.seek(0)

        res_scanned = self.client.post(
            '/api/syllabus/extract-pdf',
            data={'pdf_file': (blank_stream, 'scanned_notes.pdf')},
            content_type='multipart/form-data'
        )
        self.assertEqual(res_scanned.status_code, 400)
        err_msg = res_scanned.get_json()['error']
        self.assertIn('No readable text or syllabus content could be extracted', err_msg)

    def test_save_extracted_topics_to_subject_and_roadmap_availability(self):
        """Test confirming and saving extracted topics to a subject, and verify roadmap sees them"""
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        # Save 3 topics to the student's subject
        topics_payload = [
            {'title': 'Graph Traversals (BFS & DFS)'},
            {'title': 'Dijkstra Shortest Path Algorithm'},
            {'title': 'Minimum Spanning Trees (Kruskal & Prim)'}
        ]

        res = self.client.post(
            '/api/syllabus/save-topics',
            json={
                'subject_id': self.subject_id,
                'topics': topics_payload,
                'replace_existing': False
            }
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['saved_count'], 3)

        # Verify topics now exist in the database for this subject
        with self.app.app_context():
            subj = db.session.get(Subject, self.subject_id)
            titles = [t.title for t in subj.topics]
            self.assertIn('Graph Traversals (BFS & DFS)', titles)
            self.assertIn('Dijkstra Shortest Path Algorithm', titles)

        # Generate roadmap without manual text input -> should automatically use newly saved topics
        res_roadmap = self.client.post('/roadmap/generate', data={
            'subject_id': self.subject_id,
            'exam_date': (date.today() + timedelta(days=20)).isoformat(),
            'daily_hours': 2.0,
            'syllabus_text': ''  # blank to auto-use subject topics
        }, follow_redirects=True)

        self.assertEqual(res_roadmap.status_code, 200)
        self.assertIn(b'Graph Traversals (BFS &amp; DFS)', res_roadmap.data)
        self.assertIn(b'Dijkstra Shortest Path Algorithm', res_roadmap.data)

    def test_admin_dashboard_metrics_and_student_forbidden(self):
        """Test admin dashboard renders database-backed metrics and blocks students with 403"""
        # 1. Student access blocked
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})
        res_stud = self.client.get('/admin/')
        self.assertEqual(res_stud.status_code, 403)

        self.client.get('/logout')

        # 2. Admin access granted
        self.client.post('/login', data={'identifier': 'test_admin', 'password': 'admin123'})
        res_adm = self.client.get('/admin/')
        self.assertEqual(res_adm.status_code, 200)
        self.assertIn(b'Admin Control Center', res_adm.data)
        self.assertIn(b'Total Registered Users', res_adm.data)
        self.assertIn(b'Academic Content', res_adm.data)

    def test_admin_user_management_crud_and_safeguards(self):
        """Test user listing, creation, role change, password reset, and self-protection guards"""
        self.client.post('/login', data={'identifier': 'test_admin', 'password': 'admin123'})

        # 1. Create new user via admin
        res_create = self.client.post('/admin/users/create', data={
            'username': 'new_created_user',
            'email': 'new_created@test.com',
            'password': 'password123',
            'role': 'student',
            'is_active': 'true'
        }, follow_redirects=True)
        self.assertEqual(res_create.status_code, 200)
        self.assertIn(b'created successfully', res_create.data)

        with self.app.app_context():
            created_u = User.query.filter_by(username='new_created_user').first()
            self.assertIsNotNone(created_u)
            self.assertEqual(created_u.role, 'student')
            created_u_id = created_u.id

        # 2. Edit user (elevate to admin)
        res_edit = self.client.post(f'/admin/users/{created_u_id}/edit', data={
            'username': 'new_created_user',
            'email': 'new_created@test.com',
            'role': 'admin',
            'is_active': 'true'
        }, follow_redirects=True)
        self.assertEqual(res_edit.status_code, 200)
        self.assertIn(b'updated successfully', res_edit.data)

        # 3. Administrative password reset
        res_reset = self.client.post(f'/admin/users/{created_u_id}/reset-password', data={
            'new_password': 'newpassword123'
        }, follow_redirects=True)
        self.assertEqual(res_reset.status_code, 200)
        self.assertIn(b'successfully reset', res_reset.data)

        # 4. Safeguard: Admin cannot delete their own account (403 Forbidden)
        res_self_del = self.client.post(f'/admin/delete-user/{self.admin_id}', follow_redirects=False)
        self.assertEqual(res_self_del.status_code, 403)
        self.assertIn(b'cannot delete your own administrative account', res_self_del.data)

        # 5. Safeguard: Cannot deactivate self (403 Forbidden)
        res_self_toggle = self.client.post(f'/admin/toggle-user/{self.admin_id}', follow_redirects=False)
        self.assertEqual(res_self_toggle.status_code, 403)
        self.assertIn(b'cannot deactivate your own administrative account', res_self_toggle.data)

        # 6. Verify audit logs were generated
        with self.app.app_context():
            logs = AuditLog.query.filter_by(admin_username='test_admin').all()
            actions = [l.action for l in logs]
            self.assertIn('USER_CREATE', actions)
            self.assertIn('USER_EDIT', actions)
            self.assertIn('PASSWORD_RESET', actions)

    def test_admin_academics_and_official_exam_management(self):
        """Test admin subject creation, topic addition, and official exam entry"""
        self.client.post('/login', data={'identifier': 'test_admin', 'password': 'admin123'})

        # 1. Create subject for student
        res_sub = self.client.post('/admin/academics/subjects/create', data={
            'student_id': self.student_id,
            'name': 'Cloud Computing',
            'code': 'CC',
            'color': '#8b5cf6',
            'icon': 'cpu'
        }, follow_redirects=True)
        self.assertEqual(res_sub.status_code, 200)
        self.assertIn(b'Cloud Computing', res_sub.data)

        with self.app.app_context():
            sub = Subject.query.filter_by(name='Cloud Computing', user_id=self.student_id).first()
            self.assertIsNotNone(sub)
            sub_id = sub.id

        # 2. Add topic to that subject
        res_top = self.client.post(f'/admin/academics/subjects/{sub_id}/topics/add', data={
            'title': 'Virtual Machines & Containers',
            'is_completed': 'true'
        }, follow_redirects=True)
        self.assertEqual(res_top.status_code, 200)
        self.assertIn(b'Virtual Machines &amp; Containers', res_top.data)

        # 3. Add official exam to directory
        res_exam = self.client.post('/admin/academics/official-exams/create', data={
            'exam_code': 'ISRO_SC',
            'exam_name': 'ISRO Scientist/Engineer SC Exam',
            'conducting_authority': 'ISRO Centralised Recruitment Board',
            'category': 'Research & Academic Fellowships',
            'eligibility_summary': 'B.Tech with minimum 65%',
            'official_portal_url': 'https://www.isro.gov.in/careers',
            'official_notification_note': 'Check official portal for syllabus notification'
        }, follow_redirects=True)
        self.assertEqual(res_exam.status_code, 200)
        self.assertIn(b'ISRO_SC', res_exam.data)

    def test_admin_system_control_backup_and_audit(self):
        """Test system configuration update, database backup creation, and audit trail"""
        self.client.post('/login', data={'identifier': 'test_admin', 'password': 'admin123'})

        # 1. Update system settings
        res_settings = self.client.post('/admin/system/settings/update', data={
            'maintenance_mode': 'true',
            'allow_registrations': 'false'
        }, follow_redirects=True)
        self.assertEqual(res_settings.status_code, 200)
        self.assertIn(b'System settings updated successfully', res_settings.data)

        # Verify setting persisted
        with self.app.app_context():
            self.assertEqual(SystemSetting.get_val('allow_registrations'), 'false')
            self.assertEqual(SystemSetting.get_val('maintenance_mode'), 'true')

        # 2. Verify registration route is blocked when allow_registrations is false
        self.client.get('/logout')
        res_reg = self.client.get('/register', follow_redirects=True)
        self.assertIn(b'Public registration is currently closed', res_reg.data)

        # 3. Log back in as admin, re-enable registrations (default state), and create backup
        self.client.post('/login', data={'identifier': 'test_admin', 'password': 'admin123'})
        res_reenable = self.client.post('/admin/system/settings/update', data={
            'allow_registrations': 'true',
            'maintenance_mode': 'false'
        }, follow_redirects=True)
        self.assertEqual(res_reenable.status_code, 200)

        with self.app.app_context():
            self.assertEqual(SystemSetting.get_val('allow_registrations'), 'true')
            self.assertEqual(SystemSetting.get_val('maintenance_mode'), 'false')

        # Verify /register is now open and accessible
        self.client.get('/logout')
        res_reg_open = self.client.get('/register')
        self.assertEqual(res_reg_open.status_code, 200)
        self.assertIn(b'Create Student Account', res_reg_open.data)

        # Log back in as admin
        self.client.post('/login', data={'identifier': 'test_admin', 'password': 'admin123'})
        res_backup = self.client.post('/admin/system/backup/create', follow_redirects=True)
        self.assertEqual(res_backup.status_code, 200)
        self.assertIn(b'Database backup', res_backup.data)

        # 4. View Audit Logs page
        res_audit = self.client.get('/admin/audit-logs')
        self.assertEqual(res_audit.status_code, 200)
        self.assertIn(b'Administrative Audit Trail', res_audit.data)
        self.assertIn(b'SETTINGS_UPDATE', res_audit.data)

    def test_ai_service_gemini_primary_success(self):
        """Test Gemini primary provider returns expected output and provenance"""
        from ai_service import HybridAIService
        service = HybridAIService(gemini_api_key="test_key_gemini_12345", gemini_model="gemini-3.8-flash")

        mock_response = MagicMock()
        mock_response.text = "Binary Search operates in O(log n) time by dividing search space."

        with patch('google.genai.Client') as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.models.generate_content.return_value = mock_response

            result = service.generate_response("Explain binary search")
            self.assertTrue(result['success'])
            self.assertEqual(result['provider'], 'gemini')
            self.assertEqual(result['model'], 'gemini-3.8-flash')
            self.assertFalse(result['fallback_used'])
            self.assertIn("Binary Search operates", result['response'])

    def test_ai_service_gemini_quota_fallback_to_ollama(self):
        """Test automatic fallback to local Ollama on Gemini quota exhaustion (429)"""
        from ai_service import HybridAIService
        from google.genai.errors import ClientError
        service = HybridAIService(
            gemini_api_key="test_key_gemini_12345",
            gemini_model="gemini-3.8-flash",
            ollama_base_url="http://127.0.0.1:11434",
            ollama_model="gemma3:1b"
        )

        with patch('google.genai.Client') as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.models.generate_content.side_effect = ClientError(429, {'error': {'message': 'Resource exhausted: Free tier quota exceeded'}})

            with patch('requests.post') as mock_requests_post:
                mock_ollama_resp = MagicMock()
                mock_ollama_resp.status_code = 200
                mock_ollama_resp.json.return_value = {
                    'response': "Ollama fallback response: Binary Search halves the input each step."
                }
                mock_requests_post.return_value = mock_ollama_resp

                result = service.generate_response("Explain binary search")
                self.assertTrue(result['success'])
                self.assertEqual(result['provider'], 'ollama')
                self.assertEqual(result['model'], 'gemma3:1b')
                self.assertTrue(result['fallback_used'])
                self.assertIn("Ollama fallback response", result['response'])
                self.assertIn("Resource exhausted", result['gemini_error'])

    def test_ai_service_invalid_input_no_fallback(self):
        """Test that invalid/empty input raises InvalidInputException and does NOT trigger fallback"""
        from ai_service import HybridAIService, InvalidInputException
        service = HybridAIService(gemini_api_key="test_key", ollama_model="gemma3:1b")

        with patch.object(service, '_call_gemini') as mock_gemini, \
             patch.object(service, '_call_ollama') as mock_ollama:
            with self.assertRaises(InvalidInputException):
                service.generate_response("   ")

            mock_gemini.assert_not_called()
            mock_ollama.assert_not_called()

    def test_ai_service_both_providers_failed_honest_error(self):
        """Test honest failure reporting with full diagnostic error when both providers fail"""
        from ai_service import HybridAIService
        from google.genai.errors import ServerError
        service = HybridAIService(gemini_api_key="test_key", ollama_model="gemma3:1b")

        with patch('google.genai.Client') as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.models.generate_content.side_effect = ServerError(503, {'error': {'message': 'Service Unavailable'}})

            with patch('requests.post') as mock_requests_post:
                mock_requests_post.side_effect = Exception("Connection refused by Ollama daemon")

                result = service.generate_response("Explain quicksort")
                self.assertFalse(result['success'])
                self.assertIsNone(result['provider'])
                self.assertTrue(result['fallback_used'])
                self.assertIn("Both AI providers are currently unavailable", result['error_message'])
                self.assertIn("503", result['gemini_error'])
                self.assertIn("Connection refused", result['ollama_error'])

    def test_admin_ai_status_and_diagnostic_endpoints(self):
        """Test admin AI status and test diagnostic endpoints with RBAC and Audit Trail"""
        # 1. Unauthenticated access blocked
        res_unauth = self.client.get('/admin/ai/status')
        self.assertEqual(res_unauth.status_code, 302)

        # 2. Student access forbidden (RBAC)
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})
        res_student_status = self.client.get('/admin/ai/status')
        self.assertEqual(res_student_status.status_code, 403)
        res_student_test = self.client.post('/admin/ai/test', json={'prompt': 'test'})
        self.assertEqual(res_student_test.status_code, 403)

        # 3. Admin access permitted (logout student first)
        self.client.get('/logout')
        self.client.post('/login', data={'identifier': 'test_admin', 'password': 'admin123'})

        # Test status endpoint
        res_admin_status = self.client.get('/admin/ai/status')
        self.assertEqual(res_admin_status.status_code, 200)
        status_data = res_admin_status.get_json()
        self.assertTrue(status_data['success'])
        self.assertIn('primary', status_data['status'])
        self.assertIn('fallback', status_data['status'])
        self.assertEqual(status_data['status']['primary']['provider'], 'gemini')
        self.assertEqual(status_data['status']['fallback']['provider'], 'ollama')

        # Test diagnostic execution endpoint with mocked AI service
        with patch('admin.ai_service.generate_response') as mock_gen:
            mock_gen.return_value = {
                'success': True,
                'provider': 'gemini',
                'model': 'gemini-3.8-flash',
                'fallback_used': False,
                'response': 'Admin diagnostic executed cleanly.'
            }
            res_admin_test = self.client.post('/admin/ai/test', json={'prompt': 'Admin test prompt'})
            self.assertEqual(res_admin_test.status_code, 200)
            test_data = res_admin_test.get_json()
            self.assertTrue(test_data['success'])
            self.assertEqual(test_data['provider'], 'gemini')
            self.assertEqual(test_data['response'], 'Admin diagnostic executed cleanly.')

            # Verify Audit Trail entry created
            with self.app.app_context():
                log_entry = AuditLog.query.filter_by(action='AI_PROVIDER_TEST').first()
                self.assertIsNotNone(log_entry)
                self.assertIn('gemini', log_entry.details)

    def test_syllabus_review_and_approval_flow(self):
        """Test syllabus review page access and approval into Topic table with source pages"""
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        with self.app.app_context():
            doc = UploadedPdfDocument(
                user_id=self.student_id,
                subject_id=self.subject_id,
                filename='os_syllabus.pdf',
                file_size_bytes=4096,
                page_count=2,
                ocr_applied=False,
                status='Processed',
                extracted_text='Unit 1: Process Management\n- CPU Scheduling\n- Deadlocks',
                structured_json='{"subject": "Operating Systems", "units": [{"unit_number": 1, "title": "Unit 1: Process Management", "topics": [{"name": "CPU Scheduling", "subtopics": ["Round Robin"], "source_pages": [1]}]}]}',
                topics_count=1
            )
            db.session.add(doc)
            db.session.commit()
            doc_id = doc.id

        # Access review page
        res = self.client.get(f'/syllabus/review/{doc_id}')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Review & Approve Syllabus Topics', res.data)
        self.assertIn(b'os_syllabus.pdf', res.data)

        # Approve syllabus topics
        approve_res = self.client.post(
            '/api/syllabus/approve',
            json={
                'doc_id': doc_id,
                'subject_id': self.subject_id,
                'flat_topics': [
                    {
                        'unit_name': 'Unit 1: Process Management',
                        'title': 'CPU Scheduling',
                        'subtopics': ['Round Robin', 'FCFS'],
                        'source_pages': '1, 2'
                    }
                ],
                'units': [
                    {
                        'unit_number': 1,
                        'title': 'Unit 1: Process Management',
                        'topics': [{'name': 'CPU Scheduling', 'subtopics': ['Round Robin', 'FCFS'], 'source_pages': [1, 2]}]
                    }
                ]
            }
        )
        self.assertEqual(approve_res.status_code, 200)
        appr_data = approve_res.get_json()
        self.assertTrue(appr_data['success'])

        with self.app.app_context():
            saved_topic = Topic.query.filter_by(subject_id=self.subject_id, title='CPU Scheduling').first()
            self.assertIsNotNone(saved_topic)
            self.assertEqual(saved_topic.unit_name, 'Unit 1: Process Management')
            self.assertEqual(saved_topic.source_pages, '1, 2')
            self.assertIn('Round Robin', saved_topic.subtopics)

            updated_doc = db.session.get(UploadedPdfDocument, doc_id)
            self.assertEqual(updated_doc.status, 'Approved')

    def test_ai_roadmap_generation_and_workload_calculation(self):
        """Test study roadmap generation with workload warning and revision distribution"""
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        exam_target = (date.today() + timedelta(days=5)).isoformat()
        res = self.client.post('/roadmap/generate', data={
            'subject_id': self.subject_id,
            'exam_date': exam_target,
            'daily_hours': '1.0',
            'syllabus_text': 'Unit 1: Foundations\n- Topic A\n- Topic B\n- Topic C\n- Topic D\n- Topic E\n- Topic F\n- Topic G',
            'title': 'Intensive Midterm Prep'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with self.app.app_context():
            plan = RoadmapPlan.query.filter_by(user_id=self.student_id, title='Intensive Midterm Prep').first()
            self.assertIsNotNone(plan)
            # 7 topics require ~10.5 hrs, but 5 days * 1.0 hr = 5 hrs -> workload warning expected
            self.assertTrue(plan.has_workload_warning)
            self.assertGreater(len(plan.items), 7)
            # Verify revision item exists
            rev_items = [i for i in plan.items if i.is_revision]
            self.assertGreaterEqual(len(rev_items), 1)

    def test_ai_chat_and_history_persistence(self):
        """Test grounded AI study assistant chat and chat history persistence"""
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        with patch('ai_service.ai_service.chat_study_assistant') as mock_chat:
            mock_chat.return_value = {
                'success': True,
                'provider': 'gemini',
                'model': 'gemini-3.8-flash',
                'fallback_used': False,
                'reply': 'According to Unit 1 (Page 2), a binary tree node has at most two children.',
                'source_pages': 'Page 2'
            }

            res = self.client.post('/api/ai/chat', json={'message': 'What is a binary tree?'})
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data['online'])
            self.assertEqual(data['provider'], 'gemini')
            self.assertEqual(data['source_pages'], 'Page 2')

        # Check chat history endpoint
        hist_res = self.client.get('/api/ai/chat/history')
        self.assertEqual(hist_res.status_code, 200)
        hist_data = hist_res.get_json()
        self.assertTrue(hist_data['success'])
        self.assertGreaterEqual(len(hist_data['messages']), 1)
        self.assertEqual(hist_data['messages'][-1]['source_pages'], 'Page 2')

    def test_academic_content_notes_and_quiz_submission(self):
        """Test academic content generation (notes and MCQs) and quiz submission scoring"""
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        with self.app.app_context():
            topic = Topic.query.filter_by(subject_id=self.subject_id).first()
            topic_id = topic.id

        # 1. Test notes generation
        with patch('ai_service.ai_service.generate_academic_content') as mock_gen:
            mock_gen.return_value = {
                'success': True,
                'content_type': 'notes',
                'provider': 'gemini',
                'model': 'gemini-3.8-flash',
                'topic': 'Arrays',
                'content': '### Key Notes\nArrays store contiguous elements.'
            }

            res_notes = self.client.post('/api/ai/academic-content', json={
                'topic_id': topic_id,
                'content_type': 'notes'
            })
            self.assertEqual(res_notes.status_code, 200)
            data_notes = res_notes.get_json()
            self.assertTrue(data_notes['success'])
            self.assertIn('contiguous', data_notes['content'])

        # 2. Test quiz submission and scoring
        mock_questions = [
            {'question': 'Time complexity of array indexing?', 'options': ['O(1)', 'O(n)'], 'correct_answer': 0, 'explanation': 'Direct memory offset'}
        ]
        user_answers = [0]  # Correct answer

        res_quiz = self.client.post('/api/quiz/submit', json={
            'topic_id': topic_id,
            'subject_id': self.subject_id,
            'title': 'Arrays Quick Quiz',
            'questions': mock_questions,
            'answers': user_answers
        })
        self.assertEqual(res_quiz.status_code, 200)
        quiz_data = res_quiz.get_json()
        self.assertTrue(quiz_data['success'])
        self.assertEqual(quiz_data['score'], 1)
        self.assertEqual(quiz_data['total_questions'], 1)
        self.assertEqual(quiz_data['percentage'], 100)

        # 3. Verify QuizAttempt record in database and quizzes_view rendering
        with self.app.app_context():
            attempt = QuizAttempt.query.filter_by(user_id=self.student_id, title='Arrays Quick Quiz').first()
            self.assertIsNotNone(attempt)
            self.assertEqual(attempt.score, 1)

        res_view = self.client.get('/quizzes')
        self.assertEqual(res_view.status_code, 200)
        self.assertIn(b'Arrays Quick Quiz', res_view.data)

    def _generate_test_pdf_bytes(self, lines):
        """Helper to create minimal valid text PDF bytes for testing syllabus extraction"""
        stream_content = "BT\n/F1 12 Tf\n72 712 Td\n"
        for l in lines:
            escaped = l.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            stream_content += f"({escaped}) Tj\n0 -18 Td\n"
        stream_content += "ET\n"
        stream_bytes = stream_content.encode('utf-8')
        stream_len = len(stream_bytes)

        header = b"%PDF-1.4\n"
        obj1 = b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        obj2 = b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        obj3 = b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
        obj4 = f"4 0 obj << /Length {stream_len} >> stream\n{stream_content}endstream endobj\n".encode('utf-8')
        obj5 = b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"

        body = header + obj1 + obj2 + obj3 + obj4 + obj5
        xref = (
            f"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n"
            f"0000000115 00000 n \n0000000244 00000 n \n"
            f"{len(header)+len(obj1)+len(obj2)+len(obj3)+len(obj4):010d} 00000 n \n"
            f"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n{len(body)}\n%%EOF\n"
        ).encode('utf-8')
        return body + xref

    def test_intelligent_extractor_rejects_non_syllabus_document(self):
        """Test that uploaded non-syllabus documents (fee receipts, circulars, certificates) are rejected"""
        import io
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        non_syllabus_pdf = self._generate_test_pdf_bytes([
            "State Technical University - Office of Registrar",
            "CIRCULAR NO: STU/FEE/2026/89",
            "This is to certify that the annual fee structure has been revised.",
            "Fee details: Tuition fee Rs 60,000, Examination fee Rs 8,000.",
            "Rules of Examination: Minimum attendance required 75 percent.",
            "Students failing to pay late fee fine by deadline will not receive admit cards.",
            "Tender notice: Canteen services invitation for bids."
        ])

        res = self.client.post(
            '/api/syllabus/extract-pdf',
            data={'pdf_file': (io.BytesIO(non_syllabus_pdf), 'fee_circular.pdf')},
            content_type='multipart/form-data'
        )

        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data['success'])
        self.assertFalse(data['is_syllabus'])
        self.assertIn('No academic syllabus detected', data['error'])

        # Verify recorded document status
        with self.app.app_context():
            doc = UploadedPdfDocument.query.filter_by(filename='fee_circular.pdf').first()
            self.assertIsNotNone(doc)
            self.assertEqual(doc.status, 'No Syllabus Detected')

    def test_intelligent_extractor_handles_multiple_unit_formats_and_ignores_noise(self):
        """Test extraction across unit formats (Unit 1, Module II, Chapter 3), codes, and noise filtering"""
        import io
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        syllabus_pdf = self._generate_test_pdf_bytes([
            "Course Title: Operating Systems",
            "Course Code: CS-401",
            "Page 1 of 4",
            "Credits: 4   Marks: 100   Hours: 40",
            "UNIT 1: Process Management",
            "- Process Concepts: States, PCB, Context Switch",
            "- CPU Scheduling Algorithms: FCFS, Round Robin, Priority",
            "Module II: Concurrency and Synchronization",
            "- Inter-process Communication: Shared Memory, Message Passing",
            "- Semaphores and Deadlocks",
            "Chapter 3: Memory Management",
            "- Paging and Segmentation",
            "- Virtual Memory and Page Replacement"
        ])

        res = self.client.post(
            '/api/syllabus/extract-pdf',
            data={'pdf_file': (io.BytesIO(syllabus_pdf), 'os_curriculum.pdf')},
            content_type='multipart/form-data'
        )

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertTrue(data['is_syllabus'])
        self.assertEqual(data['subject'], 'Operating Systems')
        self.assertEqual(data['course_code'], 'CS-401')

        # Check detected units
        units = data['units']
        self.assertEqual(len(units), 3)
        self.assertIn('Unit 1', units[0]['title'])
        self.assertIn('Unit 2', units[1]['title'])
        self.assertIn('Unit 3', units[2]['title'])

        # Check topics & subtopics under Unit 1
        u1_topics = units[0]['topics']
        self.assertEqual(len(u1_topics), 2)
        self.assertEqual(u1_topics[0]['name'], 'Process Concepts')
        self.assertIn('PCB', u1_topics[0]['subtopics'])
        self.assertEqual(u1_topics[1]['name'], 'CPU Scheduling Algorithms')
        self.assertIn('Round Robin', u1_topics[1]['subtopics'])

        # Check noise filtering: "Page 1 of 4", "Credits: 4", "Hours: 40" must not be topics
        all_topic_names = [t['title'] for t in data['topics']]
        self.assertNotIn('Page 1 of 4', all_topic_names)
        self.assertNotIn('Credits: 4   Marks: 100   Hours: 40', all_topic_names)

    def test_intelligent_extractor_handles_unassigned_topics_and_manual_review(self):
        """Test that ambiguous topics before any unit heading are marked for manual review and can be approved"""
        import io
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        syllabus_pdf = self._generate_test_pdf_bytes([
            "Subject: Algorithms and Complexity",
            "Course Code: CS-305",
            "- Preliminary Math Review: Asymptotics, Recurrences",
            "UNIT 1: Divide and Conquer",
            "- Merge Sort and Quick Sort",
            "UNIT-II: Greedy Strategy",
            "- Huffman Coding and Minimum Spanning Trees"
        ])

        res = self.client.post(
            '/api/syllabus/extract-pdf',
            data={'pdf_file': (io.BytesIO(syllabus_pdf), 'algorithms_review.pdf')},
            content_type='multipart/form-data'
        )

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        doc_id = data['doc_id']

        # Preliminary math review must be in unassigned_topics with needs_review
        self.assertGreaterEqual(len(data['unassigned_topics']), 1)
        unassigned_names = [ut['name'] for ut in data['unassigned_topics']]
        self.assertIn('Preliminary Math Review', unassigned_names)
        self.assertTrue(data['unassigned_topics'][0]['needs_review'])

        # Now approve with manual assignment: student assigns the review topic into Unit 1
        approve_res = self.client.post('/api/syllabus/approve', json={
            'doc_id': doc_id,
            'subject_id': '__NEW__',
            'new_subject_name': 'Algorithms and Complexity',
            'course_code': 'CS-305',
            'units': data['units'],
            'flat_topics': [
                {
                    'unit_name': 'Unit 1: Foundations',
                    'title': 'Preliminary Math Review',
                    'subtopics': ['Asymptotics', 'Recurrences'],
                    'source_pages': '1'
                },
                {
                    'unit_name': 'Unit 1: Divide and Conquer',
                    'title': 'Merge Sort and Quick Sort',
                    'subtopics': [],
                    'source_pages': '1'
                },
                {
                    'unit_name': 'Unit 2: Greedy Strategy',
                    'title': 'Huffman Coding and Minimum Spanning Trees',
                    'subtopics': [],
                    'source_pages': '1'
                }
            ]
        })

        self.assertEqual(approve_res.status_code, 200)
        approve_data = approve_res.get_json()
        self.assertTrue(approve_data['success'])

        # Verify subject and topics created in SQLite
        with self.app.app_context():
            new_sub = Subject.query.filter_by(name='Algorithms and Complexity', user_id=self.student_id).first()
            self.assertIsNotNone(new_sub)
            self.assertEqual(new_sub.code, 'CS-305')
            self.assertEqual(len(new_sub.topics), 3)

            # Test Study Roadmap Generator integrates seamlessly with these approved topics
            exam_target = date.today() + timedelta(days=14)
            roadmap_res = self.client.post('/roadmap/generate', data={
                'subject_id': new_sub.id,
                'exam_date': exam_target.isoformat(),
                'daily_hours': 2.0
            }, follow_redirects=True)
            self.assertEqual(roadmap_res.status_code, 200)

            # Verify RoadmapPlan exists for this subject
            plan = RoadmapPlan.query.filter_by(subject_id=new_sub.id, user_id=self.student_id).first()
            self.assertIsNotNone(plan)
            self.assertGreater(len(plan.items), 0)

    def test_regression_btech_common_course_bcc_syllabus_extraction(self):
        """Regression test for genuine university syllabus PDF: Microsoft Word - B.Tech_Common_Course_BCC.pdf.
        Verifies that table-based unit formatting (Unit/Topic/Lecture with Roman numerals I-V)
        is correctly identified, detected as PYTHON PROGRAMMING (BCC302 / BCC402), extracts all 5 units,
        ignores lecture hours (03, 05, etc.) and text books bibliography, and integrates with review and roadmap.
        """
        import io
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        # Create target subject Mathematics (MATH) as in user's UI
        with self.app.app_context():
            math_sub = Subject.query.filter_by(name='Mathematics', user_id=self.student_id).first()
            if not math_sub:
                math_sub = Subject(name='Mathematics', code='MATH', user_id=self.student_id)
                db.session.add(math_sub)
                db.session.commit()
            math_sub_id = math_sub.id

        pdf_path = os.path.join(os.path.dirname(__file__), 'real_world_validation', 'Microsoft_Word_BTech_Common_Course_BCC.pdf')
        self.assertTrue(os.path.exists(pdf_path), f"Test PDF must exist at {pdf_path}")

        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()

        data = {
            'pdf_file': (io.BytesIO(pdf_bytes), 'Microsoft Word - B.Tech_Common_Course_BCC.pdf'),
            'subject_id': str(math_sub_id)
        }

        response = self.client.post('/api/syllabus/extract-pdf', data=data, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 200)
        res_data = response.get_json()

        self.assertTrue(res_data['success'])
        self.assertTrue(res_data['is_syllabus'])
        self.assertEqual(res_data['detected_subject'], 'PYTHON PROGRAMMING')
        self.assertIn('BCC302', res_data['course_code'])

        # Check all 5 units
        units = res_data['units']
        self.assertEqual(len(units), 5)
        self.assertEqual(units[0]['unit_number'], 1)
        self.assertIn('Introduction to Python', units[0]['title'])
        self.assertEqual(units[1]['unit_number'], 2)
        self.assertEqual(units[2]['unit_number'], 3)
        self.assertEqual(units[3]['unit_number'], 4)
        self.assertEqual(units[4]['unit_number'], 5)

        # Check Unit 1 topics & subtopics
        u1_topics = units[0]['topics']
        self.assertGreaterEqual(len(u1_topics), 1)
        self.assertEqual(u1_topics[0]['name'], 'Introduction to Python')
        self.assertIn('Python variables', u1_topics[0]['subtopics'])

        # Verify lecture hours ('03', '05', etc.) and references are NOT included in topics
        all_topic_names = [t['name'].lower() for u in units for t in u['topics']]
        for forbidden in ['03', '05', '04', 'wesley j. chun', 'text books']:
            self.assertFalse(any(forbidden == name for name in all_topic_names), f"'{forbidden}' should not be a topic")

        # Test Review page loads properly for this document
        doc_id = res_data['doc_id']
        review_res = self.client.get(f'/syllabus/review/{doc_id}')
        self.assertEqual(review_res.status_code, 200)
        self.assertIn(b'PYTHON PROGRAMMING', review_res.data)

        # Test approval and roadmap generation
        flat_topics = [
            {'unit_name': u['title'], 'title': t['name'], 'subtopics': t.get('subtopics', []), 'source_pages': '1'}
            for u in units for t in u['topics']
        ]
        approve_res = self.client.post('/api/syllabus/approve', json={
            'doc_id': doc_id,
            'subject_id': '__NEW__',
            'new_subject_name': 'Python Programming',
            'course_code': 'BCC302 / BCC402',
            'units': units,
            'flat_topics': flat_topics
        })
        self.assertEqual(approve_res.status_code, 200)

        # Verify RoadmapPlan can be generated
        with self.app.app_context():
            python_sub = Subject.query.filter_by(name='Python Programming', user_id=self.student_id).first()
            self.assertIsNotNone(python_sub)
            self.assertEqual(len(python_sub.topics), len(flat_topics))

            exam_target = date.today() + timedelta(days=21)
            roadmap_res = self.client.post('/roadmap/generate', data={
                'subject_id': python_sub.id,
                'exam_date': exam_target.isoformat(),
                'daily_hours': 2.0
            }, follow_redirects=True)
            self.assertEqual(roadmap_res.status_code, 200)

    def test_mark_completed_synchronizes_topic_and_roadmap_item(self):
        """Test HIGH PRIORITY requirement: Marking completed syncs DB, persists, and is reversible"""
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        with self.app.app_context():
            sub = Subject.query.filter_by(user_id=self.student_id).first()
            exam_target = date.today() + timedelta(days=15)
            self.client.post('/roadmap/generate', data={
                'subject_id': sub.id,
                'exam_date': exam_target.isoformat(),
                'daily_hours': 2.0
            }, follow_redirects=True)

            plan = RoadmapPlan.query.filter_by(subject_id=sub.id).first()
            # Pick a pending item (e.g. Trees)
            item = [i for i in plan.items if not i.is_completed][0]
            item_id = item.id
            linked_topic_id = item.topic_id

        # 1. Toggle to completed
        res = self.client.post(f'/api/roadmap/toggle/{item_id}')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertTrue(data['is_completed'])
        self.assertEqual(data['status'], 'completed')
        self.assertGreaterEqual(data['completed_count'], 1)

        # Verify database records persist
        with self.app.app_context():
            db_item = db.session.get(RoadmapItem, item_id)
            self.assertTrue(db_item.is_completed)
            self.assertEqual(db_item.status, 'completed')
            self.assertIsNotNone(db_item.completed_at)

            # Check synchronized Topic in topics table
            if linked_topic_id:
                db_topic = db.session.get(Topic, linked_topic_id)
                self.assertTrue(db_topic.is_completed)
                self.assertEqual(db_topic.status, 'completed')

        # 2. Reversibility: toggle back to pending
        res2 = self.client.post(f'/api/roadmap/toggle/{item_id}')
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertTrue(data2['success'])
        self.assertFalse(data2['is_completed'])
        self.assertEqual(data2['status'], 'pending')

        with self.app.app_context():
            db_item = db.session.get(RoadmapItem, item_id)
            self.assertFalse(db_item.is_completed)
            self.assertEqual(db_item.status, 'pending')

            if linked_topic_id:
                db_topic = db.session.get(Topic, linked_topic_id)
                self.assertFalse(db_topic.is_completed)
                self.assertEqual(db_topic.status, 'pending')

    def test_roadmap_item_status_transitions_and_details(self):
        """Test status transitions (pending -> in_progress -> completed) and details endpoint"""
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        with self.app.app_context():
            sub = Subject.query.filter_by(user_id=self.student_id).first()
            exam_target = date.today() + timedelta(days=10)
            self.client.post('/roadmap/generate', data={
                'subject_id': sub.id,
                'exam_date': exam_target.isoformat(),
                'daily_hours': 2.0
            }, follow_redirects=True)
            plan = RoadmapPlan.query.filter_by(subject_id=sub.id).first()
            item = [i for i in plan.items if not i.is_completed][0]
            item_id = item.id

        # Test set in_progress
        res = self.client.post(f'/api/roadmap/item/{item_id}/status', json={'status': 'in_progress'})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['status'], 'in_progress')
        self.assertFalse(data['is_completed'])

        # Test get details
        details_res = self.client.get(f'/api/roadmap/item/{item_id}/details')
        self.assertEqual(details_res.status_code, 200)
        d_data = details_res.get_json()
        self.assertTrue(d_data['success'])
        self.assertEqual(d_data['item']['status'], 'in_progress')
        self.assertEqual(d_data['subject']['name'], sub.name)

        # Test direct topic status endpoint
        with self.app.app_context():
            db_item = db.session.get(RoadmapItem, item_id)
            topic_id = db_item.topic_id

        topic_res = self.client.post(f'/api/topic/status/{topic_id}', json={'status': 'completed'})
        self.assertEqual(topic_res.status_code, 200)
        self.assertTrue(topic_res.get_json()['is_completed'])

        # Verify roadmap item was synchronized
        with self.app.app_context():
            refreshed_item = db.session.get(RoadmapItem, item_id)
            self.assertTrue(refreshed_item.is_completed)
            self.assertEqual(refreshed_item.status, 'completed')

    def test_automatic_next_topic_calculation(self):
        """Test that next pending topic is returned after marking a topic completed"""
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        with self.app.app_context():
            sub = Subject.query.filter_by(user_id=self.student_id).first()
            # Add a couple more topics to ensure multiple pending items
            t3 = Topic(title='Graphs', is_completed=False, subject_id=sub.id)
            t4 = Topic(title='Dynamic Programming', is_completed=False, subject_id=sub.id)
            db.session.add_all([t3, t4])
            db.session.commit()

            exam_target = date.today() + timedelta(days=20)
            self.client.post('/roadmap/generate', data={
                'subject_id': sub.id,
                'exam_date': exam_target.isoformat(),
                'daily_hours': 2.0
            }, follow_redirects=True)
            plan = RoadmapPlan.query.filter_by(subject_id=sub.id).first()
            pending_items = [i for i in plan.items if not i.is_completed]
            first_pending = pending_items[0]
            expected_next = pending_items[1].topic_title

        # Complete first pending item
        res = self.client.post(f'/api/roadmap/toggle/{first_pending.id}')
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertIsNotNone(data['next_item'])
        self.assertEqual(data['next_item']['topic_title'], expected_next)

    def test_admin_panel_role_isolation(self):
        """Test admin role separation, protected routes, and distinct layout navigation"""
        # 1. Non-admin student cannot access admin routes (403 Forbidden)
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})
        admin_res = self.client.get('/admin/')
        self.assertEqual(admin_res.status_code, 403)

        user_mgmt_res = self.client.get('/admin/users')
        self.assertEqual(user_mgmt_res.status_code, 403)

        self.client.get('/logout')

        # 2. Admin login redirects to admin dashboard
        admin_login = self.client.post('/login', data={'identifier': 'test_admin', 'password': 'admin123'}, follow_redirects=False)
        self.assertEqual(admin_login.status_code, 302)
        self.assertIn('/admin/', admin_login.location)

        # 3. Admin accessing /dashboard redirects to /admin/ unless preview_student=1
        self.client.post('/login', data={'identifier': 'test_admin', 'password': 'admin123'})
        dash_res = self.client.get('/dashboard', follow_redirects=False)
        self.assertEqual(dash_res.status_code, 302)
        self.assertIn('/admin/', dash_res.location)

        # With preview_student=1 flag, admin can inspect student view
        preview_res = self.client.get('/dashboard?preview_student=1')
        self.assertEqual(preview_res.status_code, 200)

        # 4. In Admin panel layout, student navigation links are removed
        admin_panel_page = self.client.get('/admin/')
        self.assertEqual(admin_panel_page.status_code, 200)
        self.assertIn(b'EduMate Admin', admin_panel_page.data)
        self.assertIn(b'User Management', admin_panel_page.data)
        self.assertIn(b'System &amp; AI Status', admin_panel_page.data)
        # Verify student features are removed from admin sidebar
        self.assertNotIn(b'href="/timetable"', admin_panel_page.data)
        self.assertNotIn(b'href="/quizzes"', admin_panel_page.data)
        self.assertNotIn(b'href="/revision"', admin_panel_page.data)
        self.assertNotIn(b'href="/progress"', admin_panel_page.data)

    def test_public_landing_page_unauthenticated(self):
        """Test public landing page accessible at / without login and renders required content"""
        # Ensure client is unauthenticated
        self.client.get('/logout')
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)

        # 1. Headline and core copy
        self.assertIn(b'Plan Smarter. Study Better.', res.data)
        self.assertIn(b'Achieve More.', res.data)
        self.assertIn(b'EduMate helps students organize their syllabus', res.data)

        # 2. Six implemented features
        self.assertIn(b'Intelligent Syllabus Extractor', res.data)
        self.assertIn(b'Smart Study Roadmap', res.data)
        self.assertIn(b'AI Study Assistant', res.data)
        self.assertIn(b'Topic Completion Tracking', res.data)
        self.assertIn(b'Study Progress Monitoring', res.data)
        self.assertIn(b'Academic Organization', res.data)

        # 3. How It Works steps
        self.assertIn(b'Upload Syllabus PDF', res.data)
        self.assertIn(b'Review Extracted Units', res.data)
        self.assertIn(b'Generate Study Roadmap', res.data)
        self.assertIn(b'Study &amp; Track Progress', res.data)

        # 4. About EduMate / Academic purpose
        self.assertIn(b'Built Specifically for College &amp; University Students', res.data)
        self.assertIn(b'Curriculum Integrity', res.data)

        # 5. Auth buttons for unauthenticated visitors
        self.assertIn(b'href="/login"', res.data)
        self.assertIn(b'href="/register"', res.data)

        # 6. Does not expose private internal panels
        self.assertNotIn(b'User Management', res.data)
        self.assertNotIn(b'Audit Trail Logs', res.data)

    def test_landing_page_authenticated_student(self):
        """Test landing page shows student dashboard button when student is logged in"""
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)

        # Displays student dashboard button and logout
        self.assertIn(b'My Dashboard', res.data)
        self.assertIn(b'href="/dashboard"', res.data)
        self.assertIn(b'href="/logout"', res.data)

        # Does not show login / register buttons or admin dashboard
        self.assertNotIn(b'Admin Dashboard', res.data)

    def test_landing_page_authenticated_admin(self):
        """Test landing page shows admin dashboard button when admin is logged in"""
        self.client.post('/login', data={'identifier': 'test_admin', 'password': 'admin123'})
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)

        # Displays admin dashboard button and logout
        self.assertIn(b'Admin Dashboard', res.data)
        self.assertIn(b'href="/admin/"', res.data)
        self.assertIn(b'href="/logout"', res.data)

    def test_protected_routes_remain_secure_with_landing_page(self):
        """Ensure /dashboard and /admin/ remain protected from unauthenticated access"""
        self.client.get('/logout')

        # Dashboard requires login
        dash_res = self.client.get('/dashboard', follow_redirects=False)
        self.assertEqual(dash_res.status_code, 302)
        self.assertIn('/login', dash_res.location)

        # Admin panel requires login and admin privileges
        admin_res = self.client.get('/admin/', follow_redirects=False)
        self.assertEqual(admin_res.status_code, 302)
        self.assertIn('/login', admin_res.location)

    # ==========================================================================
    # TESTS: Registration Security, Role Enforcement & Admin Data Protection
    # ==========================================================================
    def test_registration_role_student_and_rejection_of_admin_tampering(self):
        """Test that new public registrations always receive 'student' role, even if tampered with role=admin"""
        self.client.get('/logout')

        # 1. Attempt to register with tampered form data specifying role='admin'
        res = self.client.post('/register', data={
            'username': 'tampered_student',
            'email': 'tampered@student.edu',
            'password': 'password123',
            'confirm_password': 'password123',
            'role': 'admin',
            'is_admin': 'true'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # 2. Verify user in database has strictly 'student' role and NOT admin
        with self.app.app_context():
            u = User.query.filter_by(username='tampered_student').first()
            self.assertIsNotNone(u)
            self.assertEqual(u.role, 'student')
            self.assertFalse(u.is_admin)

        # 3. Verify existing admin accounts remain intact and unaltered
        with self.app.app_context():
            admin_u = User.query.filter_by(username='test_admin').first()
            self.assertIsNotNone(admin_u)
            self.assertEqual(admin_u.role, 'admin')
            self.assertTrue(admin_u.is_admin)

    def test_registration_blocks_reserved_usernames_and_case_insensitive_collisions(self):
        """Test that public registration rejects reserved administrative usernames and case-insensitive duplicates"""
        self.client.get('/logout')

        # 1. Reserved admin username
        res_res = self.client.post('/register', data={
            'username': 'administrator',
            'email': 'admin_imposter@test.edu',
            'password': 'password123',
            'confirm_password': 'password123'
        }, follow_redirects=True)
        self.assertIn(b'reserved', res_res.data)

        # 2. Case-insensitive collision with existing student 'test_student'
        res_col = self.client.post('/register', data={
            'username': 'TEST_STUDENT',
            'email': 'new_email@test.edu',
            'password': 'password123',
            'confirm_password': 'password123'
        }, follow_redirects=True)
        self.assertIn(b'already taken', res_col.data)

        # 3. Model level validator rejects invalid roles
        with self.app.app_context():
            with self.assertRaises(ValueError):
                bad_user = User(username='bad_role_user', email='bad@test.com', role='superadmin')
                db.session.add(bad_user)
                db.session.commit()

    # ==========================================================================
    # TESTS: API Management Center & Multi-Provider Architecture
    # ==========================================================================
    def test_admin_only_api_management_routes_reject_student_and_guest(self):
        """Test that /admin/api-management routes are restricted strictly to administrators"""
        self.client.get('/logout')

        # 1. Unauthenticated guest
        guest_res = self.client.get('/admin/api-management', follow_redirects=False)
        self.assertEqual(guest_res.status_code, 302)
        self.assertIn('/login', guest_res.location)

        # 2. Authenticated student receives 403 Forbidden
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})
        student_get = self.client.get('/admin/api-management')
        self.assertEqual(student_get.status_code, 403)

        student_post_save = self.client.post('/admin/api-management/save/groq', data={'model_name': 'test'})
        self.assertEqual(student_post_save.status_code, 403)

        student_post_test = self.client.post('/admin/api-management/test/groq')
        self.assertEqual(student_post_test.status_code, 403)

    def test_api_management_page_renders_clean_light_theme_with_masked_keys(self):
        """Test admin API Management dashboard rendering, provider list, and masked key presentation"""
        self.client.post('/login', data={'identifier': 'test_admin', 'password': 'admin123'})
        res = self.client.get('/admin/api-management')
        self.assertEqual(res.status_code, 200)

        # Displays all three supported providers
        self.assertIn(b'Google Gemini', res.data)
        self.assertIn(b'Groq API', res.data)
        self.assertIn(b'Ollama (Local AI)', res.data)

        # Verifies encryption badge
        self.assertIn(b'AES-256 Storage: Enabled', res.data)

        # Never exposes raw secret keys in HTML
        self.assertNotIn(b'secret_unmasked_api_key', res.data)

    def test_api_key_secure_storage_encryption_and_masking(self):
        """Test Fernet encryption at rest, masked display, and non-destructive empty form updates"""
        with self.app.app_context():
            from models import AIProviderConfig
            groq_cfg = AIProviderConfig.query.filter_by(provider_id='groq').first()
            self.assertIsNotNone(groq_cfg)

            # 1. Set key and verify encrypted at rest
            raw_key = 'gsk_test1234567890abcdef1234567890'
            groq_cfg.set_api_key(raw_key)
            db.session.commit()

            # Encrypted text in DB starts with Fernet header 'gAAAAA'
            self.assertTrue(groq_cfg.api_key_encrypted.startswith('gAAAAA'))
            self.assertNotIn(raw_key, groq_cfg.api_key_encrypted)

            # Decryption returns original key
            self.assertEqual(groq_cfg.get_api_key(), raw_key)

            # Masked key shows prefix, bullets, and suffix
            masked = groq_cfg.get_masked_key()
            self.assertTrue(masked.startswith('gsk_'))
            self.assertTrue(masked.endswith('7890'))
            self.assertIn('••••••••', masked)

            # Safe dict excludes raw and encrypted keys
            safe_d = groq_cfg.to_safe_dict()
            self.assertIn('masked_key', safe_d)
            self.assertNotIn('api_key_encrypted', safe_d)

        # 2. Submit update via admin without changing key (blank field)
        self.client.post('/login', data={'identifier': 'test_admin', 'password': 'admin123'})
        save_res = self.client.post('/admin/api-management/save/groq', data={
            'is_enabled': 'true',
            'model_name': 'llama-3.3-70b-versatile',
            'priority': 2,
            'api_key': ''  # Empty input must NOT overwrite existing key
        }, follow_redirects=True)
        self.assertEqual(save_res.status_code, 200)

        with self.app.app_context():
            groq_cfg = AIProviderConfig.query.filter_by(provider_id='groq').first()
            self.assertEqual(groq_cfg.get_api_key(), raw_key)

    def test_providers_independent_enable_disable_and_simultaneous_enabled(self):
        """Test enabling and disabling each provider independently and allowing multiple enabled providers"""
        self.client.post('/login', data={'identifier': 'test_admin', 'password': 'admin123'})

        # 1. Enable Groq while Gemini and Ollama remain enabled
        self.client.post('/admin/api-management/save/groq', data={
            'is_enabled': 'true',
            'model_name': 'llama-3.3-70b-versatile',
            'priority': 2
        })
        self.client.post('/admin/api-management/save/gemini', data={
            'is_enabled': 'true',
            'model_name': 'gemini-3.5-flash',
            'priority': 1
        })
        self.client.post('/admin/api-management/save/ollama', data={
            'is_enabled': 'true',
            'model_name': 'gemma3:1b',
            'priority': 3
        })

        with self.app.app_context():
            from models import AIProviderConfig
            cfgs = {c.provider_id: c.is_enabled for c in AIProviderConfig.query.all()}
            self.assertTrue(cfgs['gemini'])
            self.assertTrue(cfgs['groq'])
            self.assertTrue(cfgs['ollama'])

        # 2. Disable Gemini independently
        self.client.post('/admin/api-management/save/gemini', data={
            'model_name': 'gemini-3.5-flash',
            'priority': 1
            # is_enabled omitted -> False
        })

        with self.app.app_context():
            from models import AIProviderConfig
            cfgs = {c.provider_id: c.is_enabled for c in AIProviderConfig.query.all()}
            self.assertFalse(cfgs['gemini'])
            self.assertTrue(cfgs['groq'])  # Groq remains enabled!
            self.assertTrue(cfgs['ollama'])

    def test_multi_provider_priority_and_sequential_fallback(self):
        """Test automatic fallback from Primary (Gemini) to Groq when Gemini encounters a provider error"""
        from ai_service import HybridAIService
        service = HybridAIService(
            gemini_api_key="mock_gemini_key",
            groq_api_key="mock_groq_key"
        )
        service.gemini_enabled = True
        service.gemini_priority = 1
        service.groq_enabled = True
        service.groq_priority = 2
        service.ollama_enabled = False

        # Mock: Gemini fails (503), Groq succeeds
        with patch.object(service, '_call_gemini') as mock_gemini:
            mock_gemini.side_effect = Exception("Gemini server unavailable 503")
            with patch.object(service, '_call_groq') as mock_groq:
                mock_groq.return_value = "Groq response: Arrays are contiguous memory blocks."

                res = service.generate_response("Explain arrays")
                self.assertTrue(res['success'])
                self.assertEqual(res['provider'], 'groq')
                self.assertEqual(res['provider_name'], 'Groq API')
                self.assertTrue(res['fallback_used'])
                self.assertIn("Arrays are contiguous", res['response'])
                self.assertIn("503", res['gemini_error'])

    def test_disabled_providers_skipped_completely(self):
        """Test that disabled providers are completely skipped and never receive network requests"""
        from ai_service import HybridAIService
        service = HybridAIService(
            gemini_api_key="mock_gemini_key",
            groq_api_key="mock_groq_key"
        )
        service.gemini_enabled = False  # Gemini disabled
        service.groq_enabled = True     # Groq enabled (Primary)
        service.groq_priority = 1
        service.ollama_enabled = False

        with patch.object(service, '_call_gemini') as mock_gemini:
            with patch.object(service, '_call_groq') as mock_groq:
                mock_groq.return_value = "Groq direct response."

                res = service.generate_response("Hello")
                self.assertTrue(res['success'])
                self.assertEqual(res['provider'], 'groq')
                self.assertFalse(res['fallback_used'])
                # Gemini must never have been called
                mock_gemini.assert_not_called()
                mock_groq.assert_called_once()

    def test_groq_request_construction_and_response_parsing(self):
        """Test Groq API request formatting, headers, payload, and JSON response parsing"""
        from ai_service import HybridAIService
        service = HybridAIService(
            groq_api_key="gsk_valid_mock_key",
            groq_model="llama-3.3-70b-versatile"
        )

        with patch('requests.post') as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "A binary search tree has ordered left and right subtrees."
                    }
                }]
            }
            mock_post.return_value = mock_resp

            output = service._call_groq(
                prompt="Explain BST",
                system_instruction="Be concise."
            )
            self.assertIn("binary search tree", output)

            # Verify request headers and URL
            called_url = mock_post.call_args[0][0]
            self.assertEqual(called_url, "https://api.groq.com/openai/v1/chat/completions")
            called_headers = mock_post.call_args[1]['headers']
            self.assertEqual(called_headers['Authorization'], "Bearer gsk_valid_mock_key")
            called_json = mock_post.call_args[1]['json']
            self.assertEqual(called_json['model'], "llama-3.3-70b-versatile")
            self.assertEqual(len(called_json['messages']), 2)
            self.assertEqual(called_json['messages'][0]['role'], "system")
            self.assertEqual(called_json['messages'][1]['role'], "user")

    def test_groq_error_handling_invalid_key_and_rate_limit(self):
        """Test Groq error classification for invalid API key (401) and rate limits (429)"""
        from ai_service import HybridAIService, AIServiceException
        service = HybridAIService(groq_api_key="gsk_invalid_mock_key")

        with patch('requests.post') as mock_post:
            # 1. Test 401 Unauthorized
            mock_resp_401 = MagicMock()
            mock_resp_401.status_code = 401
            mock_resp_401.text = '{"error": {"message": "Invalid API Key"}}'
            mock_post.return_value = mock_resp_401

            with self.assertRaises(AIServiceException) as ctx_401:
                service._call_groq("Hello")
            self.assertIn("401 Unauthorized", str(ctx_401.exception))
            # Verify no secret key is in the exception
            self.assertNotIn("gsk_invalid_mock_key", str(ctx_401.exception))

            # 2. Test 429 Rate Limit
            mock_resp_429 = MagicMock()
            mock_resp_429.status_code = 429
            mock_resp_429.text = '{"error": {"message": "Rate limit reached"}}'
            mock_post.return_value = mock_resp_429

            with self.assertRaises(AIServiceException) as ctx_429:
                service._call_groq("Hello")
            self.assertIn("429 Rate Limit", str(ctx_429.exception))

    def test_admin_api_connection_test_endpoint(self):
        """Test the AJAX connection test endpoint for providers"""
        self.client.post('/login', data={'identifier': 'test_admin', 'password': 'admin123'})

        with patch('ai_service.HybridAIService.test_provider_connection') as mock_test:
            mock_test.return_value = {
                'success': True,
                'status': 'active',
                'message': "Connected successfully to Groq model 'llama-3.3-70b-versatile'."
            }

            res = self.client.post('/admin/api-management/test/groq')
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data['success'])
            self.assertEqual(data['status'], 'active')
            self.assertIn("Connected successfully", data['message'])

            # Verify audit log recorded action
            with self.app.app_context():
                log = AuditLog.query.filter_by(action='API_CONNECTION_TEST').first()
                self.assertIsNotNone(log)
                self.assertEqual(log.target_type, 'ai_provider')

    def test_ai_study_assistant_features_work_with_groq(self):
        """Test existing AI Study Assistant features function seamlessly when powered by Groq"""
        from ai_service import ai_service

        with patch.object(ai_service, 'generate_response') as mock_gen:
            mock_gen.return_value = {
                'success': True,
                'provider': 'groq',
                'provider_name': 'Groq API',
                'model': 'llama-3.3-70b-versatile',
                'fallback_used': False,
                'response': "### Stacks\nA Stack is a LIFO linear data structure."
            }

            res = ai_service.generate_academic_content(
                content_type="notes",
                topic_name="Stacks & Queues",
                unit_name="Unit 1",
                subject_name="Data Structures"
            )
            self.assertTrue(res['success'])
            self.assertEqual(res['provider'], 'groq')
            self.assertIn("A Stack is a LIFO", res['content'])


    def test_ai_assistant_dedicated_view_and_chat_persistence(self):
        """Test Phase 1: Dedicated AI Assistant page, authentication, chat persistence and clearing"""
        # Unauthenticated access redirects to login
        res_anon = self.client.get('/ai-assistant')
        self.assertEqual(res_anon.status_code, 302)
        self.assertIn('/login', res_anon.headers['Location'])

        # Authenticated student access succeeds
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})
        res_auth = self.client.get('/ai-assistant')
        self.assertEqual(res_auth.status_code, 200)
        self.assertIn(b'AI Study Assistant', res_auth.data)
        self.assertIn(b'Explain Topic', res_auth.data)
        self.assertIn(b'Generate Short Notes', res_auth.data)

        # Test user and assistant message persistence
        with patch('ai_service.ai_service.chat_study_assistant') as mock_chat:
            mock_chat.return_value = {
                'success': True,
                'reply': 'A binary search tree maintains sorted order.',
                'provider': 'gemini',
                'model': 'gemini-3.5-flash',
                'fallback_used': False,
                'source_pages': 'Page 10'
            }

            chat_res = self.client.post('/api/ai/chat', json={
                'message': 'What is a binary search tree?',
                'subject_id': self.subject_id
            })
            self.assertEqual(chat_res.status_code, 200)
            chat_data = chat_res.get_json()
            self.assertTrue(chat_data['online'])
            self.assertEqual(chat_data['provider'], 'gemini')

        # Check history contains both user and assistant roles
        hist_res = self.client.get('/api/ai/chat/history')
        self.assertEqual(hist_res.status_code, 200)
        hist_data = hist_res.get_json()
        self.assertTrue(hist_data['success'])
        roles = [m['role'] for m in hist_data['messages']]
        self.assertIn('user', roles)
        self.assertIn('assistant', roles)

        # Test clear chat endpoint
        clear_res = self.client.post('/api/ai/chat/clear')
        self.assertEqual(clear_res.status_code, 200)
        self.assertTrue(clear_res.get_json()['success'])

        # Verify chat history is now empty
        hist_res_after = self.client.get('/api/ai/chat/history')
        self.assertEqual(len(hist_res_after.get_json()['messages']), 0)

    def test_ai_assistant_markdown_refresh_persistence_and_zero_api_usage(self):
        """Test that page refresh and history retrieval:
        1. Never call AI APIs (zero API consumption on refresh)
        2. Deliver raw Markdown in clean <textarea class='raw-markdown-source'> containers
        3. History endpoint returns raw uncorrupted Markdown
        """
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        sample_markdown = (
            "# Merge Sort Algorithm\n\n"
            "Merge sort is an efficient, comparison-based divide-and-conquer algorithm.\n\n"
            "### Steps\n"
            "1. **Divide**: Find midpoint.\n"
            "2. **Conquer**: Recursively sort.\n"
            "3. **Combine**: Merge subarrays.\n\n"
            "```python\n"
            "def merge_sort(arr):\n"
            "    if len(arr) <= 1: return arr\n"
            "    mid = len(arr) // 2\n"
            "    left = merge_sort(arr[:mid])\n"
            "    right = merge_sort(arr[mid:])\n"
            "    return merge(left, right)\n"
            "```\n\n"
            "| Case | Complexity |\n"
            "|---|---|\n"
            "| Best | O(n log n) |\n"
            "| Worst | O(n log n) |\n\n"
            "> Example:\n"
            "Input: [38, 27, 43, 3, 9, 82, 10]\n"
            "Sorted: [3, 9, 10, 27, 38, 43, 82]\n"
        )

        with patch('ai_service.ai_service.chat_study_assistant') as mock_ai:
            mock_ai.return_value = {
                'success': True,
                'reply': sample_markdown,
                'provider': 'groq',
                'model': 'llama-3.3-70b-versatile',
                'fallback_used': False,
                'source_pages': None
            }

            post_res = self.client.post('/api/ai/chat', json={
                'message': 'Explain merge sort with example',
                'subject_id': self.subject_id
            })
            self.assertEqual(post_res.status_code, 200)
            mock_ai.assert_called_once()

        # Step 2: Test page refresh (GET /ai-assistant) MUST NOT call AI service
        with patch('ai_service.ai_service.chat_study_assistant') as mock_ai_refresh:
            refresh_res = self.client.get('/ai-assistant')
            self.assertEqual(refresh_res.status_code, 200)
            # ZERO API consumption on refresh
            mock_ai_refresh.assert_not_called()
            # Contains safe raw markdown container
            self.assertIn(b'class="raw-markdown-source"', refresh_res.data)
            self.assertIn(b'# Merge Sort Algorithm', refresh_res.data)
            self.assertIn(b'class="markdown-rendered-body"', refresh_res.data)

        # Step 3: Test history API MUST NOT call AI service
        with patch('ai_service.ai_service.chat_study_assistant') as mock_ai_hist:
            hist_res = self.client.get('/api/ai/chat/history')
            self.assertEqual(hist_res.status_code, 200)
            mock_ai_hist.assert_not_called()
            hist_data = hist_res.get_json()
            self.assertTrue(hist_data['success'])
            self.assertGreaterEqual(len(hist_data['messages']), 2)
            assistant_msg = [m for m in hist_data['messages'] if m['role'] == 'assistant'][-1]
            self.assertEqual(assistant_msg['content'], sample_markdown)

    def test_quiz_runner_step_by_step_and_full_subject_scoring(self):
        """Test Phase 2: Full-subject quiz generation, scoring with unanswered questions, and accuracy"""
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        # Test full-subject MCQ generation
        with patch('ai_service.ai_service.generate_academic_content') as mock_gen:
            mock_gen.return_value = {
                'success': True,
                'content_type': 'mcq',
                'topic': 'Comprehensive Assessment',
                'questions': [
                    {'question': 'Q1', 'options': ['A', 'B'], 'correct_answer': 0, 'explanation': 'Exp 1'},
                    {'question': 'Q2', 'options': ['A', 'B'], 'correct_answer': 1, 'explanation': 'Exp 2'},
                    {'question': 'Q3', 'options': ['A', 'B'], 'correct_answer': 0, 'explanation': 'Exp 3'},
                    {'question': 'Q4', 'options': ['A', 'B'], 'correct_answer': 1, 'explanation': 'Exp 4'},
                    {'question': 'Q5', 'options': ['A', 'B'], 'correct_answer': 0, 'explanation': 'Exp 5'}
                ]
            }

            gen_res = self.client.post('/api/ai/academic-content', json={
                'subject_id': self.subject_id,
                'topic_id': 'all',
                'content_type': 'mcq'
            })
            self.assertEqual(gen_res.status_code, 200)
            gen_data = gen_res.get_json()
            self.assertTrue(gen_data['success'])
            self.assertEqual(len(gen_data['questions']), 5)

        # Test scoring with mixed answers (2 correct, 1 incorrect, 2 unanswered)
        mock_questions = [
            {'question': 'Q1', 'options': ['A', 'B'], 'correct_answer': 0, 'explanation': 'Exp 1'},
            {'question': 'Q2', 'options': ['A', 'B'], 'correct_answer': 1, 'explanation': 'Exp 2'},
            {'question': 'Q3', 'options': ['A', 'B'], 'correct_answer': 0, 'explanation': 'Exp 3'},
            {'question': 'Q4', 'options': ['A', 'B'], 'correct_answer': 1, 'explanation': 'Exp 4'},
            {'question': 'Q5', 'options': ['A', 'B'], 'correct_answer': 0, 'explanation': 'Exp 5'}
        ]
        # Q1: 0 (correct), Q2: 1 (correct), Q3: 1 (incorrect), Q4: null (unanswered), Q5: null (unanswered)
        submitted_answers = [0, 1, 1, None, None]

        submit_res = self.client.post('/api/quiz/submit', json={
            'subject_id': self.subject_id,
            'topic_id': None,
            'title': 'Test Comprehensive Drill',
            'questions': mock_questions,
            'answers': submitted_answers
        })
        self.assertEqual(submit_res.status_code, 200)
        s_data = submit_res.get_json()
        self.assertTrue(s_data['success'])
        self.assertEqual(s_data['score'], 2)
        self.assertEqual(s_data['total_questions'], 5)
        self.assertEqual(s_data['correct_count'], 2)
        self.assertEqual(s_data['incorrect_count'], 1)
        self.assertEqual(s_data['unanswered_count'], 2)
        self.assertEqual(s_data['accuracy_percentage'], 40)
        self.assertEqual(s_data['percentage'], 40)

    def test_roadmap_option_a_syllabus_topic_selection(self):
        """Test Phase 3: Subject syllabus endpoint and generating roadmap from selected topic checkboxes"""
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        # 1. Test /api/subjects/<id>/syllabus
        syl_res = self.client.get(f'/api/subjects/{self.subject_id}/syllabus')
        self.assertEqual(syl_res.status_code, 200)
        syl_data = syl_res.get_json()
        self.assertTrue(syl_data['success'])
        self.assertEqual(syl_data['subject']['id'], self.subject_id)
        self.assertGreaterEqual(len(syl_data['subject']['units']), 1)

        # Get existing topic IDs
        all_topic_ids = []
        for unit in syl_data['subject']['units']:
            for t in unit['topics']:
                all_topic_ids.append(t['id'])
        self.assertGreaterEqual(len(all_topic_ids), 2)

        # Select only the first topic
        selected_ids = [all_topic_ids[0]]

        with self.app.app_context():
            initial_topics_count = Topic.query.filter_by(subject_id=self.subject_id).count()
            initial_subjects_count = Subject.query.filter_by(user_id=self.student_id).count()

        exam_date_val = (date.today() + timedelta(days=15)).isoformat()
        res_gen = self.client.post('/roadmap/generate', data={
            'subject_id': self.subject_id,
            'exam_date': exam_date_val,
            'daily_hours': 2.0,
            'topic_ids': selected_ids
        }, follow_redirects=True)
        self.assertEqual(res_gen.status_code, 200)

        with self.app.app_context():
            # Verify strict database rules: zero duplicate topics, zero duplicate subjects
            final_topics_count = Topic.query.filter_by(subject_id=self.subject_id).count()
            final_subjects_count = Subject.query.filter_by(user_id=self.student_id).count()
            self.assertEqual(final_topics_count, initial_topics_count)
            self.assertEqual(final_subjects_count, initial_subjects_count)

            # Verify roadmap item is linked directly to topic_id
            plan = RoadmapPlan.query.filter_by(subject_id=self.subject_id).first()
            self.assertIsNotNone(plan)
            study_items = [it for it in plan.items if not it.is_revision]
            self.assertEqual(len(study_items), 1)
            self.assertEqual(study_items[0].topic_id, selected_ids[0])

    def test_demo_credentials_removed_from_login_page(self):
        """Test Phase 1: Verify demo accounts and credentials are removed from login and public pages"""
        res = self.client.get('/login')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Hardcoded demo credentials and callout cards must NOT exist
        self.assertNotIn('student@edumate.local', html)
        self.assertNotIn('student123', html)
        self.assertNotIn('Evaluation / Viva Test Accounts', html)
        self.assertNotIn('demo-credentials-callout', html)

        # Polished light theme elements must exist
        self.assertIn('auth-card', html)
        self.assertIn('auth-logo-badge', html)
        self.assertIn('auth-input', html)
        self.assertIn('name="remember"', html)
        self.assertIn('togglePasswordVisibility', html)
        self.assertIn('openForgotModal', html)

    def test_login_username_and_email_and_remember_me(self):
        """Test Phase 2: Login via username, email, and session persistence via remember me"""
        # 1. Login with username
        res1 = self.client.post('/login', data={
            'identifier': 'test_student',
            'password': 'pass123'
        }, follow_redirects=True)
        self.assertEqual(res1.status_code, 200)
        self.assertIn('/dashboard', res1.request.path)

        # Logout
        self.client.get('/logout', follow_redirects=True)

        # 2. Login with email
        res2 = self.client.post('/login', data={
            'identifier': 'student@test.com',
            'password': 'pass123'
        }, follow_redirects=True)
        self.assertEqual(res2.status_code, 200)
        self.assertIn('/dashboard', res2.request.path)

        # Logout
        self.client.get('/logout', follow_redirects=True)

        # 3. Test Remember Me session persistence
        with self.client:
            res3 = self.client.post('/login', data={
                'identifier': 'test_student',
                'password': 'pass123',
                'remember': '1'
            }, follow_redirects=True)
            self.assertEqual(res3.status_code, 200)
            from flask import session
            self.assertTrue(session.permanent)

    def test_enhanced_registration_validation_and_profile_creation(self):
        """Test Phase 3: Registration with personal + academic details, validation, and profile creation"""
        # Successful registration with all fields
        res = self.client.post('/register', data={
            'username': 'raj_kumar',
            'email': 'raj@college.edu',
            'password': 'mypassword123',
            'confirm_password': 'mypassword123',
            'full_name': 'Raj Kumar',
            'phone_number': '9876543210',
            'college_name': 'IIT Delhi',
            'university_name': 'IIT',
            'degree_course': 'B.Tech',
            'branch_department': 'Computer Science',
            'current_semester': 'Semester 4',
            'academic_session': '2024-2028',
            'roll_number': '24CS0101'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn('/login', res.request.path)

        with self.app.app_context():
            new_user = User.query.filter_by(username='raj_kumar').first()
            self.assertIsNotNone(new_user)
            self.assertEqual(new_user.role, 'student')
            self.assertIsNotNone(new_user.profile)
            self.assertEqual(new_user.profile.full_name, 'Raj Kumar')
            self.assertEqual(new_user.profile.phone_number, '9876543210')
            self.assertEqual(new_user.profile.college_name, 'IIT Delhi')
            self.assertEqual(new_user.profile.university_name, 'IIT')
            self.assertEqual(new_user.profile.degree_course, 'B.Tech')
            self.assertEqual(new_user.profile.branch_department, 'Computer Science')
            self.assertEqual(new_user.profile.current_semester, 'Semester 4')
            self.assertEqual(new_user.profile.roll_number, '24CS0101')
            self.assertGreater(new_user.profile.completion_percentage, 50)

        # Validation failure: Password mismatch
        res_pw_mismatch = self.client.post('/register', data={
            'username': 'student_mismatch',
            'email': 'mismatch@test.com',
            'password': 'password1',
            'confirm_password': 'password2'
        }, follow_redirects=True)
        self.assertIn('Passwords do not match', res_pw_mismatch.get_data(as_text=True))

        # Validation failure: Password too short
        res_pw_short = self.client.post('/register', data={
            'username': 'student_short',
            'email': 'short@test.com',
            'password': '123',
            'confirm_password': '123'
        }, follow_redirects=True)
        self.assertIn('at least 6 characters', res_pw_short.get_data(as_text=True))

        # Validation failure: Invalid email format
        res_bad_email = self.client.post('/register', data={
            'username': 'student_bademail',
            'email': 'not-an-email',
            'password': 'validpassword123',
            'confirm_password': 'validpassword123'
        }, follow_redirects=True)
        self.assertIn('valid email address', res_bad_email.get_data(as_text=True))

    def test_registration_duplicate_username_and_email_rejection(self):
        """Test Phase 3: Case-insensitive duplicate username and email rejection"""
        # Duplicate username (case-insensitive)
        res1 = self.client.post('/register', data={
            'username': 'TEST_STUDENT',
            'email': 'unique1@test.com',
            'password': 'password123',
            'confirm_password': 'password123'
        }, follow_redirects=True)
        self.assertIn('Username is already taken', res1.get_data(as_text=True))

        # Duplicate email (case-insensitive)
        res2 = self.client.post('/register', data={
            'username': 'unique_user',
            'email': 'STUDENT@TEST.COM',
            'password': 'password123',
            'confirm_password': 'password123'
        }, follow_redirects=True)
        self.assertIn('Email is already registered', res2.get_data(as_text=True))

    def test_profile_view_and_update(self):
        """Test Phase 4: Student Profile GET view, completion calculation, and POST update"""
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        # GET Profile View
        res_get = self.client.get('/profile')
        self.assertEqual(res_get.status_code, 200)
        html = res_get.get_data(as_text=True)
        self.assertIn('Student Profile', html)
        self.assertIn('test_student', html)
        self.assertIn('Profile Completion', html)

        # POST Profile Update
        res_post = self.client.post('/profile', data={
            'full_name': 'Test Student FullName',
            'username': 'test_student',
            'email': 'student@test.com',
            'phone_number': '+91 9999988888',
            'college_name': 'National Institute of Tech',
            'university_name': 'NIT',
            'degree_course': 'B.Tech',
            'branch_department': 'Information Technology',
            'current_semester': 'Semester 6',
            'academic_session': '2023-2027',
            'roll_number': 'NIT-IT-042',
            'daily_study_hours': '4.5',
            'preferred_study_time': 'Morning',
            'preferred_language': 'Hindi',
            'target_exam': 'GATE CS 2026'
        }, follow_redirects=True)
        self.assertEqual(res_post.status_code, 200)

        with self.app.app_context():
            u = db.session.get(User, self.student_id)
            self.assertEqual(u.profile.full_name, 'Test Student FullName')
            self.assertEqual(u.profile.phone_number, '+91 9999988888')
            self.assertEqual(u.profile.college_name, 'National Institute of Tech')
            self.assertEqual(u.profile.daily_study_hours, 4.5)
            self.assertEqual(u.profile.preferred_study_time, 'Morning')
            self.assertEqual(u.profile.preferred_language, 'Hindi')
            self.assertEqual(u.profile.target_exam, 'GATE CS 2026')
            self.assertEqual(u.display_name, 'Test Student FullName')
            self.assertGreaterEqual(u.profile.completion_percentage, 90)

    def test_profile_photo_validation(self):
        """Test Phase 4: Profile photo extension and size validation"""
        import io
        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        # 1. Invalid file extension (.sh)
        invalid_file = (io.BytesIO(b'#!/bin/bash\necho hack'), 'exploit.sh')
        res_invalid = self.client.post('/profile', data={
            'full_name': 'Student User',
            'username': 'test_student',
            'email': 'student@test.com',
            'avatar': invalid_file
        }, content_type='multipart/form-data', follow_redirects=True)
        self.assertIn('Invalid photo format', res_invalid.get_data(as_text=True))

        with self.app.app_context():
            u = db.session.get(User, self.student_id)
            self.assertIsNone(u.profile.avatar_url)

        # 2. Oversized image (> 2MB)
        large_image_data = b'x' * (2 * 1024 * 1024 + 100)
        large_file = (io.BytesIO(large_image_data), 'large_avatar.png')
        res_large = self.client.post('/profile', data={
            'full_name': 'Student User',
            'username': 'test_student',
            'email': 'student@test.com',
            'avatar': large_file
        }, content_type='multipart/form-data', follow_redirects=True)
        self.assertIn('Profile photo exceeds 2 MB limit', res_large.get_data(as_text=True))

        # 3. Valid PNG upload
        valid_png = (io.BytesIO(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4'), 'my_photo.png')
        res_valid = self.client.post('/profile', data={
            'full_name': 'Student User',
            'username': 'test_student',
            'email': 'student@test.com',
            'avatar': valid_png
        }, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(res_valid.status_code, 200)

        with self.app.app_context():
            u = db.session.get(User, self.student_id)
            self.assertIsNotNone(u.profile.avatar_url)
            self.assertTrue(u.profile.avatar_url.startswith('/static/uploads/avatars/avatar_u'))
            self.assertTrue(u.profile.avatar_url.endswith('.png'))

    def test_profile_authorization_isolation(self):
        """Test Phase 4: Students cannot view/edit other students' profiles (403), admins can view/edit"""
        # Login as other_student
        self.client.post('/login', data={'identifier': 'other_student', 'password': 'pass123'})

        # Attempt to view primary student's profile -> 403 Forbidden
        res_view = self.client.get(f'/profile?user_id={self.student_id}')
        self.assertEqual(res_view.status_code, 403)

        # Attempt to edit primary student's profile -> 403 Forbidden
        res_edit = self.client.post(f'/profile?user_id={self.student_id}', data={
            'full_name': 'Hacked Name',
            'username': 'hacked_name',
            'email': 'hacked@test.com'
        })
        self.assertEqual(res_edit.status_code, 403)

        # Logout other_student
        self.client.get('/logout')

        # Login as Admin
        self.client.post('/login', data={'identifier': 'test_admin', 'password': 'admin123'})

        # Admin CAN view student's profile
        res_admin_view = self.client.get(f'/profile?user_id={self.student_id}')
        self.assertEqual(res_admin_view.status_code, 200)
        self.assertIn('Student Profile', res_admin_view.get_data(as_text=True))

        # Admin CAN edit student's profile
        res_admin_edit = self.client.post(f'/profile?user_id={self.student_id}', data={
            'full_name': 'Admin Verified Student',
            'username': 'test_student',
            'email': 'student@test.com'
        }, follow_redirects=True)
        self.assertEqual(res_admin_edit.status_code, 200)

        with self.app.app_context():
            u = db.session.get(User, self.student_id)
            self.assertEqual(u.profile.full_name, 'Admin Verified Student')

    def test_profile_preferences_used_in_greeting_and_ai_chat(self):
        """Test Phase 5: Dashboard greeting uses student full_name; AI chat passes preferred_language"""
        with self.app.app_context():
            u = db.session.get(User, self.student_id)
            prof = u.get_or_create_profile()
            prof.full_name = 'Aditi Sharma'
            prof.preferred_language = 'Hinglish'
            db.session.commit()

        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        # 1. Dashboard greeting test
        res_dash = self.client.get('/dashboard')
        self.assertEqual(res_dash.status_code, 200)
        html = res_dash.get_data(as_text=True)
        self.assertIn('Aditi Sharma', html)
        self.assertTrue('Good morning' in html or 'Good afternoon' in html or 'Good evening' in html)

        # 2. AI chat language preference test
        with patch('ai_service.ai_service.chat_study_assistant') as mock_ai:
            mock_ai.return_value = {
                'reply': 'Yeh topic bahut aasan hai!',
                'provider': 'mock',
                'model': 'mock-model'
            }
            res_chat = self.client.post('/api/ai/chat', json={
                'message': 'Explain binary search trees'
            })
            self.assertEqual(res_chat.status_code, 200)
            mock_ai.assert_called_once()
            call_kwargs = mock_ai.call_args[1]
            # Context passed to AI must contain student's preferred language
            selected_ctx = call_kwargs.get('selected_context', {})
            self.assertEqual(selected_ctx.get('preferred_language'), 'Hinglish')

    def test_roadmap_defaults_from_profile(self):
        """Test Phase 5: Roadmap generator uses student's target exam and daily study hours from profile"""
        with self.app.app_context():
            u = db.session.get(User, self.student_id)
            prof = u.get_or_create_profile()
            prof.daily_study_hours = 3.5
            prof.target_exam = 'Semester Finals'
            db.session.commit()

        self.client.post('/login', data={'identifier': 'test_student', 'password': 'pass123'})

        # GET /roadmap: Check input default and placeholder
        res_roadmap = self.client.get('/roadmap')
        self.assertEqual(res_roadmap.status_code, 200)
        html = res_roadmap.get_data(as_text=True)
        self.assertIn('value="3.5"', html)
        self.assertIn('Semester Finals Prep Roadmap', html)

        # POST /roadmap/generate without daily_hours specified: defaults to 3.5
        exam_date_val = (date.today() + timedelta(days=20)).isoformat()
        res_gen = self.client.post('/roadmap/generate', data={
            'subject_id': self.subject_id,
            'exam_date': exam_date_val
            # daily_hours omitted intentionally
        }, follow_redirects=True)
        self.assertEqual(res_gen.status_code, 200)

        with self.app.app_context():
            plan = RoadmapPlan.query.filter_by(subject_id=self.subject_id).first()
            self.assertIsNotNone(plan)
            self.assertEqual(plan.daily_study_hours, 3.5)

    def test_cleanup_verified_demo_accounts(self):
        """Test Phase 1: Explicit safe demo account cleanup leaves legitimate accounts untouched"""
        with self.app.app_context():
            # Create verified demo accounts
            demo_stud = User(username='demo_student', email='student@edumate.local', role='student')
            demo_stud.set_password('demo123')
            demo_adm = User(username='demo_admin', email='admin@edumate.local', role='admin')
            demo_adm.set_password('demo123')

            # Create legitimate user with similar name
            legit = User(username='demo_fan', email='demo_fan@gmail.com', role='student')
            legit.set_password('pass123')

            db.session.add_all([demo_stud, demo_adm, legit])
            db.session.commit()

            # Execute safe cleanup
            result = cleanup_verified_demo_accounts()
            self.assertEqual(result['count'], 2)
            deleted_usernames = [d['username'] for d in result['deleted']]
            self.assertIn('demo_student', deleted_usernames)
            self.assertIn('demo_admin', deleted_usernames)

            # Verified demo users must be deleted
            self.assertIsNone(User.query.filter_by(username='demo_student').first())
            self.assertIsNone(User.query.filter_by(username='demo_admin').first())

            # Legitimate users must be completely untouched
            self.assertIsNotNone(User.query.filter_by(username='demo_fan').first())
            self.assertIsNotNone(db.session.get(User, self.student_id))
            self.assertIsNotNone(db.session.get(User, self.admin_id))

        # Test admin route for demo cleanup (when no demo accounts remain)
        self.client.post('/login', data={'identifier': 'test_admin', 'password': 'admin123'})
        res = self.client.post('/admin/system/cleanup-demo-accounts', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn('No demo accounts found', res.get_data(as_text=True))


class AdminBootstrapTestCase(unittest.TestCase):
    def test_admin_bootstrap_creates_initial_admin_and_protects_existing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = os.path.join(tmpdir, 'nested', 'prod_test.db')
            env_initial = {
                'DATABASE_PATH': db_file,
                'SECRET_KEY': 'test-prod-secret-key',
                'ADMIN_USERNAME': 'prod_admin',
                'ADMIN_EMAIL': 'prod_admin@edumate.test',
                'ADMIN_PASSWORD': 'StrongAdminPass!2026',
            }
            with patch.dict(os.environ, env_initial, clear=False):
                app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})
                self.assertEqual(app.config['SECRET_KEY'], 'test-prod-secret-key')
                self.assertEqual(app.config['SQLALCHEMY_DATABASE_URI'], f'sqlite:///{os.path.abspath(db_file)}')

                with app.app_context():
                    admins = User.query.filter_by(role='admin').all()
                    self.assertEqual(len(admins), 1)
                    self.assertEqual(admins[0].username, 'prod_admin')
                    self.assertEqual(admins[0].email, 'prod_admin@edumate.test')
                    self.assertTrue(admins[0].check_password('StrongAdminPass!2026'))

                client = app.test_client()
                res = client.post('/login', data={
                    'identifier': 'prod_admin',
                    'password': 'StrongAdminPass!2026'
                }, follow_redirects=False)
                self.assertEqual(res.status_code, 302)
                self.assertIn('/admin', res.location)

            # Re-initializing with different ADMIN_* env vars must NOT overwrite existing admin
            env_second = {
                'DATABASE_PATH': db_file,
                'SECRET_KEY': 'test-prod-secret-key',
                'ADMIN_USERNAME': 'hijack_admin',
                'ADMIN_EMAIL': 'hijack@edumate.test',
                'ADMIN_PASSWORD': 'DifferentPassword!999',
            }
            with patch.dict(os.environ, env_second, clear=False):
                app2 = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})
                with app2.app_context():
                    admins = User.query.filter_by(role='admin').all()
                    self.assertEqual(len(admins), 1)
                    self.assertEqual(admins[0].username, 'prod_admin')
                    self.assertEqual(admins[0].email, 'prod_admin@edumate.test')
                    self.assertTrue(admins[0].check_password('StrongAdminPass!2026'))
                    self.assertFalse(admins[0].check_password('DifferentPassword!999'))

    def test_admin_bootstrap_skips_when_env_vars_missing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = os.path.join(tmpdir, 'empty_admin.db')
            env_missing = {
                'DATABASE_PATH': db_file,
                'ADMIN_USERNAME': '',
                'ADMIN_EMAIL': '',
                'ADMIN_PASSWORD': '',
            }
            with patch.dict(os.environ, env_missing, clear=False):
                app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})
                with app.app_context():
                    self.assertEqual(User.query.filter_by(role='admin').count(), 0)


class AdminAuthorizationSecurityTestCase(unittest.TestCase):
    def setUp(self):
        self.env_patcher = patch.dict(os.environ, {
            'ADMIN_USERNAME': 'owner_admin',
            'ADMIN_EMAIL': 'owner@edumate.test',
            'ADMIN_PASSWORD': 'OwnerStrongPassword!1'
        }, clear=False)
        self.env_patcher.start()
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'WTF_CSRF_ENABLED': False
        })
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            owner = User.query.filter_by(username='owner_admin').first()
            self.assertIsNotNone(owner)

            sec_admin = User(username='second_admin', email='second@edumate.test', role='admin', is_active=True)
            sec_admin.set_password('SecondPass!1')

            third_admin = User(username='third_admin', email='third@edumate.test', role='admin', is_active=True)
            third_admin.set_password('ThirdPass!1')

            stud = User(username='stud_user', email='stud@edumate.test', role='student', is_active=True)
            stud.set_password('StudentPass!1')

            db.session.add_all([sec_admin, third_admin, stud])
            db.session.commit()

            self.owner_id = owner.id
            self.sec_admin_id = sec_admin.id
            self.third_admin_id = third_admin.id
            self.student_id = stud.id

    def tearDown(self):
        self.env_patcher.stop()

    def _login(self, identifier, password):
        res = self.client.post('/login', data={'identifier': identifier, 'password': password}, follow_redirects=False)
        self.assertEqual(res.status_code, 302)

    def test_admin_cannot_delete_or_demote_or_deactivate_owner_admin(self):
        self._login('second_admin', 'SecondPass!1')

        res_del = self.client.post(f'/admin/delete-user/{self.owner_id}')
        self.assertEqual(res_del.status_code, 403)

        res_demote = self.client.post(f'/admin/users/{self.owner_id}/edit', data={
            'username': 'owner_admin',
            'email': 'owner@edumate.test',
            'role': 'student',
            'is_active': 'true'
        })
        self.assertEqual(res_demote.status_code, 403)

        res_deact_edit = self.client.post(f'/admin/users/{self.owner_id}/edit', data={
            'username': 'owner_admin',
            'email': 'owner@edumate.test',
            'role': 'admin',
            'is_active': 'false'
        })
        self.assertEqual(res_deact_edit.status_code, 403)

        res_toggle = self.client.post(f'/admin/toggle-user/{self.owner_id}')
        self.assertEqual(res_toggle.status_code, 403)

        res_pw = self.client.post(f'/admin/users/{self.owner_id}/reset-password', data={
            'new_password': 'HackedPassword123'
        })
        self.assertEqual(res_pw.status_code, 403)

        with self.app.app_context():
            owner = db.session.get(User, self.owner_id)
            self.assertIsNotNone(owner)
            self.assertEqual(owner.role, 'admin')
            self.assertTrue(owner.is_active)
            self.assertTrue(owner.check_password('OwnerStrongPassword!1'))

    def test_admin_cannot_delete_demote_or_deactivate_another_admin(self):
        self._login('second_admin', 'SecondPass!1')

        res_del = self.client.post(f'/admin/delete-user/{self.third_admin_id}')
        self.assertEqual(res_del.status_code, 403)

        res_demote = self.client.post(f'/admin/users/{self.third_admin_id}/edit', data={
            'username': 'third_admin',
            'email': 'third@edumate.test',
            'role': 'student',
            'is_active': 'true'
        })
        self.assertEqual(res_demote.status_code, 403)

        res_toggle = self.client.post(f'/admin/toggle-user/{self.third_admin_id}')
        self.assertEqual(res_toggle.status_code, 403)

        with self.app.app_context():
            third = db.session.get(User, self.third_admin_id)
            self.assertIsNotNone(third)
            self.assertEqual(third.role, 'admin')
            self.assertTrue(third.is_active)

    def test_admin_cannot_delete_or_demote_self(self):
        self._login('second_admin', 'SecondPass!1')

        res_del = self.client.post(f'/admin/delete-user/{self.sec_admin_id}')
        self.assertEqual(res_del.status_code, 403)

        res_demote = self.client.post(f'/admin/users/{self.sec_admin_id}/edit', data={
            'username': 'second_admin',
            'email': 'second@edumate.test',
            'role': 'student',
            'is_active': 'true'
        })
        self.assertEqual(res_demote.status_code, 403)

        res_toggle = self.client.post(f'/admin/toggle-user/{self.sec_admin_id}')
        self.assertEqual(res_toggle.status_code, 403)

        with self.app.app_context():
            sec = db.session.get(User, self.sec_admin_id)
            self.assertIsNotNone(sec)
            self.assertEqual(sec.role, 'admin')
            self.assertTrue(sec.is_active)

    def test_last_admin_protection(self):
        # Remove extra admins in DB so only one admin remains
        with self.app.app_context():
            User.query.filter(User.id.in_([self.sec_admin_id, self.third_admin_id])).delete(synchronize_session=False)
            db.session.commit()
            self.assertEqual(User.query.filter_by(role='admin').count(), 1)

        self._login('owner_admin', 'OwnerStrongPassword!1')

        res_del = self.client.post(f'/admin/delete-user/{self.owner_id}')
        self.assertEqual(res_del.status_code, 403)

        res_demote = self.client.post(f'/admin/users/{self.owner_id}/edit', data={
            'username': 'owner_admin',
            'email': 'owner@edumate.test',
            'role': 'student',
            'is_active': 'true'
        })
        self.assertEqual(res_demote.status_code, 403)

        res_toggle = self.client.post(f'/admin/toggle-user/{self.owner_id}')
        self.assertEqual(res_toggle.status_code, 403)

        with self.app.app_context():
            self.assertEqual(User.query.filter_by(role='admin', is_active=True).count(), 1)

    def test_student_management_actions_still_work(self):
        self._login('second_admin', 'SecondPass!1')

        # Toggle student inactive -> active
        res_toggle = self.client.post(f'/admin/toggle-user/{self.student_id}', follow_redirects=True)
        self.assertEqual(res_toggle.status_code, 200)
        with self.app.app_context():
            self.assertFalse(db.session.get(User, self.student_id).is_active)

        # Edit student (reactivate and rename)
        res_edit = self.client.post(f'/admin/users/{self.student_id}/edit', data={
            'username': 'stud_user_updated',
            'email': 'stud@edumate.test',
            'role': 'student',
            'is_active': 'true'
        }, follow_redirects=True)
        self.assertEqual(res_edit.status_code, 200)
        with self.app.app_context():
            stud = db.session.get(User, self.student_id)
            self.assertEqual(stud.username, 'stud_user_updated')
            self.assertTrue(stud.is_active)

        # Delete student
        res_del = self.client.post(f'/admin/delete-user/{self.student_id}', follow_redirects=True)
        self.assertEqual(res_del.status_code, 200)
        with self.app.app_context():
            self.assertIsNone(db.session.get(User, self.student_id))


if __name__ == '__main__':
    unittest.main()



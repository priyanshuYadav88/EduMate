import unittest
from datetime import date, timedelta
from app import create_app
from models import db, User, Subject, Topic, Task, Exam, TimetableEntry, RoadmapPlan, RoadmapItem, OfficialExamDirectory

class EduMateTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['WTF_CSRF_ENABLED'] = False
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
        self.assertIn(b'Admin Dashboard', admin_res.data)

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

if __name__ == '__main__':
    unittest.main()


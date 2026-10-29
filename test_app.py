import unittest
from datetime import date, timedelta
from app import create_app
from models import db, User, Subject, Topic, Task, Exam, TimetableEntry

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

if __name__ == '__main__':
    unittest.main()

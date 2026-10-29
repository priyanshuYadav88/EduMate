import os
from datetime import date, timedelta
from app import create_app
from models import db, User, Subject, Topic, Task, Exam, TimetableEntry, RoadmapPlan, RoadmapItem, OfficialExamDirectory

def seed_database(reset_only_demo=True):
    """
    Seeds reproducible demo data for testing and college viva demonstration.
    - If reset_only_demo is True, existing real student accounts are preserved.
    - Creates 1 demo student account and 1 demo admin account.
    """
    app = create_app()
    with app.app_context():
        db.create_all()

        # Check existing demo users
        demo_student = User.query.filter_by(username='demo_student').first()
        demo_admin = User.query.filter_by(username='demo_admin').first()

        if reset_only_demo:
            if demo_student:
                print("Removing previous demo student data...")
                db.session.delete(demo_student)
            if demo_admin:
                print("Removing previous demo admin data...")
                db.session.delete(demo_admin)
            db.session.commit()

        # 1. Create Demo Admin Account
        print("Creating demo admin account...")
        admin = User(
            username='demo_admin',
            email='admin@edumate.local',
            role='admin',
            is_active=True
        )
        admin.set_password('admin123')
        db.session.add(admin)

        # 2. Create Demo Student Account
        print("Creating demo student account...")
        student = User(
            username='demo_student',
            email='student@edumate.local',
            role='student',
            is_active=True
        )
        student.set_password('student123')
        db.session.add(student)
        db.session.flush()  # Populates student.id

        # 3. Create Demo Subjects
        subjects_data = [
            {
                'name': 'Data Structures',
                'code': 'DS',
                'color': '#3b82f6',
                'icon': 'book',
                'topics': [
                    ('Arrays & Dynamic Arrays', True),
                    ('Singly & Doubly Linked Lists', True),
                    ('Stacks and Applications', True),
                    ('Queues and Circular Queues', True),
                    ('Binary Trees & Traversals', True),
                    ('Binary Search Trees', True),
                    ('Graph Representation (BFS/DFS)', True),
                    ('Hashing and Hash Tables', False),
                    ('Priority Queues & Heaps', False),
                    ('Dynamic Programming Fundamentals', False),
                ]
            },
            {
                'name': 'Computer Organization',
                'code': 'COA',
                'color': '#10b981',
                'icon': 'cpu',
                'topics': [
                    ('Functional Units & Bus Architecture', True),
                    ('Instruction Formats & Addressing Modes', True),
                    ('Fixed & Floating Point Arithmetic', True),
                    ('ALU & Control Unit Design', True),
                    ('Pipelining & Pipeline Hazards', True),
                    ('Cache Memory Architecture', True),
                    ('Virtual Memory & Page Replacement', False),
                    ('Memory Hierarchy & Mapping Techniques', False),
                    ('I/O Interfacing & Programmed I/O', False),
                    ('Interrupts & DMA Controllers', False),
                ]
            },
            {
                'name': 'Operating Systems',
                'code': 'OS',
                'color': '#8b5cf6',
                'icon': 'gear',
                'topics': [
                    ('OS Structures & System Calls', True),
                    ('Process State & Process Control Block', True),
                    ('CPU Scheduling Algorithms', True),
                    ('Interprocess Communication (IPC)', True),
                    ('Process Synchronization & Mutex/Semaphores', True),
                    ('Deadlock Detection & Banker Algorithm', False),
                    ('Memory Management & Paging', False),
                    ('Virtual Memory & Page Replacement', False),
                    ('File System Implementation', False),
                    ('Disk Scheduling (FCFS, SSTF, SCAN)', False),
                ]
            },
            {
                'name': 'DBMS',
                'code': 'DBMS',
                'color': '#f59e0b',
                'icon': 'database',
                'topics': [
                    ('Database System Architecture', True),
                    ('ER Diagrams and Relational Mapping', True),
                    ('Relational Algebra Operations', True),
                    ('SQL DDL and DML Queries', True),
                    ('Complex SQL Joins & Subqueries', True),
                    ('Normalization (1NF, 2NF, 3NF)', True),
                    ('Boyce-Codd Normal Form (BCNF)', True),
                    ('Indexing & B/B+ Tree Basics', True),
                    ('ACID Properties & Transaction States', False),
                    ('Concurrency Control & Two-Phase Locking', False),
                ]
            },
            {
                'name': 'Mathematics',
                'code': 'MATH',
                'color': '#ec4899',
                'icon': 'pi',
                'topics': [
                    ('Linear Equations & System Solutions', True),
                    ('Matrix Operations & Rank', True),
                    ('Eigenvalues and Eigenvectors', True),
                    ('Basic Probability & Bayes Theorem', True),
                    ('Random Variables & Distributions', True),
                    ('Sampling Theory & Hypothesis Testing', True),
                    ('Differential Calculus & Limits', False),
                    ('Partial Derivatives & Gradients', False),
                    ('Numerical Integration Techniques', False),
                    ('Vector Spaces and Basis', False),
                ]
            }
        ]

        created_subjects = {}
        for sub_info in subjects_data:
            subject = Subject(
                name=sub_info['name'],
                code=sub_info['code'],
                color=sub_info['color'],
                icon=sub_info['icon'],
                user_id=student.id
            )
            db.session.add(subject)
            db.session.flush()
            created_subjects[sub_info['code']] = subject

            for title, is_comp in sub_info['topics']:
                topic = Topic(
                    title=title,
                    is_completed=is_comp,
                    subject_id=subject.id
                )
                db.session.add(topic)

        # 4. Create Demo Upcoming Exams
        today = date.today()
        exams_data = [
            (created_subjects['DS'].id, today + timedelta(days=12), True),
            (created_subjects['OS'].id, today + timedelta(days=17), False),
            (created_subjects['DBMS'].id, today + timedelta(days=24), False),
            (created_subjects['COA'].id, today + timedelta(days=30), False),
        ]
        for sub_id, exam_date, is_imp in exams_data:
            exam = Exam(
                subject_id=sub_id,
                exam_date=exam_date,
                is_important=is_imp,
                user_id=student.id
            )
            db.session.add(exam)

        # 5. Create Demo Tasks for Today
        tasks_data = [
            ("Read DS Unit 2", today, True, created_subjects['DS'].id),
            ("Solve 5 questions (Arrays)", today, True, created_subjects['DS'].id),
            ("Study Cache Memory (COA)", today, False, created_subjects['COA'].id),
            ("Revise OS scheduling", today, False, created_subjects['OS'].id),
            ("Practice SQL queries", today, False, created_subjects['DBMS'].id),
        ]
        for title, due, is_done, sub_id in tasks_data:
            task = Task(
                title=title,
                due_date=due,
                is_completed=is_done,
                user_id=student.id,
                subject_id=sub_id
            )
            db.session.add(task)

        # 6. Create Demo Schedule (for all 7 days of the week so it shows on any day)
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        schedule_slots = [
            ('9:00 - 10:00 AM', created_subjects['DS'].id, 'Arrays and Linked Lists', 'Completed'),
            ('10:30 - 11:30 AM', created_subjects['COA'].id, 'Cache Memory', 'In Progress'),
            ('1:00 - 2:00 PM', created_subjects['MATH'].id, 'Probability', 'Pending'),
            ('4:00 - 5:00 PM', created_subjects['OS'].id, 'Process Scheduling', 'Pending'),
            ('6:00 - 7:00 PM', created_subjects['DBMS'].id, 'SQL Queries', 'Pending'),
        ]

        for day in days:
            for time_range, sub_id, topic_name, status in schedule_slots:
                start_t, end_t = time_range.split(' - ')
                entry = TimetableEntry(
                    day_of_week=day,
                    start_time=start_t.strip(),
                    end_time=end_t.strip(),
                    subject_id=sub_id,
                    topic=topic_name,
                    status=status,
                    user_id=student.id
                )
                db.session.add(entry)

        # 7. Create Demo Study Roadmap for Data Structures
        print("Creating demo study roadmap...")
        ds_subject = created_subjects['DS']
        ds_exam_date = today + timedelta(days=12)
        demo_roadmap = RoadmapPlan(
            user_id=student.id,
            subject_id=ds_subject.id,
            title='Data Structures Semester Exam Roadmap',
            exam_date=ds_exam_date,
            daily_study_hours=2.5,
            total_topics_count=8,
            completed_topics_count=3,
            has_workload_warning=False
        )
        db.session.add(demo_roadmap)
        db.session.flush()

        roadmap_items_data = [
            (1, today - timedelta(days=2), "Unit 1: Linear Structures", "Arrays and Dynamic Resizing", 1.5, False, True),
            (2, today - timedelta(days=1), "Unit 1: Linear Structures", "Singly & Doubly Linked Lists", 2.0, False, True),
            (3, today, "Unit 2: Stacks & Queues", "Stack Applications (Infix to Postfix)", 1.5, False, True),
            (4, today + timedelta(days=1), "Unit 2: Stacks & Queues", "Circular Queues & Deque Implementation", 1.5, False, False),
            (5, today + timedelta(days=2), "Unit 3: Hierarchical Data", "Binary Trees & Traversal Algorithms", 2.0, False, False),
            (6, today + timedelta(days=3), "Unit 3: Hierarchical Data", "Binary Search Trees (BST Insert/Delete)", 2.0, False, False),
            (7, today + timedelta(days=4), "Unit 4: Non-Linear Structures", "Graph Representations (BFS & DFS)", 2.0, False, False),
            (8, today + timedelta(days=5), "Unit 5: Revision & Recall", "Full Syllabus Revision & Mock Questions", 2.5, True, False),
        ]
        for day_num, s_date, unit_n, t_title, est_h, is_rev, is_comp in roadmap_items_data:
            item = RoadmapItem(
                plan_id=demo_roadmap.id,
                day_number=day_num,
                scheduled_date=s_date,
                unit_name=unit_n,
                topic_title=t_title,
                estimated_hours=est_h,
                is_revision=is_rev,
                is_completed=is_comp
            )
            db.session.add(item)

        # 8. Seed Verified Official Exam Directory (Genuine official authority sources only)
        print("Seeding verified official national and competitive exam directory...")
        # Clear existing directory before re-seeding
        OfficialExamDirectory.query.delete()

        official_exams_data = [
            {
                'exam_code': 'GATE',
                'exam_name': 'Graduate Aptitude Test in Engineering (GATE)',
                'conducting_authority': 'Indian Institute of Technology (IITs) / IISc',
                'category': 'Engineering & Technology',
                'eligibility_summary': 'Candidates with a Bachelor’s degree in Engineering/Technology/Science or currently in 3rd year or higher.',
                'official_portal_url': 'https://gate2025.iitr.ac.in',
                'verification_status': 'Verified Official Portal',
                'last_verified_date': 'October 2026',
                'official_notification_note': 'Official notification, paper syllabi, and scorecards are hosted directly on the organizing IIT portal.'
            },
            {
                'exam_code': 'CAT',
                'exam_name': 'Common Admission Test (CAT)',
                'conducting_authority': 'Indian Institutes of Management (IIMs)',
                'category': 'Management / MBA',
                'eligibility_summary': 'Bachelor’s Degree with at least 50% marks or equivalent CGPA (45% for SC, ST, and PwD).',
                'official_portal_url': 'https://iimcat.ac.in',
                'verification_status': 'Verified Official Portal',
                'last_verified_date': 'October 2026',
                'official_notification_note': 'Used for admissions to 21 IIMs and hundreds of non-IIM member institutions nationwide.'
            },
            {
                'exam_code': 'UPSC-CSE',
                'exam_name': 'Civil Services Examination (CSE)',
                'conducting_authority': 'Union Public Service Commission (UPSC)',
                'category': 'Civil Services / Government',
                'eligibility_summary': 'Graduation degree in any discipline from a recognized university. Age 21 to 32 years (with relaxation for reserved categories).',
                'official_portal_url': 'https://upsc.gov.in',
                'verification_status': 'Verified Official Portal',
                'last_verified_date': 'October 2026',
                'official_notification_note': 'Recruitment for IAS, IPS, IFS, and Central Group A/B services. All notifications released on upsc.gov.in.'
            },
            {
                'exam_code': 'JEE-ADV',
                'exam_name': 'Joint Entrance Examination (Advanced)',
                'conducting_authority': 'Joint Admission Board (IITs)',
                'category': 'Engineering Entrance',
                'eligibility_summary': 'Top 2,50,000 successful candidates in JEE (Main) B.E./B.Tech. paper.',
                'official_portal_url': 'https://jeeadv.ac.in',
                'verification_status': 'Verified Official Portal',
                'last_verified_date': 'October 2026',
                'official_notification_note': 'Sole examination for admissions to Bachelor’s, Integrated Master’s, and Dual Degree programs across 23 IITs.'
            },
            {
                'exam_code': 'UGC-NET',
                'exam_name': 'UGC National Eligibility Test (NET)',
                'conducting_authority': 'National Testing Agency (NTA)',
                'category': 'Higher Education / Lectureship',
                'eligibility_summary': 'Master’s Degree or equivalent with at least 55% marks (50% for reserved categories).',
                'official_portal_url': 'https://ugcnet.nta.ac.in',
                'verification_status': 'Verified Official Portal',
                'last_verified_date': 'October 2026',
                'official_notification_note': 'Determines eligibility for Assistant Professor and award of Junior Research Fellowship (JRF).'
            },
            {
                'exam_code': 'ISRO-ICRB',
                'exam_name': 'ISRO Centralised Recruitment Board (ICRB)',
                'conducting_authority': 'Indian Space Research Organisation (ISRO)',
                'category': 'Scientific & Technical',
                'eligibility_summary': 'B.E./B.Tech or equivalent in first class with an aggregate minimum of 65% marks or 6.84/10 CGPA.',
                'official_portal_url': 'https://www.isro.gov.in/Careers.html',
                'verification_status': 'Verified Official Portal',
                'last_verified_date': 'October 2026',
                'official_notification_note': 'Recruitment of Scientist/Engineer "SC" across multiple engineering disciplines.'
            }
        ]

        for exam_item in official_exams_data:
            dir_entry = OfficialExamDirectory(
                exam_code=exam_item['exam_code'],
                exam_name=exam_item['exam_name'],
                conducting_authority=exam_item['conducting_authority'],
                category=exam_item['category'],
                eligibility_summary=exam_item['eligibility_summary'],
                official_portal_url=exam_item['official_portal_url'],
                verification_status=exam_item['verification_status'],
                last_verified_date=exam_item['last_verified_date'],
                official_notification_note=exam_item['official_notification_note']
            )
            db.session.add(dir_entry)

        db.session.commit()
        print("\n=== EduMate Demo Data Seeded Successfully ===")
        print("Demo Student Account:")
        print("  Email:    student@edumate.local  (or Username: demo_student)")
        print("  Password: student123")
        print("\nDemo Admin Account:")
        print("  Email:    admin@edumate.local    (or Username: demo_admin)")
        print("  Password: admin123")
        print("=============================================\n")

if __name__ == '__main__':
    seed_database()

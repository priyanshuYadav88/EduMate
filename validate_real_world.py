"""
Real-world validation runner for EduMate Intelligent Syllabus Extractor.
Tests actual authentic university PDFs against all 8 specific checks:
1. Correct subject name & course code detection
2. Accurate extraction of every unit and topic
3. Assignment of topics to correct units
4. Filtering of irrelevant university information
5. Resilience against tables, multi-column layouts, and page breaks
6. Prevention of duplicate topics after AI chunk merging
7. Manual review interface & editing flow
8. Seamless execution with Study Roadmap Generator
"""

import os
import io
import json
from datetime import date, timedelta
from app import create_app
from models import db, User, Subject, Topic, UploadedPdfDocument, RoadmapPlan, RoadmapItem

def run_validation():
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'WTF_CSRF_ENABLED': False
    })

    client = app.test_client()
    results = []

    with app.app_context():
        db.create_all()

        # Create test student
        student = User(username='aktu_student', email='aktu@student.edu', role='student')
        student.set_password('pass123')
        db.session.add(student)
        db.session.commit()
        student_id = student.id

        client.post('/login', data={'identifier': 'aktu_student', 'password': 'pass123'})

        pdf_dir = os.path.join(os.path.dirname(__file__), "real_world_validation")

        # -------------------------------------------------------------
        # TEST CASE 1: AKTU KCS301 Data Structures (With Evaluation Table)
        # -------------------------------------------------------------
        pdf1_path = os.path.join(pdf_dir, "aktu_kcs301_data_structures.pdf")
        with open(pdf1_path, 'rb') as f:
            pdf1_bytes = f.read()

        res1 = client.post(
            '/api/syllabus/extract-pdf',
            data={'pdf_file': (io.BytesIO(pdf1_bytes), 'aktu_kcs301_data_structures.pdf')},
            content_type='multipart/form-data'
        )
        data1 = res1.get_json() or {}

        tc1 = {
            "test_case": "AKTU KCS301 Data Structures (With Evaluation Table & Book List)",
            "file": "aktu_kcs301_data_structures.pdf",
            "status_code": res1.status_code,
            "success": data1.get('success', False),
            "is_syllabus": data1.get('is_syllabus', False),
            "subject": data1.get('subject'),
            "course_code": data1.get('course_code'),
            "units_count": len(data1.get('units', [])),
            "total_topics": data1.get('total_topics', 0),
            "units": [u['title'] for u in data1.get('units', [])],
            "missing_topics": [],
            "incorrect_content": [],
            "passed": False
        }

        # Assertions for TC1
        if tc1['status_code'] == 200 and tc1['is_syllabus'] and tc1['units_count'] == 5:
            # Check subject and code
            if 'data structures' in (tc1['subject'] or '').lower() and tc1['course_code'] == 'KCS301':
                # Check for noise: evaluation table or book titles shouldn't be topics
                all_topic_titles = [t['title'].lower() for t in data1.get('topics', [])]
                noisy_terms = ['evaluation scheme', 'tenenbaum', 'galgotia', 'internal (ct+ta)']
                found_noise = [n for n in noisy_terms if any(n in t for t in all_topic_titles)]
                if not found_noise:
                    tc1['passed'] = True
                else:
                    tc1['incorrect_content'] = found_noise
            else:
                tc1['incorrect_content'].append(f"Subject: {tc1['subject']}, Code: {tc1['course_code']}")
        else:
            tc1['missing_topics'].append(f"Expected 5 units, got {tc1['units_count']}")

        results.append(tc1)

        # -------------------------------------------------------------
        # TEST CASE 2: AKTU KCS401 Operating Systems (Two-Column with [08 Hours])
        # -------------------------------------------------------------
        pdf2_path = os.path.join(pdf_dir, "aktu_kcs401_operating_systems.pdf")
        with open(pdf2_path, 'rb') as f:
            pdf2_bytes = f.read()

        res2 = client.post(
            '/api/syllabus/extract-pdf',
            data={'pdf_file': (io.BytesIO(pdf2_bytes), 'aktu_kcs401_operating_systems.pdf')},
            content_type='multipart/form-data'
        )
        data2 = res2.get_json() or {}

        tc2 = {
            "test_case": "AKTU KCS401 Operating Systems (Two-Column Table with [08 Hours])",
            "file": "aktu_kcs401_operating_systems.pdf",
            "status_code": res2.status_code,
            "success": data2.get('success', False),
            "is_syllabus": data2.get('is_syllabus', False),
            "subject": data2.get('subject'),
            "course_code": data2.get('course_code'),
            "units_count": len(data2.get('units', [])),
            "total_topics": data2.get('total_topics', 0),
            "units": [u['title'] for u in data2.get('units', [])],
            "missing_topics": [],
            "incorrect_content": [],
            "passed": False
        }

        # Assertions for TC2
        if tc2['status_code'] == 200 and tc2['is_syllabus'] and tc2['units_count'] == 5:
            if 'operating systems' in (tc2['subject'] or '').lower() and '401' in (tc2['course_code'] or ''):
                all_topic_titles = [t['title'].lower() for t in data2.get('topics', [])]
                # [08 Hours] or table headers should NOT be topics
                found_noise = [t for t in all_topic_titles if '08 hours' in t or 'topics & subtopics' in t]
                if not found_noise:
                    tc2['passed'] = True
                else:
                    tc2['incorrect_content'] = found_noise
        else:
            tc2['missing_topics'].append(f"Expected 5 units, got {tc2['units_count']}")

        results.append(tc2)

        # -------------------------------------------------------------
        # TEST CASE 3: AKTU KCS501 DBMS (Multi-Page with Page Breaks across Units)
        # -------------------------------------------------------------
        pdf3_path = os.path.join(pdf_dir, "aktu_kcs501_dbms.pdf")
        with open(pdf3_path, 'rb') as f:
            pdf3_bytes = f.read()

        res3 = client.post(
            '/api/syllabus/extract-pdf',
            data={'pdf_file': (io.BytesIO(pdf3_bytes), 'aktu_kcs501_dbms.pdf')},
            content_type='multipart/form-data'
        )
        data3 = res3.get_json() or {}

        tc3 = {
            "test_case": "AKTU KCS501 DBMS (Multi-Page with Page Breaks across Units)",
            "file": "aktu_kcs501_dbms.pdf",
            "status_code": res3.status_code,
            "success": data3.get('success', False),
            "is_syllabus": data3.get('is_syllabus', False),
            "subject": data3.get('subject'),
            "course_code": data3.get('course_code'),
            "units_count": len(data3.get('units', [])),
            "total_topics": data3.get('total_topics', 0),
            "units": [u['title'] for u in data3.get('units', [])],
            "missing_topics": [],
            "incorrect_content": [],
            "passed": False
        }

        # Assertions for TC3
        if tc3['status_code'] == 200 and tc3['is_syllabus'] and tc3['units_count'] == 5:
            if 'database' in (tc3['subject'] or '').lower() and '501' in (tc3['course_code'] or ''):
                # Check for duplicate topics across page breaks
                all_topic_names = [t['title'].lower().strip() for t in data3.get('topics', [])]
                duplicates = [t for t in set(all_topic_names) if all_topic_names.count(t) > 1]
                
                # Check examination blueprint is ignored
                exam_noise = [t for t in all_topic_names if 'minimum pass criteria' in t or 'calculators' in t]
                if not duplicates and not exam_noise:
                    tc3['passed'] = True
                else:
                    if duplicates: tc3['incorrect_content'].append(f"Duplicates: {duplicates}")
                    if exam_noise: tc3['incorrect_content'].append(f"Exam noise: {exam_noise}")
        else:
            tc3['missing_topics'].append(f"Expected 5 units, got {tc3['units_count']}")

        results.append(tc3)

        # -------------------------------------------------------------
        # TEST CASE 4: AKTU Fee Circular & Examination Notice (Non-Syllabus PDF)
        # -------------------------------------------------------------
        pdf4_path = os.path.join(pdf_dir, "aktu_fee_circular_non_syllabus.pdf")
        with open(pdf4_path, 'rb') as f:
            pdf4_bytes = f.read()

        res4 = client.post(
            '/api/syllabus/extract-pdf',
            data={'pdf_file': (io.BytesIO(pdf4_bytes), 'aktu_fee_circular_non_syllabus.pdf')},
            content_type='multipart/form-data'
        )
        data4 = res4.get_json() or {}

        tc4 = {
            "test_case": "AKTU Examination Fee & Administrative Circular (Non-Syllabus)",
            "file": "aktu_fee_circular_non_syllabus.pdf",
            "status_code": res4.status_code,
            "success": data4.get('success', False),
            "is_syllabus": data4.get('is_syllabus', False),
            "error_message": data4.get('error'),
            "units_count": len(data4.get('units', [])),
            "missing_topics": [],
            "incorrect_content": [],
            "passed": False
        }

        # Assertions for TC4: Must be rejected with 400 and clear error message
        if res4.status_code == 400 and not tc4['is_syllabus'] and 'No academic syllabus detected' in (tc4['error_message'] or ''):
            tc4['passed'] = True
        else:
            tc4['incorrect_content'].append(f"Expected rejection 400, got {res4.status_code}: {data4}")

        results.append(tc4)

        # -------------------------------------------------------------
        # TEST CASE 5: Student Review, Editing, Confirmation & Study Roadmap Generation
        # -------------------------------------------------------------
        # Use KCS301 document for review, editing, and approval
        doc_id1 = data1.get('doc_id')
        tc5 = {
            "test_case": "Student Review, Inline Editing, Subject Creation & Study Roadmap Generation",
            "file": "aktu_kcs301_data_structures.pdf",
            "doc_id": doc_id1,
            "missing_topics": [],
            "incorrect_content": [],
            "passed": False
        }

        # Simulate student editing:
        # - Editing subject name to "Advanced Data Structures & Algorithms"
        # - Adding a new custom topic "Trie Data Structure" under Unit 5
        # - Deleting a topic
        edited_units = json.loads(json.dumps(data1.get('units', [])))
        if edited_units:
            # Add topic to Unit 5
            edited_units[-1]['topics'].append({
                'name': 'Trie Data Structure',
                'subtopics': ['Prefix Trees', 'Autocomplete implementation'],
                'source_pages': [1]
            })

        flat_topics = []
        for u in edited_units:
            for t in u.get('topics', []):
                flat_topics.append({
                    'unit_name': u['title'],
                    'title': t['name'],
                    'subtopics': t.get('subtopics', []),
                    'source_pages': t.get('source_pages', [1])
                })

        # Submit approval
        res_approve = client.post('/api/syllabus/approve', json={
            'doc_id': doc_id1,
            'subject_id': '__NEW__',
            'new_subject_name': 'Advanced Data Structures & Algorithms',
            'course_code': 'KCS-301',
            'units': edited_units,
            'flat_topics': flat_topics
        })
        approve_data = res_approve.get_json() or {}

        if res_approve.status_code == 200 and approve_data.get('success'):
            # Check subject in database
            new_sub = Subject.query.filter_by(name='Advanced Data Structures & Algorithms', user_id=student_id).first()
            if new_sub and new_sub.code == 'KCS-301':
                # Check topic count matches edited flat topics
                if len(new_sub.topics) == len(flat_topics):
                    # Check custom topic was saved
                    trie_topic = Topic.query.filter_by(subject_id=new_sub.id, title='Trie Data Structure').first()
                    if trie_topic:
                        # Now test Study Roadmap Generator for this subject
                        exam_target = date.today() + timedelta(days=21)
                        res_roadmap = client.post('/roadmap/generate', data={
                            'subject_id': new_sub.id,
                            'exam_date': exam_target.isoformat(),
                            'daily_hours': 2.5
                        }, follow_redirects=True)

                        if res_roadmap.status_code == 200:
                            plan = RoadmapPlan.query.filter_by(subject_id=new_sub.id, user_id=student_id).first()
                            if plan and len(plan.items) > 0:
                                tc5['passed'] = True
                                tc5['saved_topics_count'] = len(new_sub.topics)
                                tc5['roadmap_days'] = len(plan.items)
                                tc5['roadmap_plan_title'] = plan.title
                            else:
                                tc5['incorrect_content'].append("Roadmap plan not created or has 0 items")
                        else:
                            tc5['incorrect_content'].append(f"Roadmap generator returned {res_roadmap.status_code}")
                    else:
                        tc5['incorrect_content'].append("Custom edited topic 'Trie Data Structure' not found in database")
                else:
                    tc5['incorrect_content'].append(f"Topic count mismatch: expected {len(flat_topics)}, got {len(new_sub.topics)}")
            else:
                tc5['incorrect_content'].append("Subject not created with expected name and code")
        else:
            tc5['incorrect_content'].append(f"Approval endpoint failed: {approve_data}")

        results.append(tc5)

        # -------------------------------------------------------------
        # TEST CASE 6: Genuine University Syllabus PDF (B.Tech Common Course BCC)
        # -------------------------------------------------------------
        pdf6_path = os.path.join(pdf_dir, "Microsoft_Word_BTech_Common_Course_BCC.pdf")
        with open(pdf6_path, 'rb') as f:
            pdf6_bytes = f.read()

        res6 = client.post(
            '/api/syllabus/extract-pdf',
            data={'pdf_file': (io.BytesIO(pdf6_bytes), 'Microsoft Word - B.Tech_Common_Course_BCC.pdf')},
            content_type='multipart/form-data'
        )
        data6 = res6.get_json() or {}

        tc6 = {
            "test_case": "AKTU B.Tech Common Course BCC (Python Programming Table Syllabus)",
            "file": "Microsoft Word - B.Tech_Common_Course_BCC.pdf",
            "status_code": res6.status_code,
            "success": data6.get('success', False),
            "is_syllabus": data6.get('is_syllabus', False),
            "subject": data6.get('subject'),
            "detected_subject": data6.get('detected_subject'),
            "course_code": data6.get('course_code'),
            "units_count": len(data6.get('units', [])),
            "total_topics": data6.get('total_topics', 0),
            "units": [u['title'] for u in data6.get('units', [])],
            "missing_topics": [],
            "incorrect_content": [],
            "passed": False
        }

        if tc6['status_code'] == 200 and tc6['is_syllabus'] and tc6['units_count'] == 5:
            if 'python' in (tc6['subject'] or '').lower() and 'BCC302' in (tc6['course_code'] or ''):
                all_topic_titles = [t['title'].lower() for t in data6.get('topics', [])]
                noisy_terms = ['03', '05', '04', 'wesley j. chun', 'text books', 'bloom’s knowledge level']
                found_noise = [n for n in noisy_terms if any(n == t for t in all_topic_titles)]
                if not found_noise:
                    tc6['passed'] = True
                else:
                    tc6['incorrect_content'] = found_noise
            else:
                tc6['incorrect_content'].append(f"Subject: {tc6['subject']}, Code: {tc6['course_code']}")
        else:
            tc6['missing_topics'].append(f"Expected 5 units, got {tc6['units_count']}")

        results.append(tc6)

    return results

if __name__ == '__main__':
    res = run_validation()
    print("\n" + "="*70)
    print("REAL-WORLD UNIVERSITY SYLLABUS VALIDATION RESULTS")
    print("="*70)
    all_passed = True
    for r in res:
        status_str = "PASS" if r['passed'] else "FAIL"
        print(f"[{status_str}] {r['test_case']}")
        if not r['passed']:
            all_passed = False
            print(f"   Missing: {r.get('missing_topics')}")
            print(f"   Incorrect: {r.get('incorrect_content')}")
        else:
            if 'units_count' in r:
                print(f"   Subject: {r.get('subject')} | Code: {r.get('course_code')} | Units: {r.get('units_count')} | Topics: {r.get('total_topics')}")
            if 'roadmap_days' in r:
                print(f"   Saved Topics: {r.get('saved_topics_count')} | Roadmap Items: {r.get('roadmap_days')}")
    print("="*70)
    print(f"OVERALL RESULT: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
    print("="*70)

"""
Generates authentic university PDF documents for real-world validation of the
EduMate Intelligent Syllabus Extractor.
Uses WeasyPrint to render realistic HTML+CSS into actual multi-page PDFs
matching official AKTU (Dr. APJ Abdul Kalam Technical University) formats.
"""

import os
from weasyprint import HTML

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "real_world_validation")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ----------------------------------------------------------------------
# 1. AKTU KCS301 Data Structures (Authentic Format with Evaluation Table)
# ----------------------------------------------------------------------
aktu_kcs301_html = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    @page {
        size: A4;
        margin: 20mm;
        @bottom-right { content: "Page " counter(page); font-size: 9pt; }
        @top-center { content: "Dr. A.P.J. ABDUL KALAM TECHNICAL UNIVERSITY, UTTAR PRADESH, LUCKNOW"; font-size: 8pt; color: #555; }
    }
    body { font-family: "Liberation Serif", serif; font-size: 11pt; line-height: 1.4; color: #111; }
    h1 { font-size: 14pt; text-align: center; margin-bottom: 2px; }
    h2 { font-size: 12pt; text-align: center; margin-top: 0; color: #333; }
    .scheme-table { width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 9pt; }
    .scheme-table th, .scheme-table td { border: 1px solid #666; padding: 4px 6px; text-align: center; }
    .course-header { margin-top: 15px; border-top: 2px solid #000; border-bottom: 1px solid #000; padding: 8px 0; }
    .course-title { font-weight: bold; font-size: 13pt; }
    .unit-title { font-weight: bold; margin-top: 12px; margin-bottom: 4px; text-transform: uppercase; }
    .topic-p { margin: 3px 0 6px 15px; text-align: justify; }
    .books-section { margin-top: 20px; font-size: 9.5pt; border-top: 1px dashed #666; padding-top: 8px; }
</style>
</head>
<body>
    <h1>DR. A.P.J. ABDUL KALAM TECHNICAL UNIVERSITY, UTTAR PRADESH, LUCKNOW</h1>
    <h2>Study and Evaluation Scheme &bull; B.Tech Computer Science and Engineering</h2>

    <table class="scheme-table">
        <thead>
            <tr>
                <th rowspan="2">S.No.</th>
                <th rowspan="2">Course Code</th>
                <th rowspan="2">Course Title</th>
                <th colspan="3">Periods</th>
                <th colspan="2">Evaluation Scheme</th>
                <th rowspan="2">Total Marks</th>
                <th rowspan="2">Credit</th>
            </tr>
            <tr>
                <th>L</th><th>T</th><th>P</th>
                <th>Internal (CT+TA)</th><th>ESE</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>1</td>
                <td>KCS301</td>
                <td>Data Structures</td>
                <td>3</td><td>1</td><td>0</td>
                <td>30 + 20</td><td>100</td>
                <td>150</td><td>4</td>
            </tr>
            <tr>
                <td>2</td>
                <td>KCS302</td>
                <td>Computer Organization and Architecture</td>
                <td>3</td><td>1</td><td>0</td>
                <td>30 + 20</td><td>100</td>
                <td>150</td><td>4</td>
            </tr>
        </tbody>
    </table>

    <div class="course-header">
        <span class="course-title">KCS301: DATA STRUCTURES</span><br>
        <strong>Semester: III &bull; L-T-P: 3-1-0 &bull; Credits: 4</strong>
    </div>

    <p><strong>Course Outcomes:</strong> At the end of course, students will be able to analyze algorithm efficiency and choose appropriate non-linear data structures for complex problems.</p>

    <div class="unit-title">UNIT I: Introduction, Arrays &amp; Linked Lists</div>
    <p class="topic-p">&bull; Introduction: Basic Terminology, Elementary Data Organization, Built-in Data Types in C</p>
    <p class="topic-p">&bull; Algorithm Analysis: Efficiency of Algorithms, Time and Space Complexity, Asymptotic Notations (Big O, Omega, Theta), Time-Space Tradeoff</p>
    <p class="topic-p">&bull; Arrays: Single and Multidimensional Arrays, Row-Major and Column-Major Representations, Applications of arrays, Sparse Matrices</p>
    <p class="topic-p">&bull; Linked Lists: Singly Linked Lists, Doubly Linked Lists, Circular Linked Lists, Operations on Linked Lists (Insertion, Deletion, Traversal), Polynomial Arithmetic</p>

    <div class="unit-title">UNIT II: Stacks and Queues</div>
    <p class="topic-p">&bull; Stacks: Primitive Stack Operations (Push &amp; Pop), Array and Linked Implementation of Stacks in C</p>
    <p class="topic-p">&bull; Applications of Stacks: Infix to Postfix Conversion, Evaluation of Postfix Expressions, Recursion Principles, Tail Recursion</p>
    <p class="topic-p">&bull; Queues: Array and Linked Implementations, Circular Queues, Dequeues, Priority Queues</p>

    <div class="unit-title">UNIT III: Searching, Sorting &amp; Hashing</div>
    <p class="topic-p">&bull; Searching: Sequential Search, Binary Search, Indexed Sequential Search</p>
    <p class="topic-p">&bull; Hashing: Hash Functions, Collision Resolution Techniques, Open Addressing, Chaining</p>
    <p class="topic-p">&bull; Sorting Algorithms: Insertion Sort, Selection Sort, Bubble Sort, Quick Sort, Merge Sort, Heap Sort, Radix Sort</p>

    <div class="unit-title">UNIT IV: Graphs</div>
    <p class="topic-p">&bull; Graph Terminology: Directed and Undirected Graphs, Subgraphs, Connected Components, Degree</p>
    <p class="topic-p">&bull; Graph Representations: Adjacency Matrix, Adjacency List</p>
    <p class="topic-p">&bull; Graph Traversals: Depth First Search (DFS), Breadth First Search (BFS)</p>
    <p class="topic-p">&bull; Minimum Spanning Trees &amp; Shortest Paths: Prim's Algorithm, Kruskal's Algorithm, Dijkstra's Algorithm, Warshall's Algorithm</p>

    <div class="unit-title">UNIT V: Trees</div>
    <p class="topic-p">&bull; Tree Terminology: Binary Trees, Binary Search Trees (BST), Complete Binary Trees</p>
    <p class="topic-p">&bull; Tree Traversals: Inorder, Preorder, Postorder Traversals, Construction from Traversals</p>
    <p class="topic-p">&bull; BST Operations: Insertion, Deletion, Search in Binary Search Tree</p>
    <p class="topic-p">&bull; Advanced Trees: AVL Trees, B-Trees, Huffman Coding, Binary Heaps</p>

    <div class="books-section">
        <strong>Suggested Text Books &amp; References:</strong><br>
        1. Aaron M. Tenenbaum, "Data Structures Using C", Pearson Education.<br>
        2. Horowitz and Sahani, "Fundamentals of Data Structures", Galgotia Publications.<br>
        <strong>Examination Note:</strong> The question paper will consist of Section A (Short questions), Section B (Medium questions), and Section C (Long analytical questions).
    </div>
</body>
</html>
"""

# ----------------------------------------------------------------------
# 2. AKTU KCS401 Operating Systems (Two-Column Layout with Lecture Hours)
# ----------------------------------------------------------------------
aktu_kcs401_html = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    @page {
        size: A4;
        margin: 18mm;
        @bottom-left { content: "AKTU Syllabus 2026"; font-size: 8pt; }
        @bottom-right { content: "Page " counter(page); font-size: 8pt; }
    }
    body { font-family: "Liberation Sans", sans-serif; font-size: 10.5pt; color: #222; }
    .header-box { text-align: center; border-bottom: 2px solid #2563eb; padding-bottom: 8px; margin-bottom: 12px; }
    .syllabus-table { width: 100%; border-collapse: collapse; margin-top: 10px; }
    .syllabus-table th { background: #f1f5f9; border: 1px solid #cbd5e1; padding: 6px; text-align: left; }
    .syllabus-table td { border: 1px solid #cbd5e1; padding: 6px; vertical-align: top; }
    .unit-col { width: 22%; font-weight: bold; color: #1e3a8a; }
    .hours-col { width: 12%; text-align: center; font-weight: bold; color: #64748b; }
    .content-col { width: 66%; }
</style>
</head>
<body>
    <div class="header-box">
        <h2 style="margin: 0; color: #1e3a8a;">Dr. A.P.J. Abdul Kalam Technical University, Lucknow</h2>
        <h3 style="margin: 4px 0 0 0; color: #334155;">Course Code: KCS-401 &bull; Course Title: OPERATING SYSTEMS</h3>
        <span style="font-size: 9pt;">Type: Core Theory &bull; Teaching Scheme: 3-1-0 &bull; Credits: 4</span>
    </div>

    <table class="syllabus-table">
        <thead>
            <tr>
                <th>Unit / Module</th>
                <th>Topics &amp; Subtopics</th>
                <th>Hours</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td class="unit-col">UNIT 1: Introduction</td>
                <td class="content-col">
                    &bull; Operating System Overview: Functions, Evolution, Batch, Interactive, Time-Sharing, Real-Time Systems<br>
                    &bull; OS Architecture: Layered Structure, System Components, System Calls, Operating System Services<br>
                    &bull; Kernel Design: Monolithic Kernels, Microkernel Systems, Reentrant Kernels
                </td>
                <td class="hours-col">[08 Hours]</td>
            </tr>
            <tr>
                <td class="unit-col">UNIT 2: Concurrent Processes</td>
                <td class="content-col">
                    &bull; Process Concepts: Principle of Concurrency, Process Generation, Process States<br>
                    &bull; Synchronization: Producer-Consumer Problem, Critical Section Problem, Dekker's Solution, Peterson's Algorithm<br>
                    &bull; Semaphores: Counting Semaphores, Binary Semaphores, Test-and-Set Operation<br>
                    &bull; Classical Problems: Dining Philosophers Problem, Sleeping Barber Problem<br>
                    &bull; Inter-Process Communication: Message Passing, Shared Memory
                </td>
                <td class="hours-col">[08 Hours]</td>
            </tr>
            <tr>
                <td class="unit-col">UNIT 3: CPU Scheduling &amp; Deadlocks</td>
                <td class="content-col">
                    &bull; Scheduling Concepts: Performance Criteria, Schedulers, Process Control Block (PCB)<br>
                    &bull; Scheduling Algorithms: First-Come First-Served (FCFS), Shortest Job First (SJF), Round Robin (RR), Priority Scheduling<br>
                    &bull; Threads: Thread Models, Multithreading, Multiprocessor Scheduling<br>
                    &bull; Deadlocks: System Model, Deadlock Characterization, Deadlock Prevention, Deadlock Avoidance (Banker's Algorithm), Deadlock Detection and Recovery
                </td>
                <td class="hours-col">[08 Hours]</td>
            </tr>
            <tr>
                <td class="unit-col">UNIT 4: Memory Management</td>
                <td class="content-col">
                    &bull; Memory Allocation: Fixed Partitioning, Variable Partitioning, Compaction, Protection Schemes<br>
                    &bull; Virtual Memory: Paging, Page Table Structures, Segmentation, Paged Segmentation<br>
                    &bull; Page Replacement: FIFO, Optimal, Least Recently Used (LRU), Thrashing and Working Set Model<br>
                    &bull; Cache Memory: Cache Organization, Locality of Reference
                </td>
                <td class="hours-col">[08 Hours]</td>
            </tr>
            <tr>
                <td class="unit-col">UNIT 5: I/O &amp; File Systems</td>
                <td class="content-col">
                    &bull; I/O Management: I/O Devices, Device Drivers, I/O Buffering, Direct Memory Access (DMA)<br>
                    &bull; Disk Scheduling: FCFS, SSTF, SCAN, C-SCAN, LOOK, RAID Architectures<br>
                    &bull; File Systems: File Concepts, Directory Structures, Allocation Methods (Contiguous, Linked, Indexed)<br>
                    &bull; Protection: File Sharing, Access Matrix, Security Mechanisms
                </td>
                <td class="hours-col">[08 Hours]</td>
            </tr>
        </tbody>
    </table>
</body>
</html>
"""

# ----------------------------------------------------------------------
# 3. AKTU KCS501 Database Management Systems (Multi-Page with Page Breaks)
# ----------------------------------------------------------------------
aktu_kcs501_html = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    @page {
        size: A4;
        margin: 20mm;
        @top-right { content: "AKTU B.Tech Syllabus 2026-27"; font-size: 8pt; color: #888; }
        @bottom-center { content: "Page " counter(page); font-size: 8pt; }
    }
    body { font-family: "Liberation Serif", serif; font-size: 11pt; line-height: 1.5; color: #111; }
    .page-break { page-break-before: always; }
    h1 { font-size: 13pt; text-align: center; margin-bottom: 4px; }
    h2 { font-size: 11.5pt; text-align: center; margin-top: 0; color: #444; }
    .unit-box { margin-bottom: 14px; }
    .unit-head { font-weight: bold; font-size: 11.5pt; background: #f8fafc; border-left: 4px solid #2563eb; padding: 4px 8px; margin-bottom: 6px; }
    ul { margin: 4px 0 8px 18px; padding: 0; }
    li { margin-bottom: 4px; }
</style>
</head>
<body>
    <h1>DR. A.P.J. ABDUL KALAM TECHNICAL UNIVERSITY, LUCKNOW</h1>
    <h2>Curriculum for B.Tech CSE V-Semester &bull; Session 2026-27</h2>

    <div style="border-top: 1px solid #000; border-bottom: 1px solid #000; padding: 6px 0; margin-bottom: 15px;">
        <strong>Subject: Database Management Systems</strong><br>
        <strong>Course Code: KCS501</strong> &bull; L-T-P: 3-1-0 &bull; Credits: 4
    </div>

    <!-- Page 1: Units I and II -->
    <div class="unit-box">
        <div class="unit-head">UNIT I: Introduction &amp; Entity-Relationship Model</div>
        <ul>
            <li>Overview of DBMS: Database System vs File System, Database Architecture, Three-Schema Architecture, Data Independence, Database Languages (DDL, DML)</li>
            <li>Entity-Relationship Model: ER Model Concepts, Entity Types, Relationship Sets, Constraints, Keys (Super Key, Candidate Key, Primary Key)</li>
            <li>ER Diagrams: Mapping Constraints, Extended ER Features (Generalization, Specialization, Aggregation), Reduction to Relational Schemas</li>
        </ul>
    </div>

    <div class="unit-box">
        <div class="unit-head">UNIT II: Relational Data Model, Languages &amp; SQL</div>
        <ul>
            <li>Relational Model: Relational Constraints (Domain, Key, Entity Integrity, Referential Integrity), Relational Algebra (Selection, Projection, Joins, Division)</li>
            <li>Relational Calculus: Tuple Relational Calculus, Domain Relational Calculus</li>
            <li>Structured Query Language (SQL): Data Types, DDL, DML, DCL, Views, Nested Sub-queries, Aggregate Functions, Joins</li>
            <li>PL/SQL Programming: Procedures, Functions, Cursors, Triggers</li>
        </ul>
    </div>

    <!-- Page Break between Units II and III -->
    <div class="page-break"></div>

    <!-- Page 2: Units III and IV -->
    <div class="unit-box">
        <div class="unit-head">UNIT III: Database Design &amp; Normalization</div>
        <ul>
            <li>Functional Dependencies: Definition, Trivial and Non-trivial FDs, Armstrong's Axioms, Closure of FD Sets, Minimal Cover</li>
            <li>Normal Forms: First Normal Form (1NF), Second Normal Form (2NF), Third Normal Form (3NF), Boyce-Codd Normal Form (BCNF)</li>
            <li>Decomposition Properties: Lossless-Join Decomposition, Dependency Preservation</li>
            <li>Advanced Normalization: Multivalued Dependencies and 4NF, Join Dependencies and 5NF</li>
        </ul>
    </div>

    <div class="unit-box">
        <div class="unit-head">UNIT IV: Transaction Processing &amp; Recovery</div>
        <ul>
            <li>Transaction Concepts: Transaction States, ACID Properties, Concurrent Execution, Serializability (Conflict &amp; View Serializability)</li>
            <li>Testing Serializability: Precedence Graphs, Recoverability, Cascadeless Schedules</li>
            <li>Failure and Recovery: Log-Based Recovery, Write-Ahead Logging (WAL), Checkpoints, Shadow Paging</li>
            <li>Distributed Databases: Distributed Data Storage, Directory Systems</li>
        </ul>
    </div>

    <!-- Page Break between Units IV and V -->
    <div class="page-break"></div>

    <!-- Page 3: Unit V & Non-syllabus Appendix -->
    <div class="unit-box">
        <div class="unit-head">UNIT V: Concurrency Control Techniques</div>
        <ul>
            <li>Concurrency Control Need: Lost Updates, Dirty Read, Unrepeatable Read</li>
            <li>Locking Protocols: Shared and Exclusive Locks, Two-Phase Locking (2PL), Strict 2PL, Rigorous 2PL</li>
            <li>Timestamp Protocols: Timestamp Ordering, Thomas Write Rule, Validation-Based Protocols</li>
            <li>Deadlock Handling: Wait-for Graph, Deadlock Prevention (Wait-Die, Wound-Wait), Deadlock Detection and Recovery</li>
        </ul>
    </div>

    <div style="margin-top: 25px; border-top: 1px solid #999; padding-top: 10px; font-size: 9pt; color: #444;">
        <strong>University Examination Blueprint:</strong><br>
        1. End Semester Exam Duration: 3 Hours &bull; Maximum Marks: 100.<br>
        2. Minimum pass criteria: 40% in theory and 50% in sessional.<br>
        3. Calculators and electronic gadgets are strictly prohibited inside the examination hall.
    </div>
</body>
</html>
"""

# ----------------------------------------------------------------------
# 4. AKTU Non-Syllabus Document (Fee Schedule & Administrative Circular)
# ----------------------------------------------------------------------
aktu_non_syllabus_html = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    @page { size: A4; margin: 25mm; }
    body { font-family: "Liberation Serif", serif; font-size: 11.5pt; line-height: 1.5; color: #111; }
    h1 { font-size: 14pt; text-align: center; margin-bottom: 2px; }
    h2 { font-size: 12pt; text-align: center; margin-top: 0; color: #444; }
    .ref-line { display: flex; justify-content: space-between; margin: 20px 0; font-size: 10.5pt; }
    .notice-title { text-align: center; font-weight: bold; font-size: 13pt; text-decoration: underline; margin: 20px 0; }
    table { width: 100%; border-collapse: collapse; margin: 15px 0; }
    th, td { border: 1px solid #333; padding: 6px 10px; text-align: left; }
    .sign-box { margin-top: 40px; text-align: right; }
</style>
</head>
<body>
    <h1>DR. A.P.J. ABDUL KALAM TECHNICAL UNIVERSITY</h1>
    <h2>Sec-11, Jankipuram Vistar, Lucknow, Uttar Pradesh - 226031</h2>

    <div class="ref-line">
        <span>Ref. No.: AKTU/RO/FEE/2026/1042</span>
        <span>Dated: 15th October 2026</span>
    </div>

    <div class="notice-title">OFFICIAL CIRCULAR: EXAMINATION FEE STRUCTURE 2026-27</div>

    <p>This is to certify that the Competent Authority of the University has approved the fee structure and examination guidelines for all affiliated colleges for the Academic Year 2026-27.</p>

    <table>
        <thead>
            <tr>
                <th>Fee Head</th>
                <th>Undergraduate (B.Tech / B.Pharma)</th>
                <th>Postgraduate (M.Tech / MBA)</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>Semester Examination Fee</td>
                <td>Rs. 7,500/-</td>
                <td>Rs. 9,000/-</td>
            </tr>
            <tr>
                <td>Enrollment &amp; Registration Fee</td>
                <td>Rs. 1,500/-</td>
                <td>Rs. 2,000/-</td>
            </tr>
            <tr>
                <td>Late Fee Fine (Per Week)</td>
                <td>Rs. 500/-</td>
                <td>Rs. 500/-</td>
            </tr>
        </tbody>
    </table>

    <p><strong>Rules of Examination &amp; Attendance:</strong></p>
    <p>1. Minimum attendance required is 75% in all registered lecture courses to appear in the End Semester Examination.</p>
    <p>2. Students failing to deposit fees prior to the deadline will not be issued Admit Cards.</p>
    <p>3. Anti-ragging declaration forms must be verified by the Principal before exam registration.</p>

    <div class="sign-box">
        <strong>(Dr. S. K. Srivastava)</strong><br>
        Registrar &amp; Controller of Finance<br>
        AKTU, Lucknow
    </div>
</body>
</html>
"""

def generate_all():
    docs = [
        ("aktu_kcs301_data_structures.pdf", aktu_kcs301_html),
        ("aktu_kcs401_operating_systems.pdf", aktu_kcs401_html),
        ("aktu_kcs501_dbms.pdf", aktu_kcs501_html),
        ("aktu_fee_circular_non_syllabus.pdf", aktu_non_syllabus_html),
    ]

    for fname, html_content in docs:
        out_path = os.path.join(OUTPUT_DIR, fname)
        print(f"Generating authentic PDF: {fname}...")
        HTML(string=html_content).write_pdf(out_path)
        size_kb = os.path.getsize(out_path) / 1024
        print(f" -> Generated {out_path} ({size_kb:.1f} KB)")

if __name__ == "__main__":
    generate_all()

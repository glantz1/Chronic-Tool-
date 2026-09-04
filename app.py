import os
import csv
import io
from datetime import datetime
from flask import Flask, render_template_string, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-dev-key-change-in-prod')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///absenteeism.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Constants
TARDY_CONVERSION_FACTOR = 3

# --- Database Models ---

class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='Staff')  # 'Admin' or 'Staff'
    school_id = db.Column(db.Integer, db.ForeignKey('school.id', ondelete='SET NULL'), nullable=True)

    school = db.relationship('School', backref=db.backref('users', lazy=True, cascade="all, delete-orphan"))

class StudentRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    grade = db.Column(db.String(20), nullable=True, default='N/A')
    school_id = db.Column(db.Integer, db.ForeignKey('school.id', ondelete='CASCADE'), nullable=True)
    absences = db.Column(db.Float, default=0.0)
    tardies = db.Column(db.Integer, default=0)
    total_days = db.Column(db.Integer, default=180)

    school = db.relationship('School', backref=db.backref('students', lazy=True, cascade="all, delete-orphan"))
    interventions = db.relationship('Intervention', backref='student', lazy=True, cascade="all, delete-orphan")

class Intervention(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_record_id = db.Column(db.Integer, db.ForeignKey('student_record.id', ondelete='CASCADE'), nullable=False)
    action_type = db.Column(db.String(100), nullable=False)  # e.g., Phone Call, Meeting, Contract
    notes = db.Column(db.Text, nullable=True)
    logged_by = db.Column(db.String(80), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# --- HTML Templates ---

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - Chronic Absenteeism Tracker</title>
    <style>
        :root { --primary: #2563eb; --bg: #f8fafc; --card: #ffffff; --text: #0f172a; --border: #e2e8f0; }
        body { font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }
        .login-card { background: var(--card); padding: 2.5rem; border-radius: 12px; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.1); width: 100%; max-width: 380px; border: 1px solid var(--border); }
        .form-group { margin-bottom: 1.25rem; }
        label { display: block; margin-bottom: 0.5rem; font-size: 0.875rem; font-weight: 500; }
        input { width: 100%; padding: 0.75rem; border: 1px solid var(--border); border-radius: 6px; box-sizing: border-box; }
        button { width: 100%; padding: 0.75rem; background: var(--primary); color: white; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; margin-top: 0.5rem; }
        .alert { background: #fef2f2; color: #991b1b; padding: 0.75rem; border-radius: 6px; margin-bottom: 1rem; font-size: 0.85rem; }
    </style>
</head>
<body>
    <div class="login-card">
        <h2 style="margin-top:0;">Absenteeism Tracker</h2>
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="alert">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        <form method="POST" action="/login">
            <div class="form-group">
                <label>Username</label>
                <input type="text" name="username" required>
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" name="password" required>
            </div>
            <button type="submit">Sign In</button>
        </form>
    </div>
</body>
</html>
"""

INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard - Chronic Absenteeism Tracker</title>
    <style>
        :root { --primary: #2563eb; --primary-hover: #1d4ed8; --bg: #f8fafc; --card: #ffffff; --text: #0f172a; --muted: #64748b; --border: #e2e8f0; --danger-bg: #fef2f2; --danger-text: #991b1b; --success-bg: #f0fdf4; --success-text: #166534; }
        body { font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; }
        .navbar { background: var(--card); border-bottom: 1px solid var(--border); padding: 1rem 2rem; display: flex; justify-content: space-between; align-items: center; }
        .user-info { display: flex; align-items: center; gap: 1rem; }
        .container { max-width: 1200px; margin: 2rem auto; padding: 0 1.5rem; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 2rem; }
        .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1.25rem; margin-bottom: 2rem; }
        .metric-card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 1.25rem; }
        .metric-title { font-size: 0.875rem; color: var(--muted); margin-bottom: 0.5rem; }
        .metric-value { font-size: 1.75rem; font-weight: 700; }
        .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 1.5rem; margin-bottom: 2rem; }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.25rem; flex-wrap: wrap; gap: 1rem; }
        .card-title { font-size: 1.1rem; font-weight: 600; margin: 0; }
        .form-row { display: flex; gap: 0.75rem; align-items: center; }
        input, select, textarea { padding: 0.6rem 0.8rem; border: 1px solid var(--border); border-radius: 6px; font-size: 0.875rem; font-family: inherit; }
        .btn { background: var(--primary); color: white; border: none; padding: 0.6rem 1.2rem; border-radius: 6px; font-weight: 600; cursor: pointer; text-decoration: none; font-size: 0.875rem; }
        .btn:hover { background: var(--primary-hover); }
        .btn-outline { background: transparent; border: 1px solid var(--border); color: var(--text); }
        .btn-outline:hover { background: var(--bg); }
        .btn-sm { padding: 0.35rem 0.75rem; font-size: 0.78rem; border-radius: 4px; }
        
        /* Filter Buttons */
        .filter-btn-group { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
        .filter-btn { background: var(--card); border: 1px solid var(--border); padding: 0.5rem 1rem; border-radius: 6px; font-size: 0.85rem; font-weight: 600; cursor: pointer; color: var(--muted); transition: all 0.15s ease; }
        .filter-btn:hover { background: var(--bg); color: var(--text); }
        .filter-btn.active { background: var(--primary); color: white; border-color: var(--primary); }
        
        table { width: 100%; border-collapse: collapse; text-align: left; font-size: 0.875rem; }
        th, td { padding: 0.75rem 1rem; border-bottom: 1px solid var(--border); }
        th { background: #f8fafc; color: var(--muted); }
        .badge { padding: 0.25rem 0.625rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; }
        .badge-danger { background: var(--danger-bg); color: var(--danger-text); }
        .badge-success { background: var(--success-bg); color: var(--success-text); }
        .alert { padding: 0.75rem; border-radius: 6px; margin-bottom: 1rem; font-size: 0.875rem; }
        .alert-success { background: var(--success-bg); color: var(--success-text); border: 1px solid #bbf7d0; }
        .alert-error { background: var(--danger-bg); color: var(--danger-text); border: 1px solid #fecaca; }

        /* Intervention Modal */
        .modal { display: none; position: fixed; z-index: 100; left: 0; top: 0; width: 100%; height: 100%; background: rgba(15, 23, 42, 0.5); backdrop-filter: blur(2px); justify-content: center; align-items: center; }
        .modal-content { background: var(--card); width: 100%; max-width: 520px; border-radius: 12px; padding: 1.75rem; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.1); border: 1px solid var(--border); }
        .modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
        .close-btn { background: none; border: none; font-size: 1.5rem; cursor: pointer; color: var(--muted); }
    </style>
</head>
<body>
    <div class="navbar">
        <div style="font-weight:700; font-size:1.25rem;">📊 Chronic Absenteeism Tracker</div>
        <div class="user-info">
            <span style="font-size:0.875rem; color:var(--muted);">
                Logged in as: <strong>{{ current_user.username }}</strong> ({{ current_user.role }}) 
                {% if current_user.school %} &bull; <em>{{ current_user.school.name }}</em>{% endif %}
            </span>
            <a href="/logout" class="btn btn-outline" style="color:var(--danger-text);">Sign Out</a>
        </div>
    </div>

    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="alert alert-{{ category }}">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}

        <!-- Metrics Overview -->
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-title">Total Students</div>
                <div class="metric-value">{{ total_students }}</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">Chronic Students (&ge;10%)</div>
                <div class="metric-value" style="color: #dc2626;">{{ at_risk_count }}</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">Average Absenteeism Rate</div>
                <div class="metric-value">{{ "%.1f"|format(avg_rate) }}%</div>
            </div>
        </div>

        <!-- Add Student & Import CSV -->
        <div class="grid-2">
            <div class="card">
                <h3 class="card-title" style="margin-bottom:1rem;">Add Single Student</h3>
                <form method="POST" action="/add_student" style="display:flex; flex-direction:column; gap:0.75rem;">
                    <div class="form-row">
                        <input type="text" name="student_id" placeholder="Student ID" required style="flex:1;">
                        <input type="text" name="name" placeholder="Student Name" required style="flex:2;">
                    </div>
                    <div class="form-row">
                        <input type="text" name="grade" placeholder="Grade Level (e.g., 6, 7, 8)" style="flex:1;">
                        <input type="number" step="0.5" name="absences" placeholder="Absences" value="0" style="width:100px;">
                        <input type="number" name="tardies" placeholder="Tardies" value="0" style="width:90px;">
                        <button type="submit" class="btn">Add Student</button>
                    </div>
                </form>
            </div>

            <div class="card">
                <h3 class="card-title" style="margin-bottom:1rem;">Import Attendance CSV</h3>
                <form method="POST" action="/upload_csv" enctype="multipart/form-data" style="display:flex; flex-direction:column; gap:0.75rem;">
                    {% if current_user.role == 'Admin' %}
                    <div class="form-row">
                        <select name="school_id" style="flex:1;" required>
                            <option value="">Target School for Import...</option>
                            {% for school in schools %}
                            <option value="{{ school.id }}">{{ school.name }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    {% endif %}
                    <div class="form-row">
                        <input type="file" name="file" accept=".csv" required style="flex:1;">
                        <button type="submit" class="btn">Import CSV</button>
                    </div>
                    <small style="color:var(--muted);">Supports standard CSV files & District BI Attendance reports.</small>
                </form>
            </div>
        </div>

        <!-- Roster Table with Explicit Filter Buttons -->
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">Attendance Roster View</h3>
                <div style="display:flex; gap:1rem; align-items:center; flex-wrap:wrap;">
                    <!-- Filter Buttons -->
                    <div class="filter-btn-group">
                        <button class="filter-btn active" onclick="applyFilter('chronic', this)">Chronic Students</button>
                        <button class="filter-btn" onclick="applyFilter('most-absences', this)">Most Absences</button>
                        <button class="filter-btn" onclick="applyFilter('least-absences', this)">Least Absences</button>
                    </div>

                    <!-- Grade Level Selector Filter -->
                    <select id="gradeSelect" onchange="applyFilter(currentFilter, null)" style="padding:0.5rem; font-size:0.85rem; font-weight:600; color:var(--muted); border-radius:6px; border:1px solid var(--border);">
                        <option value="all">All Grade Levels</option>
                        {% for g in available_grades %}
                        <option value="{{ g }}">Grade {{ g }}</option>
                        {% endfor %}
                    </select>

                    <!-- Search Input -->
                    <input type="text" id="rosterSearch" onkeyup="applyFilter(currentFilter, null)" placeholder="Search name or ID..." style="width:200px;">
                </div>
            </div>

            <table>
                <thead>
                    <tr>
                        <th>Student ID</th>
                        <th>Name</th>
                        <th>Grade</th>
                        <th>Absences</th>
                        <th>Absenteeism %</th>
                        <th>Status</th>
                        <th>Interventions Logged</th>
                        <th style="text-align:right;">Action</th>
                    </tr>
                </thead>
                <tbody id="rosterTableBody">
                    {% for student in students %}
                    <tr class="roster-row" 
                        data-chronic="{{ 'true' if student.rate >= 10.0 else 'false' }}"
                        data-absences="{{ student.adjusted_absences }}"
                        data-grade="{{ student.grade }}">
                        <td><strong>{{ student.student_id }}</strong></td>
                        <td class="student-name">{{ student.name }}</td>
                        <td><span class="badge" style="background:#e2e8f0; color:#334155;">{{ student.grade }}</span></td>
                        <td><strong>{{ student.adjusted_absences }}</strong></td>
                        <td>{{ "%.1f"|format(student.rate) }}%</td>
                        <td>
                            {% if student.rate >= 10.0 %}
                                <span class="badge badge-danger">Chronic (&ge;10%)</span>
                            {% else %}
                                <span class="badge badge-success">On Track</span>
                            {% endif %}
                        </td>
                        <td>
                            <details>
                                <summary style="font-weight:600; font-size:0.8rem; cursor:pointer; color:var(--primary);">
                                    View Logs ({{ student.interventions|length }})
                                </summary>
                                <div style="margin-top:0.5rem; font-size:0.8rem; background:#f1f5f9; padding:0.5rem; border-radius:6px;">
                                    {% for log in student.interventions %}
                                        <div style="border-bottom: 1px solid var(--border); padding-bottom:0.25rem; margin-bottom:0.25rem;">
                                            <strong>{{ log.action_type }}</strong> &bull; <small>{{ log.timestamp }}</small><br>
                                            <span style="color:var(--muted);">By: {{ log.logged_by }}</span>
                                            {% if log.notes %}<p style="margin:0.25rem 0 0 0; font-style:italic;">"{{ log.notes }}"</p>{% endif %}
                                        </div>
                                    {% else %}
                                        <em style="color:var(--muted);">No interventions recorded yet.</em>
                                    {% endfor %}
                                </div>
                            </details>
                        </td>
                        <td style="text-align:right;">
                            <button class="btn btn-sm" onclick="openInterventionModal('{{ student.id }}', '{{ student.name }}')">+ Log Action</button>
                        </td>
                    </tr>
                    {% else %}
                    <tr>
                        <td colspan="8" style="text-align: center; color: var(--muted); padding: 2rem;">
                            No student record data available for this scope.
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <!-- Intervention Modal Structure -->
    <div id="interventionModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3 style="margin:0;">Log Student Intervention</h3>
                <button class="close-btn" onclick="closeInterventionModal()">&times;</button>
            </div>
            <form id="interventionForm" method="POST" action="/log_intervention">
                <input type="hidden" name="student_db_id" id="modalStudentDbId">
                <div style="margin-bottom:1rem;">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Student Name</label>
                    <input type="text" id="modalStudentName" disabled style="width:100%; background:#f1f5f9;">
                </div>
                <div style="margin-bottom:1rem;">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Intervention Type</label>
                    <select name="action_type" required style="width:100%;">
                        <option value="Parent Phone Call">Parent Phone Call</option>
                        <option value="Parent Email / Letter Sent">Parent Email / Letter Sent</option>
                        <option value="Student Attendance Meeting">Student Attendance Meeting</option>
                        <option value="Attendance Contract Signed">Attendance Contract Signed</option>
                        <option value="Home Visit">Home Visit</option>
                        <option value="Counselor Referral">Counselor Referral</option>
                    </select>
                </div>
                <div style="margin-bottom:1rem;">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Intervention Notes</label>
                    <textarea name="notes" rows="3" placeholder="Provide details about outcome or next steps..." style="width:100%; box-sizing:border-box;"></textarea>
                </div>
                <div style="display:flex; justify-content:flex-end; gap:0.5rem;">
                    <button type="button" class="btn btn-outline" onclick="closeInterventionModal()">Cancel</button>
                    <button type="submit" class="btn">Save Intervention</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Client-side Script -->
    <script>
        let currentFilter = 'chronic';

        function openInterventionModal(studentId, name) {
            document.getElementById('modalStudentDbId').value = studentId;
            document.getElementById('modalStudentName').value = name;
            document.getElementById('interventionModal').style.display = 'flex';
        }

        function closeInterventionModal() {
            document.getElementById('interventionModal').style.display = 'none';
        }

        function applyFilter(filterType, btnElement) {
            currentFilter = filterType;
            
            if (btnElement) {
                document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
                btnElement.classList.add('active');
            }

            const gradeFilter = document.getElementById('gradeSelect').value.toLowerCase();
            const searchQuery = document.getElementById('rosterSearch').value.toLowerCase();
            const tbody = document.getElementById('rosterTableBody');
            const rows = Array.from(tbody.querySelectorAll('.roster-row'));

            if (currentFilter === 'most-absences') {
                rows.sort((a, b) => parseFloat(b.getAttribute('data-absences')) - parseFloat(a.getAttribute('data-absences')));
            } else if (currentFilter === 'least-absences') {
                rows.sort((a, b) => parseFloat(a.getAttribute('data-absences')) - parseFloat(b.getAttribute('data-absences')));
            }

            rows.forEach(row => tbody.appendChild(row));

            rows.forEach(row => {
                const isChronic = row.getAttribute('data-chronic') === 'true';
                const rowGrade = row.getAttribute('data-grade').toLowerCase();
                const rowText = row.innerText.toLowerCase();

                let matchesFilter = true;
                if (currentFilter === 'chronic') {
                    matchesFilter = isChronic;
                }

                const matchesGrade = (gradeFilter === 'all') || (rowGrade === gradeFilter);
                const matchesSearch = rowText.includes(searchQuery);

                if (matchesFilter && matchesGrade && matchesSearch) {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                }
            });
        }

        window.addEventListener('DOMContentLoaded', () => {
            applyFilter('chronic', null);
        });
    </script>
</body>
</html>
"""

# --- App Initialization ---

def init_db():
    with app.app_context():
        try:
            db.session.execute(db.text('DROP SCHEMA public CASCADE;'))
            db.session.execute(db.text('CREATE SCHEMA public;'))
            db.session.commit()
        except Exception:
            db.session.rollback()

        db.create_all()

        mms = School.query.filter_by(code='HMS').first()
        if not mms:
            mms = School(name='Highland Middle School', code='HMS')
            db.session.add(mms)

        db.session.commit()

        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin', 
                password_hash=generate_password_hash('admin123'), 
                role='Admin'
            )
            db.session.add(admin)

        db.session.commit()

init_db()

# --- Helper Functions ---

def get_current_user():
    user_id = session.get('user_id')
    if user_id:
        return User.query.get(user_id)
    return None

# --- Routes ---

@app.route('/')
def index():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    if user.role == 'Admin':
        records = StudentRecord.query.all()
    else:
        records = StudentRecord.query.filter_by(school_id=user.school_id).all()

    schools = School.query.all()

    students_data = []
    total_students = len(records)
    at_risk_count = 0
    total_rate_sum = 0
    grades_set = set()

    for r in records:
        tardy_absences = r.tardies // TARDY_CONVERSION_FACTOR
        adjusted_absences = r.absences + tardy_absences
        rate = (adjusted_absences / r.total_days * 100) if r.total_days > 0 else 0

        if rate >= 10.0:
            at_risk_count += 1

        total_rate_sum += rate
        if r.grade and r.grade != 'N/A':
            grades_set.add(r.grade)

        interventions_logged = [{
            'action_type': item.action_type,
            'notes': item.notes,
            'logged_by': item.logged_by,
            'timestamp': item.timestamp.strftime('%b %d, %Y %H:%M')
        } for item in r.interventions]

        students_data.append({
            'id': r.id,
            'student_id': r.student_id,
            'name': r.name,
            'grade': r.grade or 'N/A',
            'school_name': r.school.name if r.school else 'Unassigned',
            'absences': r.absences,
            'tardies': r.tardies,
            'adjusted_absences': adjusted_absences,
            'rate': rate,
            'interventions': interventions_logged
        })

    avg_rate = (total_rate_sum / total_students) if total_students > 0 else 0.0

    return render_template_string(
        INDEX_HTML,
        current_user=user,
        students=students_data,
        schools=schools,
        total_students=total_students,
        at_risk_count=at_risk_count,
        avg_rate=avg_rate,
        available_grades=sorted(list(grades_set))
    )

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            return redirect(url_for('index'))

        flash('Invalid username or password.', 'error')

    return render_template_string(LOGIN_HTML)

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('index'))

@app.route('/log_intervention', methods=['POST'])
def log_intervention():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    student_db_id = request.form.get('student_db_id')
    action_type = request.form.get('action_type')
    notes = request.form.get('notes')

    if student_db_id and action_type:
        intervention = Intervention(
            student_record_id=int(student_db_id),
            action_type=action_type,
            notes=notes.strip() if notes else '',
            logged_by=user.username
        )
        db.session.add(intervention)
        db.session.commit()
        flash('Intervention logged successfully!', 'success')

    return redirect(url_for('index'))

@app.route('/add_student', methods=['POST'])
def add_student():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    student_id = request.form.get('student_id')
    name = request.form.get('name')
    grade = request.form.get('grade', 'N/A')
    absences = float(request.form.get('absences', 0.0))
    tardies = int(request.form.get('tardies', 0))

    school_id = user.school_id if user.role != 'Admin' else request.form.get('school_id')

    if student_id and name:
        student = StudentRecord(
            student_id=student_id.strip(),
            name=name.strip(),
            grade=grade.strip() if grade else 'N/A',
            school_id=school_id,
            absences=absences,
            tardies=tardies
        )
        db.session.add(student)
        db.session.commit()
        flash('Student added successfully!', 'success')

    return redirect(url_for('index'))

@app.route('/upload_csv', methods=['POST'])
def upload_csv():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    if 'file' not in request.files:
        flash('No file provided.', 'error')
        return redirect(url_for('index'))

    file = request.files['file']
    if file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('index'))

    school_id = user.school_id if user.role != 'Admin' else request.form.get('school_id')

    try:
        content = file.stream.read().decode('utf-8-sig')
        stream = io.StringIO(content, newline=None)
        csv_input = csv.DictReader(stream)

        if school_id:
            StudentRecord.query.filter_by(school_id=school_id).delete()

        imported_count = 0
        for row in csv_input:
            clean_row = {str(k).strip().lower(): str(v).strip() for k, v in row.items() if k}

            def parse_float(val, default=0.0):
                try:
                    return float(val) if val else default
                except ValueError:
                    return default

            def parse_int(val, default=0):
                try:
                    return int(float(val)) if val else default
                except ValueError:
                    return default

            student_id = clean_row.get('studentnumber') or clean_row.get('student_id') or ''
            name = clean_row.get('studentname') or clean_row.get('student_name') or ''
            grade = clean_row.get('grade') or clean_row.get('grade_level') or 'N/A'

            absences_raw = clean_row.get('currentschoolabsences7') or clean_row.get('absences') or '0'
            absences = parse_float(absences_raw)

            tardies = parse_int(clean_row.get('tardies') or '0')
            
            total_days_raw = clean_row.get('currentschoolmembershipdays11') or clean_row.get('total_days') or '180'
            total_days = parse_int(parse_float(total_days_raw), default=180)

            if student_id or name:
                student = StudentRecord(
                    student_id=student_id if student_id else "N/A",
                    name=name if name else "Unknown Student",
                    grade=str(grade),
                    school_id=school_id,
                    absences=absences,
                    tardies=tardies,
                    total_days=total_days if total_days > 0 else 180
                )
                db.session.add(student)
                imported_count += 1

        db.session.commit()
        if imported_count > 0:
            flash(f'Success! Imported {imported_count} student record(s).', 'success')
        else:
            flash('CSV uploaded, but 0 valid student rows were found.', 'error')

    except Exception as e:
        db.session.rollback()
        flash(f'Error processing CSV: {str(e)}', 'error')

    return redirect(url_for('index'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

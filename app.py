import os
import csv
import io
import math
from datetime import datetime
from flask import (
    Flask, render_template_string, request, redirect, 
    url_for, session, flash, jsonify
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError

# -----------------------------------------------------------------------------
# App & Database Configuration
# -----------------------------------------------------------------------------
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///attendance_tracker.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# -----------------------------------------------------------------------------
# Database Models
# -----------------------------------------------------------------------------
class School(db.Model):
    __tablename__ = 'schools'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    code = db.Column(db.String(20), nullable=False, unique=True)
    users = db.relationship('User', backref='school', lazy=True)
    students = db.relationship('StudentRecord', backref='school', lazy=True, cascade="all, delete-orphan")

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='Staff')  # 'Admin' or 'Staff'
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=True)

class StudentRecord(db.Model):
    __tablename__ = 'student_records'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    grade = db.Column(db.String(20), nullable=False, default='N/A')
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    absences = db.Column(db.Float, default=0.0)
    tardies = db.Column(db.Integer, default=0)
    total_days = db.Column(db.Float, default=180.0)
    present_fte = db.Column(db.Float, nullable=True)
    interventions = db.relationship('Intervention', backref='student', lazy=True, cascade="all, delete-orphan")

class Intervention(db.Model):
    __tablename__ = 'interventions'
    id = db.Column(db.Integer, primary_key=True)
    student_record_id = db.Column(db.Integer, db.ForeignKey('student_records.id'), nullable=False)
    action_type = db.Column(db.String(50), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    logged_by = db.Column(db.String(80), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# -----------------------------------------------------------------------------
# HTML Templates
# -----------------------------------------------------------------------------
LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - Attendance Tracker</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light d-flex align-items-center vh-100">
    <div class="container">
        <div class="row justify-content-center">
            <div class="col-md-4">
                <div class="card shadow-sm">
                    <div class="card-body p-4">
                        <h3 class="card-title text-center mb-4">Sign In</h3>
                        {% with messages = get_flashed_messages(with_categories=true) %}
                            {% if messages %}
                                {% for category, message in messages %}
                                    <div class="alert alert-{{ 'danger' if category == 'error' else 'info' }} p-2">{{ message }}</div>
                                {% endfor %}
                            {% endif %}
                        {% endwith %}
                        <form action="{{ url_for('login') }}" method="POST">
                            <div class="mb-3">
                                <label class="form-label">Username</label>
                                <input type="text" name="username" class="form-control" required autofocus>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">Password</label>
                                <input type="password" name="password" class="form-control" required>
                            </div>
                            <button type="submit" class="btn btn-primary w-100">Login</button>
                        </form>
                    </div>
                </div>
            </div>
        </div>
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
    <title>Attendance Tracker</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark mb-4">
        <div class="container-fluid">
            <a class="navbar-brand" href="#">Attendance Dashboard</a>
            <div class="d-flex text-white align-items-center">
                <span class="me-3">Logged in as: <strong>{{ current_user.username }}</strong> ({{ current_user.role }})</span>
                <a href="{{ url_for('logout') }}" class="btn btn-outline-light btn-sm">Logout</a>
            </div>
        </div>
    </nav>

    <div class="container-fluid px-4">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ 'danger' if category == 'error' else 'info' }} alert-dismissible fade show" role="alert">
                        {{ message }}
                        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        <!-- Metrics Row -->
        <div class="row mb-4">
            <div class="col-md-3">
                <div class="card text-white bg-primary">
                    <div class="card-body">
                        <h6 class="card-title">School</h6>
                        <h3>{{ active_school_name }}</h3>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-white bg-secondary">
                    <div class="card-body">
                        <h6 class="card-title">Total Students</h6>
                        <h3>{{ total_students }}</h3>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-white bg-warning">
                    <div class="card-body">
                        <h6 class="card-title">At-Risk / Chronically Absent</h6>
                        <h3>{{ at_risk_count }}</h3>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-white bg-danger">
                    <div class="card-body">
                        <h6 class="card-title">Chronic Absenteeism Rate</h6>
                        <h3>{{ "%.1f"|format(chronic_rate) }}%</h3>
                    </div>
                </div>
            </div>
        </div>

        <!-- Controls / Admin Row -->
        <div class="card mb-4">
            <div class="card-body">
                <form method="GET" action="{{ url_for('index') }}" class="row g-3 align-items-center">
                    {% if current_user.role == 'Admin' %}
                    <div class="col-md-3">
                        <label class="form-label fw-bold">Select School:</label>
                        <select name="school_id" class="form-select" onchange="this.form.submit()">
                            <option value="all" {% if selected_school_id == 'all' %}selected{% endif %}>All Schools</option>
                            {% for sch in schools %}
                                <option value="{{ sch.id }}" {% if selected_school_id == (sch.id|string) %}selected{% endif %}>{{ sch.name }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    {% endif %}

                    <div class="col-md-2">
                        <label class="form-label fw-bold">Grade:</label>
                        <select name="grade" class="form-select" onchange="this.form.submit()">
                            <option value="all" {% if selected_grade == 'all' %}selected{% endif %}>All Grades</option>
                            {% for g in available_grades %}
                                <option value="{{ g }}" {% if selected_grade == g %}selected{% endif %}>Grade {{ g }}</option>
                            {% endfor %}
                        </select>
                    </div>

                    <div class="col-md-2">
                        <label class="form-label fw-bold">Sort / Filter:</label>
                        <select name="filter" class="form-select" onchange="this.form.submit()">
                            <option value="all" {% if selected_filter == 'all' %}selected{% endif %}>All Records</option>
                            <option value="chronic" {% if selected_filter == 'chronic' %}selected{% endif %}>Chronically Absent (&lt;90%)</option>
                            <option value="most-absences" {% if selected_filter == 'most-absences' %}selected{% endif %}>Most Absences</option>
                            <option value="least-absences" {% if selected_filter == 'least-absences' %}selected{% endif %}>Least Absences</option>
                        </select>
                    </div>

                    <div class="col-md-3">
                        <label class="form-label fw-bold">Search:</label>
                        <input type="text" name="q" class="form-control" placeholder="Search by name or ID..." value="{{ search_query }}">
                    </div>

                    <div class="col-md-2 d-flex align-items-end">
                        <button type="submit" class="btn btn-primary me-2">Apply</button>
                        <a href="{{ url_for('index') }}" class="btn btn-outline-secondary">Reset</a>
                    </div>
                </form>
            </div>
        </div>

        <!-- Action Modals Bar -->
        <div class="mb-3 d-flex gap-2">
            <button class="btn btn-success" data-bs-toggle="modal" data-bs-target="#uploadCsvModal">Import CSV</button>
            <button class="btn btn-outline-primary" data-bs-toggle="modal" data-bs-target="#addStudentModal">Add Single Student</button>
            {% if current_user.role == 'Admin' %}
                <button class="btn btn-outline-dark" data-bs-toggle="modal" data-bs-target="#addSchoolModal">Add School</button>
                <button class="btn btn-outline-dark" data-bs-toggle="modal" data-bs-target="#addUserModal">Add User</button>
                <button class="btn btn-outline-danger ms-auto" data-bs-toggle="modal" data-bs-target="#clearDataModal">Clear School Data</button>
            {% endif %}
        </div>

        <!-- Student Table -->
        <div class="card">
            <div class="card-body p-0">
                <table class="table table-hover table-striped mb-0">
                    <thead class="table-dark">
                        <tr>
                            <th>Student ID</th>
                            <th>Name</th>
                            <th>Grade</th>
                            <th>School</th>
                            <th>Adjusted Absences</th>
                            <th>Present FTE %</th>
                            <th>Status</th>
                            <th>Interventions</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for s in students %}
                        <tr>
                            <td>{{ s.student_id }}</td>
                            <td>{{ s.name }}</td>
                            <td>{{ s.grade }}</td>
                            <td>{{ s.school_name }}</td>
                            <td>{{ "%.1f"|format(s.adjusted_absences) }}</td>
                            <td>{{ "%.1f"|format(s.present_fte_pct) }}%</td>
                            <td>
                                {% if s.is_chronic %}
                                    <span class="badge bg-danger">Chronically Absent</span>
                                {% else %}
                                    <span class="badge bg-success">On Track</span>
                                {% endif %}
                            </td>
                            <td>
                                <span class="badge bg-info">{{ s.interventions|length }} Recorded</span>
                            </td>
                            <td>
                                <button class="btn btn-sm btn-primary" data-bs-toggle="modal" data-bs-target="#interventionModal{{ s.id }}">
                                    Log Action
                                </button>
                            </td>
                        </tr>

                        <!-- Intervention Modal -->
                        <div class="modal fade" id="interventionModal{{ s.id }}" tabindex="-1">
                            <div class="modal-dialog">
                                <div class="modal-content">
                                    <form action="{{ url_for('log_intervention') }}" method="POST">
                                        <div class="modal-header">
                                            <h5 class="modal-title">Log Intervention - {{ s.name }}</h5>
                                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                                        </div>
                                        <div class="modal-body">
                                            <input type="hidden" name="student_db_id" value="{{ s.id }}">
                                            <div class="mb-3">
                                                <label class="form-label">Action Type</label>
                                                <select name="action_type" class="form-select" required>
                                                    <option value="Parent Contact">Parent Contact</option>
                                                    <option value="Student Conference">Student Conference</option>
                                                    <option value="Attendance Contract">Attendance Contract</option>
                                                    <option value="Home Visit">Home Visit</option>
                                                    <option value="Truancy Referral">Truancy Referral</option>
                                                </select>
                                            </div>
                                            <div class="mb-3">
                                                <label class="form-label">Notes</label>
                                                <textarea name="notes" class="form-control" rows="3"></textarea>
                                            </div>
                                            <h6>History:</h6>
                                            <ul class="list-group list-group-flush max-vh-25 overflow-auto">
                                                {% for i in s.interventions %}
                                                    <li class="list-group-item small p-2">
                                                        <strong>{{ i.action_type }}</strong> by {{ i.logged_by }} on {{ i.timestamp.strftime('%Y-%m-%d') }}<br>
                                                        <span class="text-muted">{{ i.notes }}</span>
                                                    </li>
                                                {% else %}
                                                    <li class="list-group-item small text-muted">No prior interventions.</li>
                                                {% endfor %}
                                            </ul>
                                        </div>
                                        <div class="modal-footer">
                                            <button type="submit" class="btn btn-primary">Save Intervention</button>
                                        </div>
                                    </form>
                                </div>
                            </div>
                        </div>
                        {% else %}
                        <tr>
                            <td colspan="9" class="text-center py-4 text-muted">No student records found matching the criteria.</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            
            <!-- Pagination Footer -->
            {% if total_pages > 1 %}
            <div class="card-footer d-flex justify-content-between align-items-center">
                <span>Showing {{ display_count }} total entries</span>
                <nav>
                    <ul class="pagination mb-0">
                        {% for p in range(1, total_pages + 1) %}
                            <li class="page-item {% if p == current_page %}active{% endif %}">
                                <a class="page-link" href="{{ url_for('index', page=p, school_id=selected_school_id, grade=selected_grade, filter=selected_filter, q=search_query) }}">{{ p }}</a>
                            </li>
                        {% endfor %}
                    </ul>
                </nav>
            </div>
            {% endif %}
        </div>
    </div>

    <!-- Modals -->
    <!-- CSV Upload Modal -->
    <div class="modal fade" id="uploadCsvModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content">
                <form action="{{ url_for('upload_csv') }}" method="POST" enctype="multipart/form-data">
                    <div class="modal-header">
                        <h5 class="modal-title">Import CSV Data</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        {% if current_user.role == 'Admin' %}
                        <div class="mb-3">
                            <label class="form-label">Target School</label>
                            <select name="school_id" class="form-select" required>
                                {% for sch in schools %}
                                    <option value="{{ sch.id }}">{{ sch.name }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        {% endif %}
                        <div class="mb-3">
                            <label class="form-label">Select CSV File</label>
                            <input type="file" name="file" class="form-control" accept=".csv" required>
                            <div class="form-text">Headers supported: Student_ID, Name, Grade, Absences, Tardies, Present_FTE</div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="submit" class="btn btn-primary">Upload & Process</button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <!-- Add Student Modal -->
    <div class="modal fade" id="addStudentModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content">
                <form action="{{ url_for('add_student') }}" method="POST">
                    <div class="modal-header">
                        <h5 class="modal-title">Add Student Record</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        {% if current_user.role == 'Admin' %}
                        <div class="mb-3">
                            <label class="form-label">School</label>
                            <select name="school_id" class="form-select" required>
                                {% for sch in schools %}
                                    <option value="{{ sch.id }}">{{ sch.name }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        {% endif %}
                        <div class="mb-3">
                            <label class="form-label">Student ID</label>
                            <input type="text" name="student_id" class="form-control" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Full Name</label>
                            <input type="text" name="name" class="form-control" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Grade</label>
                            <input type="text" name="grade" class="form-control" placeholder="e.g. 9, 10, 11, 12">
                        </div>
                        <div class="row">
                            <div class="col-6 mb-3">
                                <label class="form-label">Absences</label>
                                <input type="number" step="0.5" name="absences" class="form-control" value="0">
                            </div>
                            <div class="col-6 mb-3">
                                <label class="form-label">Tardies</label>
                                <input type="number" name="tardies" class="form-control" value="0">
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="submit" class="btn btn-primary">Save Student</button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <!-- Admin: Add School Modal -->
    {% if current_user.role == 'Admin' %}
    <div class="modal fade" id="addSchoolModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content">
                <form action="{{ url_for('add_school') }}" method="POST">
                    <div class="modal-header">
                        <h5 class="modal-title">Add New School</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label">School Name</label>
                            <input type="text" name="name" class="form-control" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">School Code</label>
                            <input type="text" name="code" class="form-control" required placeholder="e.g. EHS">
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="submit" class="btn btn-primary">Create School</button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <!-- Admin: Add User Modal -->
    <div class="modal fade" id="addUserModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content">
                <form action="{{ url_for('add_user') }}" method="POST">
                    <div class="modal-header">
                        <h5 class="modal-title">Add System User</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label">Username</label>
                            <input type="text" name="username" class="form-control" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Password</label>
                            <input type="password" name="password" class="form-control" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Role</label>
                            <select name="role" class="form-select">
                                <option value="Staff">Staff</option>
                                <option value="Admin">Admin</option>
                            </select>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Assigned School (for Staff)</label>
                            <select name="school_id" class="form-select">
                                <option value="">None (Global)</option>
                                {% for sch in schools %}
                                    <option value="{{ sch.id }}">{{ sch.name }}</option>
                                {% endfor %}
                            </select>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="submit" class="btn btn-primary">Create User</button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <!-- Admin: Clear Data Modal -->
    <div class="modal fade" id="clearDataModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content">
                <form action="{{ url_for('clear_school_data') }}" method="POST">
                    <div class="modal-header">
                        <h5 class="modal-title text-danger">Clear School Attendance Records</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <p class="text-danger">Warning: This action will permanently remove student records and logged interventions for the selected school.</p>
                        <div class="mb-3">
                            <label class="form-label">Select School to Clear</label>
                            <select name="school_id" class="form-select" required>
                                {% for sch in schools %}
                                    <option value="{{ sch.id }}">{{ sch.name }}</option>
                                {% endfor %}
                            </select>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="submit" class="btn btn-danger">Confirm Delete</button>
                    </div>
                </form>
            </div>
        </div>
    </div>
    {% endif %}

    <script href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

# -----------------------------------------------------------------------------
# Helpers & Database Initialization
# -----------------------------------------------------------------------------
def get_current_user():
    user_id = session.get('user_id')
    if user_id:
        return User.query.get(user_id)
    return None

def init_db():
    db.create_all()
    # Seed default Admin and Default School if empty
    if not School.query.first():
        default_school = School(name="Central High School", code="CHS")
        db.session.add(default_school)
        db.session.commit()
        
    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            password_hash=generate_password_hash('admin123'),
            role='Admin'
        )
        db.session.add(admin)
        db.session.commit()

# Initialize DB structure within application context
with app.app_context():
    init_db()

# -----------------------------------------------------------------------------
# Routes & Controllers
# -----------------------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            flash('Logged in successfully.', 'info')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password.', 'error')

    return render_template_string(LOGIN_HTML)

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/')
def index():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    schools = School.query.all()
    
    # URL parameters for filtering & pagination
    selected_school_id = request.args.get('school_id', 'all')
    selected_filter = request.args.get('filter', 'all')
    selected_grade = request.args.get('grade', 'all')
    search_query = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 25

    # Enforce staff boundaries
    if user.role != 'Admin':
        selected_school_id = str(user.school_id) if user.school_id else 'all'

    # Build base student record query
    query = StudentRecord.query
    if selected_school_id != 'all' and selected_school_id.isdigit():
        query = query.filter_by(school_id=int(selected_school_id))
        active_school = School.query.get(int(selected_school_id))
        active_school_name = active_school.name if active_school else 'Unknown'
    else:
        active_school_name = 'All Schools'

    records = query.all()

    # Dynamic calculation of attendance metrics
    all_parsed_students = []
    at_risk_count = 0
    total_students = len(records)
    grades_set = set()

    for r in records:
        adjusted_absences = r.absences + (r.tardies * 0.25) # 4 tardies = 1 absence equivalency
        
        if r.present_fte is not None:
            fte_ratio = r.present_fte if r.present_fte <= 1.0 else (r.present_fte / 100.0)
            present_fte_pct = fte_ratio * 100.0
        elif r.total_days and r.total_days > 0:
            present_fte_pct = max(0.0, ((r.total_days - adjusted_absences) / r.total_days) * 100.0)
        else:
            present_fte_pct = 100.0

        is_chronic = present_fte_pct < 90.0
        if is_chronic:
            at_risk_count += 1

        grade_str = str(r.grade).strip() if r.grade else 'N/A'
        if grade_str:
            grades_set.add(grade_str)

        all_parsed_students.append({
            'id': r.id,
            'student_id': r.student_id,
            'name': r.name,
            'grade': grade_str,
            'school_name': r.school.name if r.school else 'Unassigned',
            'adjusted_absences': adjusted_absences,
            'present_fte_pct': present_fte_pct,
            'is_chronic': is_chronic,
            'interventions': r.interventions
        })

    chronic_rate = (at_risk_count / total_students * 100.0) if total_students > 0 else 0.0
    available_grades = sorted(list(grades_set), key=lambda x: (x.isdigit(), int(x) if x.isdigit() else x))

    # Apply Filters
    filtered_students = all_parsed_students

    if selected_grade != 'all':
        filtered_students = [s for s in filtered_students if s['grade'] == selected_grade]

    if search_query:
        sq = search_query.lower()
        filtered_students = [
            s for s in filtered_students 
            if sq in s['name'].lower() or sq in str(s['student_id']).lower()
        ]

    if selected_filter == 'chronic':
        filtered_students = [s for s in filtered_students if s['is_chronic']]
        filtered_students.sort(key=lambda x: x['present_fte_pct'])
    elif selected_filter == 'most-absences':
        filtered_students.sort(key=lambda x: x['adjusted_absences'], reverse=True)
    elif selected_filter == 'least-absences':
        filtered_students.sort(key=lambda x: x['adjusted_absences'])

    display_count = len(filtered_students)
    total_pages = max(1, math.ceil(display_count / per_page))
    page = min(max(1, page), total_pages)
    
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_students = filtered_students[start_idx:end_idx]

    return render_template_string(
        INDEX_HTML,
        current_user=user,
        schools=schools,
        selected_school_id=selected_school_id,
        selected_filter=selected_filter,
        selected_grade=selected_grade,
        search_query=search_query,
        active_school_name=active_school_name,
        total_students=total_students,
        at_risk_count=at_risk_count,
        chronic_rate=chronic_rate,
        available_grades=available_grades,
        students=paginated_students,
        display_count=display_count,
        current_page=page,
        total_pages=total_pages
    )

@app.route('/add_school', methods=['POST'])
def add_school():
    user = get_current_user()
    if not user or user.role != 'Admin':
        flash('Unauthorized action.', 'error')
        return redirect(url_for('index'))

    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip().upper()

    if not name or not code:
        flash('School Name and Code are required.', 'error')
        return redirect(url_for('index'))

    try:
        new_school = School(name=name, code=code)
        db.session.add(new_school)
        db.session.commit()
        flash(f'School "{name}" added successfully.', 'info')
    except IntegrityError:
        db.session.rollback()
        flash(f'School name or code already exists.', 'error')

    return redirect(url_for('index'))

@app.route('/add_user', methods=['POST'])
def add_user():
    user = get_current_user()
    if not user or user.role != 'Admin':
        flash('Unauthorized action.', 'error')
        return redirect(url_for('index'))

    username = request.form.get('username', '').strip()
    password = request.form.get('password')
    role = request.form.get('role', 'Staff')
    school_id = request.form.get('school_id')

    if not username or not password:
        flash('Username and Password are required.', 'error')
        return redirect(url_for('index'))

    s_id = int(school_id) if school_id and school_id.isdigit() else None

    try:
        new_user = User(
            username=username,
            password_hash=generate_password_hash(password),
            role=role,
            school_id=s_id
        )
        db.session.add(new_user)
        db.session.commit()
        flash(f'User "{username}" created successfully.', 'info')
    except IntegrityError:
        db.session.rollback()
        flash('Username already exists.', 'error')

    return redirect(url_for('index'))

@app.route('/add_student', methods=['POST'])
def add_student():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    target_school_id = user.school_id
    if user.role == 'Admin':
        req_school_id = request.form.get('school_id')
        if req_school_id and req_school_id.isdigit():
            target_school_id = int(req_school_id)

    if not target_school_id:
        flash('Please select or assign a target school for this student.', 'error')
        return redirect(url_for('index'))

    student_id = request.form.get('student_id', '').strip()
    name = request.form.get('name', '').strip()
    grade = request.form.get('grade', 'N/A').strip() or 'N/A'
    
    try:
        absences = float(request.form.get('absences', 0))
        tardies = int(request.form.get('tardies', 0))
    except ValueError:
        flash('Invalid numerical values for absences or tardies.', 'error')
        return redirect(url_for('index'))

    existing = StudentRecord.query.filter_by(student_id=student_id, school_id=target_school_id).first()
    if existing:
        existing.name = name
        existing.grade = grade
        existing.absences = absences
        existing.tardies = tardies
        flash(f'Updated student record for {name}.', 'info')
    else:
        new_student = StudentRecord(
            student_id=student_id,
            name=name,
            grade=grade,
            school_id=target_school_id,
            absences=absences,
            tardies=tardies
        )
        db.session.add(new_student)
        flash(f'Added student {name}.', 'info')

    db.session.commit()
    return redirect(url_for('index'))

@app.route('/upload_csv', methods=['POST'])
def upload_csv():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    target_school_id = user.school_id
    if user.role == 'Admin':
        req_school_id = request.form.get('school_id')
        if req_school_id and req_school_id.isdigit():
            target_school_id = int(req_school_id)

    if not target_school_id:
        flash('Please select a target school before uploading data.', 'error')
        return redirect(url_for('index'))

    file = request.files.get('file')
    if not file or not file.filename.endswith('.csv'):
        flash('Please select a valid CSV file.', 'error')
        return redirect(url_for('index'))

    stream = io.StringIO(file.stream.read().decode("utf-8", errors="ignore"), newline=None)
    csv_reader = csv.DictReader(stream)

    if not csv_reader.fieldnames:
        flash('The CSV file appears to be empty or malformed.', 'error')
        return redirect(url_for('index'))

    # Normalize header mapping
    headers = {h.strip().lower(): h for h in csv_reader.fieldnames}
    
    # Identify key columns flexible to SIS export variations
    id_col = headers.get('student_id') or headers.get('student id') or headers.get('id') or headers.get('student_number')
    name_col = headers.get('name') or headers.get('student name') or headers.get('student_name')
    grade_col = headers.get('grade') or headers.get('grade level') or headers.get('grade_level')
    absences_col = headers.get('absences') or headers.get('absent') or headers.get('total_absences')
    tardies_col = headers.get('tardies') or headers.get('tardy') or headers.get('total_tardies')
    fte_col = headers.get('present_fte') or headers.get('presentfte') or headers.get('col v') or headers.get('col_v') or headers.get('fte')

    if not id_col or not name_col:
        flash('CSV must contain at least "Student ID" and "Name" columns.', 'error')
        return redirect(url_for('index'))

    imported_count = 0
    updated_count = 0

    for row in csv_reader:
        sid = str(row.get(id_col, '')).strip()
        sname = str(row.get(name_col, '')).strip()
        if not sid or not sname:
            continue

        sgrade = str(row.get(grade_col, 'N/A')).strip() if grade_col else 'N/A'
        
        try:
            sabs = float(row.get(absences_col, 0)) if absences_col and row.get(absences_col) else 0.0
        except ValueError:
            sabs = 0.0

        try:
            stard = int(float(row.get(tardies_col, 0))) if tardies_col and row.get(tardies_col) else 0
        except ValueError:
            stard = 0

        sfte = None
        if fte_col and row.get(fte_col):
            try:
                raw_fte = row.get(fte_col).replace('%', '').strip()
                sfte = float(raw_fte)
            except ValueError:
                sfte = None

        existing = StudentRecord.query.filter_by(student_id=sid, school_id=target_school_id).first()
        if existing:
            existing.name = sname
            existing.grade = sgrade or existing.grade
            existing.absences = sabs
            existing.tardies = stard
            existing.present_fte = sfte
            updated_count += 1
        else:
            new_record = StudentRecord(
                student_id=sid,
                name=sname,
                grade=sgrade or 'N/A',
                school_id=target_school_id,
                absences=sabs,
                tardies=stard,
                present_fte=sfte
            )
            db.session.add(new_record)
            imported_count += 1

    db.session.commit()
    flash(f'CSV Processed successfully: {imported_count} imported, {updated_count} updated.', 'info')
    return redirect(url_for('index'))

@app.route('/log_intervention', methods=['POST'])
def log_intervention():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    student_db_id = request.form.get('student_db_id')
    action_type = request.form.get('action_type')
    notes = request.form.get('notes', '').strip()

    if not student_db_id or not action_type:
        flash('Missing required intervention details.', 'error')
        return redirect(url_for('index'))

    student = StudentRecord.query.get(student_db_id)
    if not student:
        flash('Student record not found.', 'error')
        return redirect(url_for('index'))

    # Security check for Non-Admin Staff logging for other schools
    if user.role != 'Admin' and student.school_id != user.school_id:
        flash('Unauthorized to modify records outside your assigned school.', 'error')
        return redirect(url_for('index'))

    intervention = Intervention(
        student_record_id=student.id,
        action_type=action_type,
        notes=notes,
        logged_by=user.username
    )
    db.session.add(intervention)
    db.session.commit()

    flash(f'Intervention logged for {student.name}.', 'info')
    return redirect(url_for('index'))

@app.route('/clear_school_data', methods=['POST'])
def clear_school_data():
    user = get_current_user()
    if not user or user.role != 'Admin':
        flash('Unauthorized action.', 'error')
        return redirect(url_for('index'))

    school_id = request.form.get('school_id')
    if not school_id or school_id == 'all':
        flash('Invalid school selected for clearing.', 'error')
        return redirect(url_for('index'))

    try:
        s_id = int(school_id)
        school = School.query.get(s_id)
        if school:
            StudentRecord.query.filter_by(school_id=s_id).delete()
            db.session.commit()
            flash(f'All student records for {school.name} have been cleared.', 'info')
    except ValueError:
        flash('Invalid school ID format.', 'error')

    return redirect(url_for('index'))

# -----------------------------------------------------------------------------
# Entry Point
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)

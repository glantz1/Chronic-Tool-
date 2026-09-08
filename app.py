import os
import io
import csv
import math
from functools import wraps
from flask import (
    Flask, render_template_string, request, redirect, 
    url_for, session, flash
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ------------------------------------------------------------------------------
# Models
# ------------------------------------------------------------------------------
class School(db.Model):
    __tablename__ = 'school'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    users = db.relationship('User', backref='school', lazy=True)
    records = db.relationship('StudentRecord', backref='school', lazy=True)

class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='User')  # 'Admin' or 'User'
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class StudentRecord(db.Model):
    __tablename__ = 'student_record'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    grade = db.Column(db.String(20), nullable=False, default='N/A')
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    absences = db.Column(db.Float, default=0.0)
    tardies = db.Column(db.Integer, default=0)
    total_days = db.Column(db.Float, default=180.0)
    present_fte = db.Column(db.Float, nullable=True)  # Direct value from CSV

    interventions = db.relationship(
        'Intervention', 
        backref='student', 
        lazy=True, 
        cascade="all, delete-orphan", 
        foreign_keys='Intervention.student_record_id'
    )

class Intervention(db.Model):
    __tablename__ = 'intervention'
    id = db.Column(db.Integer, primary_key=True)
    student_record_id = db.Column(db.Integer, db.ForeignKey('student_record.id'), nullable=False)
    notes = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

# ------------------------------------------------------------------------------
# Helpers & Auth Decorators
# ------------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to access this page.", "error")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ------------------------------------------------------------------------------
# HTML Templates
# ------------------------------------------------------------------------------
LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Login - Attendance Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f8f9fa; }
        .login-card { max-width: 400px; margin: 100px auto; }
    </style>
</head>
<body>
    <div class="container">
        <div class="card login-card shadow-sm">
            <div class="card-body p-4">
                <h3 class="card-title text-center mb-4">Dashboard Login</h3>
                {% with messages = get_flashed_messages(with_categories=true) %}
                  {% if messages %}
                    {% for category, message in messages %}
                      <div class="alert alert-{{ 'danger' if category == 'error' else 'success' }} alert-dismissible fade show" role="alert">
                        {{ message }}
                        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                      </div>
                    {% endfor %}
                  {% endif %}
                {% endwith %}
                <form method="POST" action="{{ url_for('login') }}">
                    <div class="mb-3">
                        <label class="form-label">Username</label>
                        <input type="text" name="username" class="form-control" required>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Password</label>
                        <input type="password" name="password" class="form-control" required>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Sign In</button>
                </form>
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
    <title>Attendance Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f4f6f9; }
        .badge-chronic { background-color: #dc3545; color: white; padding: 0.35em 0.65em; border-radius: 0.25rem; font-size: 0.85em; }
        .badge-ontrack { background-color: #198754; color: white; padding: 0.35em 0.65em; border-radius: 0.25rem; font-size: 0.85em; }
        .kpi-card { border-left: 4px solid #0d6efd; }
        .kpi-card.danger { border-left-color: #dc3545; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container-fluid">
            <a class="navbar-brand" href="{{ url_for('index') }}">Attendance Dashboard</a>
            <div class="d-flex align-items-center text-white">
                <span class="me-3">Logged in as: <strong>{{ current_user.username }}</strong> ({{ current_user.role }})</span>
                <a href="{{ url_for('logout') }}" class="btn btn-outline-light btn-sm">Logout</a>
            </div>
        </div>
    </nav>

    <div class="container-fluid my-4 px-4">
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="alert alert-{{ 'danger' if category == 'error' else 'success' }} alert-dismissible fade show" role="alert">
                {{ message }}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
              </div>
            {% endfor %}
          {% endif %}
        {% endwith %}

        <!-- KPI Cards -->
        <div class="row g-3 mb-4">
            <div class="col-md-4">
                <div class="card shadow-sm kpi-card p-3">
                    <div class="text-muted small">Active School Filter</div>
                    <div class="h4 mb-0 fw-bold">{{ active_school_name }}</div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card shadow-sm kpi-card p-3">
                    <div class="text-muted small">Total Filtered Students</div>
                    <div class="h4 mb-0 fw-bold">{{ total_students }}</div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card shadow-sm kpi-card danger p-3">
                    <div class="text-muted small">Chronically Absent (FTE ≤ 90%)</div>
                    <div class="h4 mb-0 fw-bold text-danger">
                        {{ at_risk_count }} <span class="fs-6 text-muted">({{ "%.1f"|format(chronic_rate) }}%)</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Filters & Upload Form -->
        <div class="card shadow-sm mb-4">
            <div class="card-body">
                <form method="GET" action="{{ url_for('index') }}" class="row g-3 align-items-end">
                    {% if current_user.role == 'Admin' %}
                    <div class="col-md-3">
                        <label class="form-label fw-bold">School</label>
                        <select name="school_id" class="form-select" onchange="this.form.submit()">
                            <option value="all" {% if selected_school_id == 'all' %}selected{% endif %}>All Schools</option>
                            {% for sch in schools %}
                            <option value="{{ sch.id }}" {% if selected_school_id == str(sch.id) %}selected{% endif %}>{{ sch.name }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    {% endif %}

                    <div class="col-md-2">
                        <label class="form-label fw-bold">Grade</label>
                        <select name="grade" class="form-select" onchange="this.form.submit()">
                            <option value="all" {% if selected_grade == 'all' %}selected{% endif %}>All Grades</option>
                            {% for g in available_grades %}
                            <option value="{{ g }}" {% if selected_grade == g %}selected{% endif %}>Grade {{ g }}</option>
                            {% endfor %}
                        </select>
                    </div>

                    <div class="col-md-2">
                        <label class="form-label fw-bold">Filter</label>
                        <select name="filter" class="form-select" onchange="this.form.submit()">
                            <option value="all" {% if selected_filter == 'all' %}selected{% endif %}>All Records</option>
                            <option value="chronic" {% if selected_filter == 'chronic' %}selected{% endif %}>Chronic Only (FTE ≤ 90%)</option>
                            <option value="most-absences" {% if selected_filter == 'most-absences' %}selected{% endif %}>Most Absences</option>
                            <option value="least-absences" {% if selected_filter == 'least-absences' %}selected{% endif %}>Least Absences</option>
                        </select>
                    </div>

                    <div class="col-md-3">
                        <label class="form-label fw-bold">Search</label>
                        <input type="text" name="q" value="{{ search_query }}" class="form-control" placeholder="Search by name or ID...">
                    </div>

                    <div class="col-md-2">
                        <button type="submit" class="btn btn-primary w-100">Apply</button>
                    </div>
                </form>

                <hr class="my-3">

                <!-- CSV Upload Form -->
                <form method="POST" action="{{ url_for('upload_csv') }}" enctype="multipart/form-data" class="row g-3 align-items-center">
                    {% if current_user.role == 'Admin' %}
                    <div class="col-md-4">
                        <select name="school_id" class="form-select" required>
                            <option value="" disabled selected>Select Target School for CSV Import...</option>
                            {% for sch in schools %}
                            <option value="{{ sch.id }}">{{ sch.name }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    {% endif %}
                    <div class="col-md-5">
                        <input type="file" name="file" class="form-control" accept=".csv" required>
                    </div>
                    <div class="col-md-3">
                        <button type="submit" class="btn btn-success w-100">Upload CSV</button>
                    </div>
                </form>
            </div>
        </div>

        <!-- Student Data Table -->
        <div class="card shadow-sm">
            <div class="card-body p-0">
                <div class="table-responsive">
                    <table class="table table-hover mb-0 align-middle">
                        <thead class="table-light">
                            <tr>
                                <th>Student ID</th>
                                <th>Name</th>
                                <th>Grade</th>
                                <th>School</th>
                                <th>Absences</th>
                                <th>Tardies</th>
                                <th>Present FTE %</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for s in students %}
                            <tr>
                                <td>{{ s.student_id }}</td>
                                <td class="fw-bold">{{ s.name }}</td>
                                <td>{{ s.grade }}</td>
                                <td>{{ s.school.name }}</td>
                                <td>{{ "%.1f"|format(s.absences) }}</td>
                                <td>{{ s.tardies }}</td>
                                
                                <td class="fw-semibold">
                                    {% if s.present_fte is not none %}
                                        {{ "%.1f"|format(s.present_fte * 100) }}%
                                    {% else %}
                                        N/A
                                    {% endif %}
                                </td>

                                <td>
                                    {% if s.present_fte is not none and s.present_fte <= 0.90 %}
                                        <span class="badge-chronic">Chronic</span>
                                    {% else %}
                                        <span class="badge-ontrack">On Track</span>
                                    {% endif %}
                                </td>
                            </tr>
                            {% else %}
                            <tr>
                                <td colspan="8" class="text-center py-4 text-muted">No student records found.</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>

            {% if total_pages > 1 %}
            <div class="card-footer bg-white d-flex justify-content-between align-items-center">
                <span class="small text-muted">Showing {{ display_count }} of {{ total_students }} records</span>
                <nav>
                    <ul class="pagination pagination-sm mb-0">
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
</body>
</html>
"""

# ------------------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            flash("Logged in successfully.", "success")
            return redirect(url_for('index'))
        else:
            flash("Invalid username or password.", "error")

    return render_template_string(LOGIN_HTML)

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash("You have been logged out.", "success")
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    user = User.query.get(session['user_id'])
    
    selected_school_id = request.args.get('school_id', 'all')
    selected_grade = request.args.get('grade', 'all')
    selected_filter = request.args.get('filter', 'all')
    search_query = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)

    query = StudentRecord.query

    if user.role != 'Admin':
        if user.school_id:
            query = query.filter_by(school_id=user.school_id)
            selected_school_id = str(user.school_id)
    elif selected_school_id != 'all':
        query = query.filter_by(school_id=int(selected_school_id))

    if selected_grade != 'all':
        query = query.filter_by(grade=selected_grade)

    if search_query:
        query = query.filter(
            (StudentRecord.name.ilike(f"%{search_query}%")) | 
            (StudentRecord.student_id.ilike(f"%{search_query}%"))
        )

    if selected_filter == 'chronic':
        query = query.filter(StudentRecord.present_fte.isnot(None), StudentRecord.present_fte <= 0.90)
    elif selected_filter == 'most-absences':
        query = query.order_by(StudentRecord.absences.desc())
    elif selected_filter == 'least-absences':
        query = query.order_by(StudentRecord.absences.asc())

    total_students = query.count()
    at_risk_count = query.filter(StudentRecord.present_fte.isnot(None), StudentRecord.present_fte <= 0.90).count()
    chronic_rate = (at_risk_count / total_students * 100) if total_students > 0 else 0.0

    per_page = 25
    total_pages = math.ceil(total_students / per_page) if total_students > 0 else 1
    students = query.offset((page - 1) * per_page).limit(per_page).all()

    schools = School.query.all()
    available_grades = [g[0] for g in db.session.query(StudentRecord.grade).distinct().all() if g[0]]

    active_school_name = "All Schools"
    if selected_school_id != 'all':
        sch = School.query.get(int(selected_school_id))
        if sch:
            active_school_name = sch.name

    return render_template_string(
        INDEX_HTML,
        current_user=user,
        students=students,
        schools=schools,
        available_grades=sorted(available_grades),
        total_students=total_students,
        at_risk_count=at_risk_count,
        chronic_rate=chronic_rate,
        active_school_name=active_school_name,
        selected_school_id=selected_school_id,
        selected_grade=selected_grade,
        selected_filter=selected_filter,
        search_query=search_query,
        current_page=page,
        total_pages=total_pages,
        display_count=len(students),
        str=str
    )

@app.route('/upload_csv', methods=['POST'])
@login_required
def upload_csv():
    file = request.files.get('file')
    user = User.query.get(session['user_id'])
    
    school_id = user.school_id if user.role != 'Admin' else request.form.get('school_id', user.school_id)

    if not school_id:
        flash("Please select a school before uploading records.", "error")
        return redirect(url_for('index'))

    if not file or not file.filename.endswith('.csv'):
        flash("Invalid file format. Please upload a .csv file.", "error")
        return redirect(url_for('index'))

    stream = io.StringIO(file.stream.read().decode("UTF-8"), newline=None)
    csv_input = csv.DictReader(stream)

    count = 0
    for row in csv_input:
        s_id = row.get('Student_ID') or row.get('student_id') or row.get('ID')
        name = row.get('Name') or row.get('name')
        grade = row.get('Grade') or row.get('grade') or 'N/A'
        
        try:
            absences = float(row.get('Absences', 0.0) or 0.0)
        except ValueError:
            absences = 0.0

        try:
            tardies = int(row.get('Tardies', 0) or 0)
        except ValueError:
            tardies = 0

        raw_fte = str(row.get('Present_FTE') or row.get('present_fte') or '').replace('%', '').strip()
        if raw_fte:
            try:
                val = float(raw_fte)
                present_fte = val / 100.0 if val > 1.0 else val
            except ValueError:
                present_fte = None
        else:
            present_fte = None

        if s_id and name:
            record = StudentRecord(
                student_id=str(s_id),
                name=name,
                grade=str(grade),
                school_id=int(school_id),
                absences=absences,
                tardies=tardies,
                present_fte=present_fte
            )
            db.session.add(record)
            count += 1

    db.session.commit()
    flash(f"Successfully imported {count} student records.", "success")
    return redirect(url_for('index'))

# ------------------------------------------------------------------------------
# App Initialization & Default Seed Data
# ------------------------------------------------------------------------------
def init_db():
    db.create_all()
    if not School.query.first():
        s1 = School(name="Lincoln High School")
        s2 = School(name="Washington Middle School")
        db.session.add_all([s1, s2])
        db.session.commit()

        admin = User(username="admin", role="Admin")
        admin.set_password("admin123")
        
        user = User(username="staff", role="User", school_id=s1.id)
        user.set_password("staff123")

        db.session.add_all([admin, user])
        db.session.commit()

# INITIALIZATION HOOK FOR PRODUCTION WSGI (Gunicorn / Docker)
with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)

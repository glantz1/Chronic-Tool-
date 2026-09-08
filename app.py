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
    unexcused_absences = db.Column(db.Integer, default=0)
    tardies = db.Column(db.Integer, default=0)
    total_days = db.Column(db.Float, default=180.0)
    present_fte = db.Column(db.Float, nullable=True)

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

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to access this page.", "error")
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or user.role != 'Admin':
            flash("Access denied. Admin privileges required.", "error")
            return redirect(url_for('index'))
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

        {% if current_user.role == 'Admin' %}
        <!-- ADMIN MANAGEMENT SECTION -->
        <div class="accordion mb-4" id="adminAccordion">
            <div class="accordion-item shadow-sm">
                <h2 class="accordion-header" id="headingAdmin">
                    <button class="accordion-button collapsed bg-light fw-bold" type="button" data-bs-toggle="collapse" data-bs-target="#collapseAdmin">
                        ⚙️ Admin Controls: Manage Schools & Users
                    </button>
                </h2>
                <div id="collapseAdmin" class="accordion-collapse collapse" data-bs-parent="#adminAccordion">
                    <div class="accordion-body">
                        <div class="row g-4">
                            <!-- Add School Form -->
                            <div class="col-md-5">
                                <div class="border rounded p-3 bg-white">
                                    <h6 class="fw-bold mb-3">Add New School</h6>
                                    <form method="POST" action="{{ url_for('add_school') }}">
                                        <div class="mb-3">
                                            <input type="text" name="school_name" class="form-control" placeholder="School Name" required>
                                        </div>
                                        <button type="submit" class="btn btn-primary btn-sm w-100">Create School</button>
                                    </form>
                                    
                                    <h6 class="fw-bold mt-4 mb-2">Existing Schools</h6>
                                    <ul class="list-group list-group-flush small" style="max-height: 200px; overflow-y: auto;">
                                        {% for sch in schools %}
                                        <li class="list-group-item d-flex justify-content-between align-items-center px-0">
                                            {{ sch.name }} <span class="badge bg-secondary rounded-pill">ID: {{ sch.id }}</span>
                                        </li>
                                        {% endfor %}
                                    </ul>
                                </div>
                            </div>

                            <!-- Add User Form -->
                            <div class="col-md-7">
                                <div class="border rounded p-3 bg-white">
                                    <h6 class="fw-bold mb-3">Create User Account</h6>
                                    <form method="POST" action="{{ url_for('add_user') }}" class="row g-2">
                                        <div class="col-md-6">
                                            <input type="text" name="username" class="form-control" placeholder="Username" required>
                                        </div>
                                        <div class="col-md-6">
                                            <input type="password" name="password" class="form-control" placeholder="Password" required>
                                        </div>
                                        <div class="col-md-6">
                                            <select name="role" class="form-select">
                                                <option value="User">User</option>
                                                <option value="Admin">Admin</option>
                                            </select>
                                        </div>
                                        <div class="col-md-6">
                                            <select name="school_id" class="form-select">
                                                <option value="">No Assigned School (All)</option>
                                                {% for sch in schools %}
                                                <option value="{{ sch.id }}">{{ sch.name }}</option>
                                                {% endfor %}
                                            </select>
                                        </div>
                                        <div class="col-12 mt-3">
                                            <button type="submit" class="btn btn-success btn-sm w-100">Create User</button>
                                        </div>
                                    </form>

                                    <h6 class="fw-bold mt-4 mb-2">System Users</h6>
                                    <div class="table-responsive" style="max-height: 200px; overflow-y: auto;">
                                        <table class="table table-sm small mb-0">
                                            <thead>
                                                <tr>
                                                    <th>Username</th>
                                                    <th>Role</th>
                                                    <th>Assigned School</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {% for u in all_users %}
                                                <tr>
                                                    <td>{{ u.username }}</td>
                                                    <td><span class="badge bg-info text-dark">{{ u.role }}</span></td>
                                                    <td>{{ u.school.name if u.school else 'All Schools' }}</td>
                                                </tr>
                                                {% endfor %}
                                            </tbody>
                                        </table>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        {% endif %}

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
                            <option value="highest-fte" {% if selected_filter == 'highest-fte' %}selected{% endif %}>Highest Present FTE%</option>
                            <option value="lowest-fte" {% if selected_filter == 'lowest-fte' %}selected{% endif %}>Lowest Present FTE%</option>
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
                                <th class="text-end pe-4">Actions</th>
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
                                        {{ "%.2f"|format(s.present_fte) }}%
                                    {% else %}
                                        N/A
                                    {% endif %}
                                </td>

                                <td>
                                    {% if s.present_fte is not none and s.present_fte <= 90.0 %}
                                        <span class="badge-chronic">Chronic</span>
                                    {% else %}
                                        <span class="badge-ontrack">On Track</span>
                                    {% endif %}
                                </td>

                                <!-- LOG INTERVENTION BUTTON -->
                                <td class="text-end pe-3">
                                    <button class="btn btn-sm btn-outline-primary" data-bs-toggle="modal" data-bs-target="#interventionModal{{ s.id }}">
                                        + Log Intervention
                                    </button>

                                    <!-- INTERVENTION MODAL -->
                                    <div class="modal fade text-start" id="interventionModal{{ s.id }}" tabindex="-1" aria-hidden="true">
                                        <div class="modal-dialog">
                                            <div class="modal-content">
                                                <form method="POST" action="{{ url_for('log_intervention', student_id=s.id) }}">
                                                    <div class="modal-header">
                                                        <h5 class="modal-title fs-6 fw-bold">Log Intervention: {{ s.name }}</h5>
                                                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                                                    </div>
                                                    <div class="modal-body">
                                                        <div class="mb-3">
                                                            <label class="form-label fw-bold">Intervention Notes / Action Taken</label>
                                                            <textarea name="notes" class="form-control" rows="3" placeholder="e.g. Phone call made to parent; Attendance plan signed." required></textarea>
                                                        </div>

                                                        {% if s.interventions %}
                                                        <h6 class="fw-bold small mt-3">Previous Logs:</h6>
                                                        <ul class="list-group list-group-flush small" style="max-height: 150px; overflow-y: auto;">
                                                            {% for log in s.interventions %}
                                                            <li class="list-group-item px-0 py-1">
                                                                <span class="text-muted" style="font-size:0.8em;">{{ log.created_at.strftime('%Y-%m-%d %H:%M') }}</span>: {{ log.notes }}
                                                            </li>
                                                            {% endfor %}
                                                        </ul>
                                                        {% endif %}
                                                    </div>
                                                    <div class="modal-footer">
                                                        <button type="button" class="btn btn-sm btn-secondary" data-bs-dismiss="modal">Cancel</button>
                                                        <button type="submit" class="btn btn-sm btn-primary">Save Intervention</button>
                                                    </div>
                                                </form>
                                            </div>
                                        </div>
                                    </div>
                                </td>
                            </tr>
                            {% else %}
                            <tr>
                                <td colspan="9" class="text-center py-4 text-muted">No student records found.</td>
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

    <!-- BOOTSTRAP JS FOR EXPANDABLE ACCORDION CONTROLS & MODALS -->
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
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
    per_page = 25

    query = StudentRecord.query

    # 1. Restrict non-admins to their assigned school
    if user.role != 'Admin':
        query = query.filter_by(school_id=user.school_id)
    # 2. If Admin, filter by selected dropdown school (if not 'all')
    elif selected_school_id != 'all':
        query = query.filter_by(school_id=selected_school_id)

    # 3. Grade Filter
    if selected_grade != 'all':
        query = query.filter_by(grade=selected_grade)

    # 4. Search Query Filter
    if search_query:
        query = query.filter(
            (StudentRecord.name.ilike(f"%{search_query}%")) | 
            (StudentRecord.student_id.ilike(f"%{search_query}%"))
        )

    # 5. Status / Attendance Filter
    if selected_filter == 'chronic':
        query = query.filter(StudentRecord.present_fte.isnot(None), StudentRecord.present_fte <= 90.0)
    elif selected_filter == 'most-absences':
        query = query.order_by(StudentRecord.absences.desc())
    elif selected_filter == 'least-absences':
        query = query.order_by(StudentRecord.absences.asc())
    elif selected_filter == 'most-unexcused':  # <--- ADD THIS
        query = query.order_by(StudentRecord.unexcused_absences.desc())    
    elif selected_filter == 'highest-fte':
        query = query.order_by(StudentRecord.present_fte.desc())
    elif selected_filter == 'lowest-fte':
        query = query.order_by(StudentRecord.present_fte.asc())

    # 6. Calculate Metrics on Filtered Query
    total_students = query.count()
    at_risk_count = query.filter(StudentRecord.present_fte.isnot(None), StudentRecord.present_fte <= 90.0).count()
    chronic_rate = (at_risk_count / total_students * 100) if total_students > 0 else 0.0
    total_pages = math.ceil(total_students / per_page) if total_students > 0 else 1
    students = query.offset((page - 1) * per_page).limit(per_page).all()

    schools = School.query.all()
    all_users = User.query.all() if user.role == 'Admin' else []
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
        all_users=all_users,
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

@app.route('/log_intervention/<int:student_id>', methods=['POST'])
@login_required
def log_intervention(student_id):
    notes = request.form.get('notes', '').strip()
    student = StudentRecord.query.get_or_404(student_id)

    if notes:
        intervention = Intervention(student_record_id=student.id, notes=notes)
        db.session.add(intervention)
        db.session.commit()
        flash(f"Intervention logged for {student.name}.", "success")
    else:
        flash("Notes cannot be empty.", "error")

    return redirect(url_for('index'))

# ------------------------------------------------------------------------------
# Admin Management Routes
# ------------------------------------------------------------------------------
@app.route('/admin/add_school', methods=['POST'])
@admin_required
def add_school():
    name = request.form.get('school_name', '').strip()
    if name:
        if School.query.filter_by(name=name).first():
            flash(f"School '{name}' already exists.", "error")
        else:
            school = School(name=name)
            db.session.add(school)
            db.session.commit()
            flash(f"School '{name}' added successfully.", "success")
    else:
        flash("School name cannot be empty.", "error")
    return redirect(url_for('index'))

@app.route('/admin/add_user', methods=['POST'])
@admin_required
def add_user():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    role = request.form.get('role', 'User')
    school_id = request.form.get('school_id')

    if not username or not password:
        flash("Username and password are required.", "error")
        return redirect(url_for('index'))

    if User.query.filter_by(username=username).first():
        flash(f"Username '{username}' is already taken.", "error")
        return redirect(url_for('index'))

    new_user = User(
        username=username,
        role=role,
        school_id=int(school_id) if school_id else None
    )
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()

    flash(f"User '{username}' created successfully.", "success")
    return redirect(url_for('index'))

# ------------------------------------------------------------------------------
# CSV Data Import Route
# ------------------------------------------------------------------------------
@app.route('/upload_csv', methods=['POST'])
@login_required
def upload_csv():
    file = request.files.get('file')
    user = User.query.get(session['user_id'])
    
    school_id = user.school_id if user.role != 'Admin' else request.form.get('school_id', user.school_id)

    if not school_id:
        flash("Please select a target school for CSV import.", "error")
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
                present_fte = val * 100.0 if val <= 1.0 else val
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

with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)

import os
import csv
import io
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
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=True)

    school = db.relationship('School', backref=db.backref('users', lazy=True))

class StudentRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=True)
    absences = db.Column(db.Integer, default=0)
    tardies = db.Column(db.Integer, default=0)
    total_days = db.Column(db.Integer, default=180)

    school = db.relationship('School', backref=db.backref('students', lazy=True))

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
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.25rem; }
        .card-title { font-size: 1.1rem; font-weight: 600; margin: 0; }
        .form-row { display: flex; gap: 0.75rem; align-items: center; }
        input, select { padding: 0.6rem 0.8rem; border: 1px solid var(--border); border-radius: 6px; font-size: 0.875rem; }
        .btn { background: var(--primary); color: white; border: none; padding: 0.6rem 1.2rem; border-radius: 6px; font-weight: 600; cursor: pointer; text-decoration: none; font-size: 0.875rem; }
        .btn:hover { background: var(--primary-hover); }
        .btn-outline { background: transparent; border: 1px solid var(--border); color: var(--text); }
        .btn-outline:hover { background: var(--bg); }
        table { width: 100%; border-collapse: collapse; text-align: left; font-size: 0.875rem; }
        th, td { padding: 0.75rem 1rem; border-bottom: 1px solid var(--border); }
        th { background: #f8fafc; color: var(--muted); }
        .badge { padding: 0.25rem 0.625rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; }
        .badge-danger { background: var(--danger-bg); color: var(--danger-text); }
        .badge-success { background: var(--success-bg); color: var(--success-text); }
        .alert { background: var(--success-bg); color: var(--success-text); border: 1px solid #bbf7d0; padding: 0.75rem; border-radius: 6px; margin-bottom: 1rem; font-size: 0.875rem; }
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
              <div class="alert">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}

        <!-- Metrics Overview -->
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-title">Total Visible Students</div>
                <div class="metric-value">{{ total_students }}</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">Chronically Absent (&ge;10%)</div>
                <div class="metric-value" style="color: #dc2626;">{{ at_risk_count }}</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">Average Absenteeism Rate</div>
                <div class="metric-value">{{ "%.1f"|format(avg_rate) }}%</div>
            </div>
            {% if current_user.role == 'Admin' %}
            <div class="metric-card">
                <div class="metric-title">Registered Schools</div>
                <div class="metric-value">{{ schools|length }}</div>
            </div>
            {% endif %}
        </div>

        {% if current_user.role == 'Admin' %}
        <!-- Admin-Only System Controls -->
        <div class="grid-2">
            <!-- Add School -->
            <div class="card">
                <h3 class="card-title" style="margin-bottom:1rem;">Manage Schools</h3>
                <form method="POST" action="/add_school" class="form-row">
                    <input type="text" name="name" placeholder="School Name" required style="flex:2;">
                    <input type="text" name="code" placeholder="Code (e.g. LHS)" required style="flex:1;">
                    <button type="submit" class="btn">Add School</button>
                </form>
            </div>

            <!-- Manage Users -->
            <div class="card">
                <h3 class="card-title" style="margin-bottom:1rem;">Add System User</h3>
                <form method="POST" action="/add_user" style="display:flex; flex-direction:column; gap:0.75rem;">
                    <div class="form-row">
                        <input type="text" name="username" placeholder="Username" required style="flex:1;">
                        <input type="password" name="password" placeholder="Password" required style="flex:1;">
                    </div>
                    <div class="form-row">
                        <select name="role" style="flex:1;">
                            <option value="Staff">Staff</option>
                            <option value="Admin">Admin</option>
                        </select>
                        <select name="school_id" style="flex:1;">
                            <option value="">No School (Admin / Global)</option>
                            {% for school in schools %}
                            <option value="{{ school.id }}">{{ school.name }}</option>
                            {% endfor %}
                        </select>
                        <button type="submit" class="btn">Create User</button>
                    </div>
                </form>
            </div>
        </div>
        {% endif %}

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
                        {% if current_user.role == 'Admin' %}
                        <select name="school_id" style="flex:1;" required>
                            <option value="">Assign School...</option>
                            {% for school in schools %}
                            <option value="{{ school.id }}">{{ school.name }} ({{ school.code }})</option>
                            {% endfor %}
                        </select>
                        {% else %}
                        <input type="text" value="{{ current_user.school.name if current_user.school else 'Unassigned' }}" disabled style="flex:1; background:#f1f5f9;">
                        {% endif %}
                        <input type="number" name="absences" placeholder="Absences" value="0" style="width:90px;">
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
                    <small style="color:var(--muted);">CSV format: <code>student_id, name, absences, tardies, total_days</code></small>
                </form>
            </div>
        </div>

        {% if current_user.role == 'Admin' %}
        <!-- System Users List (Admin Only) -->
        <div class="card">
            <h3 class="card-title" style="margin-bottom:1rem;">System Accounts</h3>
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Username</th>
                        <th>Role</th>
                        <th>Assigned School Scope</th>
                    </tr>
                </thead>
                <tbody>
                    {% for u in users %}
                    <tr>
                        <td>{{ u.id }}</td>
                        <td><strong>{{ u.username }}</strong></td>
                        <td><span class="badge badge-success">{{ u.role }}</span></td>
                        <td>{{ u.school.name if u.school else 'Global Scope (All Schools)' }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}

        <!-- Student Roster -->
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">Student Attendance Roster</h3>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Student ID</th>
                        <th>Name</th>
                        <th>School</th>
                        <th>Absences</th>
                        <th>Tardies</th>
                        <th>Adjusted Absences</th>
                        <th>Absenteeism %</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {% for student in students %}
                    <tr>
                        <td><strong>{{ student.student_id }}</strong></td>
                        <td>{{ student.name }}</td>
                        <td>{{ student.school_name }}</td>
                        <td>{{ student.absences }}</td>
                        <td>{{ student.tardies }}</td>
                        <td>{{ student.adjusted_absences }}</td>
                        <td>{{ "%.1f"|format(student.rate) }}%</td>
                        <td>
                            {% if student.rate >= 10.0 %}
                                <span class="badge badge-danger">At Risk (Chronic)</span>
                            {% else %}
                                <span class="badge badge-success">On Track</span>
                            {% endif %}
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
</body>
</html>
"""

# --- App Initialization & Default Seeding ---

def init_db():
    with app.app_context():
        # Reset schema cleanly
        try:
            db.session.execute(db.text('DROP SCHEMA public CASCADE;'))
            db.session.execute(db.text('CREATE SCHEMA public;'))
            db.session.commit()
        except Exception:
            db.session.rollback()

        db.create_all()

        # Seed initial default schools
        lhs = School.query.filter_by(code='LHS').first()
        if not lhs:
            lhs = School(name='Lincoln High School', code='LHS')
            db.session.add(lhs)

        mms = School.query.filter_by(code='MMS').first()
        if not mms:
            mms = School(name='Madison Middle School', code='MMS')
            db.session.add(mms)

        db.session.commit()

        # Seed default admin user
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin', 
                password_hash=generate_password_hash('admin123'), 
                role='Admin'
            )
            db.session.add(admin)

        # Seed sample staff user assigned to Lincoln High
        if not User.query.filter_by(username='lincoln_staff').first():
            staff = User(
                username='lincoln_staff',
                password_hash=generate_password_hash('staff123'),
                role='Staff',
                school_id=lhs.id
            )
            db.session.add(staff)

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

    # Scope query by school if the user is a Staff member
    if user.role == 'Admin':
        records = StudentRecord.query.all()
    else:
        records = StudentRecord.query.filter_by(school_id=user.school_id).all()

    schools = School.query.all()
    users = User.query.all()

    students_data = []
    total_students = len(records)
    at_risk_count = 0
    total_rate_sum = 0

    for r in records:
        tardy_absences = r.tardies // TARDY_CONVERSION_FACTOR
        adjusted_absences = r.absences + tardy_absences
        rate = (adjusted_absences / r.total_days * 100) if r.total_days > 0 else 0

        if rate >= 10.0:
            at_risk_count += 1

        total_rate_sum += rate

        students_data.append({
            'student_id': r.student_id,
            'name': r.name,
            'school_name': r.school.name if r.school else 'Unassigned',
            'absences': r.absences,
            'tardies': r.tardies,
            'adjusted_absences': adjusted_absences,
            'rate': rate
        })

    avg_rate = (total_rate_sum / total_students) if total_students > 0 else 0.0

    return render_template_string(
        INDEX_HTML,
        current_user=user,
        students=students_data,
        schools=schools,
        users=users,
        total_students=total_students,
        at_risk_count=at_risk_count,
        avg_rate=avg_rate
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
    return redirect(url_for('login'))

@app.route('/add_school', methods=['POST'])
def add_school():
    user = get_current_user()
    if not user or user.role != 'Admin':
        flash('Unauthorized action.', 'error')
        return redirect(url_for('index'))

    name = request.form.get('name')
    code = request.form.get('code')

    if name and code:
        school = School(name=name.strip(), code=code.strip())
        db.session.add(school)
        db.session.commit()
        flash('School added successfully!', 'success')

    return redirect(url_for('index'))

@app.route('/add_user', methods=['POST'])
def add_user():
    user = get_current_user()
    if not user or user.role != 'Admin':
        flash('Unauthorized action.', 'error')
        return redirect(url_for('index'))

    username = request.form.get('username')
    password = request.form.get('password')
    role = request.form.get('role', 'Staff')
    school_id = request.form.get('school_id')

    if username and password:
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'error')
        else:
            new_user = User(
                username=username.strip(),
                password_hash=generate_password_hash(password),
                role=role,
                school_id=int(school_id) if school_id else None
            )
            db.session.add(new_user)
            db.session.commit()
            flash('User account created successfully!', 'success')

    return redirect(url_for('index'))

@app.route('/add_student', methods=['POST'])
def add_student():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    student_id = request.form.get('student_id')
    name = request.form.get('name')
    absences = int(request.form.get('absences', 0))
    tardies = int(request.form.get('tardies', 0))

    # Auto-assign school ID based on current user role
    if user.role == 'Admin':
        school_id = request.form.get('school_id')
        school_id = int(school_id) if school_id else None
    else:
        school_id = user.school_id

    if student_id and name:
        student = StudentRecord(
            student_id=student_id.strip(),
            name=name.strip(),
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

    # Determine school context for import
    if user.role == 'Admin':
        school_id_param = request.form.get('school_id')
        school_id = int(school_id_param) if school_id_param else None
    else:
        school_id = user.school_id

    try:
        stream = io.StringIO(file.stream.read().decode("UTF-8"), newline=None)
        csv_input = csv.DictReader(stream)

        # Remove existing records for this specific school scope
        if school_id:
            StudentRecord.query.filter_by(school_id=school_id).delete()
        elif user.role == 'Admin':
            StudentRecord.query.filter_by(school_id=None).delete()

        for row in csv_input:
            student = StudentRecord(
                student_id=str(row.get('student_id', '')).strip(),
                name=str(row.get('name', '')).strip(),
                school_id=school_id,
                absences=int(row.get('absences', 0)),
                tardies=int(row.get('tardies', 0)),
                total_days=int(row.get('total_days', 180))
            )
            db.session.add(student)

        db.session.commit()
        flash('Attendance CSV processed and roster updated!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error processing CSV: {str(e)}', 'error')

    return redirect(url_for('index'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

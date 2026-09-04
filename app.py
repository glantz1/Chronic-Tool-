import os
import csv
import io
from flask import Flask, render_template_string, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-dev-key-change-in-prod')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///absenteeism.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Constants
TARDY_CONVERSION_FACTOR = 3

# --- HTML Templates (Full Classic UI Embedded Inline) ---

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - Chronic Absenteeism Tracker</title>
    <style>
        :root {
            --primary-color: #2563eb;
            --primary-hover: #1d4ed8;
            --bg-color: #f8fafc;
            --card-bg: #ffffff;
            --text-main: #0f172a;
            --text-muted: #64748b;
            --border-color: #e2e8f0;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
        }
        .login-card {
            background: var(--card-bg);
            padding: 2.5rem;
            border-radius: 12px;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
            width: 100%;
            max-width: 380px;
            border: 1px solid var(--border-color);
        }
        .login-header {
            text-align: center;
            margin-bottom: 2rem;
        }
        .login-header h2 {
            margin: 0 0 0.5rem 0;
            font-size: 1.5rem;
            font-weight: 700;
            color: var(--text-main);
        }
        .login-header p {
            margin: 0;
            color: var(--text-muted);
            font-size: 0.875rem;
        }
        .form-group {
            margin-bottom: 1.25rem;
        }
        label {
            display: block;
            margin-bottom: 0.5rem;
            color: var(--text-main);
            font-size: 0.875rem;
            font-weight: 500;
        }
        input[type="text"], input[type="password"] {
            width: 100%;
            padding: 0.75rem 0.875rem;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            box-sizing: border-box;
            font-size: 0.875rem;
            transition: border-color 0.15s ease;
        }
        input[type="text"]:focus, input[type="password"]:focus {
            outline: none;
            border-color: var(--primary-color);
            box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
        }
        button {
            width: 100%;
            padding: 0.75rem;
            background-color: var(--primary-color);
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 0.875rem;
            font-weight: 600;
            cursor: pointer;
            transition: background-color 0.15s ease;
            margin-top: 0.5rem;
        }
        button:hover {
            background-color: var(--primary-hover);
        }
        .alert {
            background-color: #fef2f2;
            color: #991b1b;
            border: 1px solid #fecaca;
            padding: 0.75rem;
            border-radius: 6px;
            margin-bottom: 1.25rem;
            font-size: 0.85rem;
        }
    </style>
</head>
<body>
    <div class="login-card">
        <div class="login-header">
            <h2>Absenteeism Tracker</h2>
            <p>Sign in to access student reports</p>
        </div>
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="alert">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        <form method="POST" action="/login">
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" placeholder="Enter username" required>
            </div>
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" placeholder="Enter password" required>
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
        :root {
            --primary-color: #2563eb;
            --primary-hover: #1d4ed8;
            --bg-color: #f8fafc;
            --card-bg: #ffffff;
            --text-main: #0f172a;
            --text-muted: #64748b;
            --border-color: #e2e8f0;
            --danger-bg: #fef2f2;
            --danger-text: #991b1b;
            --warning-bg: #fffbeb;
            --warning-text: #92400e;
            --success-bg: #f0fdf4;
            --success-text: #166534;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            margin: 0;
            padding: 0;
        }
        .navbar {
            background-color: var(--card-bg);
            border-bottom: 1px solid var(--border-color);
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .navbar-brand {
            font-size: 1.25rem;
            font-weight: 700;
            color: var(--text-main);
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        .logout-btn {
            color: var(--danger-text);
            text-decoration: none;
            font-weight: 600;
            font-size: 0.875rem;
            padding: 0.5rem 1rem;
            border-radius: 6px;
            border: 1px solid #fecaca;
            background-color: var(--danger-bg);
            transition: all 0.15s ease;
        }
        .logout-btn:hover {
            background-color: #fee2e2;
        }
        .container {
            max-width: 1200px;
            margin: 2rem auto;
            padding: 0 1.5rem;
        }
        
        /* Metrics Grid */
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 1.25rem;
            margin-bottom: 2rem;
        }
        .metric-card {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 1.25rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }
        .metric-title {
            font-size: 0.875rem;
            color: var(--text-muted);
            font-weight: 500;
            margin-bottom: 0.5rem;
        }
        .metric-value {
            font-size: 1.75rem;
            font-weight: 700;
            color: var(--text-main);
        }

        /* Content Cards */
        .card {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 1.5rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            margin-bottom: 2rem;
        }
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.25rem;
        }
        .card-title {
            font-size: 1.1rem;
            font-weight: 600;
            margin: 0;
        }
        
        /* Upload Area */
        .upload-area {
            border: 2px dashed #cbd5e1;
            background-color: #f1f5f9;
            border-radius: 8px;
            padding: 1.5rem;
            text-align: center;
            transition: border-color 0.15s ease;
        }
        .upload-area:hover {
            border-color: var(--primary-color);
        }
        .file-input-wrapper {
            display: inline-flex;
            gap: 1rem;
            align-items: center;
        }
        input[type="file"] {
            font-size: 0.875rem;
        }
        .btn-submit {
            background-color: var(--primary-color);
            color: white;
            border: none;
            padding: 0.6rem 1.2rem;
            border-radius: 6px;
            font-weight: 600;
            font-size: 0.875rem;
            cursor: pointer;
            transition: background-color 0.15s ease;
        }
        .btn-submit:hover {
            background-color: var(--primary-hover);
        }

        /* Table Styling */
        .table-responsive {
            overflow-x: auto;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 0.875rem;
        }
        th {
            background-color: #f8fafc;
            color: var(--text-muted);
            font-weight: 600;
            padding: 0.75rem 1rem;
            border-bottom: 1px solid var(--border-color);
        }
        td {
            padding: 0.875rem 1rem;
            border-bottom: 1px solid var(--border-color);
        }
        tr:hover {
            background-color: #f8fafc;
        }

        /* Status Badges */
        .badge {
            display: inline-flex;
            align-items: center;
            padding: 0.25rem 0.625rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
        }
        .badge-danger {
            background-color: var(--danger-bg);
            color: var(--danger-text);
        }
        .badge-success {
            background-color: var(--success-bg);
            color: var(--success-text);
        }
        .alert-success {
            background-color: var(--success-bg);
            color: var(--success-text);
            border: 1px solid #bbf7d0;
            padding: 0.75rem;
            border-radius: 6px;
            margin-bottom: 1rem;
            font-size: 0.875rem;
        }
    </style>
</head>
<body>
    <div class="navbar">
        <div class="navbar-brand">
            📊 Chronic Absenteeism Tracker
        </div>
        <a href="/logout" class="logout-btn">Sign Out</a>
    </div>

    <div class="container">
        <!-- Dashboard Metrics Summary -->
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-title">Total Students</div>
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
        </div>

        <!-- File Upload Section -->
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">Upload Attendance Records</h3>
            </div>
            <form method="POST" action="/upload_csv" enctype="multipart/form-data">
                <div class="upload-area">
                    <div class="file-input-wrapper">
                        <input type="file" name="file" accept=".csv" required>
                        <button type="submit" class="btn-submit">Process &amp; Update CSV</button>
                    </div>
                    <p style="margin-top: 0.75rem; margin-bottom: 0; color: var(--text-muted); font-size: 0.8rem;">
                        Expected CSV columns: <code>student_id, name, absences, tardies, total_days</code> (3 tardies = 1 unexcused absence)
                    </p>
                </div>
            </form>
        </div>

        <!-- Student Data Table -->
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">Student Roster Summary</h3>
            </div>

            {% with messages = get_flashed_messages(with_categories=true) %}
              {% if messages %}
                {% for category, message in messages %}
                  <div class="alert-success">{{ message }}</div>
                {% endfor %}
              {% endif %}
            {% endwith %}

            <div class="table-responsive">
                <table>
                    <thead>
                        <tr>
                            <th>Student ID</th>
                            <th>Name</th>
                            <th>Unexcused Absences</th>
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
                            <td colspan="7" style="text-align: center; color: var(--text-muted); padding: 2rem;">
                                No student record data available. Upload an attendance CSV file above to populate the tracker.
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</body>
</html>
"""

# --- Database Models ---

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

class StudentRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    absences = db.Column(db.Integer, default=0)
    tardies = db.Column(db.Integer, default=0)
    total_days = db.Column(db.Integer, default=180)

# --- App Initialization & Default Seeding ---

def init_db():
    with app.app_context():
        # Cleanly drop legacy schema constraints and recreate
        try:
            db.session.execute(db.text('DROP SCHEMA public CASCADE;'))
            db.session.execute(db.text('CREATE SCHEMA public;'))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Recreate clean tables based on current app models
        db.create_all()
        
        # Seed default admin user
        if not User.query.filter_by(username='admin').first():
            hashed = generate_password_hash('admin123')
            admin = User(username='admin', password_hash=hashed)
            db.session.add(admin)
            db.session.commit()

init_db()

# --- Application Routes ---

@app.route('/')
def index():
    records = StudentRecord.query.all()
    students_data = []
    
    total_students = len(records)
    at_risk_count = 0
    total_rate_sum = 0

    for r in records:
        # 3 tardies = 1 unexcused absence
        tardy_absences = r.tardies // TARDY_CONVERSION_FACTOR
        adjusted_absences = r.absences + tardy_absences
        rate = (adjusted_absences / r.total_days * 100) if r.total_days > 0 else 0
        
        if rate >= 10.0:
            at_risk_count += 1
            
        total_rate_sum += rate

        students_data.append({
            'student_id': r.student_id,
            'name': r.name,
            'absences': r.absences,
            'tardies': r.tardies,
            'adjusted_absences': adjusted_absences,
            'rate': rate
        })

    avg_rate = (total_rate_sum / total_students) if total_students > 0 else 0.0

    return render_template_string(
        INDEX_HTML,
        students=students_data,
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
            return redirect(url_for('index'))
        
        flash('Invalid username or password.', 'error')
        
    return render_template_string(LOGIN_HTML)

@app.route('/logout')
def logout():
    return redirect(url_for('login'))

@app.route('/upload_csv', methods=['POST'])
def upload_csv():
    if 'file' not in request.files:
        flash('No file part provided.', 'error')
        return redirect(url_for('index'))
        
    file = request.files['file']
    if file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('index'))

    try:
        stream = io.StringIO(file.stream.read().decode("UTF-8"), newline=None)
        csv_input = csv.DictReader(stream)

        # Clear existing entries for fresh sync
        StudentRecord.query.delete()

        for row in csv_input:
            student = StudentRecord(
                student_id=str(row.get('student_id', '')).strip(),
                name=str(row.get('name', '')).strip(),
                absences=int(row.get('absences', 0)),
                tardies=int(row.get('tardies', 0)),
                total_days=int(row.get('total_days', 180))
            )
            db.session.add(student)
            
        db.session.commit()
        flash('Attendance CSV processed and updated successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error processing CSV file: {str(e)}', 'error')

    return redirect(url_for('index'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

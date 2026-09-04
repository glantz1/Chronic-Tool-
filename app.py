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

# --- HTML Templates (Embedded Inline) ---

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - Chronic Absenteeism Tracker</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f4f6f9; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .login-card { background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); width: 320px; }
        h2 { margin-top: 0; color: #333; }
        .form-group { margin-bottom: 1rem; }
        label { display: block; margin-bottom: 0.5rem; color: #666; font-size: 0.9rem; }
        input { width: 100%; padding: 0.5rem; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
        button { width: 100%; padding: 0.6rem; background: #0066cc; color: white; border: none; border-radius: 4px; font-weight: bold; cursor: pointer; }
        button:hover { background: #0052a3; }
        .alert { background: #ffebee; color: #c62828; padding: 0.5rem; border-radius: 4px; margin-bottom: 1rem; font-size: 0.85rem; }
    </style>
</head>
<body>
    <div class="login-card">
        <h2>Absenteeism Tracker</h2>
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
                <input type="text" id="username" name="username" required>
            </div>
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required>
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
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 2rem; background: #f8f9fa; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 2rem; }
        .card { background: white; padding: 1.5rem; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); margin-bottom: 1rem; }
        .upload-zone { border: 2px dashed #0066cc; padding: 1.5rem; background: #f0f7ff; border-radius: 6px; margin-bottom: 1rem; text-align: center; }
        table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
        th, td { text-align: left; padding: 8px; border-bottom: 1px solid #ddd; }
        th { background-color: #f2f2f2; }
        .badge-warning { background: #fff3cd; color: #856404; padding: 4px 8px; border-radius: 4px; font-weight: bold; }
        .badge-danger { background: #f8d7da; color: #721c24; padding: 4px 8px; border-radius: 4px; font-weight: bold; }
        a { color: #dc3545; text-decoration: none; font-weight: bold; }
        button { background: #0066cc; color: white; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; }
    </style>
</head>
<body>
    <div class="header">
        <h1>Chronic Absenteeism Tracker</h1>
        <a href="/logout">Logout</a>
    </div>

    <div class="card">
        <h3>Upload Attendance CSV</h3>
        <p><small>CSV columns expected: <code>student_id, name, absences, tardies, total_days</code></small></p>
        <form method="POST" action="/upload_csv" enctype="multipart/form-data" class="upload-zone">
            <input type="file" name="file" accept=".csv" required>
            <button type="submit">Process CSV</button>
        </form>
    </div>

    <div class="card">
        <h3>Student Attendance Summary</h3>
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <p style="color: green; font-weight: bold;">{{ message }}</p>
            {% endfor %}
          {% endif %}
        {% endwith %}

        <table>
            <thead>
                <tr>
                    <th>Student ID</th>
                    <th>Name</th>
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
                    <td>{{ student.student_id }}</td>
                    <td>{{ student.name }}</td>
                    <td>{{ student.absences }}</td>
                    <td>{{ student.tardies }}</td>
                    <td>{{ student.adjusted_absences }}</td>
                    <td>{{ "%.1f"|format(student.rate) }}%</td>
                    <td>
                        {% if student.rate >= 10.0 %}
                            <span class="badge-danger">At Risk (Chronic)</span>
                        {% else %}
                            <span class="badge-warning">Normal</span>
                        {% endif %}
                    </td>
                </tr>
                {% else %}
                <tr>
                    <td colspan="7">No student record data available. Upload a CSV above.</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
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
        # Drop old/mismatched tables and recreate clean schema
        db.drop_all()
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
    
    for r in records:
        # Calculate tardy conversions (3 tardies = 1 unexcused absence)
        tardy_absences = r.tardies // TARDY_CONVERSION_FACTOR
        adjusted_absences = r.absences + tardy_absences
        rate = (adjusted_absences / r.total_days * 100) if r.total_days > 0 else 0
        
        students_data.append({
            'student_id': r.student_id,
            'name': r.name,
            'absences': r.absences,
            'tardies': r.tardies,
            'adjusted_absences': adjusted_absences,
            'rate': rate
        })

    return render_template_string(INDEX_HTML, students=students_data)

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

import os
import csv
import io
import math
from datetime import datetime
from flask import Flask, render_template_string, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import joinedload, subqueryload
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-dev-key-change-in-prod')

# Handle Railway PostgreSQL URL formatting (postgres:// to postgresql://)
db_url = os.environ.get('DATABASE_URL', 'sqlite:///absenteeism.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
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
    present_fte = db.Column(db.Float, nullable=True)

    school = db.relationship('School', backref=db.backref('students', lazy=True, cascade="all, delete-orphan"))
    interventions = db.relationship('Intervention', backref='student', lazy=True, cascade="all, delete-orphan")

class Intervention(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_record_id = db.Column(db.Integer, db.ForeignKey('student_record.id', ondelete='CASCADE'), nullable=False)
    action_type = db.Column(db.String(100), nullable=False)
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
        .navbar { background: var(--card); border-bottom: 1px solid var(--border); padding: 1rem 2rem; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem; }
        .user-info { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }
        .container { max-width: 1200px; margin: 2rem auto; padding: 0 1.5rem; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 2rem; }
        .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1.25rem; margin-bottom: 2rem; }
        .metric-card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 1.25rem; }
        .metric-title { font-size: 0.875rem; color: var(--muted); margin-bottom: 0.5rem; }
        .metric-value { font-size: 1.75rem; font-weight: 700; }
        .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 1.5rem; margin-bottom: 2rem; }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.25rem; flex-wrap: wrap; gap: 1rem; }
        .card-title { font-size: 1.1rem; font-weight: 600; margin: 0; }
        .form-row { display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; }
        input, select, textarea { padding: 0.6rem 0.8rem; border: 1px solid var(--border); border-radius: 6px; font-size: 0.875rem; font-family: inherit; }
        .btn { background: var(--primary); color: white; border: none; padding: 0.6rem 1.2rem; border-radius: 6px; font-weight: 600; cursor: pointer; text-decoration: none; font-size: 0.875rem; display: inline-flex; align-items: center; }
        .btn:hover { background: var(--primary-hover); }
        .btn-outline { background: transparent; border: 1px solid var(--border); color: var(--text); }
        .btn-outline:hover { background: var(--bg); }
        .btn-danger { background: #dc2626; color: white; }
        .btn-danger:hover { background: #b91c1c; }
        .btn-sm { padding: 0.35rem 0.75rem; font-size: 0.78rem; border-radius: 4px; }
        
        .filter-btn-group { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
        .filter-btn { background: var(--card); border: 1px solid var(--border); padding: 0.5rem 1rem; border-radius: 6px; font-size: 0.85rem; font-weight: 600; cursor: pointer; color: var(--muted); transition: all 0.15s ease; text-decoration: none; }
        .filter-btn:hover { background: var(--bg); color: var(--text); }
        .filter-btn.active { background: var(--primary); color: white; border-color: var(--primary); }
        
        table { width: 100%; border-collapse: collapse; text-align: left; font-size: 0.875rem; }
        th, td { padding: 0.75rem 1rem; border-bottom: 1px solid var(--border); }
        th { background: #f8fafc; color: var(--muted); }
        
        /* Modern CSS rendering optimization for large tables */
        .roster-row {
            content-visibility: auto;
            contain-intrinsic-size: 0 45px;
        }

        .badge { padding: 0.25rem 0.625rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; }
        .badge-danger { background: var(--danger-bg); color: var(--danger-text); }
        .badge-success { background: var(--success-bg); color: var(--success-text); }
        .alert { padding: 0.75rem; border-radius: 6px; margin-bottom: 1rem; font-size: 0.875rem; }
        .alert-success, .alert-info { background: var(--success-bg); color: var(--success-text); border: 1px solid #bbf7d0; }
        .alert-error { background: var(--danger-bg); color: var(--danger-text); border: 1px solid #fecaca; }

        .pagination-bar { display: flex; justify-content: space-between; align-items: center; margin-top: 1.5rem; padding-top: 1rem; border-top: 1px solid var(--border); flex-wrap: wrap; gap: 1rem; }

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
            {% if current_user.role == 'Admin' %}
            <form method="GET" action="/" style="margin:0; display:flex; align-items:center; gap:0.5rem;">
                <label style="font-size:0.85rem; font-weight:600; color:var(--muted);">Active School:</label>
                <select name="school_id" onchange="this.form.submit()" style="font-weight:600; background:#f1f5f9; border-color:#cbd5e1;">
                    <option value="all" {% if selected_school_id == 'all' %}selected{% endif %}>All Schools (District View)</option>
                    {% for sch in schools %}
                    <option value="{{ sch.id }}" {% if selected_school_id == sch.id|string %}selected{% endif %}>{{ sch.name }}</option>
                    {% endfor %}
                </select>
            </form>
            {% else %}
            <span style="font-weight:600; font-size:0.9rem;">🏫 {{ active_school_name }}</span>
            {% endif %}

            <span style="font-size:0.875rem; color:var(--muted);">
                User: <strong>{{ current_user.username }}</strong> ({{ current_user.role }})
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

        <div style="background:#eff6ff; border:1px solid #bfdbfe; border-radius:8px; padding:0.85rem 1.25rem; margin-bottom:1.5rem; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem;">
            <div style="font-size:0.9rem; color:#1e40af;">
                Showing Data For: <strong>{{ active_school_name }}</strong>
            </div>
            
            {% if current_user.role == 'Admin' and selected_school_id != 'all' %}
            <form method="POST" action="/clear_school_data" onsubmit="return confirm('Are you sure you want to delete ALL student records for {{ active_school_name }}? This action cannot be undone.');" style="margin:0;">
                <input type="hidden" name="school_id" value="{{ selected_school_id }}">
                <button type="submit" class="btn btn-danger btn-sm">🗑️ Clear Data For {{ active_school_name }}</button>
            </form>
            {% endif %}
        </div>

        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-title">Total Students</div>
                <div class="metric-value">{{ total_students }}</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">Chronically Absent (PresentFTE &lt; 90%)</div>
                <div class="metric-value" style="color: #dc2626;">{{ at_risk_count }}</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">Chronic Absenteeism Rate</div>
                <div class="metric-value" style="color: #dc2626;">{{ "%.1f"|format(chronic_rate) }}%</div>
            </div>
        </div>

        {% if current_user.role == 'Admin' %}
        <div class="grid-2">
            <div class="card">
                <h3 class="card-title" style="margin-bottom:1rem;">🏫 Add New School</h3>
                <form method="POST" action="/add_school" style="display:flex; flex-direction:column; gap:0.75rem;">
                    <div class="form-row">
                        <input type="text" name="name" placeholder="School Name" required style="flex:2;">
                        <input type="text" name="code" placeholder="Code (e.g. HMS)" required style="flex:1;">
                        <button type="submit" class="btn">Add School</button>
                    </div>
                </form>
            </div>

            <div class="card">
                <h3 class="card-title" style="margin-bottom:1rem;">👤 Add User / Staff Account</h3>
                <form method="POST" action="/add_user" style="display:flex; flex-direction:column; gap:0.75rem;">
                    <div class="form-row">
                        <input type="text" name="username" placeholder="Username (email or name)" required style="flex:1;">
                        <input type="password" name="password" placeholder="Password" required style="flex:1;">
                    </div>
                    <div class="form-row">
                        <select name="role" required style="flex:1;">
                            <option value="Staff">Role: Staff</option>
                            <option value="Admin">Role: Admin</option>
                        </select>
                        <select name="school_id" style="flex:1;">
                            <option value="">Assigned School (Optional)</option>
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

        <div class="grid-2">
            <div class="card">
                <h3 class="card-title" style="margin-bottom:1rem;">Add Single Student</h3>
                <form method="POST" action="/add_student" style="display:flex; flex-direction:column; gap:0.75rem;">
                    {% if current_user.role == 'Admin' %}
                    <div class="form-row">
                        <select name="school_id" style="flex:1;" required>
                            <option value="">Select Target School...</option>
                            {% for school in schools %}
                            <option value="{{ school.id }}" {% if selected_school_id == school.id|string %}selected{% endif %}>{{ school.name }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    {% endif %}
                    <div class="form-row">
                        <input type="text" name="student_id" placeholder="Student ID" required style="flex:1;">
                        <input type="text" name="name" placeholder="Student Name" required style="flex:2;">
                    </div>
                    <div class="form-row">
                        <input type="text" name="grade" placeholder="Grade (e.g. 6, 7, 8)" style="flex:1;">
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
                            <option value="{{ school.id }}" {% if selected_school_id == school.id|string %}selected{% endif %}>{{ school.name }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    {% endif %}
                    <div class="form-row">
                        <input type="file" name="file" accept=".csv" required style="flex:1;">
                        <button type="submit" class="btn">Import CSV</button>
                    </div>
                    <small style="color:var(--muted);">Overwrites attendance metrics for matching student IDs while preserving intervention history & user accounts.</small>
                </form>
            </div>
        </div>

        <div class="card">
            <div class="card-header">
                <h3 class="card-title">Attendance Roster View</h3>
                <form method="GET" action="/" style="display:flex; gap:1rem; align-items:center; flex-wrap:wrap; margin:0;">
                    <input type="hidden" name="school_id" value="{{ selected_school_id }}">
                    <input type="hidden" name="page" value="1">
                    
                    <div class="filter-btn-group">
                        <a href="/?school_id={{ selected_school_id }}&filter=chronic&grade={{ selected_grade }}&search={{ search_query }}" class="filter-btn {% if selected_filter == 'chronic' %}active{% endif %}">Chronic Students (&lt;90%)</a>
                        <a href="/?school_id={{ selected_school_id }}&filter=most-absences&grade={{ selected_grade }}&search={{ search_query }}" class="filter-btn {% if selected_filter == 'most-absences' %}active{% endif %}">Most Absences</a>
                        <a href="/?school_id={{ selected_school_id }}&filter=least-absences&grade={{ selected_grade }}&search={{ search_query }}" class="filter-btn {% if selected_filter == 'least-absences' %}active{% endif %}">Least Absences</a>
                    </div>

                    <input type="hidden" name="filter" value="{{ selected_filter }}">

                    <select name="grade" onchange="this.form.submit()" style="padding:0.5rem; font-size:0.85rem; font-weight:600; color:var(--muted); border-radius:6px; border:1px solid var(--border);">
                        <option value="all" {% if selected_grade == 'all' %}selected{% endif %}>All Grade Levels</option>
                        {% for g in available_grades %}
                        <option value="{{ g }}" {% if selected_grade == g %}selected{% endif %}>Grade {{ g }}</option>
                        {% endfor %}
                    </select>

                    <input type="text" name="search" value="{{ search_query }}" placeholder="Search name or ID..." style="width:200px;">
                    <button type="submit" class="btn btn-outline btn-sm">Search</button>
                </form>
            </div>

            <table>
                <thead>
                    <tr>
                        <th>Student ID</th>
                        <th>Name</th>
                        <th>Grade</th>
                        <th>School</th>
                        <th>Absences</th>
                        <th>PresentFTE (Col V)</th>
                        <th>Status</th>
                        <th>Interventions Logged</th>
                        <th style="text-align:right;">Action</th>
                    </tr>
                </thead>
                <tbody>
                    {% for student in students %}
                    <tr class="roster-row">
                        <td><strong>{{ student.student_id }}</strong></td>
                        <td class="student-name">{{ student.name }}</td>
                        <td><span class="badge" style="background:#e2e8f0; color:#334155;">{{ student.grade }}</span></td>
                        <td>{{ student.school_name }}</td>
                        <td><strong>{{ student.adjusted_absences }}</strong></td>
                        <td><strong>{{ "%.1f"|format(student.present_fte_pct) }}%</strong></td>
                        <td>
                            {% if student.is_chronic %}
                                <span class="badge badge-danger">Chronic (&lt;90%)</span>
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
                        <td colspan="9" style="text-align: center; color: var(--muted); padding: 2rem;">
                            No student record data available for this view.
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>

            <!-- Pagination Bar -->
            {% if total_pages > 1 %}
            <div class="pagination-bar">
                <span style="font-size:0.875rem; color:var(--muted);">
                    Page <strong>{{ current_page }}</strong> of <strong>{{ total_pages }}</strong> ({{ display_count }} active students matching filters)
                </span>
                <div style="display:flex; gap:0.5rem;">
                    {% if current_page > 1 %}
                    <a href="/?school_id={{ selected_school_id }}&filter={{ selected_filter }}&grade={{ selected_grade }}&search={{ search_query }}&page={{ current_page - 1 }}" class="btn btn-outline btn-sm">&laquo; Previous</a>
                    {% endif %}
                    
                    {% if current_page < total_pages %}
                    <a href="/?school_id={{ selected_school_id }}&filter={{ selected_filter }}&grade={{ selected_grade }}&search={{ search_query }}&page={{ current_page + 1 }}" class="btn btn-outline btn-sm">Next &raquo;</a>
                    {% endif %}
                </div>
            </div>
            {% endif %}
        </div>
    </div>

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

    <script>
        function openInterventionModal(studentId, name) {
            document.getElementById('modalStudentDbId').value = studentId;
            document.getElementById('modalStudentName').value = name;
            document.getElementById('interventionModal').style.display = 'flex';
        }

        function closeInterventionModal() {
            document.getElementById('interventionModal').style.display = 'none';
        }
    </script>
</body>
</html>
"""

# --- Helper Functions ---

def get_current_user():
    user_id = session.get('user_id')
    if user_id:
        return User.query.get(user_id)
    return None

def init_db():
    db.create_all()
    # Seed default Highland Middle School if database is empty
    mms = School.query.filter_by(code='HMS').first()
    if not mms:
        mms = School(name='Highland Middle School', code='HMS')
        db.session.add(mms)

    # Seed default Admin account if missing
    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin', 
            password_hash=generate_password_hash('admin123'), 
            role='Admin'
        )
        db.session.add(admin)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()

# --- Application Startup Execution ---
with app.app_context():
    init_db()

# --- Routes ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            return redirect(url_for('index'))
        
        flash('Invalid username or password.', 'error')
    return render_template_string(LOGIN_HTML)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def index():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    schools = School.query.all()
    selected_school_id = request.args.get('school_id', 'all')
    selected_filter = request.args.get('filter', 'chronic')
    selected_grade = request.args.get('grade', 'all')
    search_query = request.args.get('search', '').strip()
    
    # Safe Integer Conversion for Page Parameter
    try:
        page = int(request.args.get('page', 1))
    except (ValueError, TypeError):
        page = 1
        
    per_page = 50  # Display 50 students per page to prevent DOM slowdown

    # Eager Load Relationships to prevent N+1 queries
    base_query = StudentRecord.query.options(
        joinedload(StudentRecord.school),
        subqueryload(StudentRecord.interventions)
    )

    if user.role == 'Admin':
        if selected_school_id != 'all' and selected_school_id:
            try:
                s_id = int(selected_school_id)
                records = base_query.filter_by(school_id=s_id).all()
                active_sch = School.query.get(s_id)
                active_school_name = active_sch.name if active_sch else 'Selected School'
            except ValueError:
                records = base_query.all()
                active_school_name = 'All District Schools'
        else:
            records = base_query.all()
            active_school_name = 'All District Schools'
    else:
        records = base_query.filter_by(school_id=user.school_id).all()
        active_school_name = user.school.name if user.school else 'Assigned School'

    all_parsed_students = []
    total_students = len(records)
    at_risk_count = 0
    grades_set = set()

    for r in records:
        tardy_absences = (r.tardies or 0) // TARDY_CONVERSION_FACTOR
        adjusted_absences = (r.absences or 0.0) + tardy_absences

        if r.present_fte is not None:
            val = r.present_fte
            fte_ratio = val / 100.0 if val > 1.0 else val
            present_fte_pct = fte_ratio * 100.0
        else:
            total_d = r.total_days if (r.total_days and r.total_days > 0) else 180
            calc_abs_rate = (adjusted_absences / total_d)
            fte_ratio = max(0.0, 1.0 - calc_abs_rate)
            present_fte_pct = fte_ratio * 100.0

        is_chronic = fte_ratio < 0.90

        if is_chronic:
            at_risk_count += 1

        if r.grade and r.grade != 'N/A':
            grades_set.add(r.grade)

        interventions_logged = [{
            'action_type': item.action_type,
            'notes': item.notes,
            'logged_by': item.logged_by,
            'timestamp': item.timestamp.strftime('%b %d, %Y %H:%M') if item.timestamp else ''
        } for item in (r.interventions or [])]

        all_parsed_students.append({
            'id': r.id,
            'student_id': r.student_id,
            'name': r.name,
            'grade': r.grade or 'N/A',
            'school_name': r.school.name if r.school else 'Unassigned',
            'absences': r.absences or 0,
            'tardies': r.tardies or 0,
            'adjusted_absences': adjusted_absences,
            'present_fte_pct': present_fte_pct,
            'is_chronic': is_chronic,
            'interventions': interventions_logged
        })

    chronic_rate = (at_risk_count / total_students * 100) if total_students > 0 else 0.0

    # Filtering Logic
    filtered_students = []
    search_lower = search_query.lower()

    for s in all_parsed_students:
        if selected_filter == 'chronic' and not s['is_chronic']:
            continue
        
        if selected_grade != 'all' and s['grade'] != selected_grade:
            continue

        if search_query and (search_lower not in s['name'].lower() and search_lower not in s['student_id'].lower()):
            continue

        filtered_students.append(s)

    # Sorting Logic
    if selected_filter == 'most-absences':
        filtered_students.sort(key=lambda x: x['adjusted_absences'], reverse=True)
    elif selected_filter == 'least-absences':
        filtered_students.sort(key=lambda x: x['adjusted_absences'])

    # Server-Side Pagination Processing
    display_count = len(filtered_students)
    total_pages = math.ceil(display_count / per_page) if display_count > 0 else 1
    page = max(1, min(page, total_pages))
    
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_students = filtered_students[start_idx:end_idx]

    return render_template_string(
        INDEX_HTML,
        current_user=user,
        students=paginated_students,
        schools=schools,
        total_students=total_students,
        at_risk_count=at_risk_count,
        chronic_rate=chronic_rate,
        selected_school_id=selected_school_id,
        selected_filter=selected_filter,
        selected_grade=selected_grade,
        search_query=search_query,
        active_school_name=active_school_name,
        available_grades=sorted(list(grades_set)),
        current_page=page,
        total_pages=total_pages,
        display_count=display_count
    )

@app.route('/add_school', methods=['POST'])
def add_school():
    user = get_current_user()
    if not user or user.role != 'Admin':
        return redirect(url_for('index'))

    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip().upper()

    if not name or not code:
        flash('School name and code are required.', 'error')
        return redirect(url_for('index'))

    school = School(name=name, code=code)
    try:
        db.session.add(school)
        db.session.commit()
        flash(f'School "{name}" created successfully.', 'success')
    except IntegrityError:
        db.session.rollback()
        flash(f'A school with name "{name}" or code "{code}" already exists.', 'error')

    return redirect(url_for('index'))

@app.route('/add_user', methods=['POST'])
def add_user():
    user = get_current_user()
    if not user or user.role != 'Admin':
        return redirect(url_for('index'))

    username = request.form.get('username', '').strip()
    password = request.form.get('password')
    role = request.form.get('role', 'Staff')
    school_id = request.form.get('school_id')

    if not username or not password:
        flash('Username and password are required.', 'error')
        return redirect(url_for('index'))

    # Check for existing user before database commit
    existing_user = User.query.filter_by(username=username).first()
    if existing_user:
        flash(f'User "{username}" already exists.', 'error')
        return redirect(url_for('index'))

    school_id = int(school_id) if school_id else None
    new_user = User(
        username=username,
        password_hash=generate_password_hash(password),
        role=role,
        school_id=school_id
    )

    try:
        db.session.add(new_user)
        db.session.commit()
        flash(f'User "{username}" created successfully.', 'success')
    except IntegrityError:
        db.session.rollback()
        flash(f'Failed to create user. Username "{username}" is already taken.', 'error')

    return redirect(url_for('index'))

@app.route('/add_student', methods=['POST'])
def add_student():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    student_id = request.form.get('student_id', '').strip()
    name = request.form.get('name', '').strip()
    grade = request.form.get('grade', 'N/A').strip()
    
    try:
        absences = float(request.form.get('absences', 0))
        tardies = int(request.form.get('tardies', 0))
    except ValueError:
        absences, tardies = 0.0, 0

    target_school_id = request.form.get('school_id') if user.role == 'Admin' else user.school_id
    target_school_id = int(target_school_id) if target_school_id else None

    # Update student attendance in place if student ID exists
    existing = StudentRecord.query.filter_by(student_id=student_id, school_id=target_school_id).first()
    if existing:
        existing.name = name
        existing.grade = grade
        existing.absences = absences
        existing.tardies = tardies
        flash(f'Attendance record for {name} updated.', 'success')
    else:
        student = StudentRecord(
            student_id=student_id,
            name=name,
            grade=grade,
            absences=absences,
            tardies=tardies,
            school_id=target_school_id
        )
        db.session.add(student)
        flash(f'Student {name} added.', 'success')

    db.session.commit()
    return redirect(url_for('index'))

@app.route('/upload_csv', methods=['POST'])
def upload_csv():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    target_school_id = request.form.get('school_id') if user.role == 'Admin' else user.school_id
    if not target_school_id:
        flash('Target school selection required for CSV import.', 'error')
        return redirect(url_for('index'))

    target_school_id = int(target_school_id)
    file = request.files.get('file')

    if not file or not file.filename.endswith('.csv'):
        flash('Please upload a valid CSV file.', 'error')
        return redirect(url_for('index'))

    stream = io.StringIO(file.stream.read().decode("UTF-8"), newline=None)
    csv_reader = csv.DictReader(stream)

    # Fetch existing students into memory map to avoid duplicate key issues
    existing_students = {
        s.student_id: s 
        for s in StudentRecord.query.filter_by(school_id=target_school_id).all()
    }

    updated_count = 0
    created_count = 0

    for row in csv_reader:
        s_id = row.get('Student ID') or row.get('ID') or row.get('student_id')
        name = row.get('Name') or row.get('Student Name') or row.get('name')
        grade = row.get('Grade') or row.get('grade') or 'N/A'
        
        try:
            absences = float(row.get('Absences') or row.get('absences') or 0.0)
            tardies = int(row.get('Tardies') or row.get('tardies') or 0)
        except ValueError:
            absences, tardies = 0.0, 0

        present_fte = row.get('PresentFTE') or row.get('present_fte')

        if s_id and name:
            s_id = str(s_id).strip()
            if s_id in existing_students:
                # Update attendance metrics in place (Preserves Interventions)
                student = existing_students[s_id]
                student.name = name
                student.grade = grade
                student.absences = absences
                student.tardies = tardies
                student.present_fte = float(present_fte) if present_fte else None
                updated_count += 1
            else:
                # Add new student record
                new_student = StudentRecord(
                    student_id=s_id,
                    name=name,
                    grade=grade,
                    absences=absences,
                    tardies=tardies,
                    present_fte=float(present_fte) if present_fte else None,
                    school_id=target_school_id
                )
                db.session.add(new_student)
                created_count += 1

    db.session.commit()
    flash(f'Import complete: Updated attendance for {updated_count} students, added {created_count} new students.', 'success')
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
            notes=notes,
            logged_by=user.username
        )
        db.session.add(intervention)
        db.session.commit()
        flash('Intervention logged successfully.', 'success')

    return redirect(url_for('index'))

@app.route('/clear_school_data', methods=['POST'])
def clear_school_data():
    user = get_current_user()
    if not user or user.role != 'Admin':
        return redirect(url_for('index'))

    school_id = request.form.get('school_id')
    if school_id and school_id != 'all':
        s_id = int(school_id)
        StudentRecord.query.filter_by(school_id=s_id).delete()
        db.session.commit()
        flash('School student records cleared.', 'success')

    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

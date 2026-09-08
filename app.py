import os
import csv
import io
import math
from datetime import datetime
from functools import wraps
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

# Fetch Railway DATABASE_URL environment variable
db_url = os.environ.get('DATABASE_URL', 'sqlite:///attendance_tracker.db')

# Automatic fix for Railway URI compatibility (convert postgres:// to postgresql://)
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# -----------------------------------------------------------------------------
# Database Models
# -----------------------------------------------------------------------------
class School(db.Model):
    __tablename__ = 'school'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    code = db.Column(db.String(20), nullable=False, unique=True)
    
    users = db.relationship('User', backref='school', lazy=True, foreign_keys='User.school_id')
    students = db.relationship('StudentRecord', backref='school', lazy=True, cascade="all, delete-orphan", foreign_keys='StudentRecord.school_id')

class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='Staff')
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=True)

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
    present_fte = db.Column(db.Float, nullable=True)
    
    interventions = db.relationship('Intervention', backref='student', lazy=True, cascade="all, delete-orphan", foreign_keys='Intervention.student_record_id')

class Intervention(db.Model):
    __tablename__ = 'intervention'
    id = db.Column(db.Integer, primary_key=True)
    student_record_id = db.Column(db.Integer, db.ForeignKey('student_record.id'), nullable=False)
    action_type = db.Column(db.String(50), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    logged_by = db.Column(db.String(80), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# -----------------------------------------------------------------------------
# Embedded HTML Templates
# -----------------------------------------------------------------------------
LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sign In - Attendance Insights</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Plus Jakarta Sans', sans-serif; background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); color: #f8fafc; }
        .login-card { background: rgba(255, 255, 255, 0.03); backdrop-filter: blur(16px); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 1rem; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5); }
        .form-control { background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255, 255, 255, 0.15); color: #f8fafc; border-radius: 0.5rem; padding: 0.75rem 1rem; }
        .form-control:focus { background: rgba(15, 23, 42, 0.8); border-color: #3b82f6; color: #fff; }
        .btn-primary-custom { background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%); border: none; border-radius: 0.5rem; padding: 0.75rem; font-weight: 600; color: white; }
    </style>
</head>
<body class="d-flex align-items-center min-vh-100">
    <div class="container">
        <div class="row justify-content-center">
            <div class="col-md-5 col-lg-4">
                <div class="card login-card p-4 p-md-5">
                    <div class="text-center mb-4">
                        <h4 class="fw-bold text-white mb-1">Attendance Tracker</h4>
                        <p class="text-secondary small mb-0">Sign in to access your dashboard</p>
                    </div>
                    {% with messages = get_flashed_messages(with_categories=true) %}
                        {% if messages %}
                            {% for category, message in messages %}
                                <div class="alert alert-{{ 'danger' if category == 'error' else 'info' }} bg-opacity-10 border-0 text-capitalize small py-2" role="alert">
                                    {{ message }}
                                </div>
                            {% endfor %}
                        {% endif %}
                    {% endwith %}
                    <form action="{{ url_for('login') }}" method="POST">
                        <div class="mb-3">
                            <label class="form-label text-secondary small fw-medium">Username</label>
                            <input type="text" name="username" class="form-control" placeholder="Enter your username" required autofocus>
                        </div>
                        <div class="mb-4">
                            <label class="form-label text-secondary small fw-medium">Password</label>
                            <input type="password" name="password" class="form-control" placeholder="••••••••" required>
                        </div>
                        <button type="submit" class="btn btn-primary-custom w-100">Sign In</button>
                    </form>
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
    <title>Dashboard - Attendance Tracker</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root { --bg-body: #f8fafc; --card-bg: #ffffff; --border-color: #e2e8f0; --text-main: #0f172a; }
        body { font-family: 'Plus Jakarta Sans', sans-serif; background-color: var(--bg-body); color: var(--text-main); }
        .navbar-custom { background-color: #0f172a; border-bottom: 1px solid #1e293b; }
        .stat-card { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 0.75rem; padding: 1.25rem; }
        .card-custom { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 0.75rem; }
        .table-custom th { background-color: #f1f5f9; color: #475569; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; padding: 0.85rem 1rem; border-bottom: 1px solid var(--border-color); }
        .table-custom td { padding: 1rem; vertical-align: middle; border-bottom: 1px solid var(--border-color); font-size: 0.875rem; }
        .badge-chronic { background-color: #fef2f2; color: #dc2626; border: 1px solid #fecaca; padding: 0.35em 0.65em; font-size: 0.75rem; border-radius: 0.375rem; font-weight: 600; }
        .badge-ontrack { background-color: #f0fdf4; color: #16a34a; border: 1px solid #bbf7d0; padding: 0.35em 0.65em; font-size: 0.75rem; border-radius: 0.375rem; font-weight: 600; }
        .btn-action { font-size: 0.8125rem; font-weight: 500; border-radius: 0.375rem; padding: 0.4rem 0.75rem; }
    </style>
</head>
<body>

    <nav class="navbar navbar-expand-lg navbar-dark navbar-custom sticky-top">
        <div class="container-fluid px-4">
            <a class="navbar-brand fw-bold" href="#">Attendance Pulse</a>
            <div class="d-flex align-items-center gap-3 text-light">
                <span class="small">{{ current_user.username }} ({{ current_user.role }})</span>
                <a href="{{ url_for('logout') }}" class="btn btn-outline-light btn-sm btn-action">Sign Out</a>
            </div>
        </div>
    </nav>

    <div class="container-fluid px-4 py-4">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ 'danger' if category == 'error' else 'success' }} alert-dismissible fade show border-0 shadow-sm mb-4" role="alert">
                        {{ message }}
                        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        <!-- KPIs -->
        <div class="row g-3 mb-4">
            <div class="col-12 col-sm-6 col-xl-3">
                <div class="stat-card">
                    <div class="text-muted small fw-medium">Active School</div>
                    <div class="h5 fw-bold mb-0 text-truncate">{{ active_school_name }}</div>
                </div>
            </div>
            <div class="col-12 col-sm-6 col-xl-3">
                <div class="stat-card">
                    <div class="text-muted small fw-medium">Total Students</div>
                    <div class="h3 fw-bold mb-0">{{ total_students }}</div>
                </div>
            </div>
            <div class="col-12 col-sm-6 col-xl-3">
                <div class="stat-card">
                    <div class="text-muted small fw-medium">Chronically Absent</div>
                    <div class="h3 fw-bold mb-0 text-danger">{{ at_risk_count }}</div>
                </div>
            </div>
            <div class="col-12 col-sm-6 col-xl-3">
                <div class="stat-card">
                    <div class="text-muted small fw-medium">Chronic Rate</div>
                    <div class="h3 fw-bold mb-0">{{ "%.1f"|format(chronic_rate) }}%</div>
                </div>
            </div>
        </div>

        <!-- Action Bar -->
        <div class="card-custom p-3 mb-4">
            <div class="d-flex flex-wrap align-items-center justify-content-between gap-3">
                <div class="d-flex flex-wrap gap-2">
                    <button class="btn btn-primary btn-action" data-bs-toggle="modal" data-bs-target="#uploadCsvModal">Import CSV</button>
                    <button class="btn btn-outline-secondary btn-action" data-bs-toggle="modal" data-bs-target="#addStudentModal">+ Student</button>
                    {% if current_user.role == 'Admin' %}
                        <button class="btn btn-outline-secondary btn-action" data-bs-toggle="modal" data-bs-target="#addSchoolModal">+ School</button>
                        <button class="btn btn-outline-secondary btn-action" data-bs-toggle="modal" data-bs-target="#addUserModal">+ User</button>
                    {% endif %}
                </div>
                {% if current_user.role == 'Admin' %}
                    <button class="btn btn-outline-danger btn-action" data-bs-toggle="modal" data-bs-target="#clearDataModal">Clear Data</button>
                {% endif %}
            </div>

            <hr class="my-3" style="border-color: var(--border-color);">

            <form method="GET" action="{{ url_for('index') }}" class="row g-2">
                {% if current_user.role == 'Admin' %}
                <div class="col-12 col-sm-6 col-md-3">
                    <select name="school_id" class="form-select form-select-sm" onchange="this.form.submit()">
                        <option value="all" {% if selected_school_id == 'all' %}selected{% endif %}>All Schools</option>
                        {% for sch in schools %}
                            <option value="{{ sch.id }}" {% if selected_school_id == (sch.id|string) %}selected{% endif %}>{{ sch.name }}</option>
                        {% endfor %}
                    </select>
                </div>
                {% endif %}

                <div class="col-6 col-md-2">
                    <select name="grade" class="form-select form-select-sm" onchange="this.form.submit()">
                        <option value="all" {% if selected_grade == 'all' %}selected{% endif %}>All Grades</option>
                        {% for g in available_grades %}
                            <option value="{{ g }}" {% if selected_grade == g %}selected{% endif %}>Grade {{ g }}</option>
                        {% endfor %}
                    </select>
                </div>

                <div class="col-6 col-md-2">
                    <select name="filter" class="form-select form-select-sm" onchange="this.form.submit()">
                        <option value="all" {% if selected_filter == 'all' %}selected{% endif %}>All Records</option>
                        <option value="chronic" {% if selected_filter == 'chronic' %}selected{% endif %}>Chronic (&lt;90%)</option>
                        <option value="most-absences" {% if selected_filter == 'most-absences' %}selected{% endif %}>Most Absences</option>
                        <option value="least-absences" {% if selected_filter == 'least-absences' %}selected{% endif %}>Least Absences</option>
                    </select>
                </div>

                <div class="col-12 col-md-3">
                    <input type="text" name="q" class="form-control form-control-sm" placeholder="Search name or ID..." value="{{ search_query }}">
                </div>

                <div class="col-12 col-md-2 d-flex gap-2">
                    <button type="submit" class="btn btn-sm btn-dark btn-action w-100">Filter</button>
                    <a href="{{ url_for('index') }}" class="btn btn-sm btn-light border btn-action">Reset</a>
                </div>
            </form>
        </div>

        <!-- Student Data Table -->
        <div class="card-custom overflow-hidden">
            <div class="table-responsive">
                <table class="table table-custom">
                    <thead>
                        <tr>
                            <th>Student ID</th>
                            <th>Name</th>
                            <th>Grade</th>
                            <th>School</th>
                            <th>Absences</th>
                            <th>Present FTE %</th>
                            <th>Status</th>
                            <th>Interventions</th>
                            <th class="text-end">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for s in students %}
                        <tr>
                            <td class="fw-semibold text-secondary">{{ s.student_id }}</td>
                            <td class="fw-bold">{{ s.name }}</td>
                            <td><span class="badge bg-light text-dark border">{{ s.grade }}</span></td>
                            <td>{{ s.school.name if s.school else 'N/A' }}</td>
                            <td>{{ "%.1f"|format(s.absences) }}</td>
                            <td class="fw-semibold">
                                {% if s.present_fte %}
                                    {{ "%.1f"|format(s.present_fte * 100) }}%
                                {% else %}
                                    {{ "%.1f"|format(((s.total_days - s.absences) / s.total_days) * 100) }}%
                                {% endif %}
                            </td>
                            <td>
                                {% if (s.absences / s.total_days) >= 0.10 %}
                                    <span class="badge-chronic">Chronic</span>
                                {% else %}
                                    <span class="badge-ontrack">On Track</span>
                                {% endif %}
                            </td>
                            <td>
                                <span class="badge bg-secondary bg-opacity-10 text-secondary border">{{ s.interventions|length }} Logs</span>
                            </td>
                            <td class="text-end">
                                <button class="btn btn-sm btn-outline-primary btn-action" data-bs-toggle="modal" data-bs-target="#interventionModal{{ s.id }}">
                                    Log Action
                                </button>
                            </td>
                        </tr>

                        <!-- Intervention Modal -->
                        <div class="modal fade" id="interventionModal{{ s.id }}" tabindex="-1">
                            <div class="modal-dialog modal-dialog-centered">
                                <div class="modal-content border-0 shadow">
                                    <form action="{{ url_for('log_intervention') }}" method="POST">
                                        <div class="modal-header border-bottom-0 pb-0">
                                            <h5 class="modal-title fw-bold">Interventions - {{ s.name }}</h5>
                                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                                        </div>
                                        <div class="modal-body">
                                            <input type="hidden" name="student_db_id" value="{{ s.id }}">
                                            <div class="mb-3">
                                                <label class="form-label small fw-semibold text-secondary">Action Type</label>
                                                <select name="action_type" class="form-select form-select-sm" required>
                                                    <option value="Parent Contact">Parent Contact</option>
                                                    <option value="Student Conference">Student Conference</option>
                                                    <option value="Attendance Contract">Attendance Contract</option>
                                                    <option value="Home Visit">Home Visit</option>
                                                    <option value="Truancy Referral">Truancy Referral</option>
                                                </select>
                                            </div>
                                            <div class="mb-3">
                                                <label class="form-label small fw-semibold text-secondary">Notes</label>
                                                <textarea name="notes" class="form-control form-control-sm" rows="3" placeholder="Log details..."></textarea>
                                            </div>
                                            <div class="fw-semibold small text-dark mb-2">Previous Logs</div>
                                            <div class="list-group list-group-flush border rounded overflow-auto" style="max-height: 180px;">
                                                {% for i in s.interventions %}
                                                    <div class="list-group-item p-2 small">
                                                        <div class="d-flex justify-content-between fw-semibold">
                                                            <span>{{ i.action_type }}</span>
                                                            <span class="text-muted" style="font-size: 0.75rem;">{{ i.timestamp.strftime('%Y-%m-%d') }}</span>
                                                        </div>
                                                        <div class="text-secondary small">{{ i.notes if i.notes else 'No notes added.' }}</div>
                                                        <div class="text-muted" style="font-size: 0.7rem;">Logged by: {{ i.logged_by }}</div>
                                                    </div>
                                                {% else %}
                                                    <div class="list-group-item p-3 text-center text-muted small">No interventions recorded.</div>
                                                {% endfor %}
                                            </div>
                                        </div>
                                        <div class="modal-footer border-top-0 pt-0">
                                            <button type="submit" class="btn btn-primary btn-action w-100">Save Log</button>
                                        </div>
                                    </form>
                                </div>
                            </div>
                        </div>
                        {% else %}
                        <tr>
                            <td colspan="9" class="text-center py-5 text-muted">No student records matched your criteria.</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>

            {% if total_pages > 1 %}
            <div class="p-3 border-top d-flex justify-content-between align-items-center">
                <span class="text-muted small">Showing {{ display_count }} total entries</span>
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

    <!-- Modals -->
    <!-- CSV Upload -->
    <div class="modal fade" id="uploadCsvModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content border-0 shadow">
                <form action="{{ url_for('upload_csv') }}" method="POST" enctype="multipart/form-data">
                    <div class="modal-header border-bottom-0 pb-0">
                        <h5 class="modal-title fw-bold">Import CSV</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        {% if current_user.role == 'Admin' %}
                        <div class="mb-3">
                            <label class="form-label small fw-semibold text-secondary">Target School</label>
                            <select name="school_id" class="form-select form-select-sm" required>
                                {% for sch in schools %}
                                    <option value="{{ sch.id }}">{{ sch.name }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        {% endif %}
                        <div class="mb-3">
                            <label class="form-label small fw-semibold text-secondary">CSV File</label>
                            <input type="file" name="file" class="form-control form-control-sm" accept=".csv" required>
                            <div class="form-text small">Headers required: Student_ID, Name, Grade, Absences, Tardies, Present_FTE.</div>
                        </div>
                    </div>
                    <div class="modal-footer border-top-0 pt-0">
                        <button type="submit" class="btn btn-primary btn-action w-100">Upload & Parse</button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <!-- Add Student -->
    <div class="modal fade" id="addStudentModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content border-0 shadow">
                <form action="{{ url_for('add_student') }}" method="POST">
                    <div class="modal-header border-bottom-0 pb-0">
                        <h5 class="modal-title fw-bold">Add Student Record</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        {% if current_user.role == 'Admin' %}
                        <div class="mb-3">
                            <label class="form-label small fw-semibold text-secondary">School</label>
                            <select name="school_id" class="form-select form-select-sm" required>
                                {% for sch in schools %}
                                    <option value="{{ sch.id }}">{{ sch.name }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        {% endif %}
                        <div class="mb-3">
                            <label class="form-label small fw-semibold text-secondary">Student ID</label>
                            <input type="text" name="student_id" class="form-control form-control-sm" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label small fw-semibold text-secondary">Full Name</label>
                            <input type="text" name="name" class="form-control form-control-sm" required>
                        </div>
                        <div class="row g-2 mb-3">
                            <div class="col-6">
                                <label class="form-label small fw-semibold text-secondary">Grade</label>
                                <input type="text" name="grade" class="form-control form-control-sm" required>
                            </div>
                            <div class="col-6">
                                <label class="form-label small fw-semibold text-secondary">Absences</label>
                                <input type="number" step="0.5" name="absences" value="0.0" class="form-control form-control-sm" required>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer border-top-0 pt-0">
                        <button type="submit" class="btn btn-primary btn-action w-100">Create Student</button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    {% if current_user.role == 'Admin' %}
    <!-- Add School -->
    <div class="modal fade" id="addSchoolModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content border-0 shadow">
                <form action="{{ url_for('add_school') }}" method="POST">
                    <div class="modal-header border-bottom-0 pb-0">
                        <h5 class="modal-title fw-bold">Add School</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label small fw-semibold text-secondary">School Name</label>
                            <input type="text" name="name" class="form-control form-control-sm" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label small fw-semibold text-secondary">School Code</label>
                            <input type="text" name="code" class="form-control form-control-sm" required>
                        </div>
                    </div>
                    <div class="modal-footer border-top-0 pt-0">
                        <button type="submit" class="btn btn-primary btn-action w-100">Add School</button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <!-- Add User -->
    <div class="modal fade" id="addUserModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content border-0 shadow">
                <form action="{{ url_for('add_user') }}" method="POST">
                    <div class="modal-header border-bottom-0 pb-0">
                        <h5 class="modal-title fw-bold">Add Staff User</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label small fw-semibold text-secondary">Username</label>
                            <input type="text" name="username" class="form-control form-control-sm" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label small fw-semibold text-secondary">Password</label>
                            <input type="password" name="password" class="form-control form-control-sm" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label small fw-semibold text-secondary">Role</label>
                            <select name="role" class="form-select form-select-sm">
                                <option value="Staff">Staff</option>
                                <option value="Admin">Admin</option>
                            </select>
                        </div>
                        <div class="mb-3">
                            <label class="form-label small fw-semibold text-secondary">Assign School</label>
                            <select name="school_id" class="form-select form-select-sm">
                                <option value="">None (Global / Admin)</option>
                                {% for sch in schools %}
                                    <option value="{{ sch.id }}">{{ sch.name }}</option>
                                {% endfor %}
                            </select>
                        </div>
                    </div>
                    <div class="modal-footer border-top-0 pt-0">
                        <button type="submit" class="btn btn-primary btn-action w-100">Create User</button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <!-- Clear Data -->
    <div class="modal fade" id="clearDataModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content border-0 shadow">
                <form action="{{ url_for('clear_data') }}" method="POST">
                    <div class="modal-header border-bottom-0 pb-0">
                        <h5 class="modal-title fw-bold text-danger">Clear All Data</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body text-secondary small">
                        Are you sure you want to erase student and intervention records? This action cannot be undone.
                    </div>
                    <div class="modal-footer border-top-0 pt-0">
                        <button type="submit" class="btn btn-danger btn-action w-100">Delete Records</button>
                    </div>
                </form>
            </div>
        </div>
    </div>
    {% endif %}

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

# -----------------------------------------------------------------------------
# Decorators & Auth Helpers
# -----------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please sign in to access this page.", "error")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'Admin':
            flash("Administrator privileges required.", "error")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# -----------------------------------------------------------------------------
# Controller Routes
# -----------------------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            session['school_id'] = user.school_id
            return redirect(url_for('index'))
        
        flash("Invalid username or password.", "error")
    return render_template_string(LOGIN_HTML)

@app.route('/logout')
def logout():
    session.clear()
    flash("Successfully signed out.", "info")
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    user = User.query.get(session['user_id'])
    
    # URL parameters
    selected_school_id = request.args.get('school_id', 'all')
    selected_grade = request.args.get('grade', 'all')
    selected_filter = request.args.get('filter', 'all')
    search_query = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)

    # Scoping Base Queries
    query = StudentRecord.query

    # Enforce School boundary for non-admin staff
    if user.role != 'Admin':
        if user.school_id:
            query = query.filter_by(school_id=user.school_id)
            selected_school_id = str(user.school_id)
    elif selected_school_id != 'all':
        query = query.filter_by(school_id=int(selected_school_id))

    # Apply Grade Filter
    if selected_grade != 'all':
        query = query.filter_by(grade=selected_grade)

    # Apply Search Filter
    if search_query:
        query = query.filter(
            (StudentRecord.name.ilike(f"%{search_query}%")) | 
            (StudentRecord.student_id.ilike(f"%{search_query}%"))
        )

    # Apply Status Filters
    if selected_filter == 'chronic':
        query = query.filter((StudentRecord.absences / StudentRecord.total_days) >= 0.10)
    elif selected_filter == 'most-absences':
        query = query.order_by(StudentRecord.absences.desc())
    elif selected_filter == 'least-absences':
        query = query.order_by(StudentRecord.absences.asc())

    # Calculate KPI Stats before Pagination
    total_students = query.count()
    at_risk_count = query.filter((StudentRecord.absences / StudentRecord.total_days) >= 0.10).count()
    chronic_rate = (at_risk_count / total_students * 100) if total_students > 0 else 0.0

    # Paginate Results
    per_page = 25
    total_pages = math.ceil(total_students / per_page) if total_students > 0 else 1
    students = query.offset((page - 1) * per_page).limit(per_page).all()

    # Dropdown contextual data
    schools = School.query.all()
    available_grades = [g[0] for g in db.session.query(StudentRecord.grade).distinct().all() if g[0]]

    # Name for Active School Badge
    if selected_school_id != 'all':
        sch = School.query.get(int(selected_school_id))
        active_school_name = sch.name if sch else "All Schools"
    else:
        active_school_name = "All Schools"

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
        display_count=len(students)
    )

@app.route('/log_intervention', methods=['POST'])
@login_required
def log_intervention():
    student_db_id = request.form.get('student_db_id')
    action_type = request.form.get('action_type')
    notes = request.form.get('notes')
    logged_by = session.get('username', 'Staff')

    if not student_db_id or not action_type:
        flash("Failed to log intervention: Missing required parameters.", "error")
        return redirect(url_for('index'))

    intervention = Intervention(
        student_record_id=int(student_db_id),
        action_type=action_type,
        notes=notes,
        logged_by=logged_by,
        timestamp=datetime.utcnow()
    )

    db.session.add(intervention)
    db.session.commit()

    flash("Intervention recorded successfully!", "success")
    return redirect(url_for('index'))

@app.route('/upload_csv', methods=['POST'])
@login_required
def upload_csv():
    file = request.files.get('file')
    user = User.query.get(session['user_id'])
    
    school_id = user.school_id
    if user.role == 'Admin':
        school_id = request.form.get('school_id', user.school_id)

    if not school_id:
        flash("Please assign or select a school before uploading records.", "error")
        return redirect(url_for('index'))

    if not file or not file.filename.endswith('.csv'):
        flash("Invalid file form format. Please upload a .csv file.", "error")
        return redirect(url_for('index'))

    stream = io.StringIO(file.stream.read().decode("UTF-8"), newline=None)
    csv_input = csv.DictReader(stream)

    count = 0
    for row in csv_input:
        # Map common header key variations cleanly
        s_id = row.get('Student_ID') or row.get('student_id') or row.get('ID')
        name = row.get('Name') or row.get('name')
        grade = row.get('Grade') or row.get('grade') or 'N/A'
        absences = float(row.get('Absences', 0.0) or 0.0)
        tardies = int(row.get('Tardies', 0) or 0)
        present_fte = float(row.get('Present_FTE', 1.0) or 1.0)

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
    flash(f"Successfully processed {count} student records.", "success")
    return redirect(url_for('index'))

@app.route('/add_student', methods=['POST'])
@login_required
def add_student():
    user = User.query.get(session['user_id'])
    school_id = user.school_id if user.role != 'Admin' else request.form.get('school_id')

    if not school_id:
        flash("Target school allocation is missing.", "error")
        return redirect(url_for('index'))

    student_id = request.form.get('student_id')
    name = request.form.get('name')
    grade = request.form.get('grade', 'N/A')
    absences = float(request.form.get('absences', 0.0))

    record = StudentRecord(
        student_id=student_id,
        name=name,
        grade=grade,
        absences=absences,
        school_id=int(school_id)
    )
    db.session.add(record)
    db.session.commit()

    flash("Student created successfully.", "success")
    return redirect(url_for('index'))

@app.route('/add_school', methods=['POST'])
@login_required
@admin_required
def add_school():
    name = request.form.get('name')
    code = request.form.get('code')
    
    try:
        sch = School(name=name, code=code)
        db.session.add(sch)
        db.session.commit()
        flash("School added successfully.", "success")
    except IntegrityError:
        db.session.rollback()
        flash("A school with that name or code already exists.", "error")

    return redirect(url_for('index'))

@app.route('/add_user', methods=['POST'])
@login_required
@admin_required
def add_user():
    username = request.form.get('username')
    password = request.form.get('password')
    role = request.form.get('role', 'Staff')
    school_id = request.form.get('school_id') or None

    try:
        usr = User(
            username=username,
            password_hash=generate_password_hash(password),
            role=role,
            school_id=int(school_id) if school_id else None
        )
        db.session.add(usr)
        db.session.commit()
        flash("User created successfully.", "success")
    except IntegrityError:
        db.session.rollback()
        flash("Username is already taken.", "error")

    return redirect(url_for('index'))

@app.route('/clear_data', methods=['POST'])
@login_required
@admin_required
def clear_data():
    db.session.query(Intervention).delete()
    db.session.query(StudentRecord).delete()
    db.session.commit()
    flash("Database wiped successfully.", "info")
    return redirect(url_for('index'))

# -----------------------------------------------------------------------------
# Database Initializer
# -----------------------------------------------------------------------------
with app.app_context():
    db.create_all()
    # Ensure default Admin account exists
    if not User.query.filter_by(username='admin').first():
        default_admin = User(
            username='admin',
            password_hash=generate_password_hash('admin123'),
            role='Admin'
        )
        db.session.add(default_admin)
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)

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
# Updated HTML Templates (Modern UI/UX)
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
        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            color: #f8fafc;
        }
        .login-card {
            background: rgba(255, 255, 255, 0.03);
            backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 1rem;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
        }
        .form-control {
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.15);
            color: #f8fafc;
            border-radius: 0.5rem;
            padding: 0.75rem 1rem;
        }
        .form-control:focus {
            background: rgba(15, 23, 42, 0.8);
            border-color: #3b82f6;
            color: #fff;
            box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.25);
        }
        .btn-primary-custom {
            background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
            border: none;
            border-radius: 0.5rem;
            padding: 0.75rem;
            font-weight: 600;
            color: white;
            transition: all 0.2s;
        }
        .btn-primary-custom:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(37, 99, 235, 0.4);
        }
    </style>
</head>
<body class="d-flex align-items-center min-vh-100">
    <div class="container">
        <div class="row justify-content-center">
            <div class="col-md-5 col-lg-4">
                <div class="card login-card p-4 p-md-5">
                    <div class="text-center mb-4">
                        <div class="d-inline-flex align-items-center justify-content-center bg-primary bg-opacity-20 text-primary rounded-circle mb-3" style="width: 56px; height: 56px;">
                            <svg width="28" height="28" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path></svg>
                        </div>
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
        :root {
            --bg-body: #f8fafc;
            --card-bg: #ffffff;
            --border-color: #e2e8f0;
            --text-main: #0f172a;
            --text-muted: #64748b;
        }
        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background-color: var(--bg-body);
            color: var(--text-main);
        }
        .navbar-custom {
            background-color: #0f172a;
            border-bottom: 1px solid #1e293b;
        }
        .stat-card {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 0.75rem;
            padding: 1.25rem;
            transition: all 0.2s ease-in-out;
        }
        .stat-card:hover {
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05);
            transform: translateY(-2px);
        }
        .stat-icon {
            width: 44px;
            height: 44px;
            border-radius: 0.5rem;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .card-custom {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 0.75rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.02);
        }
        .table-custom {
            margin-bottom: 0;
        }
        .table-custom th {
            background-color: #f1f5f9;
            color: #475569;
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            font-weight: 700;
            padding: 0.85rem 1rem;
            border-bottom: 1px solid var(--border-color);
        }
        .table-custom td {
            padding: 1rem;
            vertical-align: middle;
            border-bottom: 1px solid var(--border-color);
            color: #334155;
            font-size: 0.875rem;
        }
        .badge-status {
            padding: 0.35em 0.65em;
            font-size: 0.75rem;
            font-weight: 600;
            border-radius: 0.375rem;
        }
        .badge-chronic { background-color: #fef2f2; color: #dc2626; border: 1px solid #fecaca; }
        .badge-ontrack { background-color: #f0fdf4; color: #16a34a; border: 1px solid #bbf7d0; }
        .btn-action {
            font-size: 0.8125rem;
            font-weight: 500;
            border-radius: 0.375rem;
            padding: 0.4rem 0.75rem;
        }
    </style>
</head>
<body>

    <!-- Header Navigation -->
    <nav class="navbar navbar-expand-lg navbar-dark navbar-custom sticky-top">
        <div class="container-fluid px-4">
            <a class="navbar-brand d-flex align-items-center gap-2 fw-bold" href="#">
                <span class="bg-primary rounded p-1 d-inline-flex">
                    <svg width="20" height="20" fill="none" stroke="white" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path></svg>
                </span>
                Attendance Pulse
            </a>
            <div class="d-flex align-items-center gap-3">
                <div class="text-end text-light d-none d-sm-block">
                    <div class="fw-semibold fs-7">{{ current_user.username }}</div>
                    <div class="text-secondary small" style="font-size: 0.75rem;">Role: {{ current_user.role }}</div>
                </div>
                <a href="{{ url_for('logout') }}" class="btn btn-outline-light btn-sm btn-action">Sign Out</a>
            </div>
        </div>
    </nav>

    <div class="container-fluid px-4 py-4">

        <!-- Flash Messages -->
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ 'danger' if category == 'error' else 'success' }} alert-dismissible fade show border-0 shadow-sm mb-4" role="alert">
                        {{ message }}
                        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        <!-- KPI Summary Cards -->
        <div class="row g-3 mb-4">
            <div class="col-12 col-sm-6 col-xl-3">
                <div class="stat-card d-flex align-items-center justify-content-between">
                    <div>
                        <div class="text-muted small fw-medium">Active School</div>
                        <div class="h5 fw-bold mb-0 text-truncate" style="max-width: 180px;">{{ active_school_name }}</div>
                    </div>
                    <div class="stat-icon bg-primary bg-opacity-10 text-primary">
                        <svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5m0 0h4m-4 0V11m0 0h4m-4 0H9m4 0V7m0 0h4m-4 0H9"></path></svg>
                    </div>
                </div>
            </div>

            <div class="col-12 col-sm-6 col-xl-3">
                <div class="stat-card d-flex align-items-center justify-content-between">
                    <div>
                        <div class="text-muted small fw-medium">Total Students</div>
                        <div class="h3 fw-bold mb-0">{{ total_students }}</div>
                    </div>
                    <div class="stat-icon bg-info bg-opacity-10 text-info">
                        <svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"></path></svg>
                    </div>
                </div>
            </div>

            <div class="col-12 col-sm-6 col-xl-3">
                <div class="stat-card d-flex align-items-center justify-content-between">
                    <div>
                        <div class="text-muted small fw-medium">Chronically Absent</div>
                        <div class="h3 fw-bold mb-0 text-danger">{{ at_risk_count }}</div>
                    </div>
                    <div class="stat-icon bg-danger bg-opacity-10 text-danger">
                        <svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                    </div>
                </div>
            </div>

            <div class="col-12 col-sm-6 col-xl-3">
                <div class="stat-card d-flex align-items-center justify-content-between">
                    <div>
                        <div class="text-muted small fw-medium">Chronic Rate</div>
                        <div class="h3 fw-bold mb-0">{{ "%.1f"|format(chronic_rate) }}%</div>
                    </div>
                    <div class="stat-icon bg-warning bg-opacity-10 text-warning">
                        <svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"></path></svg>
                    </div>
                </div>
            </div>
        </div>

        <!-- Toolbar / Action Hub -->
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
                <div>
                    <button class="btn btn-outline-danger btn-action" data-bs-toggle="modal" data-bs-target="#clearDataModal">Clear Data</button>
                </div>
                {% endif %}
            </div>

            <hr class="my-3" style="border-color: var(--border-color);">

            <!-- Filter and Search Form -->
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

        <!-- Student Records Data Table -->
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
                            <td class="fw-bold text-dark">{{ s.name }}</td>
                            <td><span class="badge bg-light text-dark border">{{ s.grade }}</span></td>
                            <td>{{ s.school_name }}</td>
                            <td>{{ "%.1f"|format(s.adjusted_absences) }}</td>
                            <td class="fw-semibold">{{ "%.1f"|format(s.present_fte_pct) }}%</td>
                            <td>
                                {% if s.is_chronic %}
                                    <span class="badge-status badge-chronic">Chronic</span>
                                {% else %}
                                    <span class="badge-status badge-ontrack">On Track</span>
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

                        <!-- Intervention Modal per Student -->
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
                                                <textarea name="notes" class="form-control form-control-sm" rows="3" placeholder="Log details of the conversation or meeting..."></textarea>
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
                            <td colspan="9" class="text-center py-5 text-muted">
                                <div>No student records matched your filter criteria.</div>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>

            <!-- Footer Pagination -->
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
                            <div class="form-text small">Accepted columns: Student_ID, Name, Grade, Absences, Tardies, Present_FTE.</div>
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
                        <div class="mb-3">
                            <label class="form-label small fw-semibold text-secondary">Grade</label>
                            <input type="text" name="grade" class="form-control form-control-sm" placeholder="e.g. 9">
                        </div>
                        <div class="row">
                            <div class="col-6 mb-3">
                                <label class="form-label small fw-semibold text-secondary">Absences</label>
                                <input type="number" step="0.5" name="absences" class="form-control form-control-sm" value="0">
                            </div>
                            <div class="col-6 mb-3">
                                <label class="form-label small fw-semibold text-secondary">Tardies</label>
                                <input type="number" name="tardies" class="form-control form-control-sm" value="0">
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer border-top-0 pt-0">
                        <button type="submit" class="btn btn-primary btn-action w-100">Create Record</button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <!-- Admin: Add School -->
    {% if current_user.role == 'Admin' %}
    <div class="modal fade" id="addSchoolModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content border-0 shadow">
                <form action="{{ url_for('add_school') }}" method="POST">
                    <div class="modal-header border-bottom-0 pb-0">
                        <h5 class="modal-title fw-bold">Create School</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label small fw-semibold text-secondary">School Name</label>
                            <input type="text" name="name" class="form-control form-control-sm" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label small fw-semibold text-secondary">School Code</label>
                            <input type="text" name="code" class="form-control form-control-sm" placeholder="e.g. EHS" required>
                        </div>
                    </div>
                    <div class="modal-footer border-top-0 pt-0">
                        <button type="submit" class="btn btn-primary btn-action w-100">Save School</button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <!-- Admin: Add User -->
    <div class="modal fade" id="addUserModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content border-0 shadow">
                <form action="{{ url_for('add_user') }}" method="POST">
                    <div class="modal-header border-bottom-0 pb-0">
                        <h5 class="modal-title fw-bold">Create User Account</h5>
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
                            <label class="form-label small fw-semibold text-secondary">Assigned School (Staff)</label>
                            <select name="school_id" class="form-select form-select-sm">
                                <option value="">Global / Unassigned</option>
                                {% for sch in schools %}
                                    <option value="{{ sch.id }}">{{ sch.name }}</option>
                                {% endfor %}
                            </select>
                        </div>
                    </div>
                    <div class="modal-footer border-top-0 pt-0">
                        <button type="submit" class="btn btn-primary btn-action w-100">Save User</button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <!-- Admin: Clear School Data -->
    <div class="modal fade" id="clearDataModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content border-0 shadow">
                <form action="{{ url_for('clear_school_data') }}" method="POST">
                    <div class="modal-header border-bottom-0 pb-0">
                        <h5 class="modal-title fw-bold text-danger">Clear School Data</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="text-secondary small mb-3">
                            Caution: This action will permanently delete all student attendance records and logged interventions associated with the selected school.
                        </div>
                        <div class="mb-3">
                            <label class="form-label small fw-semibold text-secondary">Select Target School</label>
                            <select name="school_id" class="form-select form-select-sm" required>
                                {% for sch in schools %}
                                    <option value="{{ sch.id }}">{{ sch.name }}</option>
                                {% endfor %}
                            </select>
                        </div>
                    </div>
                    <div class="modal-footer border-top-0 pt-0">
                        <button type="submit" class="btn btn-danger btn-action w-100">Permanently Delete</button>
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
# Helpers & Database Initialization
# -----------------------------------------------------------------------------
def get_current_user():
    user_id = session.get('user_id')
    if user_id:
        return User.query.get(user_id)
    return None

def init_db():
    db.create_all()
    # Seed default Admin and Default School if database is empty
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
# App Routes & Controllers
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
    
    # Extract params for filtering & pagination
    selected_school_id = request.args.get('school_id', 'all')
    selected_filter = request.args.get('filter', 'all')
    selected_grade = request.args.get('grade', 'all')
    search_query = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 25

    # Enforce staff security scope
    if user.role != 'Admin':
        selected_school_id = str(user.school_id) if user.school_id else 'all'

    # Build student query
    query = StudentRecord.query
    if selected_school_id != 'all' and selected_school_id.isdigit():
        query = query.filter_by(school_id=int(selected_school_id))
        active_school = School.query.get(int(selected_school_id))
        active_school_name = active_school.name if active_school else 'Unknown'
    else:
        active_school_name = 'All Schools'

    records = query.all()

    # Calculate metrics dynamically
    all_parsed_students = []
    at_risk_count = 0
    total_students = len(records)
    grades_set = set()

    for r in records:
        adjusted_absences = r.absences + (r.tardies * 0.25)
        
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

    # Apply UI filters
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
        flash(f'School "{name}" created successfully.', 'info')
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

    headers = {h.strip().lower(): h for h in csv_reader.fieldnames}
    
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
    flash(f'CSV Processed: {imported_count} imported, {updated_count} updated.', 'info')
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

    if user.role != 'Admin' and student.school_id != user.school_id:
        flash('Unauthorized action.', 'error')
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
        flash('Invalid school selected.', 'error')
        return redirect(url_for('index'))

    try:
        s_id = int(school_id)
        school = School.query.get(s_id)
        if school:
            StudentRecord.query.filter_by(school_id=s_id).delete()
            db.session.commit()
            flash(f'All records for {school.name} cleared.', 'info')
    except ValueError:
        flash('Invalid school ID.', 'error')

    return redirect(url_for('index'))

# -----------------------------------------------------------------------------
# Script Entry Point
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)

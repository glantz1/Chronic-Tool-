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
                            <svg width="28" height="28" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path></svg>
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
                            <input type="text" name="grade" class="form-control form-control-sm" required>
                        </div>
                        <div class="row g-2 mb-3">
                            <div class="col-6">
                                <label class="form-label small fw-semibold text-secondary">Absences</label>
                                <input type="number" step="0.5" name="absences" class="form-control form-control-sm" value="0.0">
                            </div>
                            <div class="col-6">
                                <label class="form-label small fw-semibold text-secondary">Tardies</label>
                                <input type="number" name="tardies" class="form-control form-control-sm" value="0">
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer border-top-0 pt-0">
                        <button type="submit" class="btn btn-primary btn-action w-100">Save Student</button>
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
                            <input type="text" name="code" class="form-control form-control-sm" required>
                        </div>
                    </div>
                    <div class="modal-footer border-top-0 pt-0">
                        <button type="submit" class="btn btn-primary btn-action w-100">Create</button>
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
                        <h5 class="modal-title fw-bold">Create User</h5>
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
                            <select name="role" class="form-select form-select-sm" required>
                                <option value="Staff">Staff</option>
                                <option value="Admin">Admin</option>
                            </select>
                        </div>
                        <div class="mb-3">
                            <label class="form-label small fw-semibold text-secondary">Assigned School</label>
                            <select name="school_id" class="form-select form-select-sm">
                                <option value="">None (Global)</option>
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

    <!-- Clear Data Modal -->
    <div class="modal fade" id="clearDataModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content border-0 shadow">
                <form action="{{ url_for('clear_data') }}" method="POST">
                    <div class="modal-header border-bottom-0 pb-0">
                        <h5 class="modal-title fw-bold text-danger">Clear All Data</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <p class="small text-secondary mb-0">Are you sure you want to erase student records and interventions? This action cannot be undone.</p>
                    </div>
                    <div class="modal-footer border-top-0 pt-2">
                        <button type="button" class="btn btn-light btn-action" data-bs-dismiss="modal">Cancel</button>
                        <button type="submit" class="btn btn-danger btn-action">Confirm Erase</button>
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
# Helpers & Auth Decorator
# -----------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_current_user():
    if 'user_id' in session:
        return User.query.get(session['user_id'])
    return None

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            flash('Signed in successfully.', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password.', 'error')
            
    return render_template_string(LOGIN_HTML)

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    user = get_current_user()
    
    # Query Parameters
    selected_school_id = request.args.get('school_id', 'all')
    selected_grade = request.args.get('grade', 'all')
    selected_filter = request.args.get('filter', 'all')
    search_query = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 15

    # School Scope Determination
    schools = School.query.all()
    if user.role != 'Admin' and user.school_id:
        active_school = School.query.get(user.school_id)
        active_school_name = active_school.name if active_school else 'N/A'
        query = StudentRecord.query.filter_by(school_id=user.school_id)
    else:
        if selected_school_id != 'all':
            active_school = School.query.get(int(selected_school_id))
            active_school_name = active_school.name if active_school else 'Selected School'
            query = StudentRecord.query.filter_by(school_id=int(selected_school_id))
        else:
            active_school_name = 'All System Schools'
            query = StudentRecord.query

    # Apply Grade Filter
    if selected_grade != 'all':
        query = query.filter_by(grade=selected_grade)

    # Apply Search Filter
    if search_query:
        query = query.filter(
            (StudentRecord.name.ilike(f'%{search_query}%')) | 
            (StudentRecord.student_id.ilike(f'%{search_query}%'))
        )

    # Calculate Attendance KPI & Statuses
    all_filtered = query.all()
    
    processed_students = []
    for s in all_filtered:
        # Tardies count as 0.25 absences rule
        adj_absences = s.absences + (s.tardies * 0.25)
        
        if s.present_fte is not None:
            fte_pct = s.present_fte * 100.0
        else:
            fte_pct = max(0.0, ((s.total_days - adj_absences) / s.total_days) * 100.0) if s.total_days > 0 else 0.0

        is_chronic = fte_pct < 90.0

        processed_students.append({
            'id': s.id,
            'student_id': s.student_id,
            'name': s.name,
            'grade': s.grade,
            'school_name': s.school.name if s.school else 'N/A',
            'adjusted_absences': adj_absences,
            'present_fte_pct': fte_pct,
            'is_chronic': is_chronic,
            'interventions': s.interventions
        })

    # Summary Stats
    total_students = len(processed_students)
    at_risk_count = sum(1 for s in processed_students if s['is_chronic'])
    chronic_rate = (at_risk_count / total_students * 100.0) if total_students > 0 else 0.0

    # Apply Custom Filtering/Sorting
    if selected_filter == 'chronic':
        processed_students = [s for s in processed_students if s['is_chronic']]
    elif selected_filter == 'most-absences':
        processed_students.sort(key=lambda x: x['adjusted_absences'], reverse=True)
    elif selected_filter == 'least-absences':
        processed_students.sort(key=lambda x: x['adjusted_absences'])

    # Manual Pagination
    display_count = len(processed_students)
    total_pages = math.ceil(display_count / per_page) if display_count > 0 else 1
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_students = processed_students[start_idx:end_idx]

    # Unique available grades dropdown values
    available_grades = sorted(list(set([s.grade for s in StudentRecord.query.all()])))

    return render_template_string(
        INDEX_HTML,
        current_user=user,
        schools=schools,
        students=paginated_students,
        active_school_name=active_school_name,
        total_students=total_students,
        at_risk_count=at_risk_count,
        chronic_rate=chronic_rate,
        selected_school_id=selected_school_id,
        selected_grade=selected_grade,
        selected_filter=selected_filter,
        search_query=search_query,
        available_grades=available_grades,
        display_count=display_count,
        total_pages=total_pages,
        current_page=page
    )

@app.route('/upload_csv', methods=['POST'])
@login_required
def upload_csv():
    user = get_current_user()
    file = request.files.get('file')
    
    if user.role == 'Admin':
        school_id = request.form.get('school_id')
    else:
        school_id = user.school_id

    if not school_id:
        flash('Target school must be specified.', 'error')
        return redirect(url_for('index'))

    if file and file.filename.endswith('.csv'):
        stream = io.StringIO(file.stream.read().decode("UTF-8"), newline=None)
        csv_reader = csv.DictReader(stream)
        
        imported_count = 0
        for row in csv_reader:
            student_id = row.get('Student_ID') or row.get('student_id')
            name = row.get('Name') or row.get('name')
            if not student_id or not name:
                continue

            grade = row.get('Grade') or row.get('grade') or 'N/A'
            absences = float(row.get('Absences') or row.get('absences') or 0.0)
            tardies = int(row.get('Tardies') or row.get('tardies') or 0)
            present_fte = row.get('Present_FTE') or row.get('present_fte')
            present_fte = float(present_fte) if present_fte else None

            existing = StudentRecord.query.filter_by(student_id=student_id, school_id=school_id).first()
            if existing:
                existing.name = name
                existing.grade = grade
                existing.absences = absences
                existing.tardies = tardies
                existing.present_fte = present_fte
            else:
                record = StudentRecord(
                    student_id=student_id,
                    name=name,
                    grade=grade,
                    school_id=school_id,
                    absences=absences,
                    tardies=tardies,
                    present_fte=present_fte
                )
                db.session.add(record)
            imported_count += 1

        db.session.commit()
        flash(f'Successfully imported {imported_count} records.', 'success')
    else:
        flash('Invalid file format. Please upload a CSV.', 'error')

    return redirect(url_for('index'))

@app.route('/add_student', methods=['POST'])
@login_required
def add_student():
    user = get_current_user()
    school_id = request.form.get('school_id') if user.role == 'Admin' else user.school_id

    if not school_id:
        flash('A valid school must be specified to add a student.', 'error')
        return redirect(url_for('index'))

    student_id = request.form.get('student_id')
    name = request.form.get('name')
    grade = request.form.get('grade', 'N/A')
    absences = float(request.form.get('absences', 0.0))
    tardies = int(request.form.get('tardies', 0))

    record = StudentRecord(
        student_id=student_id,
        name=name,
        grade=grade,
        school_id=school_id,
        absences=absences,
        tardies=tardies
    )
    db.session.add(record)
    db.session.commit()
    flash('Student added successfully.', 'success')
    return redirect(url_for('index'))

@app.route('/log_intervention', methods=['POST'])
@login_required
def log_intervention():
    user = get_current_user()
    student_db_id = request.form.get('student_db_id')
    action_type = request.form.get('action_type')
    notes = request.form.get('notes')

    intervention = Intervention(
        student_record_id=student_db_id,
        action_type=action_type,
        notes=notes,
        logged_by=user.username
    )
    db.session.add(intervention)
    db.session.commit()
    flash('Intervention recorded.', 'success')
    return redirect(url_for('index'))

@app.route('/add_school', methods=['POST'])
@login_required
def add_school():
    user = get_current_user()
    if user.role != 'Admin':
        flash('Unauthorized action.', 'error')
        return redirect(url_for('index'))

    name = request.form.get('name')
    code = request.form.get('code')

    try:
        sch = School(name=name, code=code)
        db.session.add(sch)
        db.session.commit()
        flash('School created successfully.', 'success')
    except IntegrityError:
        db.session.rollback()
        flash('School name or code already exists.', 'error')

    return redirect(url_for('index'))

@app.route('/add_user', methods=['POST'])
@login_required
def add_user():
    user = get_current_user()
    if user.role != 'Admin':
        flash('Unauthorized action.', 'error')
        return redirect(url_for('index'))

    username = request.form.get('username')
    password = request.form.get('password')
    role = request.form.get('role', 'Staff')
    school_id = request.form.get('school_id')
    school_id = int(school_id) if school_id else None

    try:
        pw_hash = generate_password_hash(password)
        new_user = User(username=username, password_hash=pw_hash, role=role, school_id=school_id)
        db.session.add(new_user)
        db.session.commit()
        flash('User account created.', 'success')
    except IntegrityError:
        db.session.rollback()
        flash('Username already exists.', 'error')

    return redirect(url_for('index'))

@app.route('/clear_data', methods=['POST'])
@login_required
def clear_data():
    user = get_current_user()
    if user.role != 'Admin':
        flash('Unauthorized action.', 'error')
        return redirect(url_for('index'))

    StudentRecord.query.delete()
    Intervention.query.delete()
    db.session.commit()
    flash('All student records and interventions deleted.', 'success')
    return redirect(url_for('index'))

# -----------------------------------------------------------------------------
# Database Setup & Default Admin Initialization
# -----------------------------------------------------------------------------
def init_db():
    with app.app_context():
        db.create_all()
        # Create default Admin if no users exist
        if User.query.count() == 0:
            default_school = School(name="Central High School", code="CHS01")
            db.session.add(default_school)
            db.session.commit()

            admin_user = User(
                username="admin",
                password_hash=generate_password_hash("admin123"),
                role="Admin",
                school_id=default_school.id
            )
            db.session.add(admin_user)
            db.session.commit()

init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)

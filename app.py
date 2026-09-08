import os
import io
import csv
import math
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template_string, request, redirect, 
    url_for, session, jsonify, Response
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ------------------------------------------------------------------------------
# Database Models
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
    username = db.Column(db.String(100), unique=True, nullable=False) # Email/Username
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='staff') # 'admin' or 'staff'
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
    grade = db.Column(db.String(20), nullable=True, default='N/A')
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
    date = db.Column(db.String(20), nullable=False)
    type = db.Column(db.String(100), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    logged_by = db.Column(db.String(100), nullable=False, default='System User')
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

# ------------------------------------------------------------------------------
# Auth Decorators
# ------------------------------------------------------------------------------
def login_required_api(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

def admin_required_api(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401
        user = User.query.get(session['user_id'])
        if not user or user.role != 'admin':
            return jsonify({"error": "Admin privileges required"}), 403
        return f(*args, **kwargs)
    return decorated

# ------------------------------------------------------------------------------
# Single-Page Frontend HTML
# ------------------------------------------------------------------------------
INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Attendance Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body class="bg-slate-100 font-sans text-slate-800 antialiased min-h-screen">

    <!-- Auth View -->
    <div id="loginView" class="min-h-screen flex items-center justify-center bg-slate-900 px-4">
        <div class="bg-white p-8 rounded-xl shadow-2xl max-w-md w-full">
            <div class="text-center mb-6">
                <i class="fa-solid fa-school text-indigo-600 text-4xl mb-2"></i>
                <h2 class="text-2xl font-bold text-slate-800">Attendance Portal</h2>
                <p class="text-slate-500 text-sm">Sign in to access student insights</p>
            </div>
            <form onsubmit="handleLogin(event)" class="space-y-4">
                <div>
                    <label class="block text-xs font-semibold text-slate-600 uppercase mb-1">Email / Username</label>
                    <input type="text" id="loginEmail" required class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-indigo-500 focus:outline-none">
                </div>
                <div>
                    <label class="block text-xs font-semibold text-slate-600 uppercase mb-1">Password</label>
                    <input type="password" id="loginPassword" required class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-indigo-500 focus:outline-none">
                </div>
                <div id="loginError" class="text-red-600 text-sm hidden"></div>
                <button type="submit" class="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-medium py-2 rounded-lg transition">Sign In</button>
            </form>
        </div>
    </div>

    <!-- Main App Container -->
    <div id="dashboardView" class="hidden">
        <!-- Top Navigation -->
        <nav class="bg-slate-900 text-white px-6 py-3.5 flex justify-between items-center shadow-lg">
            <div class="flex items-center space-x-3">
                <i class="fa-solid fa-chart-line text-indigo-400 text-xl"></i>
                <span class="font-bold text-lg tracking-wide">Attendance Tracker</span>
            </div>
            <div id="userInfo" class="flex items-center space-x-4 hidden text-sm">
                <span id="userEmail" class="text-slate-300 font-medium"></span>
                <button id="addSchoolBtn" onclick="toggleModal('schoolModal')" class="hidden bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs px-3 py-1.5 rounded-lg border border-slate-700 transition">
                    + Add School
                </button>
                <button id="manageUsersBtn" onclick="openUsersModal()" class="hidden bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs px-3 py-1.5 rounded-lg border border-slate-700 transition">
                    <i class="fa-solid fa-users-gear mr-1"></i> Users
                </button>
                <button onclick="logout()" class="bg-red-600/80 hover:bg-red-600 text-white text-xs px-3 py-1.5 rounded-lg font-medium transition">Logout</button>
            </div>
        </nav>

        <!-- Dashboard Content -->
        <main class="max-w-7xl mx-auto px-4 py-6 space-y-6">
            <!-- Filter Bar & Control Bar -->
            <div class="bg-white p-4 rounded-xl shadow-sm border border-slate-200 flex flex-wrap gap-3 justify-between items-center">
                <div class="flex flex-wrap items-center gap-3">
                    <!-- School Selector -->
                    <div>
                        <select id="schoolSelect" onchange="loadDashboard()" class="border border-slate-300 rounded-lg px-3 py-1.5 bg-white font-medium text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none">
                            <option value="">Loading Schools...</option>
                        </select>
                    </div>

                    <!-- Search Input -->
                    <div class="relative">
                        <i class="fa-solid fa-magnifying-glass absolute left-3 top-2.5 text-slate-400 text-xs"></i>
                        <input type="text" id="searchInput" oninput="loadDashboard()" placeholder="Search name or ID..." class="pl-8 pr-3 py-1.5 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none">
                    </div>

                    <!-- Grade Filter -->
                    <div>
                        <select id="gradeFilter" onchange="loadDashboard()" class="border border-slate-300 rounded-lg px-2.5 py-1.5 bg-white text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none">
                            <option value="">All Grades</option>
                        </select>
                    </div>

                    <!-- Sorting Options -->
                    <div>
                        <select id="sortSelect" onchange="loadDashboard()" class="border border-slate-300 rounded-lg px-2.5 py-1.5 bg-white text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none">
                            <option value="absences_desc">Most Absences First</option>
                            <option value="absences_asc">Least Absences First</option>
                            <option value="fte_desc">Highest Present FTE% First</option>
                            <option value="fte_asc">Lowest Present FTE% First</option>
                            <option value="unexcused_desc">Most Unexcused Absences</option>
                            <option value="rate_asc">Lowest Attendance Rate</option>
                            <option value="name_asc">Name (A-Z)</option>
                        </select>
                    </div>

                    <!-- Chronic Filter Checkbox -->
                    <label class="flex items-center space-x-2 text-xs font-semibold text-slate-600 bg-slate-50 px-3 py-2 rounded-lg border border-slate-200 cursor-pointer">
                        <input type="checkbox" id="chronicOnly" onchange="loadDashboard()" class="rounded text-indigo-600 focus:ring-indigo-500">
                        <span>Chronic Only (≤90%)</span>
                    </label>
                </div>

                <!-- Action Buttons -->
                <div class="flex items-center space-x-2">
                    <button onclick="openUploadModal()" class="bg-indigo-600 hover:bg-indigo-700 text-white px-3.5 py-1.5 rounded-lg text-sm font-medium transition flex items-center">
                        <i class="fa-solid fa-file-csv mr-1.5"></i> Import CSV
                    </button>
                    <button onclick="exportInterventions()" class="bg-emerald-600 hover:bg-emerald-700 text-white px-3.5 py-1.5 rounded-lg text-sm font-medium transition flex items-center">
                        <i class="fa-solid fa-download mr-1.5"></i> Export Logs
                    </button>
                </div>
            </div>

            <!-- Metric KPI Cards -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm border-l-4 border-l-indigo-500">
                    <div class="text-xs font-semibold text-slate-500 uppercase">Total Students</div>
                    <div id="statTotal" class="text-2xl font-bold text-slate-800 mt-1">0</div>
                </div>
                <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm border-l-4 border-l-rose-500">
                    <div class="text-xs font-semibold text-slate-500 uppercase">Chronically Absent</div>
                    <div id="statChronic" class="text-2xl font-bold text-rose-600 mt-1">0</div>
                </div>
                <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm border-l-4 border-l-amber-500">
                    <div class="text-xs font-semibold text-slate-500 uppercase">Chronic Absence Rate</div>
                    <div id="statRate" class="text-2xl font-bold text-amber-600 mt-1">0%</div>
                </div>
            </div>

            <!-- Data Table -->
            <div class="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse">
                        <thead class="bg-slate-50 border-b border-slate-200 text-xs uppercase font-semibold text-slate-500">
                            <tr>
                                <th class="p-3.5">Student ID</th>
                                <th class="p-3.5">Name</th>
                                <th class="p-3.5">Grade</th>
                                <th class="p-3.5 text-center">Total Absences</th>
                                <th class="p-3.5 text-center">Unexcused</th>
                                <th class="p-3.5 text-center">Present FTE %</th>
                                <th class="p-3.5 text-center">Status</th>
                                <th class="p-3.5 text-right">Interventions</th>
                            </tr>
                        </thead>
                        <tbody id="studentTableBody" class="divide-y divide-slate-200 text-sm">
                            <!-- Populated via JS -->
                        </tbody>
                    </table>
                </div>
            </div>
        </main>
    </div>

    <!-- MODALS -->

    <!-- Modal: Add School -->
    <div id="schoolModal" class="fixed inset-0 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center hidden z-50">
        <div class="bg-white rounded-xl p-6 w-full max-w-sm shadow-xl border">
            <h3 class="text-lg font-bold text-slate-800 mb-4">Add New School</h3>
            <form onsubmit="handleAddSchool(event)" class="space-y-4">
                <div>
                    <label class="block text-xs font-semibold text-slate-500 uppercase mb-1">School Name</label>
                    <input type="text" id="newSchoolName" required class="w-full px-3 py-1.5 border rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none">
                </div>
                <div class="flex justify-end space-x-2">
                    <button type="button" onclick="toggleModal('schoolModal')" class="px-4 py-2 border rounded-lg text-slate-600 text-sm font-medium">Cancel</button>
                    <button type="submit" class="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700">Save School</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Modal: Upload CSV -->
    <div id="uploadModal" class="fixed inset-0 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center hidden z-50">
        <div class="bg-white rounded-xl p-6 w-full max-w-md shadow-xl border">
            <h3 class="text-lg font-bold text-slate-800 mb-1">Upload Student CSV</h3>
            <p id="uploadSchoolLabel" class="text-sm text-indigo-600 font-medium mb-4"></p>
            
            <form onsubmit="handleUpload(event)" class="space-y-4">
                <input type="hidden" id="uploadSchoolId">
                <div>
                    <label class="block text-xs font-semibold text-slate-500 uppercase mb-1">Select CSV File</label>
                    <input type="file" id="csvFile" accept=".csv" required class="w-full text-sm border border-slate-300 rounded-lg p-2 focus:ring-2 focus:ring-indigo-500 focus:outline-none">
                </div>
                <div id="uploadError" class="text-red-600 text-sm hidden"></div>
                <div class="flex justify-end space-x-2 pt-2">
                    <button type="button" onclick="toggleModal('uploadModal')" class="px-4 py-2 border rounded-lg text-slate-600 text-sm font-medium">Cancel</button>
                    <button type="submit" id="uploadSubmitBtn" class="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 text-sm font-medium">Upload & Import</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Modal: Manage Users -->
    <div id="usersModal" class="fixed inset-0 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center hidden z-50">
        <div class="bg-white rounded-xl p-6 w-full max-w-2xl shadow-xl border max-h-[90vh] flex flex-col">
            <div class="flex justify-between items-center mb-4">
                <h3 class="text-lg font-bold text-slate-800">User Management</h3>
                <button onclick="toggleModal('usersModal')" class="text-slate-400 hover:text-slate-600">
                    <i class="fa-solid fa-xmark text-xl"></i>
                </button>
            </div>

            <!-- Add User Form -->
            <form onsubmit="handleAddUser(event)" class="bg-slate-50 p-4 rounded-lg border border-slate-200 mb-6 space-y-3">
                <h4 class="text-sm font-semibold text-slate-700">Add New User</h4>
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <input type="text" id="newUserEmail" placeholder="Username / Email" required class="px-3 py-1.5 border rounded-lg text-sm">
                    <input type="password" id="newUserPassword" placeholder="Password" required class="px-3 py-1.5 border rounded-lg text-sm">
                    <select id="newUserRole" class="px-3 py-1.5 border rounded-lg text-sm bg-white">
                        <option value="staff">Staff / Counselor</option>
                        <option value="admin">Admin</option>
                    </select>
                    <select id="newUserSchool" class="px-3 py-1.5 border rounded-lg text-sm bg-white">
                        <option value="">No School Assigned (Admin Only)</option>
                    </select>
                </div>
                <div id="addUserError" class="text-red-600 text-xs hidden"></div>
                <div class="flex justify-end">
                    <button type="submit" class="bg-emerald-600 hover:bg-emerald-700 text-white text-sm px-4 py-1.5 rounded-lg font-medium transition">
                        Create User
                    </button>
                </div>
            </form>

            <!-- Existing Users Table -->
            <div class="overflow-y-auto flex-grow">
                <h4 class="text-sm font-semibold text-slate-700 mb-2">Existing System Users</h4>
                <table class="w-full text-left text-xs">
                    <thead class="bg-slate-100 text-slate-600 font-semibold uppercase">
                        <tr>
                            <th class="p-2">ID</th>
                            <th class="p-2">Username</th>
                            <th class="p-2">Role</th>
                            <th class="p-2">School</th>
                            <th class="p-2 text-right">Actions</th>
                        </tr>
                    </thead>
                    <tbody id="userListTable" class="divide-y divide-slate-200">
                        <!-- Populated dynamically via loadUsersTable() -->
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- Modal: Interventions & Actions -->
    <div id="interventionModal" class="fixed inset-0 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center hidden z-50">
        <div class="bg-white rounded-xl p-6 w-full max-w-2xl shadow-xl border max-h-[90vh] flex flex-col">
            <div class="flex justify-between items-start mb-4 border-b pb-3">
                <div>
                    <h3 id="interStudentName" class="text-xl font-bold text-slate-800"></h3>
                    <p id="interStudentMeta" class="text-xs text-slate-500 font-medium mt-0.5"></p>
                </div>
                <button onclick="toggleModal('interventionModal')" class="text-slate-400 hover:text-slate-600">
                    <i class="fa-solid fa-xmark text-xl"></i>
                </button>
            </div>

            <!-- Log Intervention Form -->
            <form onsubmit="handleSaveIntervention(event)" class="bg-indigo-50/50 p-4 rounded-lg border border-indigo-100 mb-6 space-y-3">
                <h4 class="text-sm font-semibold text-indigo-900 flex items-center">
                    <i class="fa-solid fa-pen-to-square mr-1.5"></i> Log New Intervention Action
                </h4>
                <input type="hidden" id="interStudentDbId">
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                        <label class="block text-xs font-semibold text-slate-600 mb-1">Date</label>
                        <input type="date" id="interDate" required class="w-full px-3 py-1.5 border rounded-lg text-sm bg-white">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-slate-600 mb-1">Action / Strategy Type</label>
                        <select id="interType" required class="w-full px-3 py-1.5 border rounded-lg text-sm bg-white">
                            <option value="Parent Phone Call">Parent Phone Call</option>
                            <option value="Student Conference">Student Conference</option>
                            <option value="Parent Meeting / Conference">Parent Meeting / Conference</option>
                            <option value="Attendance Contract Signed">Attendance Contract Signed</option>
                            <option value="Home Visit">Home Visit</option>
                            <option value="Counseling Referral">Counseling Referral</option>
                            <option value="Official Warning Letter Sent">Official Warning Letter Sent</option>
                            <option value="Truancy Diversion Referral">Truancy Diversion Referral</option>
                        </select>
                    </div>
                </div>
                <div>
                    <label class="block text-xs font-semibold text-slate-600 mb-1">Details & Meeting Notes</label>
                    <textarea id="interNotes" rows="2" placeholder="Record discussion outcomes or next steps..." class="w-full px-3 py-1.5 border rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"></textarea>
                </div>
                <div id="interError" class="text-red-600 text-xs hidden"></div>
                <div class="flex justify-end">
                    <button type="submit" class="bg-indigo-600 hover:bg-indigo-700 text-white text-sm px-4 py-2 rounded-lg font-medium transition flex items-center">
                        <i class="fa-solid fa-floppy-disk mr-1.5"></i> Save Action Log
                    </button>
                </div>
            </form>

            <!-- Intervention History -->
            <div class="overflow-y-auto flex-grow">
                <h4 class="text-sm font-semibold text-slate-700 mb-3">Logged Intervention History</h4>
                <div id="interventionHistoryList" class="space-y-3">
                    <!-- Dynamic entries -->
                </div>
            </div>
        </div>
    </div>

    <!-- Complete JavaScript Logic -->
    <script>
        let currentUser = null;

        function toggleModal(id) {
            const el = document.getElementById(id);
            if (el) {
                el.classList.toggle('hidden');
            } else {
                console.error(`Modal element "${id}" was not found.`);
            }
        }

        async function checkAuth() {
            try {
                const res = await fetch('/me');
                if (!res.ok) throw new Error("Auth endpoint rejected query");
                const data = await res.json();
                
                if (data.logged_in) {
                    currentUser = data.user;
                    document.getElementById('loginView').classList.add('hidden');
                    document.getElementById('dashboardView').classList.remove('hidden');
                    document.getElementById('userInfo').classList.remove('hidden');
                    document.getElementById('userEmail').textContent = currentUser.email;

                    if (currentUser.role === 'admin') {
                        document.getElementById('addSchoolBtn').classList.remove('hidden');
                        document.getElementById('manageUsersBtn').classList.remove('hidden');
                    }

                    await loadSchools();
                } else {
                    showLogin();
                }
            } catch (err) {
                console.warn("Auth check unfulfilled or offline, displaying login view", err);
                showLogin();
            }
        }

        function showLogin() {
            document.getElementById('loginView').classList.remove('hidden');
            document.getElementById('dashboardView').classList.add('hidden');
            document.getElementById('userInfo').classList.add('hidden');
        }

        async function handleLogin(e) {
            e.preventDefault();
            const email = document.getElementById('loginEmail').value;
            const password = document.getElementById('loginPassword').value;
            try {
                const res = await fetch('/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ email, password })
                });
                const data = await res.json();
                if (res.ok) {
                    checkAuth();
                } else {
                    document.getElementById('loginError').textContent = data.error || "Login failed.";
                    document.getElementById('loginError').classList.remove('hidden');
                }
            } catch (err) {
                document.getElementById('loginError').textContent = "Unable to connect to server.";
                document.getElementById('loginError').classList.remove('hidden');
            }
        }

        async function logout() {
            await fetch('/logout', { method: 'POST' });
            location.reload();
        }

        async function loadSchools() {
            try {
                const res = await fetch('/schools');
                const data = await res.json();
                const select = document.getElementById('schoolSelect');
                select.innerHTML = '';
                (data.schools || []).forEach(s => {
                    select.innerHTML += `<option value="${s.id}">${s.name}</option>`;
                });
                if (data.schools && data.schools.length > 0) {
                    loadDashboard();
                } else {
                    select.innerHTML = '<option value="">No Schools Found</option>';
                }
            } catch(e) {
                console.error("Could not load schools:", e);
            }
        }

        async function handleAddSchool(e) {
            e.preventDefault();
            const name = document.getElementById('newSchoolName').value;
            const res = await fetch('/admin/schools', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ name })
            });
            if (res.ok) {
                toggleModal('schoolModal');
                document.getElementById('newSchoolName').value = '';
                await loadSchools();
            } else {
                const err = await res.json();
                alert(err.error || "Failed to add school");
            }
        }

        async function loadDashboard() {
            const schoolId = document.getElementById('schoolSelect').value;
            if (!schoolId) return;

            const search = document.getElementById('searchInput').value;
            const grade = document.getElementById('gradeFilter').value;
            const sort = document.getElementById('sortSelect').value;
            const chronic = document.getElementById('chronicOnly').checked;

            const url = `/students?school_id=${schoolId}&search=${encodeURIComponent(search)}&grade=${encodeURIComponent(grade)}&sort=${sort}&chronic=${chronic}`;
            try {
                const res = await fetch(url);
                const data = await res.json();

                document.getElementById('statTotal').textContent = data.total_students || 0;
                document.getElementById('statChronic').textContent = data.chronic_count || 0;
                document.getElementById('statRate').textContent = `${data.chronic_rate_pct || 0}%`;

                const gradeSelect = document.getElementById('gradeFilter');
                const currentGradeSelection = gradeSelect.value;
                gradeSelect.innerHTML = '<option value="">All Grades</option>';
                (data.available_grades || []).forEach(g => {
                    const selected = g === currentGradeSelection ? 'selected' : '';
                    gradeSelect.innerHTML += `<option value="${g}" ${selected}>Grade ${g}</option>`;
                });

                const tbody = document.getElementById('studentTableBody');
                tbody.innerHTML = '';

                (data.students || []).forEach(s => {
                    const statusBadge = s.is_chronic 
                        ? `<span class="bg-red-100 text-red-700 text-xs px-2.5 py-1 rounded-full font-semibold">Chronic</span>`
                        : `<span class="bg-emerald-100 text-emerald-700 text-xs px-2.5 py-1 rounded-full font-semibold">On Track</span>`;

                    const row = document.createElement('tr');
                    row.className = "hover:bg-indigo-50/50 cursor-pointer transition";
                    row.onclick = () => openInterventionModal(s);
                    
                    row.innerHTML = `
                        <td class="p-3.5 font-medium text-slate-700">${s.student_id}</td>
                        <td class="p-3.5 font-bold text-slate-800">${s.student_name}</td>
                        <td class="p-3.5">${s.grade || '-'}</td>
                        <td class="p-3.5 text-center font-semibold text-slate-800">${s.days_absent}</td>
                        <td class="p-3.5 text-center text-amber-600 font-semibold">${s.unexcused_absences}</td>
                        <td class="p-3.5 text-center font-bold text-slate-800">${s.attendance_rate_pct}%</td>
                        <td class="p-3.5 text-center">${statusBadge}</td>
                        <td class="p-3.5 text-right font-medium text-indigo-600">
                            <span class="bg-indigo-50 border border-indigo-200 px-2.5 py-1 rounded-lg text-xs font-semibold">
                                <i class="fa-solid fa-clipboard-list mr-1"></i> ${s.interventions_count} logged
                            </span>
                        </td>
                    `;
                    tbody.appendChild(row);
                });
            } catch(e) {
                console.error("Dashboard fetch error:", e);
            }
        }

        async function openInterventionModal(student) {
            document.getElementById('interStudentDbId').value = student.db_id;
            document.getElementById('interStudentName').textContent = student.student_name;
            document.getElementById('interStudentMeta').textContent = `ID: ${student.student_id} | Grade: ${student.grade || 'N/A'} | Absences: ${student.days_absent} | Attendance: ${student.attendance_rate_pct}%`;
            
            document.getElementById('interDate').value = new Date().toISOString().split('T')[0];
            document.getElementById('interNotes').value = '';
            document.getElementById('interError').classList.add('hidden');

            toggleModal('interventionModal');
            await loadInterventionHistory(student.db_id);
        }

        async function loadInterventionHistory(studentDbId) {
            const listDiv = document.getElementById('interventionHistoryList');
            listDiv.innerHTML = '<p class="text-xs text-slate-400">Loading history...</p>';

            try {
                const res = await fetch(`/interventions?student_db_id=${studentDbId}`);
                if (!res.ok) throw new Error();
                const data = await res.json();
                listDiv.innerHTML = '';

                if (!data.interventions || data.interventions.length === 0) {
                    listDiv.innerHTML = '<p class="text-xs text-slate-400 italic">No interventions recorded yet for this student.</p>';
                    return;
                }

                data.interventions.forEach(item => {
                    listDiv.innerHTML += `
                        <div class="bg-slate-50 border border-slate-200 p-3 rounded-lg text-xs space-y-1">
                            <div class="flex justify-between items-center">
                                <span class="font-bold text-slate-800">${item.type}</span>
                                <span class="text-slate-400 font-medium">${item.date}</span>
                            </div>
                            <p class="text-slate-600">${item.notes || '<span class="italic text-slate-400">No additional notes provided.</span>'}</p>
                            <div class="text-[10px] text-indigo-600 font-medium text-right pt-1">Logged by: ${item.logged_by}</div>
                        </div>
                    `;
                });
            } catch(e) {
                listDiv.innerHTML = '<p class="text-xs text-red-500">Failed to load intervention history.</p>';
            }
        }

        async function handleSaveIntervention(e) {
            e.preventDefault();
            const studentDbId = document.getElementById('interStudentDbId').value;
            const date = document.getElementById('interDate').value;
            const type = document.getElementById('interType').value;
            const notes = document.getElementById('interNotes').value;
            const errDiv = document.getElementById('interError');

            errDiv.classList.add('hidden');

            const res = await fetch('/interventions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    student_db_id: studentDbId,
                    date: date,
                    type: type,
                    notes: notes
                })
            });

            const data = await res.json();
            if (res.ok) {
                document.getElementById('interNotes').value = '';
                await loadInterventionHistory(studentDbId);
                await loadDashboard();
            } else {
                errDiv.textContent = data.error || "Failed to log intervention.";
                errDiv.classList.remove('hidden');
            }
        }

        function openUploadModal() {
            const schoolSelect = document.getElementById('schoolSelect');
            const schoolId = schoolSelect.value;
            
            if (!schoolId) {
                alert("Please select or create a school first.");
                return;
            }

            const schoolName = schoolSelect.options[schoolSelect.selectedIndex].text;
            
            document.getElementById('uploadSchoolId').value = schoolId;
            document.getElementById('uploadSchoolLabel').textContent = `Target School: ${schoolName}`;
            document.getElementById('uploadError').classList.add('hidden');
            document.getElementById('csvFile').value = '';
            
            toggleModal('uploadModal');
        }

        async function handleUpload(e) {
            e.preventDefault();
            const schoolId = document.getElementById('uploadSchoolId').value;
            const fileInput = document.getElementById('csvFile');
            const submitBtn = document.getElementById('uploadSubmitBtn');
            const errorDiv = document.getElementById('uploadError');

            if (!fileInput.files.length) {
                errorDiv.textContent = "Please select a file.";
                errorDiv.classList.remove('hidden');
                return;
            }

            const formData = new FormData();
            formData.append('school_id', schoolId);
            formData.append('file', fileInput.files[0]);

            submitBtn.disabled = true;
            submitBtn.textContent = "Uploading...";
            errorDiv.classList.add('hidden');

            try {
                const res = await fetch('/upload', { method: 'POST', body: formData });
                const data = await res.json();

                if (res.ok) {
                    alert(data.message || "CSV data successfully uploaded and imported!");
                    toggleModal('uploadModal');
                    await loadDashboard();
                } else {
                    errorDiv.textContent = data.error || "Failed to process CSV file.";
                    errorDiv.classList.remove('hidden');
                }
            } catch (err) {
                errorDiv.textContent = "An unexpected error occurred during upload.";
                errorDiv.classList.remove('hidden');
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = "Upload & Import";
            }
        }

        async function openUsersModal() {
            toggleModal('usersModal');
            await populateSchoolDropdownForUser();
            await loadUsersTable();
        }

        async function loadUsersTable() {
            try {
                const res = await fetch('/admin/users');
                if (!res.ok) return;
                const data = await res.json();
                const tbody = document.getElementById('userListTable');
                tbody.innerHTML = '';

                (data.users || []).forEach(u => {
                    const deleteBtn = (currentUser && currentUser.id !== u.id)
                        ? `<button onclick="deleteUser(${u.id}, '${u.username}')" class="text-red-600 hover:text-red-800 font-medium">Delete</button>`
                        : `<span class="text-slate-400 font-medium">Current User</span>`;

                    tbody.innerHTML += `
                        <tr class="hover:bg-slate-50">
                            <td class="p-2 font-medium text-slate-800">${u.id}</td>
                            <td class="p-2 text-slate-800">${u.username}</td>
                            <td class="p-2 capitalize text-slate-600">${u.role}</td>
                            <td class="p-2 text-slate-600">${u.school_name}</td>
                            <td class="p-2 text-right">${deleteBtn}</td>
                        </tr>
                    `;
                });
            } catch(e) {
                console.error("Failed loading user list:", e);
            }
        }

        async function deleteUser(userId, username) {
            if (!confirm(`Are you sure you want to delete user ${username}?`)) return;
            try {
                const res = await fetch(`/admin/users/${userId}`, { method: 'DELETE' });
                if (res.ok) {
                    await loadUsersTable();
                } else {
                    const data = await res.json();
                    alert(data.error || "Failed to delete user.");
                }
            } catch(e) {
                alert("An error occurred while deleting user.");
            }
        }

        async function populateSchoolDropdownForUser() {
            try {
                const res = await fetch('/schools');
                const data = await res.json();
                const select = document.getElementById('newUserSchool');
                select.innerHTML = '<option value="">No School Assigned (Admin Only)</option>';
                (data.schools || []).forEach(s => {
                    select.innerHTML += `<option value="${s.id}">${s.name}</option>`;
                });
            } catch (e) {
                console.error("Could not populate user school options:", e);
            }
        }

        async function handleAddUser(e) {
            e.preventDefault();
            const email = document.getElementById('newUserEmail').value;
            const password = document.getElementById('newUserPassword').value;
            const role = document.getElementById('newUserRole').value;
            const school_id = document.getElementById('newUserSchool').value;
            const errDiv = document.getElementById('addUserError');

            errDiv.classList.add('hidden');

            const res = await fetch('/admin/users', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password, role, school_id })
            });

            const data = await res.json();
            if (res.ok) {
                document.getElementById('newUserEmail').value = '';
                document.getElementById('newUserPassword').value = '';
                await loadUsersTable();
            } else {
                errDiv.textContent = data.error || "Failed to add user.";
                errDiv.classList.remove('hidden');
            }
        }

        function exportInterventions() {
            const schoolId = document.getElementById('schoolSelect').value;
            if (!schoolId) {
                alert("Please select a school to export data.");
                return;
            }
            window.location.href = `/export/interventions?school_id=${schoolId}`;
        }

        // Initialize application on startup
        document.addEventListener('DOMContentLoaded', checkAuth);
    </script>
</body>
</html>
"""

# ------------------------------------------------------------------------------
# Flask API & Application Routes
# ------------------------------------------------------------------------------
@app.route('/')
def index():
    return render_template_string(INDEX_HTML)

@app.route('/me', methods=['GET'])
def me():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            return jsonify({
                "logged_in": True,
                "user": {
                    "id": user.id,
                    "email": user.username,
                    "role": user.role,
                    "school_id": user.school_id
                }
            })
    return jsonify({"logged_in": False})

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    email = data.get('email', '').strip()
    password = data.get('password', '').strip()

    user = User.query.filter_by(username=email).first()
    if user and user.check_password(password):
        session['user_id'] = user.id
        return jsonify({"message": "Logged in successfully."})
    return jsonify({"error": "Invalid email/username or password."}), 401

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    return jsonify({"message": "Logged out successfully."})

@app.route('/schools', methods=['GET'])
@login_required_api
def get_schools():
    user = User.query.get(session['user_id'])
    if user.role != 'admin' and user.school_id:
        schools = School.query.filter_by(id=user.school_id).all()
    else:
        schools = School.query.all()

    return jsonify({
        "schools": [{"id": s.id, "name": s.name} for s in schools]
    })

@app.route('/admin/schools', methods=['POST'])
@admin_required_api
def create_school():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({"error": "School name is required."}), 400
    if School.query.filter_by(name=name).first():
        return jsonify({"error": f"School '{name}' already exists."}), 400

    school = School(name=name)
    db.session.add(school)
    db.session.commit()
    return jsonify({"message": "School added successfully.", "id": school.id})

@app.route('/admin/users', methods=['GET'])
@admin_required_api
def get_users():
    users = User.query.all()
    out = []
    for u in users:
        sch_name = u.school.name if u.school else ('All Schools' if u.role == 'admin' else 'Unassigned')
        out.append({
            "id": u.id,
            "username": u.username,
            "role": u.role,
            "school_id": u.school_id,
            "school_name": sch_name
        })
    return jsonify({"users": out})

@app.route('/admin/users', methods=['POST'])
@admin_required_api
def create_user():
    data = request.get_json() or {}
    email = data.get('email', '').strip()
    password = data.get('password', '').strip()
    role = data.get('role', 'staff')
    school_id = data.get('school_id')

    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    if User.query.filter_by(username=email).first():
        return jsonify({"error": f"User '{email}' already exists."}), 400

    user = User(username=email, role=role)
    user.set_password(password)
    if school_id:
        user.school_id = int(school_id)

    db.session.add(user)
    db.session.commit()
    return jsonify({"message": "User created successfully."})

@app.route('/admin/users/<int:user_id>', methods=['DELETE'])
@admin_required_api
def delete_user(user_id):
    if session.get('user_id') == user_id:
        return jsonify({"error": "Cannot delete current logged in user."}), 400
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    return jsonify({"message": "User deleted successfully."})

@app.route('/students', methods=['GET'])
@login_required_api
def get_students():
    user = User.query.get(session['user_id'])
    
    school_id = request.args.get('school_id')
    search = request.args.get('search', '').strip()
    grade = request.args.get('grade', '').strip()
    sort_option = request.args.get('sort', 'absences_desc')
    chronic_only = request.args.get('chronic', 'false').lower() == 'true'

    query = StudentRecord.query

    # Enforce Non-Admin Security
    if user.role != 'admin':
        if not user.school_id:
            return jsonify({"students": [], "total_students": 0, "chronic_count": 0, "chronic_rate_pct": 0, "available_grades": []})
        query = query.filter_by(school_id=user.school_id)
    elif school_id:
        query = query.filter_by(school_id=school_id)

    # Apply Search Filter
    if search:
        query = query.filter(
            (StudentRecord.name.ilike(f"%{search}%")) |
            (StudentRecord.student_id.ilike(f"%{search}%"))
        )

    # Fetch available grades before grade filtering
    available_grades = [
        g[0] for g in db.session.query(StudentRecord.grade)
        .filter(StudentRecord.school_id == (school_id if user.role == 'admin' else user.school_id))
        .distinct().all() if g[0]
    ]

    # Apply Grade Filter
    if grade:
        query = query.filter_by(grade=grade)

    # Apply Chronic Filter
    if chronic_only:
        query = query.filter(StudentRecord.present_fte.isnot(None), StudentRecord.present_fte <= 90.0)

    # Apply Sort Options
    if sort_option == 'absences_desc':
        query = query.order_by(StudentRecord.absences.desc())
    elif sort_option == 'absences_asc':
        query = query.order_by(StudentRecord.absences.asc())
    elif sort_option == 'fte_desc':
        query = query.order_by(StudentRecord.present_fte.desc())
    elif sort_option == 'fte_asc':
        query = query.order_by(StudentRecord.present_fte.asc())
    elif sort_option == 'unexcused_desc':
        query = query.order_by(StudentRecord.unexcused_absences.desc())
    elif sort_option == 'rate_asc':
        query = query.order_by(StudentRecord.present_fte.asc())
    elif sort_option == 'name_asc':
        query = query.order_by(StudentRecord.name.asc())

    all_filtered = query.all()

    total_students = len(all_filtered)
    chronic_count = sum(1 for s in all_filtered if s.present_fte is not None and s.present_fte <= 90.0)
    chronic_rate_pct = round((chronic_count / total_students * 100), 1) if total_students > 0 else 0.0

    student_list = []
    for s in all_filtered:
        fte_val = round(s.present_fte, 2) if s.present_fte is not None else 0.0
        student_list.append({
            "db_id": s.id,
            "student_id": s.student_id,
            "student_name": s.name,
            "grade": s.grade,
            "days_absent": s.absences,
            "unexcused_absences": s.unexcused_absences,
            "attendance_rate_pct": fte_val,
            "is_chronic": (s.present_fte <= 90.0 if s.present_fte is not None else False),
            "interventions_count": len(s.interventions)
        })

    return jsonify({
        "students": student_list,
        "total_students": total_students,
        "chronic_count": chronic_count,
        "chronic_rate_pct": chronic_rate_pct,
        "available_grades": sorted(available_grades)
    })

@app.route('/interventions', methods=['GET'])
@login_required_api
def get_interventions():
    student_db_id = request.args.get('student_db_id')
    if not student_db_id:
        return jsonify({"error": "student_db_id parameter required"}), 400

    student = StudentRecord.query.get_or_404(student_db_id)
    logs = Intervention.query.filter_by(student_record_id=student.id).order_by(Intervention.id.desc()).all()

    out = []
    for log in logs:
        out.append({
            "id": log.id,
            "date": log.date,
            "type": log.type,
            "notes": log.notes,
            "logged_by": log.logged_by
        })
    return jsonify({"interventions": out})

@app.route('/interventions', methods=['POST'])
@login_required_api
def save_intervention():
    user = User.query.get(session['user_id'])
    data = request.get_json() or {}
    
    student_db_id = data.get('student_db_id')
    date = data.get('date')
    action_type = data.get('type')
    notes = data.get('notes', '').strip()

    if not student_db_id or not date or not action_type:
        return jsonify({"error": "Missing required intervention fields."}), 400

    student = StudentRecord.query.get_or_404(student_db_id)

    log = Intervention(
        student_record_id=student.id,
        date=date,
        type=action_type,
        notes=notes,
        logged_by=user.username
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({"message": "Intervention logged successfully."})

@app.route('/upload', methods=['POST'])
@login_required_api
def upload_csv():
    user = User.query.get(session['user_id'])
    school_id = request.form.get('school_id')

    if user.role != 'admin':
        school_id = user.school_id
    elif not school_id:
        return jsonify({"error": "Target school_id is required"}), 400

    file = request.files.get('file')
    if not file or not file.filename.endswith('.csv'):
        return jsonify({"error": "Invalid file format. CSV file required."}), 400

    try:
        stream = io.StringIO(file.stream.read().decode("utf-8-sig"), newline=None)
        reader = csv.DictReader(stream)

        imported = 0
        for row in reader:
            def val(keys, default=None):
                for k in keys:
                    for r_key in row.keys():
                        if r_key and r_key.strip().lower() == k.lower():
                            return row[r_key].strip()
                return default

            student_id = val(['student_id', 'id', 'student id'])
            name = val(['name', 'student_name', 'student name'])
            grade = val(['grade'], 'N/A')
            absences = float(val(['absences', 'days_absent', 'total_absences'], 0.0))
            unexcused = int(val(['unexcused_absences', 'unexcused'], 0))
            tardies = int(val(['tardies'], 0))
            total_days = float(val(['total_days'], 180.0))

            if not student_id or not name:
                continue

            present_fte = max(0.0, ((total_days - absences) / total_days) * 100) if total_days > 0 else 0.0

            record = StudentRecord.query.filter_by(student_id=student_id, school_id=school_id).first()
            if not record:
                record = StudentRecord(student_id=student_id, school_id=school_id)
                db.session.add(record)

            record.name = name
            record.grade = grade
            record.absences = absences
            record.unexcused_absences = unexcused
            record.tardies = tardies
            record.total_days = total_days
            record.present_fte = present_fte

            imported += 1

        db.session.commit()
        return jsonify({"message": f"Successfully imported {imported} student records."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Failed to process CSV file: {str(e)}"}), 500

@app.route('/export/interventions', methods=['GET'])
@login_required_api
def export_interventions():
    school_id = request.args.get('school_id')
    if not school_id:
        return "School ID required", 400

    students = StudentRecord.query.filter_by(school_id=school_id).all()
    student_ids = [s.id for s in students]

    interventions = Intervention.query.filter(Intervention.student_record_id.in_(student_ids)).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Student ID', 'Student Name', 'Grade', 'Intervention Date', 'Action Type', 'Notes', 'Logged By'])

    for item in interventions:
        writer.writerow([
            item.student.student_id,
            item.student.name,
            item.student.grade,
            item.date,
            item.type,
            item.notes,
            item.logged_by
        ])

    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename=interventions_school_{school_id}.csv"
    return response

# ------------------------------------------------------------------------------
# Initialize Database Setup
# ------------------------------------------------------------------------------
def init_db():
    with app.app_context():
        db.create_all()
        # Create Default Admin user if absent
        if not User.query.filter_by(username='admin@example.com').first():
            admin = User(username='admin@example.com', role='admin')
            admin.set_password('admin123')
            db.session.add(admin)
            
            # Default School
            default_school = School(name="Demo High School")
            db.session.add(default_school)
            db.session.commit()

if __name__ == '__main__':
    init_db()
    app.run(debug=True)

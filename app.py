import os
import io
from datetime import datetime
from functools import wraps

import pandas as pd
from flask import (
    Flask, render_template_string, request, jsonify, 
    session, redirect, url_for, send_file
)
from flask_sqlalchemy import SQLAlchemy
from flask_talisman import Talisman
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash

# ------------------------------------------------------------------------------
# APP & SETUP CONFIGURATION
# ------------------------------------------------------------------------------
app = Flask(__name__)

# Secret key configuration
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

# Database configuration (PostgreSQL production fallback to local SQLite)
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///attendance_app.db')
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ------------------------------------------------------------------------------
# SECURITY & RATE LIMITING
# ------------------------------------------------------------------------------
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

csp = {
    'default-src': '\'self\'',
    'script-src': ['\'self\'', '\'unsafe-inline\'', 'https://cdn.tailwindcss.com'],
    'style-src': ['\'self\'', '\'unsafe-inline\'', 'https://cdnjs.cloudflare.com'],
    'font-src': ['\'self\'', 'https://cdnjs.cloudflare.com']
}
talisman = Talisman(
    app, 
    content_security_policy=csp, 
    force_https=os.getenv('FLASK_ENV') == 'production'
)

# ------------------------------------------------------------------------------
# DATABASE MODELS
# ------------------------------------------------------------------------------
class School(db.Model):
    __tablename__ = 'schools'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    
    users = db.relationship('User', backref='school', lazy=True, cascade="all, delete-orphan")
    students = db.relationship('Student', backref='school', lazy=True, cascade="all, delete-orphan")

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='staff')  # 'admin' or 'staff'
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=True)

    interventions = db.relationship('Intervention', backref='logged_by_user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Student(db.Model):
    __tablename__ = 'students'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), nullable=False)
    student_name = db.Column(db.String(120), nullable=False)
    grade = db.Column(db.String(20), nullable=False)
    days_absent = db.Column(db.Float, nullable=False, default=0.0)
    total_days = db.Column(db.Float, nullable=False, default=1.0)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)

    interventions = db.relationship('Intervention', backref='student', lazy=True, cascade="all, delete-orphan")

    @property
    def attendance_rate(self):
        if self.total_days <= 0:
            return 100.0
        return round(((self.total_days - self.days_absent) / self.total_days) * 100, 1)

    @property
    def is_chronic(self):
        return self.attendance_rate < 90.0

class Intervention(db.Model):
    __tablename__ = 'interventions'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date = db.Column(db.String(20), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ------------------------------------------------------------------------------
# AUTHENTICATION & ACCESS CONTROL HELPERS
# ------------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized access'}), 401
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'admin':
            return jsonify({'error': 'Admin privileges required'}), 403
        return f(*args, **kwargs)
    return decorated_function

# ------------------------------------------------------------------------------
# CORE APPLICATION ROUTES
# ------------------------------------------------------------------------------
@app.route('/')
def index():
    with open('index.html', 'r', encoding='utf-8') if os.path.exists('index.html') else io.StringIO('<h1>App Running</h1>') as f:
        content = f.read()
    return render_template_string(content)

@app.route('/login', methods=['POST'])
@limiter.limit("5 per minute")
def login():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    user = User.query.filter_by(email=email).first()
    if user and user.check_password(password):
        session['user_id'] = user.id
        session['role'] = user.role
        session['school_id'] = user.school_id
        return jsonify({
            'message': 'Login successful',
            'user': {
                'id': user.id,
                'email': user.email,
                'role': user.role,
                'school_id': user.school_id
            }
        })
    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Logged out successfully'})

@app.route('/me', methods=['GET'])
def current_user():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            return jsonify({
                'logged_in': True,
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'role': user.role,
                    'school_id': user.school_id
                }
            })
    return jsonify({'logged_in': False})

# ------------------------------------------------------------------------------
# DATA & SCHOOL API ROUTES
# ------------------------------------------------------------------------------
@app.route('/schools', methods=['GET'])
@login_required
def get_schools():
    user = User.query.get(session['user_id'])
    if user.role == 'admin':
        schools = School.query.all()
    elif user.school_id:
        schools = School.query.filter_by(id=user.school_id).all()
    else:
        schools = []
    
    return jsonify({'schools': [{'id': s.id, 'name': s.name} for s in schools]})

@app.route('/students', methods=['GET'])
@login_required
def get_students():
    school_id = request.args.get('school_id', type=int)
    grade = request.args.get('grade', type=str, default='').strip()
    chronic = request.args.get('chronic', default='false').lower() == 'true'
    search = request.args.get('search', type=str, default='').strip().lower()
    sort_by = request.args.get('sort', type=str, default='absences_desc')

    user = User.query.get(session['user_id'])
    if user.role != 'admin' and user.school_id != school_id:
        return jsonify({'error': 'Access denied to this school'}), 403

    query = Student.query.filter_by(school_id=school_id)

    all_students_for_school = query.all()
    available_grades = sorted(list({s.grade for s in all_students_for_school if s.grade}))

    if grade:
        query = query.filter_by(grade=grade)

    students = query.all()

    result = []
    total_count = 0
    chronic_count = 0

    for s in students:
        is_chr = s.is_chronic
        if is_chr:
            chronic_count += 1
        
        if chronic and not is_chr:
            continue

        if search and (search not in s.student_name.lower() and search not in s.student_id.lower()):
            continue

        total_count += 1
        result.append({
            'db_id': s.id,
            'student_id': s.student_id,
            'student_name': s.student_name,
            'grade': s.grade,
            'days_absent': s.days_absent,
            'total_days': s.total_days,
            'attendance_rate_pct': s.attendance_rate,
            'is_chronic': is_chr,
            'interventions_count': len(s.interventions)
        })

    # Enhanced sorting logic for all interactive headers
    if sort_by == 'absences_desc':
        result.sort(key=lambda x: x['days_absent'], reverse=True)
    elif sort_by == 'absences_asc':
        result.sort(key=lambda x: x['days_absent'])
    elif sort_by == 'rate_asc':
        result.sort(key=lambda x: x['attendance_rate_pct'])
    elif sort_by == 'rate_desc':
        result.sort(key=lambda x: x['attendance_rate_pct'], reverse=True)
    elif sort_by == 'name_asc':
        result.sort(key=lambda x: x['student_name'].lower())
    elif sort_by == 'name_desc':
        result.sort(key=lambda x: x['student_name'].lower(), reverse=True)
    elif sort_by == 'id_asc':
        result.sort(key=lambda x: str(x['student_id']).lower())
    elif sort_by == 'id_desc':
        result.sort(key=lambda x: str(x['student_id']).lower(), reverse=True)
    elif sort_by == 'grade_asc':
        result.sort(key=lambda x: str(x['grade']).lower())
    elif sort_by == 'grade_desc':
        result.sort(key=lambda x: str(x['grade']).lower(), reverse=True)

    return jsonify({
        'total_students': total_count,
        'chronic_count': chronic_count,
        'available_grades': available_grades,
        'students': result
    })

# ------------------------------------------------------------------------------
# FILE IMPORT (CSV / EXCEL VIA PANDAS)
# ------------------------------------------------------------------------------
@app.route('/upload', methods=['POST'])
@login_required
def upload_data():
    school_id = request.form.get('school_id', type=int)
    if 'file' not in request.files or not school_id:
        return jsonify({'error': 'File and school_id are required'}), 400

    file = request.files['file']
    filename = file.filename.lower()

    try:
        if filename.endswith('.csv'):
            df = pd.read_csv(file)
        elif filename.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(file)
        else:
            return jsonify({'error': 'Unsupported file format'}), 400

        df.columns = [str(c).strip().lower().replace(' ', '_') for c in df.columns]

        id_col = next((c for c in df.columns if 'id' in c), None)
        name_col = next((c for c in df.columns if 'name' in c), None)
        grade_col = next((c for c in df.columns if 'grade' in c), None)
        absent_col = next((c for c in df.columns if 'absent' in c), None)
        total_col = next((c for c in df.columns if 'total' in c or 'membership' in c), None)

        if not all([id_col, name_col, grade_col, absent_col, total_col]):
            return jsonify({'error': 'Missing required columns (ID, Name, Grade, Absent Days, Total Days)'}), 400

        count = 0
        for _, row in df.iterrows():
            st_id = str(row[id_col]).strip()
            student = Student.query.filter_by(student_id=st_id, school_id=school_id).first()
            if not student:
                student = Student(student_id=st_id, school_id=school_id)
                db.session.add(student)

            student.student_name = str(row[name_col]).strip()
            student.grade = str(row[grade_col]).strip()
            student.days_absent = float(row[absent_col])
            student.total_days = float(row[total_col])
            count += 1

        db.session.commit()
        return jsonify({'message': f'Successfully processed {count} student records.'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to process file: {str(e)}'}), 500

# ------------------------------------------------------------------------------
# INTERVENTIONS LOGGING & EXPORTING
# ------------------------------------------------------------------------------
@app.route('/interventions', methods=['GET', 'POST'])
@login_required
def handle_interventions():
    if request.method == 'GET':
        student_db_id = request.args.get('student_db_id', type=int)
        interventions = Intervention.query.filter_by(student_id=student_db_id).order_by(Intervention.created_at.desc()).all()
        return jsonify({
            'interventions': [{
                'id': i.id,
                'date': i.date,
                'type': i.type,
                'notes': i.notes,
                'logged_by': i.logged_by_user.email if i.logged_by_user else 'Unknown'
            } for i in interventions]
        })

    data = request.get_json() or {}
    intervention = Intervention(
        student_id=data.get('student_db_id'),
        user_id=session['user_id'],
        date=data.get('date'),
        type=data.get('type'),
        notes=data.get('notes')
    )
    db.session.add(intervention)
    db.session.commit()
    return jsonify({'message': 'Intervention logged successfully'})

@app.route('/export/interventions', methods=['GET'])
@login_required
def export_interventions():
    school_id = request.args.get('school_id', type=int)
    
    interventions = db.session.query(Intervention, Student, User).\
        join(Student, Intervention.student_id == Student.id).\
        join(User, Intervention.user_id == User.id).\
        filter(Student.school_id == school_id).all()

    data = []
    for intv, st, usr in interventions:
        data.append({
            'Student ID': st.student_id,
            'Student Name': st.student_name,
            'Grade': st.grade,
            'Attendance Rate (%)': st.attendance_rate,
            'Intervention Date': intv.date,
            'Action Type': intv.type,
            'Notes': intv.notes,
            'Logged By': usr.email
        })

    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Interventions')
    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'interventions_school_{school_id}.xlsx'
    )

# ------------------------------------------------------------------------------
# ADMIN CONSOLE ROUTES
# ------------------------------------------------------------------------------
@app.route('/admin/schools', methods=['POST'])
@login_required
@admin_required
def create_school():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'School name is required'}), 400

    if School.query.filter_by(name=name).first():
        return jsonify({'error': 'School already exists'}), 400

    school = School(name=name)
    db.session.add(school)
    db.session.commit()
    return jsonify({'message': 'School created successfully'})

@app.route('/admin/schools/<int:school_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_school(school_id):
    school = School.query.get(school_id)
    if not school:
        return jsonify({'error': 'School not found'}), 404

    db.session.delete(school)
    db.session.commit()
    return jsonify({'message': 'School and related data deleted successfully'})

@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_users():
    if request.method == 'GET':
        users = User.query.all()
        return jsonify({
            'users': [{
                'id': u.id,
                'email': u.email,
                'role': u.role,
                'school_name': u.school.name if u.school else None
            } for u in users]
        })

    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    role = data.get('role', 'staff')
    school_id = data.get('school_id') if role == 'staff' else None

    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'User email already exists'}), 400

    user = User(email=email, role=role, school_id=school_id)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify({'message': 'User created successfully'})

@app.route('/admin/users/<int:user_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    db.session.delete(user)
    db.session.commit()
    return jsonify({'message': 'User deleted successfully'})

# ------------------------------------------------------------------------------
# INITIALIZATION & CLI SETUP
# ------------------------------------------------------------------------------
def init_db():
    db.create_all()
    if not User.query.filter_by(role='admin').first():
        admin = User(email='admin@school.org', role='admin')
        admin.set_password('AdminPass123!')
        db.session.add(admin)
        db.session.commit()
        print("Default admin account created: admin@school.org / AdminPass123!")

if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)

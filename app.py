import os
import io
import pandas as pd
from flask import Flask, request, jsonify, render_template, session
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import insert
from werkzeug.security import generate_password_hash, check_password_hash
from jinja2 import FileSystemLoader

# Resolve the project root path explicitly for Render
base_dir = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'chronic-absenteeism-secret-key-2026')
CORS(app)

# Explicitly register template paths so Jinja always finds index.html
app.jinja_loader = FileSystemLoader([
    os.path.join(base_dir, 'templates'),
    base_dir
])

# Database Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///app.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith("postgres://"):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# -----------------------------------------------------------------
# DATABASE MODELS
# -----------------------------------------------------------------

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='staff') # 'admin' or 'staff'

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class School(db.Model):
    __tablename__ = 'schools'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    students = db.relationship('Student', backref='school', lazy=True, cascade="all, delete-orphan")

class Student(db.Model):
    __tablename__ = 'students'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), nullable=False)
    student_name = db.Column(db.String(100), nullable=False)
    grade = db.Column(db.String(20), nullable=True)
    days_absent = db.Column(db.Float, default=0.0)
    total_days = db.Column(db.Float, default=0.0)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    interventions = db.relationship('Intervention', backref='student', lazy=True, cascade="all, delete-orphan")

    __table_args__ = (
        db.UniqueConstraint('student_id', 'school_id', name='unique_student_per_school'),
    )

    @property
    def absence_rate(self):
        if self.total_days > 0:
            return round((self.days_absent / self.total_days) * 100, 1)
        return 0.0

    @property
    def is_chronic(self):
        return self.absence_rate >= 10.0

class Intervention(db.Model):
    __tablename__ = 'interventions'
    id = db.Column(db.Integer, primary_key=True)
    student_db_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    date = db.Column(db.String(20), nullable=False)
    type = db.Column(db.String(50), nullable=False) # e.g., 'Parent Contact', 'Attendance Contract', 'Home Visit'
    notes = db.Column(db.Text, nullable=True)
    logged_by = db.Column(db.String(80), nullable=True)

# -----------------------------------------------------------------
# MAIN PAGE & AUTHENTICATION ENDPOINTS (LOGIN / LOGOUT / REGISTER)
# -----------------------------------------------------------------

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    role = data.get('role', 'staff')

    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already exists'}), 400

    user = User(username=username, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    return jsonify({'message': 'User registered successfully!'}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')

    user = User.query.filter_by(username=username).first()
    if user and user.check_password(password):
        session['user_id'] = user.id
        session['username'] = user.username
        session['role'] = user.role
        return jsonify({
            'message': 'Login successful!',
            'user': {'id': user.id, 'username': user.username, 'role': user.role}
        }), 200

    return jsonify({'error': 'Invalid username or password'}), 401

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Logged out successfully!'}), 200

@app.route('/me', methods=['GET'])
def current_user():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'logged_in': False}), 200
    user = User.query.get(user_id)
    return jsonify({
        'logged_in': True,
        'user': {'id': user.id, 'username': user.username, 'role': user.role}
    })

# -----------------------------------------------------------------
# SCHOOL ENDPOINTS
# -----------------------------------------------------------------

@app.route('/schools', methods=['GET', 'POST'])
def handle_schools():
    if request.method == 'POST':
        data = request.get_json() or {}
        name = data.get('name')
        if not name:
            return jsonify({'error': 'School name is required'}), 400
        
        school = School(name=name)
        db.session.add(school)
        db.session.commit()
        return jsonify({'id': school.id, 'name': school.name}), 201

    schools = School.query.all()
    return jsonify({'schools': [{'id': s.id, 'name': s.name} for s in schools]})

# -----------------------------------------------------------------
# FILE UPLOAD & PARSING WITH UPSERT
# -----------------------------------------------------------------

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    school_id = request.form.get('school_id', type=int)

    if not school_id:
        return jsonify({'error': 'School ID is required'}), 400

    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    try:
        if file.filename.endswith('.csv'):
            df = pd.read_csv(io.StringIO(file.stream.read().decode('utf-8')))
        else:
            df = pd.read_excel(file)

        # Dynamic column detection
        id_col = next((c for c in df.columns if 'student' in c.lower() and 'id' in c.lower()), df.columns[0])
        name_col = next((c for c in df.columns if 'name' in c.lower()), df.columns[1] if len(df.columns) > 1 else df.columns[0])
        absent_col = next((c for c in df.columns if 'absent' in c.lower() or 'unexcused' in c.lower()), None)
        total_col = next((c for c in df.columns if 'total' in c.lower() or 'enrolled' in c.lower() or 'membership' in c.lower()), None)
        grade_col = next((c for c in df.columns if 'grade' in c.lower()), None)

        # 1. CLEAN HEADER METADATA (Drops "Attendance Date Range:", titles, empty rows)
        df[id_col] = df[id_col].astype(str).str.strip()
        df = df[
            df[id_col].notna() & 
            (df[id_col] != '') & 
            ~df[id_col].str.contains('Attendance Date Range|Report|Total|Date', case=False, na=False)
        ]

        # 2. BULK UPSERT
        processed_count = 0
        chronic_count = 0

        for _, row in df.iterrows():
            st_id = str(row[id_col]).strip()
            st_name = str(row[name_col]).strip() if name_col else "Unknown"
            st_grade = str(row[grade_col]).strip() if grade_col and pd.notna(row[grade_col]) else "N/A"
            days_abs = float(row[absent_col]) if absent_col and pd.notna(row[absent_col]) else 0.0
            tot_days = float(row[total_col]) if total_col and pd.notna(row[total_col]) else 0.0

            if tot_days > 0 and (days_abs / tot_days) >= 0.10:
                chronic_count += 1

            stmt = insert(Student).values(
                student_id=st_id,
                student_name=st_name,
                grade=st_grade,
                days_absent=days_abs,
                total_days=tot_days,
                school_id=school_id
            )

            # On duplicate (student_id + school_id), update record stats
            stmt = stmt.on_conflict_do_update(
                constraint='unique_student_per_school',
                set_={
                    'student_name': st_name,
                    'grade': st_grade,
                    'days_absent': days_abs,
                    'total_days': tot_days
                }
            )

            db.session.execute(stmt)
            processed_count += 1

        db.session.commit()
        return jsonify({
            'message': 'File uploaded and processed successfully!',
            'total_students': processed_count,
            'chronic_count': chronic_count
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to process file: {str(e)}'}), 500

# -----------------------------------------------------------------
# STUDENT ROSTER & MULTI-CRITERIA FILTERING
# -----------------------------------------------------------------

@app.route('/students', methods=['GET'])
def get_students():
    school_id = request.args.get('school_id', type=int)
    grade = request.args.get('grade', type=str)
    filter_chronic = request.args.get('chronic', type=str) # 'true' or 'false'
    search_query = request.args.get('search', type=str)

    query = Student.query

    # Apply Database Filters
    if school_id:
        query = query.filter_by(school_id=school_id)

    if grade:
        query = query.filter_by(grade=grade)

    if search_query:
        search_pattern = f"%{search_query}%"
        query = query.filter(
            (Student.student_name.ilike(search_pattern)) | 
            (Student.student_id.ilike(search_pattern))
        )

    students = query.all()

    # Dynamic Computation and Chronic Filtering
    student_list = []
    total_chronic = 0
    unique_grades = sorted(list(set(s.grade for s in Student.query.all() if s.grade)))

    for s in students:
        is_chr = s.is_chronic
        if is_chr:
            total_chronic += 1

        # Apply Chronic Filter if requested
        if filter_chronic == 'true' and not is_chr:
            continue

        # Get total interventions logged for student
        int_count = Intervention.query.filter_by(student_db_id=s.id).count()

        student_list.append({
            'db_id': s.id,
            'student_id': s.student_id,
            'student_name': s.student_name,
            'grade': s.grade,
            'days_absent': s.days_absent,
            'total_days': s.total_days,
            'absence_rate_pct': s.absence_rate,
            'is_chronic': is_chr,
            'school_id': s.school_id,
            'interventions_count': int_count
        })

    return jsonify({
        'total_students': len(students),
        'chronic_count': total_chronic,
        'available_grades': unique_grades,
        'students': student_list
    })

# -----------------------------------------------------------------
# INTERVENTIONS MANAGEMENT (LOG & RETRIEVE & DELETE)
# -----------------------------------------------------------------

@app.route('/interventions', methods=['GET', 'POST', 'DELETE'])
def handle_interventions():
    if request.method == 'POST':
        data = request.get_json() or {}
        student_db_id = data.get('student_db_id')
        date_str = data.get('date')
        int_type = data.get('type')
        notes = data.get('notes', '')
        logged_by = session.get('username', data.get('logged_by', 'Staff'))

        if not student_db_id or not date_str or not int_type:
            return jsonify({'error': 'Missing required intervention fields'}), 400

        intervention = Intervention(
            student_db_id=student_db_id,
            date=date_str,
            type=int_type,
            notes=notes,
            logged_by=logged_by
        )
        db.session.add(intervention)
        db.session.commit()
        return jsonify({'message': 'Intervention logged successfully!', 'id': intervention.id}), 201

    elif request.method == 'DELETE':
        int_id = request.args.get('id', type=int)
        if not int_id:
            return jsonify({'error': 'Intervention ID required'}), 400

        intervention = Intervention.query.get(int_id)
        if not intervention:
            return jsonify({'error': 'Intervention not found'}), 404

        db.session.delete(intervention)
        db.session.commit()
        return jsonify({'message': 'Intervention deleted successfully!'}), 200

    # GET Request: Filter by student_db_id if provided
    student_db_id = request.args.get('student_db_id', type=int)
    if student_db_id:
        interventions = Intervention.query.filter_by(student_db_id=student_db_id).order_by(Intervention.id.desc()).all()
    else:
        interventions = Intervention.query.order_by(Intervention.id.desc()).all()

    return jsonify({
        'interventions': [{
            'id': i.id,
            'student_db_id': i.student_db_id,
            'date': i.date,
            'type': i.type,
            'notes': i.notes,
            'logged_by': i.logged_by
        } for i in interventions]
    })

# Initialize Database tables if running standalone
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)

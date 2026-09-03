import os
import csv
import io
from datetime import datetime
from functools import wraps
from urllib.parse import quote_plus

from flask import (
    Flask, render_template, request, jsonify, 
    redirect, url_for, flash, session
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

# ==========================================
# APP INITIALIZATION
# ==========================================
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# ==========================================
# SAFE DATABASE CONFIGURATION (GUNICORN FIX)
# ==========================================
raw_db_url = os.environ.get('DATABASE_URL', '').strip()

if not raw_db_url:
    # Default to local SQLite if env var is missing or empty string
    SQLALCHEMY_DATABASE_URI = 'sqlite:///attendance.db'
elif raw_db_url.startswith('postgres://'):
    # Standardize legacy Postgres scheme for SQLAlchemy 1.4+
    SQLALCHEMY_DATABASE_URI = raw_db_url.replace('postgres://', 'postgresql://', 1)
else:
    SQLALCHEMY_DATABASE_URI = raw_db_url

app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Tardy conversion rule (e.g., 3 tardies = 1 full day absent equivalent)
TARDY_CONVERSION_FACTOR = 3 


# ==========================================
# DATABASE MODELS
# ==========================================
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    school_id = db.Column(db.Integer, nullable=False, default=1)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Student(db.Model):
    __tablename__ = 'students'
    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, nullable=False, default=1, index=True)
    student_id = db.Column(db.String(50), nullable=False)
    student_name = db.Column(db.String(100), nullable=False)
    grade = db.Column(db.String(20), nullable=True)
    
    # Attendance Inputs
    enrolled_days = db.Column(db.Float, default=180.0)
    full_day_absences = db.Column(db.Float, default=0.0)
    half_days = db.Column(db.Float, default=0.0)
    tardies = db.Column(db.Integer, default=0)
    unexcused_absences = db.Column(db.Float, default=0.0)
    
    # Calculated Fields
    total_effective_absences = db.Column(db.Float, default=0.0)
    days_absent = db.Column(db.Float, default=0.0)
    attendance_rate_pct = db.Column(db.Float, nullable=False, default=100.0, index=True)

    interventions = db.relationship('Intervention', backref='student', cascade='all, delete-orphan')

    def calculate_metrics(self):
        """Calculates total lost time (full + half + tardies) and updates percentage."""
        tardy_days = (self.tardies / TARDY_CONVERSION_FACTOR) if TARDY_CONVERSION_FACTOR > 0 else 0.0
        half_day_equivalents = self.half_days * 0.5
        
        self.total_effective_absences = round(self.full_day_absences + half_day_equivalents + tardy_days, 2)
        self.days_absent = self.total_effective_absences
        
        if self.enrolled_days > 0:
            rate = ((self.enrolled_days - self.total_effective_absences) / self.enrolled_days) * 100.0
            self.attendance_rate_pct = max(0.0, min(100.0, round(rate, 2)))
        else:
            self.attendance_rate_pct = 100.0


class Intervention(db.Model):
    __tablename__ = 'interventions'
    id = db.Column(db.Integer, primary_key=True)
    student_db_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    date_logged = db.Column(db.DateTime, default=datetime.utcnow)
    intervention_type = db.Column(db.String(100), nullable=False)
    notes = db.Column(db.Text, nullable=True)


# ==========================================
# AUTHENTICATION DECORATOR
# ==========================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function


# ==========================================
# ROUTES
# ==========================================

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            session['user_id'] = user.id
            session['school_id'] = user.school_id
            session['username'] = user.username
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password', 'danger')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ------------------------------------------
# API: GET STUDENTS & METRICS
# ------------------------------------------
@app.route('/api/students', methods=['GET'])
@login_required
def get_students():
    school_id = session.get('school_id', 1)
    
    # Query Parameters
    search = request.args.get('search', '').strip()
    grade = request.args.get('grade', '').strip()
    sort_by = request.args.get('sort', 'rate_asc')
    chronic_only = request.args.get('chronic', 'false').lower() == 'true'

    query = Student.query.filter(Student.school_id == school_id)

    # 1. Search Filter
    if search:
        query = query.filter(
            db.or_(
                Student.student_name.ilike(f"%{search}%"),
                Student.student_id.ilike(f"%{search}%")
            )
        )

    # 2. Grade Filter
    if grade:
        query = query.filter(Student.grade == grade)

    # 3. Chronic Absence Filter (STRICTLY BELOW 90.0%)
    if chronic_only:
        query = query.filter(Student.attendance_rate_pct < 90.0)

    # 4. Sorting
    if sort_by == 'rate_asc':
        query = query.order_by(Student.attendance_rate_pct.asc())
    elif sort_by == 'rate_desc':
        query = query.order_by(Student.attendance_rate_pct.desc())
    elif sort_by == 'absences_desc':
        query = query.order_by(Student.total_effective_absences.desc())
    elif sort_by == 'name_asc':
        query = query.order_by(Student.student_name.asc())

    filtered_students = query.all()

    # 5. Global School Metrics
    all_school_students = Student.query.filter(Student.school_id == school_id).all()
    total_enrolled = len(all_school_students)
    
    chronic_students_count = sum(1 for s in all_school_students if s.attendance_rate_pct < 90.0)
    chronic_rate_pct = round((chronic_students_count / total_enrolled * 100.0), 1) if total_enrolled > 0 else 0.0

    return jsonify({
        "metrics": {
            "total_students": total_enrolled,
            "chronic_count": chronic_students_count,
            "chronic_rate_pct": chronic_rate_pct,
            "available_grades": sorted(list(set(s.grade for s in all_school_students if s.grade)))
        },
        "count": len(filtered_students),
        "students": [{
            "id": s.id,
            "student_id": s.student_id,
            "name": s.student_name,
            "grade": s.grade,
            "enrolled_days": s.enrolled_days,
            "full_day_absences": s.full_day_absences,
            "half_days": s.half_days,
            "tardies": s.tardies,
            "total_effective_absences": s.total_effective_absences,
            "unexcused_absences": s.unexcused_absences,
            "attendance_rate_pct": s.attendance_rate_pct,
            "is_chronic": s.attendance_rate_pct < 90.0,
            "interventions_count": len(s.interventions)
        } for s in filtered_students]
    })


# ------------------------------------------
# API: CSV UPLOAD
# ------------------------------------------
@app.route('/api/upload_csv', methods=['POST'])
@login_required
def upload_csv():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['file']
    if not file.filename.endswith('.csv'):
        return jsonify({"error": "File must be a CSV"}), 400

    school_id = session.get('school_id', 1)
    
    try:
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_input = csv.DictReader(stream)
        processed_count = 0
        
        for row in csv_input:
            row_clean = {k.strip().lower().replace(" ", "_"): v.strip() for k, v in row.items() if k}
            
            s_id = row_clean.get('student_id') or row_clean.get('id')
            s_name = row_clean.get('student_name') or row_clean.get('name')
            
            if not s_id or not s_name:
                continue

            student = Student.query.filter_by(school_id=school_id, student_id=s_id).first()
            if not student:
                student = Student(school_id=school_id, student_id=s_id)

            student.student_name = s_name
            student.grade = row_clean.get('grade', student.grade or 'N/A')
            student.enrolled_days = float(row_clean.get('enrolled_days', student.enrolled_days or 180.0))
            student.full_day_absences = float(row_clean.get('full_absences', row_clean.get('full_day_absences', 0)))
            student.half_days = float(row_clean.get('half_days', 0))
            student.tardies = int(float(row_clean.get('tardies', 0)))
            student.unexcused_absences = float(row_clean.get('unexcused', row_clean.get('unexcused_absences', 0)))

            student.calculate_metrics()

            db.session.add(student)
            processed_count += 1

        db.session.commit()
        return jsonify({"message": f"Successfully processed {processed_count} student records."})

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Failed to parse CSV: {str(e)}"}), 500


# ------------------------------------------
# API: ADD INTERVENTION
# ------------------------------------------
@app.route('/api/interventions', methods=['POST'])
@login_required
def add_intervention():
    data = request.json or {}
    student_db_id = data.get('student_db_id')
    intervention_type = data.get('type')
    notes = data.get('notes', '')

    if not student_db_id or not intervention_type:
        return jsonify({"error": "Missing required fields"}), 400

    intervention = Intervention(
        student_db_id=student_db_id,
        intervention_type=intervention_type,
        notes=notes
    )
    db.session.add(intervention)
    db.session.commit()

    return jsonify({"message": "Intervention recorded successfully."})


# ==========================================
# INITIALIZATION & STARTUP
# ==========================================
def init_db():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            default_user = User(username='admin', school_id=1)
            default_user.set_password('admin123')
            db.session.add(default_user)
            db.session.commit()

init_db()

if __name__ == '__main__':
    app.run(debug=True, port=5000)

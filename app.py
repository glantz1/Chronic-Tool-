import os
import io
import pandas as pd
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

# Explicit dynamic template path
base_dir = os.path.abspath(os.path.dirname(__file__))
template_dir = os.path.join(base_dir, 'templates')

app = Flask(__name__, template_folder=template_dir)
CORS(app)

# Get the absolute path of the directory containing app.py
base_dir = os.path.abspath(os.path.dirname(__file__))
template_dir = os.path.join(base_dir, 'templates')

app = Flask(__name__, template_folder=template_dir)from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, template_folder='.')
CORS(app)

# Database Configuration
db_url = os.environ.get('DATABASE_URL')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url or 'sqlite:///attendance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ==========================================
# DATABASE MODELS
# ==========================================

class School(db.Model):
    __tablename__ = 'schools'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    students = db.relationship('Student', backref='school', lazy=True, cascade="all, delete-orphan")
    users = db.relationship('User', backref='school', lazy=True)

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='staff')  # 'district_admin', 'school_admin', 'staff'
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=True)

class Student(db.Model):
    __tablename__ = 'students'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), nullable=False)
    student_name = db.Column(db.String(100), nullable=False)
    grade = db.Column(db.String(20), nullable=False, default='N/A')
    days_absent = db.Column(db.Integer, nullable=False, default=0)
    total_days = db.Column(db.Integer, nullable=False, default=1)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)

class Intervention(db.Model):
    __tablename__ = 'interventions'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), nullable=False)
    student_name = db.Column(db.String(100), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    staff_name = db.Column(db.String(100), nullable=False)
    note = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

# Initialize DB and seed admin if needed
with app.app_context():
    db.create_all()
    if not School.query.filter_by(name="Default High School").first():
        default_school = School(name="Default High School")
        db.session.add(default_school)
        db.session.commit()

    if not User.query.filter_by(username="admin").first():
        admin_user = User(
            username="admin",
            password_hash=generate_password_hash("Admin2026!"),
            full_name="District Administrator",
            role="district_admin"
        )
        db.session.add(admin_user)
        db.session.commit()

# ==========================================
# RESILIENT CSV PARSER
# ==========================================

def process_attendance_csv(file):
    raw_bytes = file.read()
    try:
        decoded_text = raw_bytes.decode('utf-8-sig')
    except UnicodeDecodeError:
        decoded_text = raw_bytes.decode('latin-1')

    try:
        df = pd.read_csv(io.StringIO(decoded_text), sep=None, engine='python')
    except Exception:
        df = pd.read_csv(io.StringIO(decoded_text))

    # Clean headers (strip, lowercase, remove punctuation)
    df.columns = [
        str(col).strip().strip('"').strip("'").lower().replace(" ", "").replace("_", "").replace("-", "")
        for col in df.columns
    ]

    # Map header variations to standardized fields
    aliases = {
        'studentnumber': 'student_id', 'studentnumber1': 'student_id', 'studentid': 'student_id', 'id': 'student_id', 'pupilid': 'student_id', 'stuid': 'student_id',
        'studentname': 'student_name', 'fullname': 'student_name', 'name': 'student_name', 'pupilname': 'student_name', 'student': 'student_name',
        'grade': 'grade', 'gradelevel': 'grade', 'gr': 'grade',
        'currentschoolabsences7': 'days_absent', 'totalabsenceindistricthdwd10': 'days_absent', 'unexcusedabsences': 'days_absent',
        'unexcusedabsencesdist': 'days_absent', 'daysabsent': 'days_absent', 'absences': 'days_absent', 'absent': 'days_absent', 'totabs': 'days_absent',
        'currentschoolmembershipdays11': 'total_days', 'totalmembershipdaysindistrict10': 'total_days', 'totaldays': 'total_days',
        'enrolleddays': 'total_days', 'membershipdays': 'total_days', 'daysenrolled': 'total_days', 'totdays': 'total_days'
    }

    df.rename(columns=aliases, inplace=True)
    df = df.loc[:, ~df.columns.duplicated(keep='first')]

    # Prevent dropping missing columns by assigning smart fallbacks
    if 'student_id' not in df.columns:
        df['student_id'] = [f"STU-{i+1}" for i in range(len(df))]
    if 'student_name' not in df.columns:
        df['student_name'] = 'Unknown Student'
    if 'grade' not in df.columns:
        df['grade'] = 'N/A'
    if 'days_absent' not in df.columns:
        df['days_absent'] = 0
    if 'total_days' not in df.columns:
        df['total_days'] = 100

    # Sanitize data formats
    df['student_id'] = df['student_id'].astype(str).str.strip().replace('', 'N/A').fillna('N/A')
    df['student_name'] = df['student_name'].astype(str).str.strip().replace('', 'N/A').fillna('N/A')
    df['grade'] = df['grade'].astype(str).str.strip().replace('', 'N/A').fillna('N/A')
    df['days_absent'] = pd.to_numeric(df['days_absent'], errors='coerce').fillna(0).astype(int)
    df['total_days'] = pd.to_numeric(df['total_days'], errors='coerce').fillna(1)
    df['total_days'] = df['total_days'].apply(lambda x: x if x > 0 else 1)

    df['absence_rate_raw'] = df['days_absent'] / df['total_days']
    df['absence_rate_pct'] = (df['absence_rate_raw'] * 100).round(1).astype(str) + '%'

    return df

# ==========================================
# API ENDPOINTS
# ==========================================

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    data = request.json or {}
    user = User.query.filter_by(username=data.get('username')).first()
    if user and check_password_hash(user.password_hash, data.get('password')):
        school_name = user.school.name if user.school else "District Wide"
        return jsonify({
            "message": "Login successful",
            "user": {
                "id": user.id,
                "username": user.username,
                "full_name": user.full_name,
                "role": user.role,
                "school_id": user.school_id,
                "school_name": school_name
            }
        })
    return jsonify({"error": "Invalid username or password"}), 401

@app.route('/schools', methods=['GET', 'POST'])
def handle_schools():
    if request.method == 'POST':
        data = request.json or {}
        name = data.get('name')
        if not name:
            return jsonify({"error": "School name is required"}), 400
        if School.query.filter_by(name=name).first():
            return jsonify({"error": "School already exists"}), 400
        new_school = School(name=name)
        db.session.add(new_school)
        db.session.commit()
        return jsonify({"message": "School added", "id": new_school.id, "name": new_school.name}), 201

    schools = School.query.all()
    return jsonify({"schools": [{"id": s.id, "name": s.name} for s in schools]})

@app.route('/students', methods=['GET'])
def get_students():
    school_id = request.args.get('school_id')
    query = Student.query
    if school_id:
        query = query.filter_by(school_id=school_id)
    
    students = query.all()
    out = []
    chronic_count = 0

    for s in students:
        raw_rate = s.days_absent / s.total_days if s.total_days > 0 else 0
        is_chronic = raw_rate >= 0.10
        if is_chronic:
            chronic_count += 1

        out.append({
            "id": s.id,
            "student_id": s.student_id,
            "student_name": s.student_name,
            "grade": s.grade,
            "days_absent": s.days_absent,
            "total_days": s.total_days,
            "absence_rate_raw": round(raw_rate, 4),
            "absence_rate_pct": f"{round(raw_rate * 100, 1)}%",
            "school_id": s.school_id,
            "is_chronic": is_chronic
        })

    return jsonify({
        "total_students": len(out),
        "chronic_count": chronic_count,
        "students": out
    })

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files['file']
    school_id = request.form.get('school_id')

    if not school_id:
        return jsonify({"error": "A school_id must be selected"}), 400

    try:
        df = process_attendance_csv(file)
        
        # Clear existing records for this school to avoid duplicates
        Student.query.filter_by(school_id=school_id).delete()

        new_students = []
        for _, row in df.iterrows():
            student = Student(
                student_id=str(row['student_id']),
                student_name=str(row['student_name']),
                grade=str(row['grade']),
                days_absent=int(row['days_absent']),
                total_days=int(row['total_days']),
                school_id=int(school_id)
            )
            new_students.append(student)

        db.session.bulk_save_objects(new_students)
        db.session.commit()

        chronic_count = sum(1 for s in new_students if (s.days_absent / s.total_days) >= 0.10)

        return jsonify({
            "message": "File processed successfully",
            "total_students": len(new_students),
            "chronic_count": chronic_count
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Failed to process file: {str(e)}"}), 500

@app.route('/interventions', methods=['GET', 'POST'])
def handle_interventions():
    if request.method == 'POST':
        data = request.json or {}
        required = ['student_id', 'student_name', 'school_id', 'staff_name', 'note']
        if not all(k in data for k in required):
            return jsonify({"error": "Missing required fields"}), 400

        intervention = Intervention(
            student_id=data['student_id'],
            student_name=data['student_name'],
            school_id=data['school_id'],
            staff_name=data['staff_name'],
            note=data['note']
        )
        db.session.add(intervention)
        db.session.commit()
        return jsonify({"message": "Intervention saved successfully"}), 201

    school_id = request.args.get('school_id')
    query = Intervention.query
    if school_id:
        query = query.filter_by(school_id=school_id)

    interventions = query.order_by(Intervention.created_at.desc()).all()
    
    out = []
    for i in interventions:
        school = School.query.get(i.school_id)
        out.append({
            "id": i.id,
            "student_id": i.student_id,
            "student_name": i.student_name,
            "school_id": i.school_id,
            "school_name": school.name if school else "N/A",
            "staff_name": i.staff_name,
            "note": i.note,
            "created_at": i.created_at.strftime("%Y-%m-%d %H:%M") if i.created_at else ""
        })

    return jsonify({"interventions": out})

@app.route('/users', methods=['POST'])
def create_user():
    data = request.json or {}
    username = data.get('username')
    password = data.get('password')
    full_name = data.get('full_name')
    role = data.get('role', 'staff')
    school_id = data.get('school_id')

    if not username or not password or not full_name:
        return jsonify({"error": "Username, password, and full name required"}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({"error": "Username already exists"}), 400

    user = User(
        username=username,
        password_hash=generate_password_hash(password),
        full_name=full_name,
        role=role,
        school_id=school_id if school_id else None
    )
    db.session.add(user)
    db.session.commit()
    return jsonify({"message": "User created successfully"}), 201

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

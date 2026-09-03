import os
import re
import io
import csv
from flask import Flask, request, jsonify, render_template, session, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'default-dev-secret-key-change-me')

# --- DATABASE CONFIGURATION ---
# Check standard env var or fallback if Railway merged the key name
raw_db_url = os.environ.get('DATABASE_URL') or os.environ.get('DATABASE_URLpostgresql', '')
raw_db_url = raw_db_url.strip().strip('"').strip("'")

# Fix corrupted strings like "postgresql="://${{...}}" or extra quotes
if 'postgresql="' in raw_db_url:
    raw_db_url = raw_db_url.replace('postgresql="', 'postgresql')
elif raw_db_url.startswith('="'):
    raw_db_url = 'postgresql' + raw_db_url[2:]

# Strip any residual quotes/braces
raw_db_url = raw_db_url.replace('"', '').replace("'", "")

# Fall back safely to SQLite if variables aren't resolved
if not raw_db_url or raw_db_url.startswith("${{") or '://' not in raw_db_url:
    db_url = 'sqlite:///attendance.db'
else:
    db_url = raw_db_url

# Fix legacy PostgreSQL driver scheme
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- MODELS ---
class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    users = db.relationship('User', backref='school', lazy=True)
    students = db.relationship('Student', backref='school', lazy=True, cascade="all, delete-orphan")

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='staff')
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    student_id = db.Column(db.String(50), nullable=False)
    student_name = db.Column(db.String(100), nullable=False)
    grade = db.Column(db.String(20), nullable=True)
    days_absent = db.Column(db.Float, default=0.0)
    unexcused_absences = db.Column(db.Float, default=0.0)
    total_days = db.Column(db.Float, default=0.0)
    attendance_rate = db.Column(db.Float, default=100.0)
    is_chronic = db.Column(db.Boolean, default=False)
    interventions = db.relationship('Intervention', backref='student', lazy=True, cascade="all, delete-orphan")

class Intervention(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    date = db.Column(db.String(20), nullable=False)
    type = db.Column(db.String(100), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    logged_by_email = db.Column(db.String(120), nullable=True)

# --- DATABASE INITIALIZATION ---
def init_db():
    db.create_all()
    try:
        with db.engine.connect() as conn:
            conn.execute(db.text("ALTER TABLE student ADD COLUMN unexcused_absences FLOAT DEFAULT 0.0"))
            conn.commit()
    except Exception:
        pass

    if not User.query.filter_by(role='admin').first():
        default_admin = User(email='admin@school.edu', role='admin')
        default_admin.set_password('AdminPass123!')
        db.session.add(default_admin)
        db.session.commit()

with app.app_context():
    init_db()
    masked_db = app.config['SQLALCHEMY_DATABASE_URI'].split('@')[-1]
    print(f"==================================================")
    print(f"--> ACTIVE DATABASE BACKEND: {masked_db}")
    print(f"==================================================")

# --- ROUTES ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/me', methods=['GET'])
def me():
    if 'user_id' not in session:
        return jsonify({"logged_in": False})
    user = User.query.get(session['user_id'])
    if not user:
        session.clear()
        return jsonify({"logged_in": False})
    return jsonify({
        "logged_in": True,
        "user": {
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "school_id": user.school_id
        }
    })

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or request.form
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    user = User.query.filter_by(email=email).first()
    if user and user.check_password(password):
        session['user_id'] = user.id
        return jsonify({
            "message": "Login successful",
            "user": {
                "id": user.id,
                "email": user.email,
                "role": user.role,
                "school_id": user.school_id
            }
        })
    return jsonify({"error": "Invalid email or password"}), 401

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"message": "Logged out successfully"})

@app.route('/schools', methods=['GET'])
def get_schools():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user = User.query.get(session['user_id'])
    if user.role == 'admin':
        schools = School.query.all()
    else:
        schools = School.query.filter_by(id=user.school_id).all() if user.school_id else []
    return jsonify({"schools": [{"id": s.id, "name": s.name} for s in schools]})

@app.route('/admin/schools', methods=['POST'])
def add_school():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user = User.query.get(session['user_id'])
    if user.role != 'admin':
        return jsonify({"error": "Admin access required"}), 403
    data = request.get_json(silent=True) or request.form
    name = data.get('name', '').strip()
    if not name:
        return jsonify({"error": "School name is required"}), 400
    if School.query.filter_by(name=name).first():
        return jsonify({"error": "School already exists"}), 400
    school = School(name=name)
    db.session.add(school)
    db.session.commit()
    return jsonify({"message": "School added successfully", "school": {"id": school.id, "name": school.name}})

@app.route('/admin/users', methods=['GET', 'POST'])
def handle_users():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    current_user = User.query.get(session['user_id'])
    if not current_user or current_user.role != 'admin':
        return jsonify({"error": "Admin access required"}), 403

    if request.method == 'GET':
        users = User.query.all()
        return jsonify({
            "users": [
                {
                    "id": u.id,
                    "email": u.email,
                    "role": u.role,
                    "school_id": u.school_id,
                    "school_name": u.school.name if u.school else "Unassigned"
                } for u in users
            ]
        })

    data = request.get_json(silent=True) or request.form
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    role = data.get('role', 'staff')
    school_id = data.get('school_id') or None

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "User with this email already exists"}), 400

    new_user = User(email=email, role=role, school_id=school_id)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"message": "User created successfully"})

@app.route('/admin/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    current_user = User.query.get(session['user_id'])
    if not current_user or current_user.role != 'admin':
        return jsonify({"error": "Admin access required"}), 403

    if current_user.id == user_id:
        return jsonify({"error": "You cannot delete your own account while logged in."}), 400

    user_to_delete = User.query.get(user_id)
    if not user_to_delete:
        return jsonify({"error": "User not found."}), 404

    interventions = Intervention.query.filter_by(user_id=user_id).all()
    for item in interventions:
        item.user_id = None

    db.session.delete(user_to_delete)
    db.session.commit()
    return jsonify({"message": f"Successfully deleted user {user_to_delete.email}."})

@app.route('/admin/assign-school', methods=['GET', 'POST'])
def assign_school():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    current_user = User.query.get(session['user_id'])
    if not current_user or current_user.role != 'admin':
        return jsonify({"error": "Admin access required"}), 403

    if request.method == 'GET':
        return jsonify({"message": "Send a POST request with user_id and school_id."})

    data = request.get_json(silent=True) or request.form
    target_user_id = data.get('user_id')
    school_id = data.get('school_id')

    if not target_user_id:
        return jsonify({"error": "user_id is required"}), 400

    user_to_update = User.query.get(target_user_id)
    if not user_to_update:
        return jsonify({"error": "User not found"}), 404

    try:
        user_to_update.school_id = int(school_id) if school_id else None
    except (ValueError, TypeError):
        user_to_update.school_id = None

    db.session.commit()
    return jsonify({"message": f"Successfully assigned school to {user_to_update.email}"})

@app.route('/students', methods=['GET'])
def get_students():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    school_id = request.args.get('school_id', type=int)
    search = request.args.get('search', '').strip().lower()
    grade = request.args.get('grade', '').strip()
    chronic_only = request.args.get('chronic', 'false').lower() == 'true'
    sort_by = request.args.get('sort', 'absences_desc')

    if not school_id:
        return jsonify({"error": "school_id query param is required"}), 400

    query = Student.query.filter_by(school_id=school_id)
    all_school_students = query.all()

    total_enrolled = len(all_school_students)
    chronic_count = len([s for s in all_school_students if s.is_chronic])
    chronic_rate_pct = round((chronic_count / total_enrolled * 100), 1) if total_enrolled > 0 else 0.0

    available_grades = sorted(list(set(s.grade for s in all_school_students if s.grade)))

    if search:
        query = query.filter((Student.student_name.ilike(f"%{search}%")) | (Student.student_id.ilike(f"%{search}%")))
    if grade:
        query = query.filter_by(grade=grade)
    if chronic_only:
        query = query.filter_by(is_chronic=True)

    if sort_by == 'absences_desc':
        query = query.order_by(Student.days_absent.desc())
    elif sort_by == 'absences_asc':
        query = query.order_by(Student.days_absent.asc())
    elif sort_by == 'unexcused_desc':
        query = query.order_by(Student.unexcused_absences.desc())
    elif sort_by == 'rate_asc':
        query = query.order_by(Student.attendance_rate.asc())
    elif sort_by == 'rate_desc':
        query = query.order_by(Student.attendance_rate.desc())
    elif sort_by == 'name_asc':
        query = query.order_by(Student.student_name.asc())
    elif sort_by == 'name_desc':
        query = query.order_by(Student.student_name.desc())

    filtered_students = query.all()

    return jsonify({
        "total_students": total_enrolled,
        "chronic_count": chronic_count,
        "chronic_rate_pct": chronic_rate_pct,
        "available_grades": available_grades,
        "students": [
            {
                "db_id": s.id,
                "student_id": s.student_id,
                "student_name": s.student_name,
                "grade": s.grade,
                "days_absent": s.days_absent,
                "unexcused_absences": getattr(s, 'unexcused_absences', 0.0) or 0.0,
                "total_days": s.total_days,
                "attendance_rate_pct": round(s.attendance_rate, 1),
                "is_chronic": s.is_chronic,
                "interventions_count": len(s.interventions)
            } for s in filtered_students
        ]
    })

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    school_id = request.form.get('school_id')
    if not school_id:
        return jsonify({"error": "school_id form field is required"}), 400
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['file']
    filename = file.filename.lower()

    records = []
    try:
        if filename.endswith('.csv'):
            stream = io.StringIO(file.stream.read().decode("utf-8-sig"), newline=None)
            reader = csv.DictReader(stream)
            records = list(reader)
        else:
            return jsonify({"error": "Please upload a CSV file"}), 400
    except Exception as e:
        return jsonify({"error": f"Failed to parse CSV file: {str(e)}"}), 400

    processed = 0
    for row in records:
        clean_row = {k.strip().lower(): str(v).strip() for k, v in row.items() if k}
        
        sid = (clean_row.get('student_id') or clean_row.get('id') or 
               clean_row.get('student id') or clean_row.get('studentnumber') or 
               clean_row.get('student_number') or clean_row.get('studentnumber1'))
        
        sname = (clean_row.get('student_name') or clean_row.get('name') or 
                 clean_row.get('student name') or clean_row.get('studentname') or 
                 clean_row.get('full_name'))
        
        grade = clean_row.get('grade') or clean_row.get('grade level') or ''
        
        absent_val = (clean_row.get('days_absent') or clean_row.get('absences') or 
                      clean_row.get('days absent') or clean_row.get('currentschoolabsences7') or '0')
                      
        unexcused_val = (clean_row.get('unexcused_absences') or clean_row.get('unexcused') or 
                         clean_row.get('unexcused absences') or clean_row.get('unexcusedabsences') or '0')
                         
        total_val = (clean_row.get('total_days') or clean_row.get('membership_days') or 
                     clean_row.get('total days') or clean_row.get('currentschoolmembershipdays11') or '180')

        if not sid or not sname:
            continue

        try:
            days_absent = float(absent_val)
            unexcused = float(unexcused_val)
            total_days = float(total_val)
        except ValueError:
            continue

        rate = ((total_days - days_absent) / total_days * 100) if total_days > 0 else 100.0
        is_chronic = (rate < 90.0) or (days_absent >= 10.0)

        student = Student.query.filter_by(school_id=school_id, student_id=sid).first()
        if not student:
            student = Student(school_id=school_id, student_id=sid)
            db.session.add(student)

        student.student_name = sname
        student.grade = grade
        student.days_absent = days_absent
        student.unexcused_absences = unexcused
        student.total_days = total_days
        student.attendance_rate = rate
        student.is_chronic = is_chronic
        processed += 1

    db.session.commit()
    return jsonify({"message": f"Successfully processed {processed} student records!"})

@app.route('/schools/<int:school_id>/reset-data', methods=['DELETE'])
def reset_school_data(school_id):
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user = User.query.get(session['user_id'])
    if not user or user.role != 'admin':
        return jsonify({"error": "Admin permission required to reset data"}), 403

    students = Student.query.filter_by(school_id=school_id).all()
    for s in students:
        db.session.delete(s)
    db.session.commit()
    return jsonify({"message": "All student and intervention data cleared for this school."})

@app.route('/interventions', methods=['GET', 'POST'])
def handle_interventions():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user = User.query.get(session['user_id'])

    if request.method == 'GET':
        student_db_id = request.args.get('student_db_id', type=int)
        if not student_db_id:
            return jsonify({"error": "student_db_id parameter required"}), 400
        interventions = Intervention.query.filter_by(student_id=student_db_id).order_by(Intervention.id.desc()).all()
        return jsonify({
            "interventions": [
                {
                    "id": i.id,
                    "date": i.date,
                    "type": i.type,
                    "notes": i.notes,
                    "logged_by": i.logged_by_email or "Staff"
                } for i in interventions
            ]
        })

    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form
        student_db_id = data.get('student_db_id')
        date = data.get('date')
        int_type = data.get('type')
        notes = data.get('notes', '')

        if not student_db_id or not date or not int_type:
            return jsonify({"error": "Missing required fields"}), 400

        intervention = Intervention(
            student_id=student_db_id,
            user_id=user.id if user else None,
            date=date,
            type=int_type,
            notes=notes,
            logged_by_email=user.email if user else "System"
        )
        db.session.add(intervention)
        db.session.commit()
        return jsonify({"message": "Intervention saved successfully"})

@app.route('/export/interventions', methods=['GET'])
def export_interventions():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    school_id = request.args.get('school_id', type=int)
    if not school_id:
        return jsonify({"error": "school_id parameter required"}), 400

    students = Student.query.filter_by(school_id=school_id).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Student ID', 'Student Name', 'Grade', 'Total Absences', 'Unexcused Absences', 'Attendance Rate %', 'Action Date', 'Action Type', 'Action Details', 'Logged By'])

    for s in students:
        for i in s.interventions:
            writer.writerow([s.student_id, s.student_name, s.grade, s.days_absent, s.unexcused_absences, f"{s.attendance_rate:.1f}%", i.date, i.type, i.notes, i.logged_by_email])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'interventions_export_school_{school_id}.csv'
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

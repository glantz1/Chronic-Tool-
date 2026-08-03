import os
import re
import io
import secrets
import pandas as pd
from flask import Flask, request, jsonify, render_template, session, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from sqlalchemy import inspect, text

# Security Extensions
from flask_talisman import Talisman
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)

# -------------------------------------------------------------
# APPLICATION SECURITY & SESSION CONFIGURATION
# -------------------------------------------------------------
raw_secret = os.environ.get("SECRET_KEY")
if not raw_secret or raw_secret == "super-secret-key-change-in-prod":
    app.secret_key = secrets.token_hex(32)
else:
    app.secret_key = raw_secret

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,       # Prevent JavaScript reading session cookies
    SESSION_COOKIE_SAMESITE='Lax',      # CSRF mitigation
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production"  # HTTPS only in production
)

# Apply Security Headers
Talisman(app, content_security_policy=None, force_https=os.environ.get("FLASK_ENV") == "production")

# Rate Limiter
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# -------------------------------------------------------------
# DATABASE CONFIGURATION
# -------------------------------------------------------------
db_url = os.environ.get("DATABASE_URL", "sqlite:///attendance.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# -------------------------------------------------------------
# HELPER PARSERS & CALCULATIONS
# -------------------------------------------------------------
def safe_float_convert(val, default=0.0):
    """Safely extracts numbers from strings or returns default if non-numeric."""
    if pd.isnull(val):
        return default
    try:
        str_val = str(val).replace('%', '').replace(',', '').strip()
        return float(str_val)
    except (ValueError, TypeError):
        match = re.search(r"[-+]?\d*\.\d+|\d+", str(val))
        if match:
            try:
                return float(match.group())
            except ValueError:
                pass
        return default

def calculate_chronic_status(student, threshold=90.0):
    """Calculates attendance rate and determines chronic absenteeism status (<90%)."""
    day_rate = (student.days_absent / student.total_days * 100.0) if (student.total_days and student.total_days > 0) else 0.0
    min_rate = (student.minutes_absent / student.total_minutes * 100.0) if (student.total_minutes and student.total_minutes > 0) else 0.0
    
    if student.present_fte3 >= 0.0:
        attendance_rate = student.present_fte3
        absence_rate = 100.0 - attendance_rate
    else:
        absence_rate = max(day_rate, min_rate)
        attendance_rate = 100.0 - absence_rate

    is_chronic_fte3 = (student.present_fte3 >= 0.0 and student.present_fte3 < threshold)
    is_chronic_days = day_rate >= (100.0 - threshold)
    is_chronic_mins = min_rate >= (100.0 - threshold)

    is_chronic = is_chronic_fte3 or is_chronic_days or is_chronic_mins

    reason = "Regular"
    if is_chronic:
        if is_chronic_fte3 or attendance_rate < threshold:
            reason = f"Attendance Rate ({attendance_rate:.1f}%) < {threshold:.0f}%"
        elif is_chronic_days or is_chronic_mins:
            reason = f"Absence Rate ({absence_rate:.1f}%) >= 10%"

    return {
        "attendance_rate": round(attendance_rate, 1),
        "absence_rate": round(absence_rate, 1),
        "is_chronic": is_chronic,
        "chronic_reason": reason
    }

# -------------------------------------------------------------
# DATABASE MODELS
# -------------------------------------------------------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default="staff")
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=True)

    school = db.relationship('School', backref='users', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    grade_levels = db.Column(db.String(100), default="K,1,2,3,4,5,6,7,8,9,10,11,12")

class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    student_id_str = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    grade = db.Column(db.String(20), nullable=False)
    days_absent = db.Column(db.Float, nullable=False, default=0)
    total_days = db.Column(db.Float, nullable=False, default=180)
    minutes_absent = db.Column(db.Float, nullable=False, default=0)
    total_minutes = db.Column(db.Float, nullable=False, default=0)
    present_fte3 = db.Column(db.Float, nullable=False, default=-1.0)

    interventions = db.relationship('Intervention', backref='student', cascade="all, delete-orphan", lazy=True)

class Intervention(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    date = db.Column(db.String(20), nullable=False)
    action_type = db.Column(db.String(50), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    logged_by = db.Column(db.String(120), nullable=True)

# -------------------------------------------------------------
# DB INITIALIZATION & MIGRATIONS
# -------------------------------------------------------------
with app.app_context():
    db.create_all()

    inspector = inspect(db.engine)
    
    if "user" in inspector.get_table_names():
        columns = [col['name'] for col in inspector.get_columns('user')]
        if 'school_id' not in columns:
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE "user" ADD COLUMN school_id INTEGER REFERENCES school(id);'))
                conn.commit()

    if "student" in inspector.get_table_names():
        columns = [col['name'] for col in inspector.get_columns('student')]
        with db.engine.connect() as conn:
            if 'minutes_absent' not in columns:
                conn.execute(text('ALTER TABLE student ADD COLUMN minutes_absent FLOAT DEFAULT 0;'))
            if 'total_minutes' not in columns:
                conn.execute(text('ALTER TABLE student ADD COLUMN total_minutes FLOAT DEFAULT 0;'))
            if 'present_fte3' not in columns:
                conn.execute(text('ALTER TABLE student ADD COLUMN present_fte3 FLOAT DEFAULT -1.0;'))
            conn.commit()

    if not User.query.filter_by(role="admin").first():
        default_school = School.query.first()
        if not default_school:
            default_school = School(name="Main High School", grade_levels="9,10,11,12")
            db.session.add(default_school)
            db.session.commit()

        default_admin = User(email="admin@school.edu", role="admin", school_id=None)
        default_admin.set_password("admin123")
        db.session.add(default_admin)
        db.session.commit()

# -------------------------------------------------------------
# AUTHENTICATION DECORATORS
# -------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Authentication required"}), 401
        user = User.query.get(session["user_id"])
        if not user or user.role != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated_function

# -------------------------------------------------------------
# AUTHENTICATION ROUTES
# -------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login", methods=["POST"])
@limiter.limit("5 per minute")
def login():
    data = request.json or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    user = User.query.filter_by(email=email).first()
    if user and user.check_password(password):
        session.clear()
        session["user_id"] = user.id
        session["email"] = user.email
        session["role"] = user.role
        session["school_id"] = user.school_id
        return jsonify({
            "message": "Logged in successfully", 
            "user": {"email": user.email, "role": user.role, "school_id": user.school_id}
        })
    
    return jsonify({"error": "Invalid email or password"}), 401

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Logged out"})

@app.route("/me", methods=["GET"])
def me():
    if "user_id" in session:
        user = User.query.get(session["user_id"])
        if user:
            return jsonify({
                "logged_in": True, 
                "user": {"email": user.email, "role": user.role, "school_id": user.school_id}
            })
    return jsonify({"logged_in": False})

# -------------------------------------------------------------
# ADMIN MANAGEMENT ROUTES
# -------------------------------------------------------------
@app.route("/admin/users", methods=["GET", "POST"])
@admin_required
def manage_users():
    if request.method == "POST":
        data = request.json or {}
        email = data.get("email", "").strip().lower()
        password = data.get("password")
        role = data.get("role", "staff")
        school_id = data.get("school_id")

        if not email or not password:
            return jsonify({"error": "Email and password are required"}), 400

        if role == "staff" and not school_id:
            return jsonify({"error": "Staff members must be assigned to a specific school."}), 400

        if User.query.filter_by(email=email).first():
            return jsonify({"error": "User with this email already exists"}), 400

        new_user = User(email=email, role=role, school_id=int(school_id) if school_id else None)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        return jsonify({"message": f"User {email} created successfully!"})

    users = User.query.all()
    return jsonify({"users": [
        {"id": u.id, "email": u.email, "role": u.role, "school_name": u.school.name if u.school else "All Schools"} 
        for u in users
    ]})

@app.route("/admin/users/<int:user_id>", methods=["DELETE"])
@admin_required
def delete_user(user_id):
    if session.get("user_id") == user_id:
        return jsonify({"error": "You cannot delete your own account while logged in."}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found."}), 404

    try:
        db.session.delete(user)
        db.session.commit()
        return jsonify({"message": f"User '{user.email}' deleted successfully."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Failed to delete user: {str(e)}"}), 500

@app.route("/admin/schools", methods=["POST"])
@admin_required
def add_school():
    data = request.json or {}
    name = data.get("name", "").strip()
    grades = data.get("grade_levels", "").strip()

    if not grades:
        grades = "K,1,2,3,4,5,6,7,8,9,10,11,12"

    if not name:
        return jsonify({"error": "School name is required"}), 400

    existing_school = School.query.filter_by(name=name).first()
    if existing_school:
        existing_school.grade_levels = grades
        db.session.commit()
        return jsonify({"message": f"Updated school '{name}' with grade levels: {grades}"})

    new_school = School(name=name, grade_levels=grades)
    db.session.add(new_school)
    db.session.commit()
    return jsonify({"message": f"School '{name}' added successfully!"})

# -------------------------------------------------------------
# FILE UPLOAD ROUTE
# -------------------------------------------------------------
@app.route("/upload", methods=["POST"])
@login_required
def upload_file():
    user = User.query.get(session["user_id"])
    school_id = request.form.get("school_id")
    file = request.files.get("file")

    if user.role != "admin" and str(user.school_id) != str(school_id):
        return jsonify({"error": "Unauthorized: You do not have permissions to upload to this school."}), 403

    if not school_id or not file:
        return jsonify({"error": "School selection and file are required."}), 400

    school = School.query.get(school_id)
    if not school:
        return jsonify({"error": "Invalid School ID selected."}), 400

    try:
        filename = file.filename.lower()
        if filename.endswith(".csv"):
            df = pd.read_csv(file)
        elif filename.endswith((".xls", ".xlsx")):
            all_sheets = pd.read_excel(file, sheet_name=None)
            df = pd.concat(all_sheets.values(), ignore_index=True) if hasattr(pd, "concat") else pd.read_excel(file)
        else:
            return jsonify({"error": "Unsupported file format. Please upload a .csv or .xlsx file."}), 400

        fte3_col = next(
            (c for c in df.columns if str(c).strip().replace(" ", "").replace("_", "") == "PresentFTE3"), 
            None
        )
        if not fte3_col and len(df.columns) > 21:
            fte3_col = df.columns[21]

        columns_lower = [str(c).strip().lower().replace(" ", "_").replace("-", "_") for c in df.columns]

        id_col = next((df.columns[i] for i, c in enumerate(columns_lower) if "studentnu" in c or "student_id" in c or c == "id"), None)
        name_col = next((df.columns[i] for i, c in enumerate(columns_lower) if "studentna" in c or "student_name" in c or c == "name"), None)
        absent_col = next((df.columns[i] for i, c in enumerate(columns_lower) if "totalabse" in c or "days_absent" in c or "absent" in c), None)
        grade_col = next((df.columns[i] for i, c in enumerate(columns_lower) if "grade" in c), None)
        total_col = next((df.columns[i] for i, c in enumerate(columns_lower) if ("total_mem" in c or "membership" in c or "total_days" in c or "enrolled" in c) and "year" not in c and "date" not in c and "min" not in c), None)

        if not id_col or not name_col:
            return jsonify({"error": "Missing required Student ID or Name columns."}), 400

        df = df.dropna(subset=[id_col, name_col])

        Student.query.filter_by(school_id=school_id).delete()

        records = []
        for _, row in df.iterrows():
            id_str = str(row[id_col]).split('.')[0].strip()
            name_str = str(row[name_col]).strip()

            if not id_str or id_str.lower() == 'nan' or not name_str or name_str.lower() == 'nan':
                continue

            absent_val = safe_float_convert(row[absent_col] if absent_col else None, default=0.0)
            total_val = safe_float_convert(row[total_col] if total_col else None, default=180.0)
            if total_val > 300 or total_val <= 0:
                total_val = 180.0

            raw_fte3 = row[fte3_col] if fte3_col and fte3_col in row else None
            fte3_val = safe_float_convert(raw_fte3, default=-1.0)

            if 0.0 < fte3_val <= 1.0:
                fte3_val = fte3_val * 100.0

            if fte3_val >= 0.0 and absent_val == 0.0 and total_val > 0:
                absent_val = total_val * ((100.0 - fte3_val) / 100.0)

            grade_val = str(row[grade_col]).strip() if grade_col and pd.notnull(row[grade_col]) else "N/A"

            student = Student(
                school_id=school.id,
                student_id_str=id_str,
                name=name_str,
                grade=grade_val,
                days_absent=absent_val,
                total_days=total_val,
                present_fte3=fte3_val
            )
            records.append(student)

        db.session.bulk_save_objects(records)
        db.session.commit()

        return jsonify({
            "message": f"Successfully processed {len(records)} student records for {school.name}."
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"File parsing failed: {str(e)}"}), 500

# -------------------------------------------------------------
# STUDENT RETRIEVAL & INTERVENTIONS
# -------------------------------------------------------------
@app.route("/schools", methods=["GET"])
@login_required
def get_schools():
    user = User.query.get(session["user_id"])
    if user.role != "admin" and user.school_id:
        schools = School.query.filter_by(id=user.school_id).all()
    else:
        schools = School.query.all()
    return jsonify({"schools": [{"id": s.id, "name": s.name, "grade_levels": [g.strip() for g in s.grade_levels.split(",") if g.strip()]} for s in schools]})

@app.route("/students", methods=["GET"])
@login_required
def get_students():
    user = User.query.get(session["user_id"])
    school_id = request.args.get("school_id")

    if user.role != "admin" and str(user.school_id) != str(school_id):
        return jsonify({"error": "Access denied"}), 403

    if not school_id:
        return jsonify({"students": [], "total_students": 0, "chronic_count": 0})

    grade = request.args.get("grade")
    chronic_only = request.args.get("chronic") == "true"
    search = request.args.get("search", "").strip().lower()

    query = Student.query.filter_by(school_id=school_id)
    if grade:
        query = query.filter_by(grade=grade)

    students = query.all()
    filtered = []

    for s in students:
        status_info = calculate_chronic_status(s)

        if chronic_only and not status_info["is_chronic"]:
            continue

        if search and (search not in s.name.lower() and search not in s.student_id_str.lower()):
            continue

        filtered.append({
            "db_id": s.id,
            "student_id": s.student_id_str,
            "student_name": s.name,
            "grade": s.grade,
            "days_absent": round(s.days_absent, 2),
            "total_days": s.total_days,
            "absence_rate_pct": status_info["absence_rate"],
            "attendance_rate_pct": status_info["attendance_rate"],
            "is_chronic": status_info["is_chronic"],
            "chronic_reason": status_info["chronic_reason"],
            "interventions_count": len(s.interventions)
        })

    school = School.query.get(school_id)
    available_grades = [g.strip() for g in school.grade_levels.split(",") if g.strip()] if school else []

    return jsonify({
        "students": filtered,
        "total_students": len(filtered),
        "chronic_count": sum(1 for s in filtered if s["is_chronic"]),
        "available_grades": available_grades
    })

@app.route("/interventions", methods=["GET", "POST"])
@login_required
def handle_interventions():
    if request.method == "POST":
        data = request.json or {}
        student_db_id = data.get("student_db_id")
        date = data.get("date")
        action_type = data.get("type")
        notes = data.get("notes")

        if not student_db_id or not action_type:
            return jsonify({"error": "Missing parameters"}), 400

        intervention = Intervention(
            student_id=student_db_id,
            date=date,
            action_type=action_type,
            notes=notes,
            logged_by=session.get("email")
        )
        db.session.add(intervention)
        db.session.commit()
        return jsonify({"message": "Intervention saved successfully"})

    student_db_id = request.args.get("student_db_id")
    interventions = Intervention.query.filter_by(student_id=student_db_id).order_by(Intervention.id.desc()).all()
    return jsonify({
        "interventions": [{
            "id": i.id,
            "date": i.date,
            "type": i.action_type,
            "notes": i.notes,
            "logged_by": i.logged_by
        } for i in interventions]
    })

# -------------------------------------------------------------
# INTERVENTION EXPORT ROUTE (EXCEL / CSV)
# -------------------------------------------------------------
@app.route("/export/interventions", methods=["GET"])
@login_required
def export_interventions():
    user = User.query.get(session["user_id"])
    school_id = request.args.get("school_id")

    if user.role != "admin" and str(user.school_id) != str(school_id):
        return jsonify({"error": "Unauthorized access to this school's records."}), 403

    if not school_id:
        return jsonify({"error": "School ID is required."}), 400

    students = Student.query.filter_by(school_id=school_id).all()
    
    export_data = []
    for student in students:
        for intervention in student.interventions:
            export_data.append({
                "Student ID": student.student_id_str,
                "Student Name": student.name,
                "Grade": student.grade,
                "Intervention Date": intervention.date,
                "Action Type": intervention.action_type,
                "Notes": intervention.notes or "",
                "Logged By": intervention.logged_by or "System"
            })

    if not export_data:
        return jsonify({"error": "No intervention logs found for this school."}), 404

    df = pd.DataFrame(export_data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Intervention Logs')
    output.seek(0)

    school = School.query.get(school_id)
    school_name_clean = school.name.replace(" ", "_") if school else f"School_{school_id}"

    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"Intervention_Logs_{school_name_clean}.xlsx"
    )

# -------------------------------------------------------------
# APPLICATION ENTRYPOINT
# -------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True, port=5000)

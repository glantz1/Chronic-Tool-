import os
import pandas as pd
from flask import Flask, request, jsonify, render_template, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from sqlalchemy import inspect, text

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "super-secret-key-change-in-prod")

# Database setup (PostgreSQL on Render, fallback to local SQLite)
db_url = os.environ.get("DATABASE_URL", "sqlite:///attendance.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# -------------------------------------------------------------
# DATABASE MODELS
# -------------------------------------------------------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default="staff")  # "admin" or "staff"
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=True)  # Null for Global Admins

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

    interventions = db.relationship('Intervention', backref='student', cascade="all, delete-orphan", lazy=True)

class Intervention(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    date = db.Column(db.String(20), nullable=False)
    action_type = db.Column(db.String(50), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    logged_by = db.Column(db.String(120), nullable=True)

# -------------------------------------------------------------
# DB INITIALIZATION & SAFE MIGRATION
# -------------------------------------------------------------
with app.app_context():
    db.create_all()

    # Safely migrate existing tables if school_id column is missing
    inspector = inspect(db.engine)
    if "user" in inspector.get_table_names():
        columns = [col['name'] for col in inspector.get_columns('user')]
        if 'school_id' not in columns:
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE "user" ADD COLUMN school_id INTEGER REFERENCES school(id);'))
                conn.commit()

    # Seed initial data if empty
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
# HELPER DECORATORS
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
def login():
    data = request.json or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    user = User.query.filter_by(email=email).first()
    if user and user.check_password(password):
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
# ADMIN ROUTES
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
    grades = data.get("grade_levels", "K,1,2,3,4,5,6,7,8,9,10,11,12").strip()

    if not name:
        return jsonify({"error": "School name is required"}), 400

    if School.query.filter_by(name=name).first():
        return jsonify({"error": "School already exists"}), 400

    new_school = School(name=name, grade_levels=grades)
    db.session.add(new_school)
    db.session.commit()
    return jsonify({"message": "School added successfully"})

# -------------------------------------------------------------
# FILE UPLOAD ROUTE (Enhanced Column Matching)
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
            df = pd.read_excel(file)
        else:
            return jsonify({"error": "Unsupported file format. Please upload a .csv or .xlsx file."}), 400

        # Clean and normalize column headers (lowercase, remove spaces/hyphens)
        df.columns = [str(c).strip().lower().replace(" ", "_").replace("-", "_") for c in df.columns]

        # Flexible & truncated matching for required columns
        id_col = next((c for c in df.columns if "studentnu" in c or "student_id" in c or c == "id" or "id" in c), None)
        name_col = next((c for c in df.columns if "studentna" in c or "student_name" in c or c == "name" or "name" in c), None)
        absent_col = next((c for c in df.columns if "totalabse" in c or "unexcuse" in c or "absent" in c or "absence" in c or "days_absent" in c), None)

        # Flexible & truncated matching for optional columns
        grade_col = next((c for c in df.columns if "grade" in c or "level" in c), None)
        total_col = next((c for c in df.columns if "totalmem" in c or "totalminp" in c or "total" in c or "enrolled" in c or "total_days" in c), None)

        missing_cols = []
        if not id_col:
            missing_cols.append("ID (e.g., StudentNu, ID)")
        if not name_col:
            missing_cols.append("Name (e.g., StudentNa, Name)")
        if not absent_col:
            missing_cols.append("Absences (e.g., TotalAbse, Absences)")

        if missing_cols:
            return jsonify({
                "error": f"Missing required column(s): {', '.join(missing_cols)}."
            }), 400

        # Refresh dataset for the designated school
        Student.query.filter_by(school_id=school_id).delete()

        records = []
        for _, row in df.iterrows():
            absent_val = float(row[absent_col]) if pd.notnull(row[absent_col]) else 0.0
            total_val = float(row[total_col]) if total_col and pd.notnull(row[total_col]) else 180.0
            grade_val = str(row[grade_col]).strip() if grade_col and pd.notnull(row[grade_col]) else "N/A"

            student = Student(
                school_id=school.id,
                student_id_str=str(row[id_col]).strip(),
                name=str(row[name_col]).strip(),
                grade=grade_val,
                days_absent=absent_val,
                total_days=total_val if total_val > 0 else 180.0
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
# RESTRICTED DATA ROUTES
# -------------------------------------------------------------
@app.route("/schools", methods=["GET"])
@login_required
def get_schools():
    user = User.query.get(session["user_id"])
    
    if user.role != "admin" and user.school_id:
        schools = School.query.filter_by(id=user.school_id).all()
    else:
        schools = School.query.all()
        
    return jsonify({"schools": [{"id": s.id, "name": s.name, "grade_levels": s.grade_levels.split(",")} for s in schools]})

@app.route("/students", methods=["GET"])
@login_required
def get_students():
    user = User.query.get(session["user_id"])
    school_id = request.args.get("school_id")

    if user.role != "admin" and str(user.school_id) != str(school_id):
        return jsonify({"error": "Access denied to this school's data"}), 403

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
        rate = (s.days_absent / s.total_days) * 100 if s.total_days > 0 else 0
        is_chronic = rate >= 10.0

        if chronic_only and not is_chronic:
            continue

        if search and (search not in s.name.lower() and search not in s.student_id_str.lower()):
            continue

        filtered.append({
            "db_id": s.id,
            "student_id": s.student_id_str,
            "student_name": s.name,
            "grade": s.grade,
            "days_absent": s.days_absent,
            "total_days": s.total_days,
            "absence_rate_pct": round(rate, 1),
            "is_chronic": is_chronic,
            "interventions_count": len(s.interventions)
        })

    school = School.query.get(school_id)
    available_grades = school.grade_levels.split(",") if school else []

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

if __name__ == "__main__":
    app.run(debug=True)

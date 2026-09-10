import csv
import io
import math
from functools import wraps
from flask import (
    Flask,
    render_template_string,
    request,
    redirect,
    url_for,
    flash,
    session,
    jsonify,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

# ----------------------------------------------------------------------
# Application Setup & Configurations
# ----------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = "super-secret-key-change-in-production"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///attendance_tracker.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

INDEX_HTML = "<h1>Student Attendance System</h1>"  # Replace with actual HTML template


# ----------------------------------------------------------------------
# Database Models
# ----------------------------------------------------------------------
class School(db.Model):
    __tablename__ = "schools"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)

    users = db.relationship("User", backref="school", lazy=True)
    students = db.relationship("StudentRecord", backref="school", lazy=True)


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default="User")  # Admin or User
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class StudentRecord(db.Model):
    __tablename__ = "student_records"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    grade = db.Column(db.String(20), default="N/A")
    absences = db.Column(db.Float, default=0.0)
    unexcused_absences = db.Column(db.Integer, default=0)
    tardies = db.Column(db.Integer, default=0)
    total_days = db.Column(db.Float, default=180.0)
    present_fte = db.Column(db.Float, nullable=True)

    interventions = db.relationship(
        "Intervention", backref="student_record", lazy=True
    )


class Intervention(db.Model):
    __tablename__ = "interventions"
    id = db.Column(db.Integer, primary_key=True)
    student_record_id = db.Column(
        db.Integer, db.ForeignKey("student_records.id"), nullable=False
    )
    action_type = db.Column(db.String(100), default="General Support")
    notes = db.Column(db.Text, nullable=False)
    logged_by = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)


# ----------------------------------------------------------------------
# Access Control Decorators
# ----------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access this page.", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            flash("Please log in first.", "error")
            return redirect(url_for("index"))
        user = db.session.get(User, user_id)
        if not user or user.role.lower() != "admin":
            flash("Administrator rights required.", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)

    return decorated_function


# ----------------------------------------------------------------------
# Core Routes
# ----------------------------------------------------------------------
@app.route("/")
@login_required
def index():
    user = db.session.get(User, session["user_id"])

    # Extract filter parameters
    selected_school_id = request.args.get("school_id", "all")
    selected_grade = request.args.get("grade", "all")
    selected_filter = request.args.get("filter", "all")
    search_query = request.args.get("search", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 25

    query = StudentRecord.query

    # Apply authorization and filters to query
    if user.role.lower() != "admin":
        query = query.filter_by(school_id=user.school_id)
    elif selected_school_id != "all":
        query = query.filter_by(school_id=int(selected_school_id))

    if selected_grade != "all":
        query = query.filter_by(grade=selected_grade)

    if search_query:
        query = query.filter(StudentRecord.name.ilike(f"%{search_query}%"))

    # 5. Calculate Metrics on Filtered Query safely
    total_students = query.count()
    at_risk_count = query.filter(
        StudentRecord.present_fte.isnot(None), StudentRecord.present_fte <= 90.0
    ).count()
    chronic_rate = (
        (at_risk_count / total_students * 100) if total_students > 0 else 0.0
    )
    total_pages = math.ceil(total_students / per_page) if total_students > 0 else 1
    students = query.offset((page - 1) * per_page).limit(per_page).all()

    schools = School.query.all()
    all_users = User.query.all() if user.role == "Admin" else []
    available_grades = [
        g[0] for g in db.session.query(StudentRecord.grade).distinct().all() if g[0]
    ]

    active_school_name = "All Schools"
    if user.role != "Admin" and user.school:
        active_school_name = user.school.name
    elif selected_school_id != "all":
        sch = db.session.get(School, int(selected_school_id))
        if sch:
            active_school_name = sch.name

    return render_template_string(
        INDEX_HTML,
        current_user=user,
        students=students,
        schools=schools,
        all_users=all_users,
        available_grades=sorted(available_grades),
        total_students=total_students,
        at_risk_count=at_risk_count,
        chronic_rate=chronic_rate,
        active_school_name=active_school_name,
        selected_school_id=selected_school_id,
        selected_grade=selected_grade,
        selected_filter=selected_filter,
        search_query=search_query,
        current_page=page,
        total_pages=total_pages,
        display_count=len(students),
        str=str,
    )


@app.route("/log_intervention/<int:student_id>", methods=["POST"])
@login_required
def log_intervention(student_id):
    # Support both form data and JSON requests
    data = request.get_json(silent=True) or request.form

    user_id = session.get("user_id")
    user = db.session.get(User, user_id)
    student = db.session.get(StudentRecord, student_id)

    if not student:
        if request.is_json:
            return jsonify({"error": "Student record not found."}), 404
        flash("Student record not found.", "error")
        return redirect(url_for("index"))

    if (
        user.role.lower() != "admin"
        and student.school_id != user.school_id
    ):
        if request.is_json:
            return jsonify({"error": "Permission denied."}), 403
        flash("Permission denied.", "error")
        return redirect(url_for("index"))

    # Retrieve parameters
    action_type = (
        data.get("action_type") or data.get("type") or "General Support"
    )
    notes = (data.get("notes") or "").strip()

    if not notes:
        if request.is_json:
            return jsonify({"error": "Intervention notes cannot be empty."}), 400
        flash("Intervention notes cannot be empty.", "error")
        return redirect(url_for("index"))

    # Determine logged_by string/username depending on model column type
    logged_by_value = (
        getattr(user, "username", None)
        or getattr(user, "email", None)
        or str(user_id)
    )

    # Create intervention with logged_by / logged_by_id set
    intervention = Intervention(
        student_record_id=student.id,
        action_type=action_type,
        notes=notes,
        logged_by=logged_by_value,
    )

    # Attach optional user relationships if present
    if hasattr(Intervention, "logged_by_user_id"):
        intervention.logged_by_user_id = user_id
    elif hasattr(Intervention, "user_id"):
        intervention.user_id = user_id

    db.session.add(intervention)
    db.session.commit()

    if request.is_json:
        return (
            jsonify(
                {
                    "message": f"Intervention logged for {student.name}.",
                    "id": intervention.id,
                }
            ),
            200,
        )

    flash(f"Intervention logged successfully for {student.name}.", "success")
    return redirect(url_for("index"))


@app.route("/add_school", methods=["POST"])
@admin_required
def add_school():
    school_name = request.form.get("school_name", "").strip()
    if not school_name:
        flash("School name is required.", "error")
        return redirect(url_for("index"))

    existing = School.query.filter_by(name=school_name).first()
    if existing:
        flash(f"School '{school_name}' already exists.", "error")
        return redirect(url_for("index"))

    school = School(name=school_name)
    db.session.add(school)
    db.session.commit()

    flash(f"School '{school_name}' created successfully.", "success")
    return redirect(url_for("index"))


@app.route("/add_user", methods=["POST"])
@admin_required
def add_user():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    role = request.form.get("role", "User")
    school_id = request.form.get("school_id")

    if not username or not password:
        flash("Username and password are required.", "error")
        return redirect(url_for("index"))

    if User.query.filter_by(username=username).first():
        flash("Username already exists.", "error")
        return redirect(url_for("index"))

    user = User(
        username=username,
        role=role,
        school_id=int(school_id) if school_id else None,
    )
    user.set_password(password)

    db.session.add(user)
    db.session.commit()

    flash(f"User '{username}' created successfully.", "success")
    return redirect(url_for("index"))


@app.route("/delete_user/<int:user_id>", methods=["POST"])
@admin_required
def delete_user(user_id):
    if user_id == session.get("user_id"):
        flash("You cannot delete your own active account.", "error")
        return redirect(url_for("index"))

    user = db.session.get(User, user_id)
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("index"))

    db.session.delete(user)
    db.session.commit()

    flash(f"User '{user.username}' deleted.", "success")
    return redirect(url_for("index"))


@app.route("/upload_csv", methods=["POST"])
@login_required
def upload_csv():
    user = db.session.get(User, session["user_id"])

    if user.role == "Admin":
        school_id = request.form.get("school_id")
        if not school_id:
            flash("Please select a target school for the CSV upload.", "error")
            return redirect(url_for("index"))
        school_id = int(school_id)
    else:
        school_id = user.school_id
        if not school_id:
            flash("Your account is not associated with a school.", "error")
            return redirect(url_for("index"))

    file = request.files.get("file")
    if not file or not file.filename.lower().endswith(".csv"):
        flash("Please upload a valid CSV file.", "error")
        return redirect(url_for("index"))

    try:
        content = file.stream.read().decode("utf-8-sig")
        stream = io.StringIO(content, newline=None)
        reader = csv.DictReader(stream)

        imported_count = 0
        skipped_count = 0

        # Safe parsing helpers
        def safe_float(val, default=0.0):
            if val is None:
                return default
            val_str = str(val).replace("%", "").strip()
            if not val_str:
                return default
            try:
                return float(val_str)
            except ValueError:
                return default

        def safe_int(val, default=0):
            if val is None:
                return default
            val_str = str(val).strip()
            if not val_str:
                return default
            try:
                return int(float(val_str))
            except ValueError:
                return default

        for row in reader:
            clean_row = {
                (str(k).strip().lower() if k else ""): (
                    str(v).strip() if v is not None else ""
                )
                for k, v in row.items()
            }

            student_id = (
                clean_row.get("studentnumber")
                or clean_row.get("student_number")
                or clean_row.get("studentnumber1")
                or clean_row.get("student_id")
                or clean_row.get("id")
            )

            name = (
                clean_row.get("studentname")
                or clean_row.get("student_name")
                or clean_row.get("name")
                or clean_row.get("full_name")
            )

            if not name:
                first = (
                    clean_row.get("first_name")
                    or clean_row.get("firstname")
                    or ""
                )
                last = (
                    clean_row.get("last_name")
                    or clean_row.get("lastname")
                    or ""
                )
                if first or last:
                    name = f"{first} {last}".strip()

            if not student_id or not name:
                skipped_count += 1
                continue

            grade = (
                clean_row.get("grade")
                or clean_row.get("grade_level")
                or "N/A"
            )

            absences = safe_float(
                clean_row.get("currentschoolabsences7")
                or clean_row.get("absences")
            )
            unexcused = safe_int(
                clean_row.get("unexcusedabsences")
                or clean_row.get("unexcused_absences")
            )
            tardies = safe_int(clean_row.get("tardies"))
            total_days = safe_float(
                clean_row.get("currentschoolmembershipdays11")
                or clean_row.get("total_days"),
                180.0,
            )

            present_fte_val = (
                clean_row.get("presentfte3")
                or clean_row.get("present_fte")
                or clean_row.get("presentfte_dist3")
            )
            if present_fte_val:
                present_fte = safe_float(present_fte_val)
            else:
                present_fte = (
                    max(
                        0.0,
                        min(
                            100.0,
                            ((total_days - absences) / total_days) * 100,
                        ),
                    )
                    if total_days > 0
                    else 0.0
                )

            record = StudentRecord.query.filter_by(
                student_id=str(student_id), school_id=school_id
            ).first()
            if not record:
                record = StudentRecord(
                    student_id=str(student_id), school_id=school_id
                )
                db.session.add(record)

            record.name = name
            record.grade = str(grade)
            record.absences = absences
            record.unexcused_absences = unexcused
            record.tardies = tardies
            record.total_days = total_days
            record.present_fte = present_fte

            imported_count += 1

        db.session.commit()

        if imported_count == 0:
            flash(
                "No valid records could be processed from the uploaded file.",
                "error",
            )
        else:
            msg = f"Successfully processed {imported_count} student records."
            if skipped_count > 0:
                msg += f" ({skipped_count} skipped)"
            flash(msg, "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Error parsing CSV file: {str(e)}", "error")

    return redirect(url_for("index"))


# ----------------------------------------------------------------------
# Application Initialization
# ----------------------------------------------------------------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username="admin").first():
            default_admin = User(username="admin", role="Admin")
            default_admin.set_password("admin123")
            db.session.add(default_admin)
            db.session.commit()
            print("Default admin created (Username: admin, Password: admin123)")

    app.run(debug=True)
    

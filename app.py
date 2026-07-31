import os
import io
import math
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_file
import pandas as pd
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# --------------------------------------------------------------------
# DATABASE CONFIGURATION
# --------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'attendance.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --------------------------------------------------------------------
# DATABASE MODELS
# --------------------------------------------------------------------
class Student(db.Model):
    __tablename__ = 'students'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id_str = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    grade = db.Column(db.String(20), nullable=True)
    school_name = db.Column(db.String(100), nullable=True)
    
    # Core Metrics
    days_absent = db.Column(db.Float, default=0.0)
    total_days = db.Column(db.Float, default=0.0)
    minutes_absent = db.Column(db.Float, default=0.0)
    total_minutes = db.Column(db.Float, default=0.0)
    present_fte3 = db.Column(db.Float, default=-1.0)  # Stores PresentFTE3 % directly from Column V

    # Metadata
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    interventions = db.relationship('Intervention', backref='student', lazy=True, cascade="all, delete-orphan")
    records = db.relationship('AttendanceRecord', backref='student', lazy=True, cascade="all, delete-orphan")


class Intervention(db.Model):
    __tablename__ = 'interventions'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    date = db.Column(db.String(20), nullable=False)
    type = db.Column(db.String(100), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    staff_member = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AttendanceRecord(db.Model):
    __tablename__ = 'attendance_records'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    date = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), nullable=False)  # Absent, Present, Tardy
    reason = db.Column(db.String(100), nullable=True)


class SchoolConfig(db.Model):
    __tablename__ = 'school_config'
    
    id = db.Column(db.Integer, primary_key=True)
    academic_year = db.Column(db.String(20), default="2025-2026")
    chronic_threshold_pct = db.Column(db.Float, default=90.0)  # Standard < 90%

# Initialize database tables
with app.app_context():
    db.create_all()
    if not SchoolConfig.query.first():
        db.session.add(SchoolConfig())
        db.session.commit()

# --------------------------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------------------------
def safe_float_convert(val, default=0.0):
    """Safely converts string/numeric inputs to float."""
    if val is None or pd.isna(val):
        return default
    try:
        str_val = str(val).replace('%', '').replace(',', '').strip()
        return float(str_val)
    except (ValueError, TypeError):
        return default

def calculate_chronic_status(student, threshold=90.0):
    """Calculates attendance rate and determines if student is chronically absent."""
    day_rate = (student.days_absent / student.total_days * 100.0) if (student.total_days and student.total_days > 0) else 0.0
    min_rate = (student.minutes_absent / student.total_minutes * 100.0) if (student.total_minutes and student.total_minutes > 0) else 0.0
    
    # Priority check: PresentFTE3 from Column V
    if student.present_fte3 >= 0.0:
        attendance_rate = student.present_fte3
        absence_rate = 100.0 - attendance_rate
    else:
        absence_rate = max(day_rate, min_rate)
        attendance_rate = 100.0 - absence_rate

    # Chronic threshold: Attendance < 90.0% (or Absence >= 10.0%)
    is_chronic = attendance_rate < threshold or day_rate >= (100.0 - threshold) or min_rate >= (100.0 - threshold)

    reason = "N/A"
    if is_chronic:
        if student.present_fte3 >= 0.0 and student.present_fte3 < threshold:
            reason = f"PresentFTE3 ({student.present_fte3:.1f}%) < {threshold}%"
        elif day_rate >= (100.0 - threshold):
            reason = f"Days Absence Rate ({day_rate:.1f}%) >= 10%"
        elif min_rate >= (100.0 - threshold):
            reason = f"Minutes Absence Rate ({min_rate:.1f}%) >= 10%"

    return {
        "attendance_rate": round(attendance_rate, 1),
        "absence_rate": round(absence_rate, 1),
        "is_chronic": is_chronic,
        "chronic_reason": reason
    }

# --------------------------------------------------------------------
# ROUTES & ENDPOINTS
# --------------------------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    try:
        # Load Dataframe
        if file.filename.endswith('.csv'):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)

        # 1. Target PresentFTE3 Specifically (or Column V at Index 21 as Fallback)
        fte3_col = next(
            (c for c in df.columns if str(c).strip().replace(" ", "").replace("_", "") == "PresentFTE3"), 
            None
        )
        if not fte3_col and len(df.columns) > 21:
            fte3_col = df.columns[21]  # Column V

        # 2. Flexible column matching for core demographic and attendance metrics
        columns_lower = {str(c).strip().lower().replace(" ", "_").replace("-", "_"): c for c in df.columns}

        id_col = next((df.columns[i] for i, c in enumerate(columns_lower.keys()) if "studentnu" in c or "student_id" in c or c == "id"), None)
        name_col = next((df.columns[i] for i, c in enumerate(columns_lower.keys()) if "studentna" in c or "student_name" in c or c == "name"), None)
        absent_col = next((df.columns[i] for i, c in enumerate(columns_lower.keys()) if "totalabse" in c or "days_absent" in c or "absent" in c), None)
        grade_col = next((df.columns[i] for i, c in enumerate(columns_lower.keys()) if "grade" in c), None)
        total_col = next((df.columns[i] for i, c in enumerate(columns_lower.keys()) if ("total_mem" in c or "membership" in c or "total_days" in c or "enrolled" in c) and "year" not in c and "date" not in c), None)

        records_processed = 0

        for idx, row in df.iterrows():
            # Extract Student ID, Name, Grade
            raw_id = str(row[id_col]).split('.')[0].strip() if id_col and pd.notna(row[id_col]) else f"TEMP_{idx}"
            raw_name = str(row[name_col]).strip() if name_col and pd.notna(row[name_col]) else f"Student {raw_id}"
            raw_grade = str(row[grade_col]).strip() if grade_col and pd.notna(row[grade_col]) else "N/A"

            # Parse Numerics
            absent_val = safe_float_convert(row[absent_col] if absent_col else None, default=0.0)
            total_val = safe_float_convert(row[total_col] if total_col else None, default=180.0)

            # Read PresentFTE3 (Column V)
            raw_fte3 = row[fte3_col] if fte3_col and fte3_col in row else None
            fte3_val = safe_float_convert(raw_fte3, default=-1.0)

            # Standardize decimal percentages (e.g., 0.885 -> 88.5%)
            if 0.0 < fte3_val <= 1.0:
                fte3_val = fte3_val * 100.0

            # Derive absent days if missing based on PresentFTE3
            if fte3_val >= 0.0 and absent_val == 0.0 and total_val > 0:
                absent_val = total_val * ((100.0 - fte3_val) / 100.0)

            # Database Upsert
            student = Student.query.filter_by(student_id_str=raw_id).first()
            if not student:
                student = Student(
                    student_id_str=raw_id,
                    name=raw_name,
                    grade=raw_grade,
                    days_absent=absent_val,
                    total_days=total_val,
                    present_fte3=fte3_val
                )
                db.session.add(student)
            else:
                student.name = raw_name
                student.grade = raw_grade
                student.days_absent = absent_val
                student.total_days = total_val
                student.present_fte3 = fte3_val

            records_processed += 1

        db.session.commit()
        return jsonify({"message": f"Successfully processed {records_processed} student records."}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route('/students', methods=['GET'])
def get_students():
    chronic_only = request.args.get('chronic_only', 'false').lower() == 'true'
    search = request.args.get('search', '').lower().strip()
    grade_filter = request.args.get('grade', '').strip()

    students = Student.query.all()
    filtered = []

    for s in students:
        status_info = calculate_chronic_status(s)

        if chronic_only and not status_info["is_chronic"]:
            continue

        if grade_filter and s.grade != grade_filter:
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
            "present_fte3": round(s.present_fte3, 2) if s.present_fte3 >= 0.0 else None,
            "absence_rate_pct": status_info["absence_rate"],
            "attendance_rate_pct": status_info["attendance_rate"],
            "is_chronic": status_info["is_chronic"],
            "chronic_reason": status_info["chronic_reason"],
            "interventions_count": len(s.interventions)
        })

    return jsonify({"students": filtered, "total_count": len(filtered)}), 200


@app.route('/students/<int:student_id>', methods=['GET'])
def get_student_detail(student_id):
    student = Student.query.get_or_404(student_id)
    status_info = calculate_chronic_status(student)

    interventions = [{
        "id": i.id,
        "date": i.date,
        "type": i.type,
        "notes": i.notes,
        "staff_member": i.staff_member
    } for i in student.interventions]

    return jsonify({
        "db_id": student.id,
        "student_id": student.student_id_str,
        "name": student.name,
        "grade": student.grade,
        "days_absent": round(student.days_absent, 2),
        "total_days": student.total_days,
        "present_fte3": round(student.present_fte3, 2) if student.present_fte3 >= 0.0 else None,
        "attendance_rate_pct": status_info["attendance_rate"],
        "is_chronic": status_info["is_chronic"],
        "chronic_reason": status_info["chronic_reason"],
        "interventions": interventions
    }), 200


@app.route('/interventions', methods=['POST'])
def add_intervention():
    data = request.json or {}
    student_db_id = data.get('student_db_id')
    date_str = data.get('date', datetime.utcnow().strftime('%Y-%m-%d'))
    int_type = data.get('type')
    notes = data.get('notes', '')
    staff = data.get('staff_member', 'System')

    if not student_db_id or not int_type:
        return jsonify({"error": "Missing student ID or intervention type"}), 400

    student = Student.query.get(student_db_id)
    if not student:
        return jsonify({"error": "Student not found"}), 404

    intervention = Intervention(
        student_id=student.id,
        date=date_str,
        type=int_type,
        notes=notes,
        staff_member=staff
    )
    db.session.add(intervention)
    db.session.commit()

    return jsonify({"message": "Intervention recorded successfully"}), 201


@app.route('/stats', methods=['GET'])
def get_dashboard_stats():
    students = Student.query.all()
    total_students = len(students)
    if total_students == 0:
        return jsonify({
            "total_students": 0,
            "chronic_count": 0,
            "chronic_percentage": 0.0,
            "avg_attendance_rate": 0.0
        }), 200

    chronic_count = 0
    total_att_rate = 0.0

    for s in students:
        status_info = calculate_chronic_status(s)
        if status_info["is_chronic"]:
            chronic_count += 1
        total_att_rate += status_info["attendance_rate"]

    return jsonify({
        "total_students": total_students,
        "chronic_count": chronic_count,
        "chronic_percentage": round((chronic_count / total_students) * 100.0, 1),
        "avg_attendance_rate": round(total_att_rate / total_students, 1)
    }), 200


@app.route('/export', methods=['GET'])
def export_chronic_csv():
    students = Student.query.all()
    export_data = []

    for s in students:
        status_info = calculate_chronic_status(s)
        if status_info["is_chronic"]:
            export_data.append({
                "Student ID": s.student_id_str,
                "Name": s.name,
                "Grade": s.grade,
                "PresentFTE3 (%)": s.present_fte3 if s.present_fte3 >= 0.0 else "N/A",
                "Days Absent": s.days_absent,
                "Total Days": s.total_days,
                "Attendance Rate (%)": status_info["attendance_rate"],
                "Chronic Reason": status_info["chronic_reason"],
                "Interventions Count": len(s.interventions)
            })

    df_export = pd.DataFrame(export_data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_export.to_excel(writer, sheet_name='Chronic Absenteeism', index=False)
    
    output.seek(0)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        download_name='chronic_absenteeism_report.xlsx',
        as_attachment=True
    )

# --------------------------------------------------------------------
# APPLICATION ENTRYPOINT
# --------------------------------------------------------------------
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

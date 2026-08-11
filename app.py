import os
import sqlite3
import io
import pandas as pd
from flask import Flask, request, jsonify, render_template, session, send_file
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "super-secret-key-change-this")
DATABASE = "attendance.db"

# -----------------------------------------------------------------------------
# DATABASE INITIALIZATION
# -----------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Schools Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS schools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    ''')

    # Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'staff',
            school_id INTEGER,
            FOREIGN KEY (school_id) REFERENCES schools (id)
        )
    ''')

    # Students Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            school_id INTEGER NOT NULL,
            student_id TEXT NOT NULL,
            student_name TEXT NOT NULL,
            grade TEXT,
            days_absent REAL DEFAULT 0,
            total_days REAL DEFAULT 0,
            attendance_rate REAL DEFAULT 100.0,
            is_chronic INTEGER DEFAULT 0,
            FOREIGN KEY (school_id) REFERENCES schools (id),
            UNIQUE(school_id, student_id)
        )
    ''')

    # Interventions Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS interventions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            notes TEXT,
            logged_by TEXT,
            FOREIGN KEY (student_id) REFERENCES students (id) ON DELETE CASCADE
        )
    ''')

    # Create default Admin if no users exist
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        admin_pass = generate_password_hash("admin123")
        cursor.execute("INSERT INTO users (email, password_hash, role) VALUES (?, ?, ?)",
                       ("admin@school.edu", admin_pass, "admin"))

    conn.commit()
    conn.close()

init_db()

# -----------------------------------------------------------------------------
# AUTHENTICATION ROUTES
# -----------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/me")
def me():
    if "user" in session:
        return jsonify({"logged_in": True, "user": session["user"]})
    return jsonify({"logged_in": False})

@app.route("/login", methods=["POST"])
def login():
    data = request.json or {}
    email = data.get("email", "").strip()
    password = data.get("password", "").strip()

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()
    conn.close()

    if user and check_password_hash(user["password_hash"], password):
        user_data = {
            "id": user["id"],
            "email": user["email"],
            "role": user["role"],
            "school_id": user["school_id"]
        }
        session["user"] = user_data
        return jsonify({"message": "Login successful", "user": user_data})

    return jsonify({"error": "Invalid email or password"}), 401

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Logged out"})

# -----------------------------------------------------------------------------
# SCHOOL & STUDENT DATA ROUTES
# -----------------------------------------------------------------------------
@app.route("/schools", methods=["GET"])
def get_schools():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    conn = get_db()
    cursor = conn.cursor()
    user = session["user"]

    if user["role"] == "admin":
        cursor.execute("SELECT * FROM schools ORDER BY name ASC")
    else:
        cursor.execute("SELECT * FROM schools WHERE id = ?", (user["school_id"],))

    schools = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({"schools": schools})

@app.route("/students", methods=["GET"])
def get_students():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    school_id = request.args.get("school_id")
    grade = request.args.get("grade", "").strip()
    chronic_only = request.args.get("chronic") == "true"
    search = request.args.get("search", "").strip()

    if not school_id:
        return jsonify({"students": [], "total_students": 0, "chronic_count": 0, "available_grades": []})

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT DISTINCT grade FROM students WHERE school_id = ? AND grade IS NOT NULL ORDER BY grade ASC", (school_id,))
    available_grades = [r["grade"] for r in cursor.fetchall() if r["grade"]]

    query = """
        SELECT s.*, COUNT(i.id) as interventions_count
        FROM students s
        LEFT JOIN interventions i ON s.id = i.student_id
        WHERE s.school_id = ?
    """
    params = [school_id]

    if grade:
        query += " AND s.grade = ?"
        params.append(grade)

    if chronic_only:
        query += " AND s.is_chronic = 1"

    if search:
        query += " AND (s.student_name LIKE ? OR s.student_id LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])

    query += " GROUP BY s.id ORDER BY s.student_name ASC"

    cursor.execute(query, params)
    students_rows = cursor.fetchall()

    students = []
    chronic_count = 0

    for r in students_rows:
        student = {
            "db_id": r["id"],
            "student_id": r["student_id"],
            "student_name": r["student_name"],
            "grade": r["grade"],
            "days_absent": r["days_absent"],
            "total_days": r["total_days"],
            "attendance_rate_pct": r["attendance_rate"],
            "is_chronic": bool(r["is_chronic"]),
            "interventions_count": r["interventions_count"]
        }
        if student["is_chronic"]:
            chronic_count += 1
        students.append(student)

    conn.close()

    return jsonify({
        "students": students,
        "total_students": len(students),
        "chronic_count": chronic_count,
        "available_grades": available_grades
    })

# -----------------------------------------------------------------------------
# FILE UPLOAD (NORMALIZED LINE ENDINGS + DYNAMIC CurrentSchoolMembe)
# -----------------------------------------------------------------------------
@app.route("/upload", methods=["POST"])
def upload_file():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    school_id = request.form.get("school_id")
    file = request.files.get("file")

    if not school_id or not file:
        return jsonify({"error": "Missing school ID or file"}), 400

    try:
        filename = file.filename.lower()
        if filename.endswith(".csv"):
            # Clean Carriage Return (\r\n and \r -> \n) so pandas reads all rows correctly
            file_bytes = file.read().decode('utf-8-sig', errors='replace')
            file_bytes = file_bytes.replace('\r\n', '\n').replace('\r', '\n')
            df = pd.read_csv(io.StringIO(file_bytes), dtype=str, on_bad_lines='skip')
        elif filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(file, dtype=str)
        else:
            return jsonify({"error": "Unsupported file type. Upload CSV or Excel."}), 400

        # Normalize column header strings
        cols_cleaned = {c: str(c).strip().replace(" ", "").replace("_", "").lower() for c in df.columns}

        # Locate column headers dynamically
        id_col = next((orig for orig, clean in cols_cleaned.items() if "studentnu" in clean or "studentid" in clean or clean == "id"), None)
        name_col = next((orig for orig, clean in cols_cleaned.items() if "studentna" in clean or "studentname" in clean or clean == "name"), None)
        grade_col = next((orig for orig, clean in cols_cleaned.items() if "grade" in clean), None)
        absent_col = next((orig for orig, clean in cols_cleaned.items() if "totalabse" in clean or "daysabse" in clean or "absent" in clean), None)
        total_col = next((orig for orig, clean in cols_cleaned.items() if "currentschoolmembe" in clean or "schoolmembe" in clean or "membership" in clean), None)

        # Positional index fallbacks if headers cannot be matched
        if not id_col and len(df.columns) > 0: id_col = df.columns[0]
        if not name_col and len(df.columns) > 1: name_col = df.columns[1]
        if not grade_col and len(df.columns) > 2: grade_col = df.columns[2]
        if not absent_col and len(df.columns) > 13: absent_col = df.columns[13]
        if not total_col and len(df.columns) > 14: total_col = df.columns[14]

        conn = get_db()
        cursor = conn.cursor()

        processed_count = 0

        for _, row in df.iterrows():
            st_id = str(row[id_col]).strip() if pd.notna(row[id_col]) else ""
            st_name = str(row[name_col]).strip() if pd.notna(row[name_col]) else ""
            st_grade = str(row[grade_col]).strip() if grade_col and pd.notna(row[grade_col]) else ""

            # Safely skip blank rows using continue
            if not st_id or st_id.lower() in ["nan", "none", ""] or not st_name or st_name.lower() in ["nan", "none", ""]:
                continue

            # Parse Days Absent safely
            try:
                days_absent = float(str(row[absent_col]).replace(",", "").strip()) if absent_col and pd.notna(row[absent_col]) else 0.0
            except (ValueError, TypeError):
                days_absent = 0.0

            # Parse Total Membership Days explicitly from CurrentSchoolMembe
            try:
                total_days = float(str(row[total_col]).replace(",", "").strip()) if total_col and pd.notna(row[total_col]) else 0.0
            except (ValueError, TypeError):
                total_days = 0.0

            # Calculate attendance rate
            if total_days > 0:
                attendance_rate = round(((total_days - days_absent) / total_days) * 100, 1)
            else:
                attendance_rate = 100.0

            is_chronic = 1 if attendance_rate < 90.0 else 0

            cursor.execute("""
                INSERT INTO students (school_id, student_id, student_name, grade, days_absent, total_days, attendance_rate, is_chronic)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(school_id, student_id) DO UPDATE SET
                    student_name=excluded.student_name,
                    grade=excluded.grade,
                    days_absent=excluded.days_absent,
                    total_days=excluded.total_days,
                    attendance_rate=excluded.attendance_rate,
                    is_chronic=excluded.is_chronic
            """, (school_id, st_id, st_name, st_grade, days_absent, total_days, attendance_rate, is_chronic))

            processed_count += 1

        conn.commit()
        conn.close()

        return jsonify({"message": f"Successfully processed {processed_count} student records."})

    except Exception as e:
        return jsonify({"error": f"Failed to process file: {str(e)}"}), 500

# -----------------------------------------------------------------------------
# INTERVENTIONS & EXPORT
# -----------------------------------------------------------------------------
@app.route("/interventions", methods=["GET", "POST"])
def handle_interventions():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    cursor = conn.cursor()

    if request.method == "GET":
        student_db_id = request.args.get("student_db_id")
        cursor.execute("SELECT * FROM interventions WHERE student_id = ? ORDER BY date DESC", (student_db_id,))
        logs = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return jsonify({"interventions": logs})

    if request.method == "POST":
        data = request.json or {}
        student_db_id = data.get("student_db_id")
        date_str = data.get("date")
        int_type = data.get("type")
        notes = data.get("notes")
        logged_by = session["user"]["email"]

        cursor.execute("""
            INSERT INTO interventions (student_id, date, type, notes, logged_by)
            VALUES (?, ?, ?, ?, ?)
        """, (student_db_id, date_str, int_type, notes, logged_by))

        conn.commit()
        conn.close()
        return jsonify({"message": "Intervention logged successfully"})

@app.route("/export/interventions", methods=["GET"])
def export_interventions():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    school_id = request.args.get("school_id")
    if not school_id:
        return jsonify({"error": "School ID required"}), 400

    conn = get_db()
    cursor = conn.cursor()

    query = """
        SELECT s.student_id, s.student_name, s.grade, s.days_absent, s.total_days, s.attendance_rate,
               i.date as intervention_date, i.type as intervention_type, i.notes, i.logged_by
        FROM students s
        LEFT JOIN interventions i ON s.id = i.student_id
        WHERE s.school_id = ?
        ORDER BY s.student_name ASC, i.date DESC
    """
    cursor.execute(query, (school_id,))
    rows = cursor.fetchall()
    conn.close()

    export_data = []
    for r in rows:
        export_data.append({
            "Student ID": r["student_id"],
            "Student Name": r["student_name"],
            "Grade": r["grade"],
            "Days Absent": r["days_absent"],
            "Total Membership Days": r["total_days"],
            "Attendance Rate (%)": r["attendance_rate"],
            "Intervention Date": r["intervention_date"] or "N/A",
            "Intervention Type": r["intervention_type"] or "None",
            "Notes": r["notes"] or "",
            "Logged By": r["logged_by"] or ""
        })

    df = pd.DataFrame(export_data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Interventions')
    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'attendance_interventions_school_{school_id}.xlsx'
    )

# -----------------------------------------------------------------------------
# ADMIN MANAGEMENT
# -----------------------------------------------------------------------------
@app.route("/admin/schools", methods=["POST"])
def add_school():
    if "user" not in session or session["user"]["role"] != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    name = (request.json or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "School name required"}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO schools (name) VALUES (?)", (name,))
        conn.commit()
        return jsonify({"message": "School added successfully"})
    except sqlite3.IntegrityError:
        return jsonify({"error": "School name already exists"}), 400
    finally:
        conn.close()

@app.route("/admin/schools/<int:school_id>", methods=["DELETE"])
def delete_school(school_id):
    if "user" not in session or session["user"]["role"] != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM schools WHERE id = ?", (school_id,))
    cursor.execute("DELETE FROM students WHERE school_id = ?", (school_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "School and associated data deleted successfully"})

@app.route("/admin/users", methods=["GET", "POST"])
def admin_users():
    if "user" not in session or session["user"]["role"] != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    conn = get_db()
    cursor = conn.cursor()

    if request.method == "GET":
        cursor.execute("""
            SELECT u.id, u.email, u.role, s.name as school_name
            FROM users u
            LEFT JOIN schools s ON u.school_id = s.id
            ORDER BY u.email ASC
        """)
        users = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return jsonify({"users": users})

    if request.method == "POST":
        data = request.json or {}
        email = data.get("email", "").strip()
        password = data.get("password", "").strip()
        role = data.get("role", "staff")
        school_id = data.get("school_id") or None

        if not email or not password:
            return jsonify({"error": "Email and password required"}), 400

        try:
            pw_hash = generate_password_hash(password)
            cursor.execute("INSERT INTO users (email, password_hash, role, school_id) VALUES (?, ?, ?, ?)",
                           (email, pw_hash, role, school_id))
            conn.commit()
            return jsonify({"message": "User created successfully"})
        except sqlite3.IntegrityError:
            return jsonify({"error": "User email already exists"}), 400
        finally:
            conn.close()

@app.route("/admin/users/<int:user_id>", methods=["DELETE"])
def delete_user(user_id):
    if "user" not in session or session["user"]["role"] != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "User deleted successfully"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)

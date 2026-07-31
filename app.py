import os
import io
import pandas as pd
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import insert
from werkzeug.security import generate_password_hash, check_password_hash
from jinja2 import FileSystemLoader

# Resolve the project root path explicitly for Render
base_dir = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
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

# Database Models
class School(db.Model):
    __tablename__ = 'schools'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

class Student(db.Model):
    __tablename__ = 'students'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), nullable=False)
    student_name = db.Column(db.String(100), nullable=False)
    grade = db.Column(db.String(20), nullable=True)
    days_absent = db.Column(db.Float, default=0.0)
    total_days = db.Column(db.Float, default=0.0)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)

    __table_args__ = (
        db.UniqueConstraint('student_id', 'school_id', name='unique_student_per_school'),
    )

# Routes
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    school_id = request.form.get('school_id', 1, type=int)

    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    try:
        # Read uploaded file
        if file.filename.endswith('.csv'):
            df = pd.read_csv(io.StringIO(file.stream.read().decode('utf-8')))
        else:
            df = pd.read_excel(file)

        # -----------------------------------------------------------------
        # 1. CLEAN & FILTER HEADER METADATA
        # -----------------------------------------------------------------
        # Find the real Student ID column (case-insensitive search)
        id_col = next((c for c in df.columns if 'student' in c.lower() and 'id' in c.lower()), df.columns[0])
        name_col = next((c for c in df.columns if 'name' in c.lower()), df.columns[1] if len(df.columns) > 1 else df.columns[0])
        absent_col = next((c for c in df.columns if 'absent' in c.lower() or 'unexcused' in c.lower()), None)
        total_col = next((c for c in df.columns if 'total' in c.lower() or 'enrolled' in c.lower() or 'membership' in c.lower()), None)
        grade_col = next((c for c in df.columns if 'grade' in c.lower()), None)

        # Convert ID column to string and filter out non-student metadata rows
        df[id_col] = df[id_col].astype(str).str.strip()
        
        # Remove header noise like "Attendance Date Range:", NaN values, or empty strings
        df = df[
            df[id_col].notna() & 
            (df[id_col] != '') & 
            ~df[id_col].str.contains('Attendance Date Range|Report|Total|Date', case=False, na=False)
        ]

        # -----------------------------------------------------------------
        # 2. BULK UPSERT TO PREVENT UNIQUE VIOLATION ERRORS
        # -----------------------------------------------------------------
        for _, row in df.iterrows():
            st_id = str(row[id_col]).strip()
            st_name = str(row[name_col]).strip() if name_col else "Unknown"
            st_grade = str(row[grade_col]).strip() if grade_col and pd.notna(row[grade_col]) else "N/A"
            days_abs = float(row[absent_col]) if absent_col and pd.notna(row[absent_col]) else 0.0
            tot_days = float(row[total_col]) if total_col and pd.notna(row[total_col]) else 0.0

            # PostgreSQL Upsert syntax (ON CONFLICT DO UPDATE)
            stmt = insert(Student).values(
                student_id=st_id,
                student_name=st_name,
                grade=st_grade,
                days_absent=days_abs,
                total_days=tot_days,
                school_id=school_id
            )

            # If student ID already exists for this school, update stats instead of failing
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

        db.session.commit()
        return jsonify({'message': f'Successfully processed {len(df)} student records!'}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to process file: {str(e)}'}), 500

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)

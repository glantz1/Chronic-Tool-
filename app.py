import os
from flask import Flask, render_template_string, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-in-production'

# Database Configuration
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ------------------------------------------------------------------------------
# Models
# ------------------------------------------------------------------------------

class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    users = db.relationship('User', backref='school', lazy=True)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='Staff')  # 'Admin' or 'Staff'
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------

def get_current_user():
    user_id = session.get('user_id')
    if user_id:
        return User.query.get(user_id)
    return None

# ------------------------------------------------------------------------------
# HTML Templates
# ------------------------------------------------------------------------------

LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Login</title>
    <style>
        body { font-family: sans-serif; background: #f4f6f8; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .card { background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); width: 320px; }
        input, button { width: 100%; padding: 0.5rem; margin-top: 0.5rem; box-sizing: border-box; }
        button { background: #0066cc; color: white; border: none; border-radius: 4px; cursor: pointer; }
        .error { color: red; font-size: 0.85rem; margin-bottom: 0.5rem; }
    </style>
</head>
<body>
    <div class="card">
        <h2>Login</h2>
        {% with messages = get_flashed_messages(category_filter=["error"]) %}
            {% if messages %}
                {% for message in messages %}
                    <div class="error">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        <form method="POST" action="/login">
            <label>Username</label>
            <input type="text" name="username" required>
            <label style="margin-top:0.5rem; display:block;">Password</label>
            <input type="password" name="password" required>
            <button type="submit" style="margin-top: 1rem;">Sign In</button>
        </form>
    </div>
</body>
</html>
"""

INDEX_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Dashboard</title>
    <style>
        :root { --muted: #666; --danger: #d9534f; }
        body { font-family: sans-serif; background: #f4f6f8; margin: 0; padding: 2rem; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 2rem; }
        .card { background: white; padding: 1.5rem; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); margin-bottom: 1.5rem; }
        .form-row { display: flex; gap: 0.5rem; }
        input, select, button { padding: 0.5rem; border: 1px solid #ccc; border-radius: 4px; }
        .btn { background: #0066cc; color: white; border: none; cursor: pointer; }
        .btn-danger { background: var(--danger); color: white; border: none; cursor: pointer; }
        .btn-sm { padding: 0.25rem 0.5rem; font-size: 0.75rem; border-radius: 3px; }
        table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
        th, td { text-align: left; padding: 0.5rem; border-bottom: 1px solid #eee; }
        .flash { padding: 0.75rem; background: #e3f2fd; color: #0d47a1; border-radius: 4px; margin-bottom: 1rem; }
        .flash.error { background: #ffebee; color: #c62828; }
    </style>
</head>
<body>
    <div class="header">
        <h2>Dashboard</h2>
        <div>
            Logged in as <strong>{{ current_user.username }}</strong> ({{ current_user.role }})
            | <a href="/logout">Logout</a>
        </div>
    </div>

    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="flash {{ category }}">{{ message }}</div>
            {% endfor %}
        {% endif %}
    {% endwith %}

    {% if current_user.role == 'Admin' %}
    <!-- User Management Section -->
    <div class="card">
        <h3 style="margin-top:0;">👤 User Management</h3>
        
        <!-- Add User Form -->
        <form method="POST" action="/add_user" style="display:flex; flex-direction:column; gap:0.75rem; margin-bottom:1.5rem;">
            <div class="form-row">
                <input type="text" name="username" placeholder="Username (email or name)" required style="flex:1;">
                <input type="password" name="password" placeholder="Password" required style="flex:1;">
            </div>
            <div class="form-row">
                <select name="role" required style="flex:1;">
                    <option value="Staff">Role: Staff</option>
                    <option value="Admin">Role: Admin</option>
                </select>
                <select name="school_id" style="flex:1;">
                    <option value="">Assigned School (Optional)</option>
                    {% for school in schools %}
                    <option value="{{ school.id }}">{{ school.name }}</option>
                    {% endfor %}
                </select>
                <button type="submit" class="btn">Create User</button>
            </div>
        </form>

        <!-- Existing Accounts Table -->
        <h4 style="margin:0 0 0.5rem 0; font-size:0.9rem; color:var(--muted);">Existing Accounts</h4>
        <table>
            <thead>
                <tr>
                    <th>Username</th>
                    <th>Role</th>
                    <th>Assigned School</th>
                    <th style="text-align:right;">Action</th>
                </tr>
            </thead>
            <tbody>
                {% for u in all_users %}
                <tr>
                    <td><strong>{{ u.username }}</strong></td>
                    <td>{{ u.role }}</td>
                    <td>{{ u.school.name if u.school else 'All District' }}</td>
                    <td style="text-align:right;">
                        {% if u.id != current_user.id %}
                        <form method="POST" action="/delete_user/{{ u.id }}" onsubmit="return confirm('Delete user {{ u.username }}?');" style="margin:0; display:inline;">
                            <button type="submit" class="btn btn-danger btn-sm">Delete</button>
                        </form>
                        {% else %}
                        <span style="color:var(--muted); font-size:0.75rem;">(You)</span>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% endif %}

    <div class="card">
        <h3>System Content</h3>
        <p>Welcome to the dashboard. Additional system metrics and forms go here.</p>
    </div>
</body>
</html>
"""

# ------------------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------------------

@app.route('/')
def index():
    current_user = get_current_user()
    if not current_user:
        return redirect(url_for('login'))
    
    schools = School.query.all()
    all_users = User.query.all() if current_user.role == 'Admin' else []
    
    return render_template_string(
        INDEX_HTML, 
        current_user=current_user, 
        schools=schools, 
        all_users=all_users
    )

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            session['user_id'] = user.id
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password.', 'error')

    return render_template_string(LOGIN_HTML)

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/add_user', methods=['POST'])
def add_user():
    current = get_current_user()
    if not current or current.role != 'Admin':
        return redirect(url_for('index'))

    username = request.form.get('username')
    password = request.form.get('password')
    role = request.form.get('role', 'Staff')
    school_id = request.form.get('school_id')

    if User.query.filter_by(username=username).first():
        flash(f'User "{username}" already exists.', 'error')
        return redirect(url_for('index'))

    new_user = User(
        username=username,
        role=role,
        school_id=int(school_id) if school_id else None
    )
    new_user.set_password(password)

    db.session.add(new_user)
    db.session.commit()
    flash(f'User "{username}" created successfully.', 'success')

    return redirect(url_for('index'))

@app.route('/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    current = get_current_user()
    if not current or current.role != 'Admin':
        return redirect(url_for('index'))

    # Prevent admin from deleting their own active account
    if current.id == user_id:
        flash('You cannot delete your own account while logged in.', 'error')
        return redirect(url_for('index'))

    user_to_delete = User.query.get(user_id)
    if user_to_delete:
        username = user_to_delete.username
        db.session.delete(user_to_delete)
        db.session.commit()
        flash(f'User "{username}" has been deleted.', 'success')
    else:
        flash('User not found.', 'error')

    return redirect(url_for('index'))

# ------------------------------------------------------------------------------
# Database Initialization
# ------------------------------------------------------------------------------

def init_db():
    with app.app_context():
        db.create_all()
        # Create default Admin if no users exist
        if not User.query.first():
            admin = User(username='admin', role='Admin')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("Default admin created (Username: admin, Password: admin123)")

if __name__ == '__main__':
    init_db()
    app.run(debug=True)

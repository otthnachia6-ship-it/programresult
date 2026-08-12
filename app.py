"""
KISAUNI PRIMARY SCHOOL - RESULT MANAGEMENT SYSTEM
Main Flask application.
"""
import os
import secrets
import string
from functools import wraps
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect, url_for, session, flash,
    jsonify, send_file, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from config import Config, grade_for_score, detect_gender, ROLE_HEADMASTER, ROLE_CLASS_TEACHER, EXAM_TYPES
from database import get_db, init_db, log_action, get_setting

app = Flask(__name__)
app.config.from_object(Config)

if not os.path.exists(Config.DATABASE):
    init_db()
else:
    # make sure schema/seed data exists even if db file already present
    init_db()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def current_user():
    if "user_id" not in session:
        return None
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    conn.close()
    return user


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def headmaster_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        if session.get("role") != ROLE_HEADMASTER:
            flash("You do not have permission to access this page.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return wrapper


def generate_temp_password(length=8):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ---------------------------------------------------------------------------
# SECURITY: force password change for temporary passwords, and prevent
# cached/back-button access to protected pages after logout.
# ---------------------------------------------------------------------------
@app.before_request
def enforce_password_change():
    if "user_id" in session:
        if request.endpoint in ("change_password", "logout", "static", "login", None):
            return
        conn = get_db()
        row = conn.execute(
            "SELECT must_change_password FROM users WHERE id=?", (session["user_id"],)
        ).fetchone()
        conn.close()
        if row and row["must_change_password"]:
            flash("You must change your temporary password before continuing.", "warning")
            return redirect(url_for("change_password"))


@app.after_request
def add_no_cache_headers(response):
    # Prevents the browser from serving a cached authenticated page (via the
    # back/forward button) after the user has logged out.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


STATUS_LABELS = {
    "draft": "Draft",
    "submitted": "Pending Review",
    "under_review": "Pending Review",
    "approved": "Approved",
    "returned": "Returned for Correction",
}


def get_status_history(conn, exam_id, class_id):
    """Return the full audit trail (submit / review / approve / return) for
    a given exam+class, most recent first — this is the permanent history
    the Headmaster and Class Teacher can both see (not a fleeting notice)."""
    exact = f"exam={exam_id} class={class_id}"
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE action IN "
        "('SUBMIT_RESULTS','START_REVIEW','APPROVE_RESULTS','RETURN_RESULTS') "
        "AND (details = ? OR details LIKE ?) ORDER BY id DESC",
        (exact, exact + ":%"),
    ).fetchall()
    return rows


@app.context_processor
def inject_globals():
    conn = get_db()
    school_name = get_setting(conn, "school_name", "KISAUNI PRIMARY SCHOOL")
    academic_year = get_setting(conn, "academic_year", "2026")
    logo_path = get_setting(conn, "logo_path", "images/logo.png")
    conn.close()
    return dict(
        school_name=school_name,
        academic_year=academic_year,
        logo_path=logo_path,
        session_user=current_user(),
        ROLE_HEADMASTER=ROLE_HEADMASTER,
        ROLE_CLASS_TEACHER=ROLE_CLASS_TEACHER,
        STATUS_LABELS=STATUS_LABELS,
    )


# ---------------------------------------------------------------------------
# AUTH ROUTES
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not user:
            flash("Incorrect username or password.", "danger")
            conn.close()
            return render_template("login.html")
        if not check_password_hash(user["password_hash"], password):
            flash("Incorrect username or password.", "danger")
            conn.close()
            return render_template("login.html")
        if not user["active"]:
            flash("This account has been deactivated. Please contact the Headmaster.", "danger")
            conn.close()
            return render_template("login.html")

        session["user_id"] = user["id"]
        session["role"] = user["role"]
        session["full_name"] = user["full_name"]
        session["class_id"] = user["class_id"]
        log_action(conn, user, "LOGIN", f"{user['username']} logged in")
        conn.close()
        if user["must_change_password"]:
            flash("Welcome! For your security, please set a new password before continuing.", "info")
            return redirect(url_for("change_password"))
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    user = current_user()
    if user:
        conn = get_db()
        log_action(conn, user, "LOGOUT", f"{user['username']} logged out")
        conn.close()
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    temp_password = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not user:
            flash("No account was found with that username.", "danger")
            conn.close()
            return render_template("forgot_password.html", temp_password=None)
        if not user["active"]:
            flash("This account has been deactivated. Please contact the Headmaster.", "danger")
            conn.close()
            return render_template("forgot_password.html", temp_password=None)

        temp_password = generate_temp_password()
        conn.execute(
            "UPDATE users SET password_hash=?, must_change_password=1 WHERE id=?",
            (generate_password_hash(temp_password), user["id"]),
        )
        conn.commit()
        log_action(conn, user, "FORGOT_PASSWORD_RESET", f"{user['username']} requested a password reset")
        conn.close()
    return render_template("forgot_password.html", temp_password=temp_password)


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if not check_password_hash(user["password_hash"], current):
            flash("Your current password is incorrect.", "danger")
        elif len(new) < 4:
            flash("New password must be at least 4 characters long.", "danger")
        elif new != confirm:
            flash("New password and confirmation do not match.", "danger")
        else:
            conn.execute(
                "UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?",
                (generate_password_hash(new), user["id"]),
            )
            conn.commit()
            log_action(conn, user, "CHANGE_PASSWORD", "User changed own password")
            flash("Your password has been changed successfully.", "success")
            conn.close()
            return redirect(url_for("dashboard"))
        conn.close()
    return render_template("change_password.html")


@app.route("/profile")
@login_required
def profile():
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    cls = None
    if user["class_id"]:
        cls = conn.execute("SELECT * FROM classes WHERE id=?", (user["class_id"],)).fetchone()
    conn.close()
    return render_template("profile.html", user=user, cls=cls)


# ---------------------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()
    stats = {}
    stats["students"] = conn.execute("SELECT COUNT(*) c FROM students WHERE active=1").fetchone()["c"]
    stats["classes"] = conn.execute("SELECT COUNT(*) c FROM classes").fetchone()["c"]
    stats["subjects"] = conn.execute("SELECT COUNT(*) c FROM subjects").fetchone()["c"]
    stats["exams"] = conn.execute("SELECT COUNT(*) c FROM examinations").fetchone()["c"]
    stats["pending"] = conn.execute(
        "SELECT COUNT(*) c FROM exam_class_status WHERE status IN ('submitted','under_review')"
    ).fetchone()["c"]
    stats["approved"] = conn.execute(
        "SELECT COUNT(*) c FROM exam_class_status WHERE status='approved'"
    ).fetchone()["c"]

    my_class = None
    my_class_students = 0
    returned_results = []
    if session["role"] == ROLE_CLASS_TEACHER and session.get("class_id"):
        my_class = conn.execute("SELECT * FROM classes WHERE id=?", (session["class_id"],)).fetchone()
        my_class_students = conn.execute(
            "SELECT COUNT(*) c FROM students WHERE class_id=? AND active=1", (session["class_id"],)
        ).fetchone()["c"]
        returned_results = conn.execute("""
            SELECT ecs.*, e.exam_type, e.academic_year, e.id as exam_id_val
            FROM exam_class_status ecs JOIN examinations e ON ecs.exam_id = e.id
            WHERE ecs.class_id=? AND ecs.status='returned'
            ORDER BY e.id DESC
        """, (session["class_id"],)).fetchall()

    recent_logs = conn.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT 8"
    ).fetchall()
    conn.close()
    return render_template("dashboard.html", stats=stats, my_class=my_class,
                            my_class_students=my_class_students, recent_logs=recent_logs,
                            returned_results=returned_results)


# ---------------------------------------------------------------------------
# STUDENTS
# ---------------------------------------------------------------------------
@app.route("/students")
@login_required
def students():
    conn = get_db()
    class_filter = request.args.get("class_id", "")
    search = request.args.get("q", "").strip()

    query = """
        SELECT s.*, c.name as class_name, c.sort_order
        FROM students s JOIN classes c ON s.class_id = c.id
        WHERE s.active = 1
    """
    params = []
    if session["role"] == ROLE_CLASS_TEACHER:
        query += " AND s.class_id = ?"
        params.append(session.get("class_id"))
    elif class_filter:
        query += " AND s.class_id = ?"
        params.append(class_filter)

    if search:
        query += " AND (s.full_name LIKE ? OR s.reg_no LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])

    query += (
        " ORDER BY c.sort_order ASC, "
        "CASE s.gender WHEN 'Male' THEN 0 WHEN 'Female' THEN 1 ELSE 2 END ASC, "
        "s.full_name COLLATE NOCASE ASC"
    )
    rows = conn.execute(query, params).fetchall()

    classes = conn.execute("SELECT * FROM classes ORDER BY sort_order").fetchall()

    # group students alphabetically per class (Standard order)
    grouped = {}
    for r in rows:
        grouped.setdefault(r["class_name"], []).append(r)

    conn.close()
    return render_template("students.html", grouped=grouped, classes=classes,
                            class_filter=class_filter, search=search)


@app.route("/api/detect-gender")
@login_required
def api_detect_gender():
    name = request.args.get("name", "")
    gender = detect_gender(name)
    return jsonify({"gender": gender})


@app.route("/api/students-by-class/<int:class_id>")
@login_required
def api_students_by_class(class_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, reg_no, full_name FROM students WHERE class_id=? AND active=1 "
        "ORDER BY CASE gender WHEN 'Male' THEN 0 WHEN 'Female' THEN 1 ELSE 2 END ASC, full_name COLLATE NOCASE ASC",
        (class_id,),
    ).fetchall()
    conn.close()
    return jsonify([{"id": r["id"], "reg_no": r["reg_no"], "full_name": r["full_name"]} for r in rows])


@app.route("/students/add", methods=["GET", "POST"])
@login_required
def add_student():
    conn = get_db()
    if session["role"] == ROLE_CLASS_TEACHER:
        classes = conn.execute("SELECT * FROM classes WHERE id=?", (session.get("class_id"),)).fetchall()
    else:
        classes = conn.execute("SELECT * FROM classes ORDER BY sort_order").fetchall()

    if request.method == "POST":
        reg_no = request.form.get("reg_no", "").strip()
        full_name = request.form.get("full_name", "").strip()
        class_id = request.form.get("class_id")
        gender = request.form.get("gender", "").strip()
        gender_confirmed = 1 if request.form.get("gender_confirmed") == "on" else 0

        error = None
        if not reg_no or not full_name or not class_id:
            error = "Please fill in Reg No, Full Name and Class."
        elif conn.execute("SELECT 1 FROM students WHERE reg_no=?", (reg_no,)).fetchone():
            error = "This Reg No is already registered in the system."
        elif session["role"] == ROLE_CLASS_TEACHER and str(class_id) != str(session.get("class_id")):
            error = "You can only register students for your own assigned class."

        if error:
            flash(error, "danger")
            conn.close()
            return render_template("student_form.html", classes=classes, student=request.form, mode="add")

        if not gender:
            gender = detect_gender(full_name) or "Unknown"

        conn.execute(
            "INSERT INTO students (reg_no, full_name, gender, gender_confirmed, class_id, active, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?)",
            (reg_no, full_name, gender, gender_confirmed, class_id,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        log_action(conn, current_user(), "ADD_STUDENT", f"{full_name} ({reg_no})")
        conn.close()
        flash(f"Student {full_name} registered successfully.", "success")
        return redirect(url_for("students"))

    conn.close()
    return render_template("student_form.html", classes=classes, student=None, mode="add")


@app.route("/students/edit/<int:student_id>", methods=["GET", "POST"])
@login_required
def edit_student(student_id):
    conn = get_db()
    student = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
    if not student:
        conn.close()
        abort(404)
    if session["role"] == ROLE_CLASS_TEACHER and student["class_id"] != session.get("class_id"):
        conn.close()
        flash("You can only edit students in your own assigned class.", "danger")
        return redirect(url_for("students"))

    if session["role"] == ROLE_CLASS_TEACHER:
        classes = conn.execute("SELECT * FROM classes WHERE id=?", (session.get("class_id"),)).fetchall()
    else:
        classes = conn.execute("SELECT * FROM classes ORDER BY sort_order").fetchall()

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        class_id = request.form.get("class_id")
        gender = request.form.get("gender", "").strip()
        gender_confirmed = 1 if request.form.get("gender_confirmed") == "on" else 0
        reg_no = request.form.get("reg_no", "").strip()

        dup = conn.execute("SELECT 1 FROM students WHERE reg_no=? AND id != ?", (reg_no, student_id)).fetchone()
        if dup:
            flash("This Reg No is already used by another student.", "danger")
            conn.close()
            return render_template("student_form.html", classes=classes, student=student, mode="edit")

        conn.execute(
            "UPDATE students SET reg_no=?, full_name=?, gender=?, gender_confirmed=?, class_id=? WHERE id=?",
            (reg_no, full_name, gender, gender_confirmed, class_id, student_id),
        )
        conn.commit()
        log_action(conn, current_user(), "EDIT_STUDENT", f"{full_name} ({reg_no})")
        conn.close()
        flash("Student details updated successfully.", "success")
        return redirect(url_for("students"))

    conn.close()
    return render_template("student_form.html", classes=classes, student=student, mode="edit")


@app.route("/students/delete/<int:student_id>", methods=["POST"])
@login_required
def delete_student(student_id):
    conn = get_db()
    student = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
    if not student:
        conn.close()
        abort(404)
    if session["role"] == ROLE_CLASS_TEACHER and student["class_id"] != session.get("class_id"):
        conn.close()
        flash("You can only remove students in your own assigned class.", "danger")
        return redirect(url_for("students"))

    # soft-delete so historical marks/results remain intact
    conn.execute("UPDATE students SET active=0 WHERE id=?", (student_id,))
    conn.commit()
    log_action(conn, current_user(), "DELETE_STUDENT", f"{student['full_name']} ({student['reg_no']})")
    conn.close()
    flash(f"Student {student['full_name']} has been removed.", "info")
    return redirect(url_for("students"))


# ---------------------------------------------------------------------------
# CLASSES  (headmaster assigns class teachers)
# ---------------------------------------------------------------------------
@app.route("/classes", methods=["GET", "POST"])
@headmaster_required
def classes():
    conn = get_db()
    if request.method == "POST":
        class_id = request.form.get("class_id")
        teacher_id = request.form.get("teacher_id") or None
        conn.execute("UPDATE classes SET teacher_id=? WHERE id=?", (teacher_id, class_id))
        # keep users.class_id in sync with the assignment
        conn.execute("UPDATE users SET class_id=NULL WHERE class_id=?", (class_id,))
        if teacher_id:
            conn.execute("UPDATE users SET class_id=? WHERE id=?", (class_id, teacher_id))
        conn.commit()
        log_action(conn, current_user(), "ASSIGN_CLASS_TEACHER", f"class_id={class_id} teacher_id={teacher_id}")
        flash("Class Teacher assigned to class successfully.", "success")
        conn.close()
        return redirect(url_for("classes"))

    rows = conn.execute("""
        SELECT c.*, u.full_name as teacher_name,
        (SELECT COUNT(*) FROM students s WHERE s.class_id=c.id AND s.active=1) as student_count
        FROM classes c LEFT JOIN users u ON c.teacher_id = u.id
        ORDER BY c.sort_order
    """).fetchall()
    teachers = conn.execute(
        "SELECT * FROM users WHERE role='class_teacher' AND active=1 ORDER BY full_name"
    ).fetchall()
    conn.close()
    return render_template("classes.html", classes=rows, teachers=teachers)


# ---------------------------------------------------------------------------
# SUBJECTS
# ---------------------------------------------------------------------------
@app.route("/subjects", methods=["GET", "POST"])
@login_required
def subjects():
    conn = get_db()
    if request.method == "POST" and session["role"] == ROLE_HEADMASTER:
        action = request.form.get("action")
        if action == "add_subject":
            name = request.form.get("name", "").strip()
            class_ids = request.form.getlist("class_ids")
            if name:
                cur = conn.execute("INSERT INTO subjects (name) VALUES (?)", (name,))
                sid = cur.lastrowid
                for cid in class_ids:
                    conn.execute("INSERT OR IGNORE INTO class_subjects (class_id, subject_id) VALUES (?, ?)", (cid, sid))
                conn.commit()
                log_action(conn, current_user(), "ADD_SUBJECT", name)
                flash(f"Subject '{name}' added successfully.", "success")
        elif action == "toggle":
            class_id = request.form.get("class_id")
            subject_id = request.form.get("subject_id")
            exists = conn.execute(
                "SELECT 1 FROM class_subjects WHERE class_id=? AND subject_id=?", (class_id, subject_id)
            ).fetchone()
            if exists:
                conn.execute("DELETE FROM class_subjects WHERE class_id=? AND subject_id=?", (class_id, subject_id))
            else:
                conn.execute("INSERT INTO class_subjects (class_id, subject_id) VALUES (?, ?)", (class_id, subject_id))
            conn.commit()
        return redirect(url_for("subjects"))
    classes = conn.execute("SELECT * FROM classes ORDER BY sort_order").fetchall()
    all_subjects = conn.execute("SELECT * FROM subjects ORDER BY name").fetchall()
    mapping = conn.execute("SELECT * FROM class_subjects").fetchall()
    mapping_set = {(m["class_id"], m["subject_id"]) for m in mapping}
    conn.close()
    return render_template("subjects.html", classes=classes, all_subjects=all_subjects, mapping_set=mapping_set)


@app.route("/subjects/delete/<int:subject_id>", methods=["POST"])
@headmaster_required
def delete_subject(subject_id):
    conn = get_db()
    subject = conn.execute("SELECT * FROM subjects WHERE id=?", (subject_id,)).fetchone()
    if not subject:
        conn.close()
        abort(404)
    has_marks = conn.execute("SELECT 1 FROM marks WHERE subject_id=? LIMIT 1", (subject_id,)).fetchone()
    if has_marks:
        flash(f"Cannot delete '{subject['name']}' — marks have already been recorded for it. "
              f"Remove it from all classes instead (toggle off) if it is no longer taught.", "danger")
        conn.close()
        return redirect(url_for("subjects"))
    conn.execute("DELETE FROM class_subjects WHERE subject_id=?", (subject_id,))
    conn.execute("DELETE FROM subjects WHERE id=?", (subject_id,))
    conn.commit()
    log_action(conn, current_user(), "DELETE_SUBJECT", subject["name"])
    conn.close()
    flash(f"Subject '{subject['name']}' deleted successfully.", "info")
    return redirect(url_for("subjects"))


# ---------------------------------------------------------------------------
# EXAMINATIONS
# ---------------------------------------------------------------------------
@app.route("/examinations", methods=["GET", "POST"])
@login_required
def examinations():
    conn = get_db()
    if request.method == "POST" and session["role"] == ROLE_HEADMASTER:
        exam_type = request.form.get("exam_type")
        academic_year = request.form.get("academic_year", "").strip()
        if exam_type in EXAM_TYPES and academic_year:
            try:
                conn.execute(
                    "INSERT INTO examinations (exam_type, academic_year, created_at) VALUES (?, ?, ?)",
                    (exam_type, academic_year, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                )
                conn.commit()
                log_action(conn, current_user(), "ADD_EXAM", f"{exam_type} {academic_year}")
                flash("Examination added successfully.", "success")
            except Exception:
                flash("This examination already exists for that academic year.", "warning")
        return redirect(url_for("examinations"))

    exams = conn.execute("SELECT * FROM examinations ORDER BY academic_year DESC, id DESC").fetchall()
    conn.close()
    return render_template("examinations.html", exams=exams, exam_types=EXAM_TYPES)


# ---------------------------------------------------------------------------
# USERS / ACCOUNTS  (headmaster only)
# ---------------------------------------------------------------------------
@app.route("/users")
@headmaster_required
def users():
    conn = get_db()
    rows = conn.execute("""
        SELECT u.*, c.name as class_name FROM users u
        LEFT JOIN classes c ON u.class_id = c.id
        ORDER BY u.role DESC, u.full_name
    """).fetchall()
    conn.close()
    return render_template("users.html", users=rows)


@app.route("/users/add", methods=["GET", "POST"])
@headmaster_required
def add_user():
    conn = get_db()
    classes = conn.execute("SELECT * FROM classes ORDER BY sort_order").fetchall()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        full_name = request.form.get("full_name", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role")
        class_id = request.form.get("class_id") or None
        if role != ROLE_CLASS_TEACHER:
            class_id = None

        if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            flash("This username is already taken.", "danger")
            conn.close()
            return render_template("user_form.html", classes=classes, user=request.form, mode="add")

        conn.execute(
            "INSERT INTO users (username, password_hash, full_name, role, class_id, active, must_change_password, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1, 1, ?)",
            (username, generate_password_hash(password), full_name, role, class_id,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        log_action(conn, current_user(), "ADD_USER", f"{username} ({role})")
        conn.close()
        flash(f"Account for {full_name} created successfully. Share the username and temporary "
              f"password with them — they will be asked to set a new password on first login.", "success")
        return redirect(url_for("users"))
    conn.close()
    return render_template("user_form.html", classes=classes, user=None, mode="add")


@app.route("/users/edit/<int:user_id>", methods=["GET", "POST"])
@headmaster_required
def edit_user(user_id):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        conn.close()
        abort(404)
    classes = conn.execute("SELECT * FROM classes ORDER BY sort_order").fetchall()
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        role = request.form.get("role")
        class_id = request.form.get("class_id") or None
        if role != ROLE_CLASS_TEACHER:
            class_id = None
        new_password = request.form.get("password", "").strip()

        conn.execute("UPDATE users SET full_name=?, role=?, class_id=? WHERE id=?",
                     (full_name, role, class_id, user_id))
        if new_password:
            conn.execute("UPDATE users SET password_hash=?, must_change_password=1 WHERE id=?",
                         (generate_password_hash(new_password), user_id))
        conn.commit()
        log_action(conn, current_user(), "EDIT_USER", f"{user['username']}")
        conn.close()
        flash("User details updated successfully.", "success")
        return redirect(url_for("users"))
    conn.close()
    return render_template("user_form.html", classes=classes, user=user, mode="edit")


@app.route("/users/toggle/<int:user_id>", methods=["POST"])
@headmaster_required
def toggle_user(user_id):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        conn.close()
        abort(404)
    if user["role"] == ROLE_HEADMASTER:
        flash("You cannot deactivate the Headmaster account.", "warning")
        conn.close()
        return redirect(url_for("users"))
    new_status = 0 if user["active"] else 1
    conn.execute("UPDATE users SET active=? WHERE id=?", (new_status, user_id))
    conn.commit()
    log_action(conn, current_user(), "TOGGLE_USER", f"{user['username']} -> active={new_status}")
    conn.close()
    flash("Account status updated.", "info")
    return redirect(url_for("users"))


# ---------------------------------------------------------------------------
# RESULT COMPUTATION HELPER
# ---------------------------------------------------------------------------
def compute_class_results(conn, class_id, exam_id):
    """Returns (subjects_list, results_list) for a class+exam.
    results_list items: {student, scores: {subject_id: score}, total, average, grade, colour, position}
    """
    subjects = conn.execute("""
        SELECT sub.* FROM subjects sub
        JOIN class_subjects cs ON cs.subject_id = sub.id
        WHERE cs.class_id = ?
        ORDER BY sub.name
    """, (class_id,)).fetchall()
    subject_ids = [s["id"] for s in subjects]

    students = conn.execute(
        "SELECT * FROM students WHERE class_id=? AND active=1 "
        "ORDER BY CASE gender WHEN 'Male' THEN 0 WHEN 'Female' THEN 1 ELSE 2 END ASC, full_name COLLATE NOCASE ASC",
        (class_id,)
    ).fetchall()

    all_marks = conn.execute("""
        SELECT * FROM marks WHERE exam_id=? AND student_id IN (
            SELECT id FROM students WHERE class_id=? AND active=1
        )
    """, (exam_id, class_id)).fetchall()
    marks_map = {}
    for m in all_marks:
        marks_map.setdefault(m["student_id"], {})[m["subject_id"]] = m["score"]

    results = []
    for st in students:
        scores = marks_map.get(st["id"], {})
        entered = [scores[sid] for sid in subject_ids if scores.get(sid) is not None]
        total = sum(entered) if entered else 0
        average = (total / len(entered)) if entered else None
        grade, colour = grade_for_score(average) if average is not None else ("-", "#6c757d")
        results.append({
            "student": st,
            "scores": scores,
            "total": total,
            "average": round(average, 1) if average is not None else None,
            "grade": grade,
            "colour": colour,
            "subjects_entered": len(entered),
        })

    # Rank by average (desc); students with no marks go last
    ranked = sorted(
        [r for r in results if r["average"] is not None],
        key=lambda r: r["average"], reverse=True
    )
    pos = 0
    prev_avg = None
    for i, r in enumerate(ranked, start=1):
        if r["average"] != prev_avg:
            pos = i
            prev_avg = r["average"]
        r["position"] = pos
    for r in results:
        if r["average"] is None:
            r["position"] = "-"

    # keep display order alphabetical (already queried that way)
    order_map = {r["student"]["id"]: r for r in results}
    ordered_results = [order_map[st["id"]] for st in students]

    return subjects, ordered_results


def get_exam_status(conn, exam_id, class_id):
    row = conn.execute(
        "SELECT * FROM exam_class_status WHERE exam_id=? AND class_id=?", (exam_id, class_id)
    ).fetchone()
    return row


# ---------------------------------------------------------------------------
# MARKS ENTRY  (Class Teacher enters marks for their own class)
# ---------------------------------------------------------------------------
@app.route("/marks", methods=["GET"])
@login_required
def marks_select():
    conn = get_db()
    exams = conn.execute("SELECT * FROM examinations ORDER BY academic_year DESC, id DESC").fetchall()
    if session["role"] == ROLE_CLASS_TEACHER:
        classes = conn.execute("SELECT * FROM classes WHERE id=?", (session.get("class_id"),)).fetchall()
    else:
        classes = conn.execute("SELECT * FROM classes ORDER BY sort_order").fetchall()
    conn.close()
    return render_template("marks_select.html", exams=exams, classes=classes)


@app.route("/marks/<int:exam_id>/<int:class_id>", methods=["GET", "POST"])
@login_required
def marks(exam_id, class_id):
    conn = get_db()
    if session["role"] == ROLE_CLASS_TEACHER and class_id != session.get("class_id"):
        conn.close()
        flash("You can only enter marks for your own assigned class.", "danger")
        return redirect(url_for("marks_select"))

    exam = conn.execute("SELECT * FROM examinations WHERE id=?", (exam_id,)).fetchone()
    cls = conn.execute("SELECT * FROM classes WHERE id=?", (class_id,)).fetchone()
    status_row = get_exam_status(conn, exam_id, class_id)
    status = status_row["status"] if status_row else "draft"
    locked = status in ("submitted", "under_review", "approved")

    if request.method == "POST":
        if locked:
            flash("Marks for this class have already been submitted/approved and cannot be edited.", "warning")
            conn.close()
            return redirect(url_for("marks", exam_id=exam_id, class_id=class_id))

        subjects = conn.execute("""
            SELECT sub.* FROM subjects sub JOIN class_subjects cs ON cs.subject_id = sub.id
            WHERE cs.class_id=?
        """, (class_id,)).fetchall()
        students = conn.execute(
            "SELECT * FROM students WHERE class_id=? AND active=1", (class_id,)
        ).fetchall()

        for st in students:
            for sub in subjects:
                field = f"score_{st['id']}_{sub['id']}"
                val = request.form.get(field, "").strip()
                score = None
                if val != "":
                    try:
                        score = max(0, min(100, float(val)))
                    except ValueError:
                        score = None
                existing = conn.execute(
                    "SELECT 1 FROM marks WHERE student_id=? AND exam_id=? AND subject_id=?",
                    (st["id"], exam_id, sub["id"]),
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE marks SET score=?, entered_by=?, updated_at=? "
                        "WHERE student_id=? AND exam_id=? AND subject_id=?",
                        (score, session["user_id"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                         st["id"], exam_id, sub["id"]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO marks (student_id, exam_id, subject_id, score, entered_by, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (st["id"], exam_id, sub["id"], score, session["user_id"],
                         datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                    )
        conn.execute(
            "INSERT INTO exam_class_status (exam_id, class_id, status) VALUES (?, ?, 'draft') "
            "ON CONFLICT(exam_id, class_id) DO UPDATE SET status='draft'",
            (exam_id, class_id),
        )
        conn.commit()
        log_action(conn, current_user(), "ENTER_MARKS", f"exam={exam_id} class={class_id}")
        flash("Marks saved successfully.", "success")
        conn.close()
        return redirect(url_for("marks", exam_id=exam_id, class_id=class_id))

    subjects, results = compute_class_results(conn, class_id, exam_id)
    history = get_status_history(conn, exam_id, class_id)
    conn.close()
    return render_template("marks.html", exam=exam, cls=cls, subjects=subjects,
                            results=results, status=status, locked=locked, history=history)


@app.route("/marks/submit/<int:exam_id>/<int:class_id>", methods=["POST"])
@login_required
def submit_marks(exam_id, class_id):
    conn = get_db()
    if session["role"] == ROLE_CLASS_TEACHER and class_id != session.get("class_id"):
        conn.close()
        flash("You do not have permission to do that.", "danger")
        return redirect(url_for("marks_select"))
    conn.execute(
        "INSERT INTO exam_class_status (exam_id, class_id, status, submitted_by, submitted_at) "
        "VALUES (?, ?, 'submitted', ?, ?) "
        "ON CONFLICT(exam_id, class_id) DO UPDATE SET status='submitted', submitted_by=?, submitted_at=?",
        (exam_id, class_id, session["user_id"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
         session["user_id"], datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    log_action(conn, current_user(), "SUBMIT_RESULTS", f"exam={exam_id} class={class_id}")
    conn.close()
    flash("Results submitted to the Headmaster for review.", "success")
    return redirect(url_for("marks", exam_id=exam_id, class_id=class_id))


# ---------------------------------------------------------------------------
# RESULTS REVIEW & APPROVAL  (Headmaster)
# ---------------------------------------------------------------------------
@app.route("/results")
@headmaster_required
def results():
    conn = get_db()
    rows = conn.execute("""
        SELECT ecs.*, e.exam_type, e.academic_year, c.name as class_name, c.id as class_id_val
        FROM exam_class_status ecs
        JOIN examinations e ON ecs.exam_id = e.id
        JOIN classes c ON ecs.class_id = c.id
        WHERE ecs.status IN ('submitted','under_review','approved','returned')
        ORDER BY (ecs.status IN ('submitted','under_review')) DESC, e.academic_year DESC, c.sort_order
    """).fetchall()
    conn.close()
    return render_template("results.html", rows=rows)


@app.route("/results/review/<int:exam_id>/<int:class_id>", methods=["GET", "POST"])
@headmaster_required
def review_results(exam_id, class_id):
    conn = get_db()
    exam = conn.execute("SELECT * FROM examinations WHERE id=?", (exam_id,)).fetchone()
    cls = conn.execute("SELECT * FROM classes WHERE id=?", (class_id,)).fetchone()
    status_row = get_exam_status(conn, exam_id, class_id)

    # Headmaster opening the review page moves SUBMITTED -> UNDER REVIEW
    if request.method == "GET" and status_row and status_row["status"] == "submitted":
        conn.execute(
            "UPDATE exam_class_status SET status='under_review' WHERE exam_id=? AND class_id=?",
            (exam_id, class_id),
        )
        conn.commit()
        log_action(conn, current_user(), "START_REVIEW", f"exam={exam_id} class={class_id}")
        status_row = get_exam_status(conn, exam_id, class_id)

    if request.method == "POST":
        action = request.form.get("action")
        remarks = request.form.get("remarks", "").strip()
        if action == "approve":
            conn.execute(
                "UPDATE exam_class_status SET status='approved', approved_by=?, approved_at=?, remarks=? "
                "WHERE exam_id=? AND class_id=?",
                (session["user_id"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), remarks, exam_id, class_id),
            )
            conn.commit()
            log_action(conn, current_user(), "APPROVE_RESULTS", f"exam={exam_id} class={class_id}")
            flash("Results approved and locked successfully.", "success")
        elif action == "return":
            if not remarks:
                flash("Please provide a reason/feedback when returning results for correction.", "warning")
                conn.close()
                return redirect(url_for("review_results", exam_id=exam_id, class_id=class_id))
            conn.execute(
                "UPDATE exam_class_status SET status='returned', remarks=? WHERE exam_id=? AND class_id=?",
                (remarks, exam_id, class_id),
            )
            conn.commit()
            log_action(conn, current_user(), "RETURN_RESULTS", f"exam={exam_id} class={class_id}: {remarks}")
            flash("Results returned to the Class Teacher for correction.", "info")
        conn.close()
        return redirect(url_for("results"))

    subjects, res = compute_class_results(conn, class_id, exam_id)
    history = get_status_history(conn, exam_id, class_id)
    conn.close()
    return render_template("review_results.html", exam=exam, cls=cls, subjects=subjects,
                            results=res, status_row=status_row, history=history)


# ---------------------------------------------------------------------------
# HEADMASTER OVERVIEW  (summary of all classes' performance)
# ---------------------------------------------------------------------------
@app.route("/headmaster/overview")
@headmaster_required
def headmaster_overview():
    conn = get_db()
    exam_id = request.args.get("exam_id")
    exams = conn.execute("SELECT * FROM examinations ORDER BY academic_year DESC, id DESC").fetchall()
    if not exam_id and exams:
        exam_id = exams[0]["id"]

    overview = []
    if exam_id:
        classes = conn.execute("SELECT * FROM classes ORDER BY sort_order").fetchall()
        for cls in classes:
            subjects, res = compute_class_results(conn, cls["id"], exam_id)
            averages = [r["average"] for r in res if r["average"] is not None]
            class_avg = round(sum(averages) / len(averages), 1) if averages else None
            status_row = get_exam_status(conn, exam_id, cls["id"])
            overview.append({
                "cls": cls,
                "student_count": len(res),
                "class_average": class_avg,
                "status": status_row["status"] if status_row else "draft",
                "top_student": res[0]["student"]["full_name"] if res and res[0]["average"] is not None else None,
            })
            # find true top student by position 1
            top = [r for r in res if r.get("position") == 1]
            overview[-1]["top_student"] = top[0]["student"]["full_name"] if top else None

    conn.close()
    return render_template("headmaster_overview.html", exams=exams, exam_id=int(exam_id) if exam_id else None,
                            overview=overview)


# ---------------------------------------------------------------------------
# REPORTS
# ---------------------------------------------------------------------------
@app.route("/reports")
@login_required
def reports():
    conn = get_db()
    exams = conn.execute("SELECT * FROM examinations ORDER BY academic_year DESC, id DESC").fetchall()
    if session["role"] == ROLE_CLASS_TEACHER:
        classes = conn.execute("SELECT * FROM classes WHERE id=?", (session.get("class_id"),)).fetchall()
    else:
        classes = conn.execute("SELECT * FROM classes ORDER BY sort_order").fetchall()
    conn.close()
    return render_template("reports.html", exams=exams, classes=classes)



@app.route("/reports/student/<int:student_id>/<int:exam_id>")
@login_required
def student_report(student_id, exam_id):
    conn = get_db()
    student = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
    if not student:
        conn.close()
        abort(404)
    if session["role"] == ROLE_CLASS_TEACHER and student["class_id"] != session.get("class_id"):
        conn.close()
        flash("You do not have permission to do that.", "danger")
        return redirect(url_for("reports"))

    exam = conn.execute("SELECT * FROM examinations WHERE id=?", (exam_id,)).fetchone()
    cls = conn.execute("SELECT * FROM classes WHERE id=?", (student["class_id"],)).fetchone()
    teacher = None
    if cls["teacher_id"]:
        teacher = conn.execute("SELECT * FROM users WHERE id=?", (cls["teacher_id"],)).fetchone()

    subjects, results = compute_class_results(conn, cls["id"], exam_id)
    my_result = next((r for r in results if r["student"]["id"] == student_id), None)
    total_students = len(results)
    status_row = get_exam_status(conn, exam_id, cls["id"])
    conn.close()
    return render_template("student_report.html", exam=exam, cls=cls, student=student,
                            subjects=subjects, result=my_result, total_students=total_students,
                            teacher=teacher, status_row=status_row,
                            report_date=datetime.now().strftime("%d/%m/%Y"))


# ---------------------------------------------------------------------------
# SETTINGS  (headmaster only)
# ---------------------------------------------------------------------------
@app.route("/settings", methods=["GET", "POST"])
@headmaster_required
def settings_page():
    conn = get_db()
    if request.method == "POST":
        school_name = request.form.get("school_name", "").strip()
        academic_year = request.form.get("academic_year", "").strip()
        conn.execute("UPDATE settings SET value=? WHERE key='school_name'", (school_name,))
        conn.execute("UPDATE settings SET value=? WHERE key='academic_year'", (academic_year,))

        logo = request.files.get("logo")
        if logo and logo.filename:
            filename = secure_filename(logo.filename)
            save_path = os.path.join(Config.UPLOAD_DIR, filename)
            logo.save(save_path)
            conn.execute("UPDATE settings SET value=? WHERE key='logo_path'", (f"images/{filename}",))

        conn.commit()
        log_action(conn, current_user(), "UPDATE_SETTINGS", "School settings updated")
        flash("School settings saved successfully.", "success")
        conn.close()
        return redirect(url_for("settings_page"))

    current = {row["key"]: row["value"] for row in conn.execute("SELECT * FROM settings").fetchall()}
    conn.close()
    return render_template("settings.html", current=current)


# ---------------------------------------------------------------------------
# AUDIT LOG  (headmaster only)
# ---------------------------------------------------------------------------
@app.route("/audit-logs")
@headmaster_required
def audit_logs():
    conn = get_db()
    logs = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 300").fetchall()
    conn.close()
    return render_template("audit_logs.html", logs=logs)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

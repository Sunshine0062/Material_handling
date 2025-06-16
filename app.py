from flask import Flask, render_template, request, redirect, session, url_for, flash
from functools import wraps
from datetime import datetime
import os
from supabase import create_client, Client
from dotenv import load_dotenv

# ------------------- Load Environment -------------------
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# ---------------------- Global Data ----------------------
users = {}
materials = []
stock_logs = []
data_loaded = False  # Flag

# ---------------------- Load / Save ----------------------

def load_data():
    global users, materials, stock_logs
    users.clear()
    materials.clear()
    stock_logs.clear()

    try:
        user_data = supabase.table("users").select("*").execute().data
        material_data = supabase.table("materials").select("*").execute().data
        log_data = supabase.table("stock_logs").select("*").execute().data

        for u in user_data:
            users[u["username"]] = {
                "password": u["password"],
                "is_admin": u["is_admin"]
            }

        materials.extend(material_data)
        stock_logs.extend(log_data)

    except Exception as e:
        print("❌ Error loading data from Supabase:", e)

@app.before_request
def ensure_data_loaded():
    global data_loaded
    if not data_loaded:
        print("🔄 Loading data from Supabase before first real request...")
        load_data()
        data_loaded = True


def save_users():
    supabase.table("users").delete().neq("username", "").execute()
    for u, d in users.items():
        supabase.table("users").insert({
            "username": u,
            "password": d["password"],
            "is_admin": d["is_admin"]
        }).execute()


def save_materials():
    supabase.table("materials").delete().neq("code", "").execute()
    supabase.table("materials").insert(materials).execute()


def save_stock_logs():
    supabase.table("stock_logs").delete().neq("code", "").execute()
    supabase.table("stock_logs").insert(stock_logs).execute()


def save_data():
    save_users()
    save_materials()
    save_stock_logs()

# ---------------------- Helpers ----------------------
def generate_material_code():
    existing_codes = [m.get("code") for m in materials if m.get("code")]
    index = 1
    while True:
        code = f"MAT{index:03}"
        if code not in existing_codes:
            return code
        index += 1


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            flash("อนุญาตให้เฉพาะแอดมินเท่านั้น")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated

# ---------------------- Routes ----------------------
@app.route("/")
def index():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = users.get(username)
        if user and user["password"] == password:
            session["username"] = username
            session["is_admin"] = user.get("is_admin", False)
            return redirect(url_for("dashboard"))
        flash("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", username=session["username"])

@app.route("/materials")
@login_required
def materials_view():
    return render_template("materials.html", materials=materials)

@app.route("/edit-material", methods=["GET", "POST"])
@app.route("/edit-material/<int:index>", methods=["GET", "POST"])
@admin_required
def edit_material(index=None):
    material = materials[index] if index is not None and index < len(materials) else None

    if request.method == "POST":
        name = request.form["name"]
        try:
            quantity = int(request.form["quantity"])
        except:
            flash("จำนวนต้องเป็นตัวเลข")
            return redirect(request.url)
        unit = request.form["unit"]
        code = request.form.get("code", "").strip() or generate_material_code()

        new_material = {
            "name": name,
            "quantity": quantity,
            "unit": unit,
            "code": code
        }

        if material is None:
            if any(m["name"] == name for m in materials):
                flash("มีวัสดุนี้อยู่แล้วในระบบ", "error")
                return redirect(url_for("edit_material"))
            materials.append(new_material)
        else:
            materials[index] = new_material

        save_materials()
        return redirect(url_for("materials_view"))

    return render_template("edit_material.html", material=material)

@app.route("/delete-material/<int:index>")
@admin_required
def delete_material(index):
    if index < len(materials):
        materials.pop(index)
        save_materials()
    return redirect(url_for("materials_view"))

@app.route("/admin-delete-material/<material_code>", methods=["POST"])
@admin_required
def admin_delete_material(material_code):
    global materials, stock_logs
    materials = [m for m in materials if m["code"] != material_code]
    stock_logs = [log for log in stock_logs if log.get("code") != material_code]
    flash(f"ลบวัสดุ {material_code} และข้อมูลที่เกี่ยวข้องทั้งหมดเรียบร้อยแล้ว", "success")
    save_materials()
    save_stock_logs()
    return redirect(url_for("admin_page"))

@app.route("/stock-in", methods=["GET", "POST"])
@admin_required
def stock_in():
    if request.method == "POST":
        material_code = request.form.get("material_code")
        quantity_str = request.form.get("quantity")

        if not material_code:
            flash("กรุณาเลือกวัสดุ")
            return redirect(url_for("stock_in"))

        try:
            quantity = int(quantity_str)
            if quantity <= 0:
                flash("จำนวนต้องมากกว่า 0")
                return redirect(url_for("stock_in"))
        except:
            flash("กรุณากรอกจำนวนเป็นตัวเลขที่ถูกต้อง")
            return redirect(url_for("stock_in"))

        material = next((m for m in materials if m["code"] == material_code), None)
        if not material:
            flash("ไม่พบวัสดุที่เลือก")
            return redirect(url_for("stock_in"))

        material["quantity"] += quantity

        stock_logs.append({
            "type": "in",
            "code": material["code"],
            "name": material["name"],
            "quantity": quantity,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M")
        })

        save_materials()
        save_stock_logs()
        flash(f'บันทึกการรับเข้า {material["name"]} จำนวน {quantity} {material["unit"]} เรียบร้อยแล้ว')
        return redirect(url_for("stock_in"))

    return render_template("stock_in.html", materials=materials, stock_logs=stock_logs)

@app.route("/stock-out", methods=["GET", "POST"])
@admin_required
def stock_out():
    if request.method == "POST":
        material_input = request.form.get("material")
        quantity_str = request.form.get("quantity")
        requester = request.form.get("requester", "").strip()
        project = request.form.get("project", "").strip()

        if not material_input:
            flash("กรุณาเลือกวัสดุ")
            return redirect(url_for("stock_out"))

        try:
            material_code = material_input.split(" - ")[0].strip()
        except Exception:
            material_code = material_input.strip()

        try:
            quantity = int(quantity_str)
            if quantity <= 0:
                flash("จำนวนต้องมากกว่า 0")
                return redirect(url_for("stock_out"))
        except:
            flash("กรุณากรอกจำนวนเป็นตัวเลขที่ถูกต้อง")
            return redirect(url_for("stock_out"))

        material = next((m for m in materials if m["code"] == material_code), None)
        if not material:
            flash("ไม่พบวัสดุที่เลือก")
            return redirect(url_for("stock_out"))

        if material["quantity"] < quantity:
            flash(f"จำนวนในคลังไม่พอ (เหลือ {material['quantity']})")
            return redirect(url_for("stock_out"))

        material["quantity"] -= quantity

        stock_logs.append({
            "type": "out",
            "code": material["code"],
            "name": material["name"],
            "quantity": quantity,
            "requester": requester,
            "project": project,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M")
        })

        save_materials()
        save_stock_logs()
        flash(f'บันทึกการเบิกออก {material["name"]} จำนวน {quantity} {material["unit"]} เรียบร้อยแล้ว')
        return redirect(url_for("stock_out"))

    return render_template("stock_out.html", materials=materials, stock_logs=stock_logs)

@app.route("/tracking")
@login_required
def tracking():
    return render_template("tracking.html", materials=materials, logs=stock_logs)

@app.route("/admin", methods=["GET", "POST"])
@admin_required
def admin_page():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        is_admin = request.form["is_admin"] == "true"

        if username not in users:
            users[username] = {"password": password, "is_admin": is_admin}
            flash("เพิ่มผู้ใช้เรียบร้อยแล้ว")
            save_users()
        else:
            flash("ผู้ใช้นี้มีอยู่แล้ว")

        return redirect(url_for("admin_page"))

    return render_template("admin.html", users=users, materials=materials)

@app.route("/delete-user/<username>", methods=["POST"])
@admin_required
def delete_user(username):
    current_user = session.get("username")

    if username not in users:
        flash("ไม่พบผู้ใช้ที่ต้องการลบ", "error")
        return redirect(url_for("admin_page"))

    if users[username].get("is_admin"):
        if current_user != "admin_1234":
            flash("ไม่อนุญาตให้ลบแอดมิน", "error")
            return redirect(url_for("admin_page"))
        if username == "admin_1234":
            flash("ไม่อนุญาตให้ลบตัวเอง", "error")
            return redirect(url_for("admin_page"))

    users.pop(username)
    flash(f"ลบผู้ใช้ {username} เรียบร้อยแล้ว")
    save_users()
    return redirect(url_for("admin_page"))

# ---------------------- Main ----------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

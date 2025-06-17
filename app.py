from flask import Flask, render_template, request, redirect, session, url_for, flash
from functools import wraps
from datetime import datetime
import os
import pytz
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
data_loaded = False

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
    try:
        supabase.table("stock_logs").delete().neq("code", "").execute()
        supabase.table("stock_logs").insert(stock_logs).execute()
        print("✅ Stock logs saved:", len(stock_logs))
    except Exception as e:
        print("❌ Failed to save stock logs:", e)
        flash("เกิดข้อผิดพลาดขณะบันทึกประวัติการเบิกวัสดุ", "error")

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

        if not requester:
            flash("กรุณากรอกชื่อผู้เบิก")
            return redirect(url_for("stock_out"))
        if not project:
            flash("กรุณากรอกชื่อโครงการหรือหน้างาน")
            return redirect(url_for("stock_out"))

        material = next((m for m in materials if m["code"] == material_code), None)
        if not material:
            flash("ไม่พบวัสดุที่เลือก")
            return redirect(url_for("stock_out"))

        if material["quantity"] < quantity:
            flash(f"จำนวนในคลังไม่พอ (เหลือ {material['quantity']})")
            return redirect(url_for("stock_out"))

        material["quantity"] -= quantity

        thai_time = datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%Y-%m-%d %H:%M")
        stock_logs.append({
            "type": "out",
            "code": material["code"],
            "name": material["name"],
            "quantity": quantity,
            "requester": requester,
            "project": project,
            "date": thai_time
        })

        save_materials()
        save_stock_logs()
        flash(f'บันทึกการเบิกออก {material["name"]} จำนวน {quantity} {material["unit"]} เรียบร้อยแล้ว')
        return redirect(url_for("stock_out"))

    return render_template("stock_out.html", materials=materials, stock_logs=stock_logs)

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

        thai_time = datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%Y-%m-%d %H:%M")
        stock_logs.append({
            "type": "in",
            "code": material["code"],
            "name": material["name"],
            "quantity": quantity,
            "date": thai_time
        })

        save_materials()
        save_stock_logs()
        flash(f'บันทึกการรับเข้า {material["name"]} จำนวน {quantity} {material["unit"]} เรียบร้อยแล้ว')
        return redirect(url_for("stock_in"))

    return render_template("stock_in.html", materials=materials, stock_logs=stock_logs)



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

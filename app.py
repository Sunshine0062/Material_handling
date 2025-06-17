
from flask import Flask, flash
from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

stock_logs = []  # This will be replaced by real logs in production


def save_stock_logs():
    try:
        # ลบ key 'id' ออก ถ้ามีใน log
        cleaned_logs = [{k: v for k, v in log.items() if k != "id"} for log in stock_logs]
        supabase.table("stock_logs").delete().neq("code", "").execute()
        supabase.table("stock_logs").insert(cleaned_logs).execute()
        print("✅ Stock logs saved:", len(cleaned_logs))
    except Exception as e:
        print("❌ Failed to save stock logs:", e)
        flash("เกิดข้อผิดพลาดขณะบันทึกประวัติการเบิกวัสดุ", "error")


if __name__ == "__main__":
    app.run(debug=True)

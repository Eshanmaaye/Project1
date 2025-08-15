import os
from datetime import date, datetime
from decimal import Decimal
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import pymysql
from passlib.hash import pbkdf2_sha256

load_dotenv()

def get_db():
    conn = pymysql.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DB", "thogai_db"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
        charset="utf8mb4"
    )
    return conn

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret")

# -------- Helpers --------
def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    with get_db().cursor() as cur:
        cur.execute("SELECT id, name, email, created_at FROM users WHERE id=%s", (uid,))
        return cur.fetchone()

def login_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        return func(*args, **kwargs)
    return wrapper

# -------- Auth --------
@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name","").strip()
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        if not name or not email or not password:
            flash("All fields are required", "error")
            return redirect(url_for("register"))
        pwdhash = pbkdf2_sha256.hash(password)
        try:
            with get_db().cursor() as cur:
                cur.execute("INSERT INTO users (name,email,password_hash) VALUES (%s,%s,%s)", (name,email,pwdhash))
                session["user_id"] = cur.lastrowid
            flash("Welcome to THOGAI HOMEMADES!", "success")
            return redirect(url_for("dashboard"))
        except Exception as e:
            flash("Registration failed. Maybe email already used.", "error")
            return redirect(url_for("register"))
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        with get_db().cursor() as cur:
            cur.execute("SELECT * FROM users WHERE email=%s", (email,))
            user = cur.fetchone()
        if user and pbkdf2_sha256.verify(password, user["password_hash"]):
            session["user_id"] = user["id"]
            flash("Logged in!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid email or password", "error")
        return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out", "info")
    return redirect(url_for("login"))

# -------- Dashboard --------
@app.route("/")
@login_required
def dashboard():
    return render_template("dashboard.html", user=current_user())

# -------- Stock (Products) --------
@app.route("/stock", methods=["GET","POST"])
@login_required
def stock():
    u = current_user()
    if request.method == "POST":
        name = request.form.get("name","").strip()
        price = request.form.get("price","0").strip()
        quantity = request.form.get("quantity","0").strip()
        if not name:
            flash("Product name is required", "error")
            return redirect(url_for("stock"))
        try:
            price = Decimal(price)
            quantity = int(quantity)
        except:
            flash("Enter valid price and quantity", "error")
            return redirect(url_for("stock"))
        with get_db().cursor() as cur:
            cur.execute("INSERT INTO products (user_id,name,price,quantity) VALUES (%s,%s,%s,%s)",
                        (u["id"], name, price, quantity))
        flash("Product added", "success")
        return redirect(url_for("stock"))

    with get_db().cursor() as cur:
        cur.execute("SELECT * FROM products WHERE user_id=%s ORDER BY updated_at DESC", (u["id"],))
        products = cur.fetchall()
    return render_template("stock.html", products=products, user=u)

@app.route("/stock/<int:pid>/update", methods=["POST"])
@login_required
def stock_update(pid):
    u = current_user()
    name = request.form.get("name","").strip()
    price = request.form.get("price","0").strip()
    quantity = request.form.get("quantity","0").strip()
    with get_db().cursor() as cur:
        cur.execute("UPDATE products SET name=%s, price=%s, quantity=%s WHERE id=%s AND user_id=%s",
                    (name, price, quantity, pid, u["id"]))
    flash("Product updated", "success")
    return redirect(url_for("stock"))

@app.route("/stock/<int:pid>/delete", methods=["POST"])
@login_required
def stock_delete(pid):
    u = current_user()
    with get_db().cursor() as cur:
        cur.execute("DELETE FROM products WHERE id=%s AND user_id=%s", (pid, u["id"]))
    flash("Product deleted", "info")
    return redirect(url_for("stock"))

# -------- Sales --------
@app.route("/sales")
@login_required
def sales_home():
    return render_template("sales.html", user=current_user())

@app.route("/sales/previous")
@login_required
def sales_previous():
    u = current_user()
    with get_db().cursor() as cur:
        cur.execute("""
            SELECT s.id, s.sale_date, s.total_amount,
                   GROUP_CONCAT(CONCAT(p.name, ' x', si.quantity) SEPARATOR ', ') AS items
            FROM sales s
            JOIN sale_items si ON si.sale_id = s.id
            JOIN products p ON p.id = si.product_id
            WHERE s.user_id=%s
            GROUP BY s.id
            ORDER BY s.sale_date DESC, s.id DESC
        """, (u["id"],))
        rows = cur.fetchall()
    return render_template("sales_previous.html", rows=rows, user=u)

@app.route("/sales/monthly")
@login_required
def sales_monthly():
    u = current_user()
    with get_db().cursor() as cur:
        cur.execute("""
            SELECT DATE_FORMAT(s.sale_date, '%%Y-%%m') AS ym,
                   SUM(si.quantity * si.price_each) AS amount,
                   SUM(si.quantity) AS qty
            FROM sales s
            JOIN sale_items si ON si.sale_id = s.id
            WHERE s.user_id=%s
            GROUP BY ym
            ORDER BY ym DESC
        """, (u["id"],))
        months = cur.fetchall()
    return render_template("sales_monthly.html", months=months, user=u)

@app.route("/sales/today", methods=["GET","POST"])
@login_required
def sales_today():
    u = current_user()
    if request.method == "POST":
        # POSTed JSON: {items: [{product_id, quantity}], sale_date?}
        payload = request.get_json(force=True)
        sale_date = payload.get("sale_date") or date.today().isoformat()
        items = payload.get("items", [])
        if not items:
            return jsonify({"ok": False, "error": "No items"}), 400
        # Load products
        with get_db().cursor() as cur:
            cur.execute("SELECT id, name, price, quantity FROM products WHERE user_id=%s", (u["id"],))
            products = {str(r["id"]): r for r in cur.fetchall()}

        # Validate stock & compute total
        total = Decimal("0.00")
        for it in items:
            pid = str(it.get("product_id"))
            qty = int(it.get("quantity", 0))
            if qty <= 0: 
                continue
            if pid not in products:
                return jsonify({"ok": False, "error": "Invalid product"}), 400
            if products[pid]["quantity"] < qty:
                return jsonify({"ok": False, "error": f"Not enough stock for {products[pid]['name']}"}), 400
            total += Decimal(str(products[pid]["price"])) * qty

        # Create sale
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO sales (user_id, sale_date, total_amount) VALUES (%s,%s,%s)",
                            (u["id"], sale_date, total))
                sale_id = cur.lastrowid
                for it in items:
                    pid = int(it["product_id"]); qty = int(it["quantity"])
                    if qty <= 0: 
                        continue
                    price_each = Decimal(str(products[str(pid)]["price"]))
                    cur.execute("""
                        INSERT INTO sale_items (sale_id, product_id, quantity, price_each)
                        VALUES (%s,%s,%s,%s)
                    """, (sale_id, pid, qty, price_each))
                    # Reduce stock
                    cur.execute("UPDATE products SET quantity = quantity - %s WHERE id=%s AND user_id=%s",
                                (qty, pid, u["id"]))
            return jsonify({"ok": True, "sale_id": sale_id, "total": float(total)})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    # GET: render UI with available products
    with get_db().cursor() as cur:
        cur.execute("SELECT * FROM products WHERE user_id=%s ORDER BY name", (u["id"],))
        products = cur.fetchall()
    return render_template("sales_today.html", products=products, user=u, today=date.today().isoformat())

# -------- Earnings --------
@app.route("/earnings")
@login_required
def earnings():
    u = current_user()
    with get_db().cursor() as cur:
        # total earnings
        cur.execute("""
            SELECT COALESCE(SUM(total_amount),0) as total
            FROM sales WHERE user_id=%s
        """, (u["id"],))
        total = cur.fetchone()["total"] or 0

        # monthly per product
        cur.execute("""
            SELECT DATE_FORMAT(s.sale_date, '%%Y-%%m') AS ym, p.name,
                   SUM(si.quantity * si.price_each) AS amount
            FROM sales s
            JOIN sale_items si ON si.sale_id = s.id
            JOIN products p ON p.id = si.product_id
            WHERE s.user_id=%s
            GROUP BY ym, p.name
            ORDER BY ym DESC, p.name
        """, (u["id"],))
        per_product = cur.fetchall()
    return render_template("earnings.html", total=total, per_product=per_product, user=u)

# -------- Social (view co-users earnings) --------
@app.route("/social")
@login_required
def social():
    u = current_user()
    # See other users' total earnings (not detailed line items)
    with get_db().cursor() as cur:
        cur.execute("""
            SELECT u.id, u.name,
                   COALESCE(SUM(s.total_amount),0) AS total
            FROM users u
            LEFT JOIN sales s ON s.user_id = u.id
            GROUP BY u.id, u.name
            ORDER BY total DESC, u.name
        """)
        rows = cur.fetchall()
    return render_template("social.html", rows=rows, me=u)

# -------- Calculator --------
@app.route("/calculator")
@login_required
def calculator():
    return render_template("calculator.html", user=current_user())

# API to calculate totals client-side if needed
@app.route("/api/calc_total", methods=["POST"])
@login_required
def api_calc_total():
    payload = request.get_json(force=True)
    items = payload.get("items", [])
    total = Decimal("0.00")
    with get_db().cursor() as cur:
        ids = [it["product_id"] for it in items if int(it.get("quantity", 0)) > 0]
        if ids:
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(f"SELECT id, price FROM products WHERE id IN ({placeholders})", ids)
            price_map = {str(r["id"]): Decimal(str(r["price"])) for r in cur.fetchall()}
            for it in items:
                pid = str(it["product_id"]); qty = int(it.get("quantity", 0))
                if qty > 0 and pid in price_map:
                    total += price_map[pid] * qty
    return jsonify({"total": float(total)})

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)

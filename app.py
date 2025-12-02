from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_mysqldb import MySQL
import MySQLdb.cursors
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = "sipedo_secret_key"
app.config["MYSQL_HOST"] = "localhost"
app.config["MYSQL_USER"] = "root"
app.config["MYSQL_PASSWORD"] = ""
app.config["MYSQL_DB"] = "sipedo"
app.config["MYSQL_CURSORCLASS"] = "DictCursor"
mysql = MySQL(app)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        kata_sandi = request.form["kata_sandi"]

        cursor = mysql.connection.cursor()
        cursor.execute("SELECT * FROM donatur WHERE email = %s", (email,))
        akun = cursor.fetchone()
        if akun and check_password_hash(akun["kata_sandi"], kata_sandi):
            session["login"] = True
            session["id_donatur"] = akun["id_donatur"]
            session["nama_donatur"] = akun["nama_donatur"]
            return redirect(url_for("dashboard"))
        else:
            flash("Email atau kata sandi salah!", "danger")

    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        nama = request.form["nama"]
        email = request.form["email"]
        kata_sandi = generate_password_hash(request.form["kata_sandi"])
        nomor_hp = request.form["nomor_hp"]
        alamat = request.form["alamat"]

        cursor = mysql.connection.cursor()
        cursor.execute("""
            INSERT INTO donatur (nama_donatur, email, kata_sandi, nomor_hp, alamat)
            VALUES (%s, %s, %s, %s, %s)
        """, (nama, email, kata_sandi, nomor_hp, alamat))
        mysql.connection.commit()

        flash("Registrasi berhasil! Silakan login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/dashboard")
def dashboard():
    if "login" not in session:
        return redirect(url_for("login"))
    
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT COALESCE(SUM(jumlah_donasi), 0) AS total FROM donasi")
    total_donasi = cursor.fetchone()["total"]
    cursor.execute("SELECT COUNT(*) AS total FROM donatur")
    total_donatur = cursor.fetchone()["total"]
    cursor.execute("SELECT COUNT(*) AS total FROM charity")
    total_charity = cursor.fetchone()["total"]
    cursor.execute("""
        SELECT MONTH(tanggal_donasi) AS bulan, SUM(jumlah_donasi) AS total
        FROM donasi
        GROUP BY MONTH(tanggal_donasi)
        ORDER BY bulan
    """)
    donasi_per_bulan = cursor.fetchall()
    cursor.execute("""
        SELECT d.jumlah_donasi, d.tanggal_donasi, n.nama_donatur, c.nama_charity
        FROM donasi d
        JOIN donatur n ON d.id_donatur = n.id_donatur
        JOIN charity c ON d.id_charity = c.id_charity
        ORDER BY d.tanggal_donasi DESC
        LIMIT 10
    """)
    recent_activities = cursor.fetchall()

    return render_template(
        "dashboard.html",
        total_donasi=total_donasi,
        total_donatur=total_donatur,
        total_charity=total_charity,
        donasi_per_bulan=donasi_per_bulan,
        recent_activities=recent_activities,
        title="Dashboard"
    )

@app.route("/tambah-donasi", methods=["GET", "POST"])
def tambah_donasi():
    if "login" not in session:
        return redirect(url_for("login"))

    cursor = mysql.connection.cursor()
    cursor.execute("SELECT * FROM charity")
    charity_list = cursor.fetchall()

    if request.method == "POST":
        id_donatur = session["id_donatur"]
        id_charity = request.form["id_charity"]
        jumlah_donasi = request.form["jumlah_donasi"]
        metode = request.form["metode_pembayaran"]
        file = request.files["bukti"]

        filename = datetime.now().strftime("%Y%m%d%H%M%S") + "_" + file.filename
        save_path = os.path.join("static/bukti", filename)
        file.save(save_path)

        cursor.execute("""
            INSERT INTO donasi (id_donatur, id_charity, jumlah_donasi, metode_pembayaran, bukti)
            VALUES (%s, %s, %s, %s, %s)
        """, (id_donatur, id_charity, jumlah_donasi, metode, filename))
        cursor.execute("""
            INSERT INTO log_aktivitas (aksi)
            VALUES (%s)
        """, (f"Donatur {id_donatur} menambahkan donasi",))

        mysql.connection.commit()
        flash("Donasi berhasil ditambahkan!", "success")
        return redirect(url_for("dashboard"))

    return render_template("tambah_donasi.html", charity_list=charity_list, title="Tambah Donasi")

@app.route("/ranking-charity")
def ranking_charity():
    cursor = mysql.connection.cursor()

    cursor.execute("SELECT nama_kategori FROM kategori_charity")
    semua_kategori = [row["nama_kategori"] for row in cursor.fetchall()]
    kategori = request.args.get("kategori", "")
    filter_val = request.args.get("filter", "")
    limit = request.args.get("limit", "10")

    sql = """
        SELECT 
            c.id_charity,
            c.nama_charity,
            k.nama_kategori,
            COALESCE(SUM(d.jumlah_donasi), 0) AS total_donasi
        FROM charity c
        LEFT JOIN kategori_charity k ON c.id_kategori = k.id_kategori
        LEFT JOIN donasi d ON c.id_charity = d.id_charity
    """

    params = []
    if kategori:
        sql += " WHERE k.nama_kategori = %s"
        params.append(kategori)
    sql += " GROUP BY c.id_charity, c.nama_charity, k.nama_kategori"
    if filter_val == "lt50":
        sql += " HAVING total_donasi < %s"
        params.append(50000000)
    elif filter_val == "gt50":
        sql += " HAVING total_donasi > %s"
        params.append(50000000)
    sql += " ORDER BY total_donasi DESC"
    if limit != "9999":
        sql += f" LIMIT {limit}"

    cursor.execute(sql, params)
    data = cursor.fetchall()

    return render_template(
        "ranking_charity.html",
        data=data,
        semua_kategori=semua_kategori,
        kategori=kategori,
        filter_val=filter_val,
        limit=limit,
        title="Ranking Charity"
    )

@app.route("/progress-charity")
def progress_charity():
    cursor = mysql.connection.cursor()

    filter_value = request.args.get("filter", "")
    limit = request.args.get("limit", "10")

    sql = "SELECT * FROM v_progress_charity"
    params = []

    if filter_value == "low":
        sql += " WHERE persen_progress <= %s"
        params.append(50)

    elif filter_value == "mid":
        sql += " WHERE persen_progress >= %s AND persen_progress <= %s"
        params.extend([50, 100])

    elif filter_value == "high":
        sql += " WHERE persen_progress >= %s"
        params.append(100)

    sql += " ORDER BY persen_progress DESC"

    if limit != "9999":
        sql += f" LIMIT {limit}"

    cursor.execute(sql, params)
    data = cursor.fetchall()

    return render_template(
        "progress_charity.html",
        data=data,
        filter_value=filter_value,
        limit=limit,
        title="Progress Charity"
    )

@app.route("/top-donatur")
def top_donatur():
    cursor = mysql.connection.cursor()

    filter_value = request.args.get("filter", "")
    limit = request.args.get("limit", "10")

    sql = "SELECT * FROM v_top_donatur"
    params = []
    if filter_value == "low": 
        sql += " WHERE total_donasi < %s"
        params.append(5000000)
    elif filter_value == "mid":
        sql += " WHERE total_donasi >= %s AND total_donasi <= %s"
        params.extend([5000000, 10000000])
    elif filter_value == "high":
        sql += " WHERE total_donasi > %s"
        params.append(10000000)
    sql += " ORDER BY total_donasi DESC"
    sql += f" LIMIT {limit}"

    cursor.execute(sql, params)
    data = cursor.fetchall()

    return render_template(
        "top_donatur.html",
        data=data,
        filter_value=filter_value,
        limit=limit,
        title="Top Donatur"
    )

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(debug=True)


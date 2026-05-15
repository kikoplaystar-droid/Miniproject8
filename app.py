from flask import (
    Flask, render_template, session,
    request, redirect, flash, url_for,
    send_from_directory
)
from flask_login import (
    login_user, login_required,
    current_user, LoginManager,
    logout_user
)

from datetime import datetime
import dotenv
import secrets
import uuid
import os

from database import Session, Users, Menu, Orders, Reservation

import uuid


dotenv.load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY")

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
app.config['MAX_FORM_MEMORY_SIZE'] = 1024 * 1024      # 1MB
app.config['MAX_FORM_PARTS'] = 500
app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'

FILES_PATH = 'static/menu'


login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

@login_manager.user_loader
def load_user(user_id):
    with Session() as session_db:
        return session_db.query(Users).filter_by(id=user_id).first()


@app.after_request
def apply_csp(response):
    nonce = secrets.token_urlsafe(16)
    csp = (
        f"default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        f"style-src 'self' 'unsafe-inline'; "
        f"frame-ancestors 'none'; "
        f"base-uri 'self'; "
        f"form-action 'self'"
    )

    response.headers["Content-Security-Policy"] = csp
    response.set_cookie('nonce', nonce)
    return response


@app.route('/')
def home():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return render_template('home.html', user=current_user)


@app.route("/register", methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if request.form.get("csrf_token") != session["csrf_token"]:
            return "Запит заблоковано!", 403

        nickname = request.form['nickname']
        email = request.form['email']
        password = request.form['password']

        with Session() as cursor:
            if cursor.query(Users).filter_by(email=email).first() or \
               cursor.query(Users).filter_by(nickname=nickname).first():
                flash('Користувач з таким email або нікнеймом вже існує!', 'danger')
                return render_template('register.html', csrf_token=session["csrf_token"])

            new_user = Users(nickname=nickname, email=email)
            new_user.set_password(password)
            cursor.add(new_user)
            cursor.commit()
            cursor.refresh(new_user)

            login_user(new_user)
            return redirect(url_for('home'))

    return render_template('register.html', csrf_token=session["csrf_token"], user=current_user)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':

        if request.form.get('csrf_token') != session.get('csrf_token'):
            return 'Запит заблоковано!', 403

        nickname = request.form['nickname']
        password = request.form['password']

        with Session() as cursor:
            user = cursor.query(Users).filter_by(nickname=nickname).first()

            if user and user.check_password(password):
                login_user(user)
                return redirect(url_for('home'))

            flash('Неправильний nickname або пароль!', 'danger')

    return render_template('login.html', csrf_token=session['csrf_token'], user=current_user)


@app.route("/add_position", methods=['GET', 'POST'])
@login_required
def add_position():
    if current_user.nickname != 'Admin':
        return redirect(url_for('home'))

    if request.method == "POST":
        if request.form.get("csrf_token") != session["csrf_token"]:
            return "Запит заблоковано!", 403

        name = request.form['name']
        file = request.files.get('img')
        ingredients = request.form['ingredients']
        description = request.form['description']
        price = request.form['price']
        weight = request.form['weight']

        if not file or not file.filename:
            return 'Файл не вибрано або завантаження не вдалося'

        unique_filename = f"{uuid.uuid4()}_{file.filename}"
        output_path = os.path.join(FILES_PATH, unique_filename)

        with open(output_path, 'wb') as f:
            f.write(file.read())

        with Session() as cursor:
            new_position = Menu(
                name=name,
                ingredients=ingredients,
                description=description,
                price=price,
                weight=weight,
                file_name=unique_filename
            )
            cursor.add(new_position)
            cursor.commit()

        flash('Позицію додано успішно!')

    return render_template('add_position.html', csrf_token=session["csrf_token"], user=current_user)


@app.route('/menu')
def menu():
    with Session() as session_db:
        all_positions = session_db.query(Menu).filter_by(active=True).all()
    return render_template('menu.html', all_positions=all_positions, user=current_user)


@app.route("/position/<name>", methods=["GET", "POST"])
def position(name):
    with Session() as cursor:
        us_position = cursor.query(Menu).filter_by(
            active=True, name=name).first()
    if request.method == "POST":
        if request.form.get("csrf_token") != session["csrf_token"]:
            return "Запит заблоковано!", 403

        position_num = request.form.get("num")
        if "basket" not in session:
            basket = {}
        else:
            basket = session.get("basket")
        basket[us_position.id] = {
            "name": us_position.name, "count": position_num}
        session["basket"] = basket
        flash("Позицію додано у кошик!")

    return render_template(
        "position.html", csrf_token=session["csrf_token"], position=us_position, user=current_user)


@app.route("/create_order", methods=["GET", "POST"])
def create_order():
    basket = session.get("basket")
    if request.method == "POST":
        if request.form.get("csrf_token") != session["csrf_token"]:
            return "Запит заблоковано!", 403

        if not current_user:
            flash("Для оформлення замовлення необхідно бути зареєстрованим")
        else:
            if not basket:
                flash("Ваш кошик порожній")
            else:
                with Session() as cursor:
                    new_order = Orders(
                        order_list=basket,
                        order_time=datetime.now(),
                        user_id=current_user.id,
                    )
                    cursor.add(new_order)
                    cursor.commit()
                    session.pop("basket")
                    cursor.refresh(new_order)
                    return redirect(f"/my_order/{new_order.id}")

    return render_template(
        "create_order.html", csrf_token=session["csrf_token"], basket=basket, user=current_user)


@app.route("/my_order/<int:id>")
@login_required
def my_order(id):
    with Session() as cursor:
        us_order = cursor.query(Orders).filter_by(id=id).first()
        total_price = sum(
            int(cursor.query(Menu).filter_by(
                id=i).first().price) * int(data["count"])
            for i, data in us_order.order_list.items()
        )
    return render_template("my_order.html", order=us_order, total_price=total_price, user=current_user)


@app.route("/my_orders")
@login_required
def my_orders():
    with Session() as cursor:
        us_orders = cursor.query(Orders).filter_by(
            user_id=current_user.id).all()
    return render_template("my_orders.html", us_orders=us_orders, user=current_user)

@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for('home'))


TABLE_NUM = {"1-2": 5, "3-4": 2, "4+": 2}


@app.route("/reserved", methods=["GET", "POST"])
@login_required
def reserved():
    if request.method == "POST":
        if request.form.get("csrf_token") != session["csrf_token"]:
            return "Запит заблоковано!", 403

        table_type = request.form["table_type"]
        reserved_time_start = request.form["time"]

        with Session() as cursor:
            reserved_check = (
                cursor.query(Reservation).filter_by(
                    type_table=table_type).count()
            )
            user_reserved_check = (
                cursor.query(Reservation).filter_by(
                    user_id=current_user.id).first()
            )

            message = f"Бронь на {reserved_time_start} столика на {table_type} людини успішно створено!"
            if reserved_check < TABLE_NUM.get(table_type) and not user_reserved_check:
                new_reserved = Reservation(
                    type_table=table_type,
                    time_start=reserved_time_start,
                    user_id=current_user.id,
                )
                cursor.add(new_reserved)
                cursor.commit()
            elif user_reserved_check:
                message = "Можна мати лише одну активну бронь"
            else:
                message = "На жаль, бронь такого типу стола наразі неможлива"
            return render_template(
                "reserved.html", message=message, csrf_token=session["csrf_token"]
            )
    return render_template("reserved.html", csrf_token=session["csrf_token"], user=current_user)


@app.route("/reservations_check", methods=["GET", "POST"])
@login_required
def reservations_check():
    if current_user.nickname != "Admin":
        return redirect(url_for("home"))

    if request.method == "POST":
        if request.form.get("csrf_token") != session["csrf_token"]:
            return "Запит заблоковано!", 403

        reserv_id = request.form["reserv_id"]
        with Session() as cursor:
            reservation = cursor.query(
                Reservation).filter_by(id=reserv_id).first()
            cursor.delete(reservation)
            cursor.commit()

    with Session() as cursor:
        all_reservations = cursor.query(Reservation).all()
        return render_template(
            "reservations_check.html",
            all_reservations=all_reservations,
            csrf_token=session["csrf_token"],
            user=current_user
        )
    

@app.route('/menu_check', methods=['GET', 'POST'])
@login_required
def menu_check():
    if current_user.nickname != 'Admin':
        return redirect(url_for('home'))

    if request.method == 'POST':
        if request.form.get("csrf_token") != session['csrf_token']:
            return "Запит заблоковано!", 403

        position_id = request.form['pos_id']
        with Session() as cursor:
            position_obj = cursor.query(Menu).filter_by(id=position_id).first()
            if 'change_status' in request.form:
                position_obj.active = not position_obj.active
            elif 'delete_position' in request.form:
                cursor.delete(position_obj)
            cursor.commit()

    with Session() as cursor:
        all_positions = cursor.query(Menu).all()
    return render_template('menu_check.html', all_positions=all_positions, csrf_token=session["csrf_token"], user=current_user)


@app.route('/about')
def about():
    return render_template('about.html', user=current_user)


@app.route('/orders_check')
@login_required
def orders_check():
    if current_user.nickname != "Admin":
        return redirect(url_for("home"))

    with Session() as cursor:
        all_orders = cursor.query(Orders).all()

    return render_template(
        "orders_check.html",
        all_orders=all_orders,
        user=current_user
    )


@app.route('/all_users')
@login_required
def all_users():
    if current_user.nickname != 'Admin':
        return redirect(url_for('home'))

    with Session() as cursor:
        all_users = cursor.query(Users).with_entities(
            Users.id, Users.nickname, Users.email).all()
    return render_template('all_users.html', all_users=all_users, user=current_user)

if __name__ == '__main__':
    app.run(debug=True)

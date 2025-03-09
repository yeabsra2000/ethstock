from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import random
from datetime import datetime
from sqlalchemy.ext.mutable import MutableDict, MutableList

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///trading.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = "your_secret_key"

db = SQLAlchemy(app)

# Models with mutable PickleTypes for automatic change tracking
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    balance = db.Column(db.Float, default=10000)
    portfolio = db.Column(MutableDict.as_mutable(db.PickleType), default=dict)  # Stores a dict
    watchlist = db.Column(MutableList.as_mutable(db.PickleType), default=list)    # Stores a list

class Stock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(10), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    type = db.Column(db.String(10), nullable=False)  # "buy" or "sell"
    symbol = db.Column(db.String(10), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)  # price per unit at time of transaction
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# Create the database and add initial stocks if none exist.
with app.app_context():
    db.create_all()
    if Stock.query.first() is None:
        initial_stocks = [
            Stock(symbol="ETH1", name="Ethiopian Airlines", price=random.randint(60, 100)),
            Stock(symbol="ETH2", name="Ethio Telecom", price=random.randint(70, 150)),
            Stock(symbol="ETH3", name="Dashen Bank", price=random.randint(80, 200))
        ]
        db.session.add_all(initial_stocks)
        db.session.commit()

def update_stock_prices():
    """Randomly update stock prices on refresh."""
    stocks = Stock.query.all()
    for stock in stocks:
        # Change price by a random integer between -10 and 10, but not below 1.
        stock.price = max(1, stock.price + random.randint(-4, 4))
    db.session.commit()

def get_recent_transactions(user):
    # Get the 5 most recent transactions for the user.
    txs = Transaction.query.filter_by(user_id=user.id).order_by(Transaction.timestamp.desc()).limit(5).all()
    transactions = []
    for tx in txs:
        transactions.append({
            "type": tx.type,
            "symbol": tx.symbol,
            "quantity": tx.quantity,
            "price": tx.price,
            "timestamp": tx.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        })
    return transactions

@app.route("/")
def home():
    if "user" in session:
        return redirect(url_for("portfolio"))
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if User.query.filter_by(username=username).first():
            return "Username already exists!"

        hashed_password = generate_password_hash(password)
        new_user = User(username=username, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        session["user"] = username
        return redirect(url_for("portfolio"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session["user"] = username
            return redirect(url_for("portfolio"))
        return "Invalid credentials!"
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("home"))

@app.route("/portfolio")
def portfolio():
    if "user" not in session:
        return redirect(url_for("login"))
    update_stock_prices()  # Update stock prices on each refresh.
    user = User.query.filter_by(username=session["user"]).first()
    if not user:
        return redirect(url_for("login"))
    stocks = Stock.query.all()
    return render_template("portfolio.html", user=user, stocks=stocks)

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    update_stock_prices()  # Update prices before showing dashboard.
    user = User.query.filter_by(username=session["user"]).first()
    if not user:
        return "User not found!", 404
    recent_transactions = get_recent_transactions(user)
    market_trends = [{"symbol": stock.symbol, "price": stock.price} for stock in Stock.query.all()]
    return render_template("dashboard.html", 
                           dashboard={
                               "balance": user.balance,
                               "portfolio_value": sum([s["total_cost"] for s in user.portfolio.values()]),
                               "total_value": user.balance + sum([s["total_cost"] for s in user.portfolio.values()]),
                               "recent_transactions": recent_transactions,
                               "watchlist": user.watchlist,
                               "market_trends": market_trends
                           })

@app.route("/buy", methods=["POST"])
def buy():
    if "user" not in session:
        return jsonify({"error": "Not logged in"}), 401
    symbol = request.form["symbol"]
    quantity = int(request.form["quantity"])
    user = User.query.filter_by(username=session["user"]).first()
    stock = Stock.query.filter_by(symbol=symbol).first()
    if not stock:
        return jsonify({"error": "Stock not found"}), 404
    cost = stock.price * quantity
    if user.balance < cost:
        return jsonify({"error": "Insufficient funds"}), 400
    user.balance -= cost
    if symbol in user.portfolio:
        user.portfolio[symbol]["quantity"] += quantity
        user.portfolio[symbol]["total_cost"] += cost
    else:
        user.portfolio[symbol] = {"name": stock.name, "quantity": quantity, "total_cost": cost}
    # Record the buy transaction
    new_tx = Transaction(user_id=user.id, type="buy", symbol=symbol, quantity=quantity, price=stock.price)
    db.session.add(new_tx)
    db.session.commit()
    updated_portfolio = {"stocks": user.portfolio, "balance": user.balance}
    return jsonify(updated_portfolio)

@app.route("/sell", methods=["POST"])
def sell():
    if "user" not in session:
        return jsonify({"error": "Not logged in"}), 401
    symbol = request.form["symbol"]
    quantity = int(request.form["quantity"])
    user = User.query.filter_by(username=session["user"]).first()
    stock = Stock.query.filter_by(symbol=symbol).first()
    if not stock:
        return jsonify({"error": "Stock not found"}), 404
    if symbol not in user.portfolio or user.portfolio[symbol]["quantity"] < quantity:
        return jsonify({"error": "Not enough stock to sell"}), 400
    user.balance += stock.price * quantity
    user.portfolio[symbol]["quantity"] -= quantity
    user.portfolio[symbol]["total_cost"] -= stock.price * quantity
    if user.portfolio[symbol]["quantity"] == 0:
        del user.portfolio[symbol]
    # Record the sell transaction
    new_tx = Transaction(user_id=user.id, type="sell", symbol=symbol, quantity=quantity, price=stock.price)
    db.session.add(new_tx)
    db.session.commit()
    return jsonify({"success": True})

@app.route("/add_to_watchlist", methods=["POST"])
def add_to_watchlist():
    if "user" not in session:
        return jsonify({"error": "Not logged in"}), 401
    symbol = request.form["symbol"]
    user = User.query.filter_by(username=session["user"]).first()
    if symbol not in user.watchlist:
        user.watchlist.append(symbol)
        db.session.commit()
        return jsonify({"success": True})
    return jsonify({"error": "Stock already in watchlist"}), 400

@app.route("/remove_from_watchlist", methods=["POST"])
def remove_from_watchlist():
    if "user" not in session:
        return jsonify({"error": "Not logged in"}), 401
    symbol = request.form["symbol"]
    user = User.query.filter_by(username=session["user"]).first()
    if symbol in user.watchlist:
        user.watchlist.remove(symbol)
        db.session.commit()
        return jsonify({"success": True})
    return jsonify({"error": "Stock not in watchlist"}), 400

if __name__ == "__main__":
    app.run(debug=True)

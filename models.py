from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import date
db = SQLAlchemy()

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='child')  # 'parent' or 'child'
    credit_score = db.Column(db.Integer, default=575)
    allowance_rate = db.Column(db.Float, default=0.0)
    savings_apr = db.Column(db.Float, default=0.05)
    reward_points = db.Column(db.Integer, default=0)
    reset_password = db.Column(db.Boolean, default=False)
    totp_secret = db.Column(db.String(16), nullable=True, default="")
    two_factor_enabled = db.Column(db.Boolean, default=False)
    avatar = db.Column(db.String(120), default='default.gif')
    background = db.Column(db.String(120), default='default.png')

    def __repr__(self):
        return f'<User {self.username}>'

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # spending, savings, credit
    balance = db.Column(db.Float, default=0.0)
    interest_balance = db.Column(db.Float, default=0.0)
    credit_limit = db.Column(db.Float, default=0.0)
    interest_rate = db.Column(db.Float, default=0.0)
    due_date = db.Column(db.String(20), nullable=True)
    past_due = db.Column(db.Boolean, default=False)
    past_amt = db.Column(db.Float, default=0.0)

    user = db.relationship('User', backref='accounts')

    def __repr__(self):
        return f'<Account {self.id} {self.type} user:{self.user_id}>'

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    from_account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=True)
    to_account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=True)
    from_user_id = db.Column(db.Integer, nullable=True)
    to_user_id = db.Column(db.Integer, nullable=True)
    amount = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())
    description = db.Column(db.String(200), nullable=True)

    from_account = db.relationship('Account', foreign_keys=[from_account_id])
    to_account = db.relationship('Account', foreign_keys=[to_account_id])
    from_balance_after = db.Column(db.Float, nullable=True)
    to_balance_after   = db.Column(db.Float, nullable=True)

    def __repr__(self):
        return f'<Tx {self.id} {self.amount}>'

def init_db(app):
    with app.app_context():
        db.create_all()

import os
import io
import glob
import json
import pyotp
import qrcode
import base64
import requests
from dotenv import load_dotenv
from flask import Flask, render_template, redirect, url_for, request, flash, abort, current_app, session, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from models import db, User, Account, Transaction, init_db
from datetime import datetime, timedelta, date
from rewards import REWARDS
from config import *

load_dotenv(".env") 
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////homebank.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['AVATAR_FOLDER'] = AVATAR_FOLDER
app.config['BG_FOLDER'] = BG_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 15 * 1024 * 1024
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
LOG_FILE = os.path.join(os.path.dirname(__file__), "log/rewards_history.log")
AUTH_LOG_FILE = os.path.join(os.path.dirname(__file__), "log/auth.log")

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["2000 per day", "500 per hour"]
)

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = '/'
init_db(app)

def log_user_transaction(user, message):
    log_dir = "log/transactions"
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, user.username)
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    header = "TIMESTAMP           | ACTION   | ROUTE                | AMOUNT   | CHANGE                                   | REASON\n"
    separator = "-" * 135 + "\n"
    write_header = not os.path.exists(log_file) or os.path.getsize(log_file) == 0

    with open(log_file, "a") as f:
        if write_header:
            f.write(header)
            f.write(separator)
        f.write(f"{timestamp} | {message}\n")
        
def log_user_auth(user, message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    header = "TIMESTAMP           | RESULT  | ACTION              | USERNAME       | IP ADDRESS             \n"
    separator = "-" * 95 + "\n"

    write_header = not os.path.exists(AUTH_LOG_FILE) or os.path.getsize(AUTH_LOG_FILE) == 0

    with open(AUTH_LOG_FILE, "a") as f:
        if write_header:
            f.write(header)
            f.write(separator)
        f.write(f"{timestamp} | {message}\n")
        
def fmt_auth(result, event, user, ip):
        return (
            f"{result:<7} | "
            f"{event:<19} | "
            f"{user:<14} | "
            f"{ip}"
        )
        
def requires_role(role):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if current_user.role != role:
                abort(403)
            return f(*args, **kwargs)
        return wrapped
    return decorator
    
def build_ai_system_prompt(user, accounts, transactions):
    credit_acc = next((a for a in accounts if a.type == "credit"), None)
    spending_acc = next((a for a in accounts if a.type == "spending"), None)
    savings_acc = next((a for a in accounts if a.type == "savings"), None)

    # Calculate minimum due for credit
    remaining_min_due = 0
    if credit_acc:
        due_date = date.fromisoformat(credit_acc.due_date)
        start_cycle = due_date - timedelta(days=BILLING_CYCLE_DAYS - 1)
        start_dt = datetime.combine(start_cycle, datetime.min.time())
        end_dt = datetime.combine(due_date, datetime.max.time())

        draws = [tx.amount for tx in transactions
                 if tx.from_account_id == credit_acc.id and tx.description == 'Credit withdraw'
                 and start_dt <= tx.timestamp <= end_dt]
        payments = [tx.amount for tx in transactions
                    if tx.to_account_id == credit_acc.id and tx.description == 'Credit payment'
                    and start_dt <= tx.timestamp <= end_dt]

        carried_balance = max(credit_acc.past_amt, 0)
        min_due = round(MIN_PAYMENT_AMT * carried_balance, 2)
        borrowed_this_cycle = max(sum(draws) - sum(payments), 0)
        remaining_min_due = min_due - sum(payments)
        remaining_min_due = max(remaining_min_due, 0)

    context = f"""
You are a friendly, educational AI assistant embedded in a home banking web application called My Home Bank, designed for children and families.

Your role is to teach financial responsibility and guide users ONLY using the information explicitly provided below.

Today's Date: {datetime.now().strftime('%a, %Y-%m-%d')}

====================
STRICT INFORMATION BOUNDARY
====================

You MUST follow these rules:

- Only use information explicitly shown in this context.
- Never invent balances, transactions, interest amounts, dates, fees, or rules.
- Never assume missing data.
- Never estimate numbers unless they can be calculated directly from values provided here.
- If information is missing, say: "I don’t have enough information to determine that."
- Do NOT predict future balances unless you clearly show the calculation using only provided numbers.
- Do NOT fabricate transaction history.
- Do NOT fabricate credit score history.
- Do NOT fabricate billing cycle events.
- Do NOT create new rules, fees, or rewards.
- If unsure about an action, direct the user to /help.

You are not allowed to make up information.

====================
USER CONTEXT
====================
- Username: {user.username}
- Credit Score: {user.credit_score}
- Reward Points: {user.reward_points}
- Weekly Allowance: {user.allowance_rate} (automatically deposited into savings every Friday)
- Two-Factor Enabled: {user.two_factor_enabled}

====================
SPENDING ACCOUNT CONTEXT
====================
- Spending Balance: ${spending_acc.balance if spending_acc else 0}

====================
SAVINGS ACCOUNT CONTEXT
====================
- Savings Balance: ${savings_acc.balance if savings_acc else 0}
- Monthly Savings Interest Rate: {(user.savings_apr * 100) / 12}% (compounds monthly on due date)

====================
CREDIT ACCOUNT CONTEXT
====================
- Is {'' if credit_acc.past_due else 'NOT'} past due!
{f'- Past Due Amount: ${credit_acc.past_amt}' if credit_acc.past_due else ''}

- Credit Balance: ${credit_acc.balance if credit_acc else 0}
- Credit Limit: ${credit_acc.credit_limit if credit_acc else 0}
- Credit Utilization: {((credit_acc.balance / credit_acc.credit_limit) * 100) if credit_acc.credit_limit > 0 else 0}%
- Available Credit: ${credit_acc.credit_limit - credit_acc.balance}
- Minimum Due: ${remaining_min_due if credit_acc else 0}
- Due Date: {credit_acc.due_date if credit_acc else 'N/A'}
- Monthly Credit Interest Rate: {(credit_acc.interest_rate * 100) / 12 if credit_acc else 0}%
- Billing cycle length: 30 days

====================
ACCOUNT RULES
====================

SPENDING ACCOUNT:
- Available funds.
- Used for everyday purchases and payments.
- Used to pay credit balance.
- Receives redeemed reward cash.
- Can send money to other users' spending accounts.

SAVINGS ACCOUNT:
- Saved funds.
- Earns monthly compound interest.
- 10% fee on withdrawals.
- Can ONLY transfer to the user's own spending account.
- Minimum $1 withdrawal.
- Earns 1 reward point per $1 deposited.

CREDIT ACCOUNT:
- Borrowed funds.
- Has a credit limit.
- Borrowing increases credit balance.
- Payments decrease credit balance.
- Cannot be used in normal transfers.
- Must use credit-specific routes.
- Has a billing cycle and due date.
- Minimum payment is based on carried balance.
- ${NO_PAYMENT_FEE}0 late fee is added to balance if minimum not paid on time.
- Can become "past due" if minimum unpaid.
- Interest posts at the end of the billing cycle on the due date.

====================
CREDIT SCORE SCALE
====================
Credit score must be interpreted using this exact scale:

300–399: Very Poor
400–499: Poor
500–599: Fair
600–699: Good
700–799: Very Good
800–850: Excellent

- Accurately classify the score.
- Never describe a low score as “good,” “great,” or “excellent.”
- Be honest but supportive.
- Encourage improvement when score is below 600.

====================
TRANSFER RULES
====================
Route: dashboard → transfer

- Cannot transfer to the same account.
- Cannot transfer from credit account.
- Cannot transfer to credit account.
- Savings withdrawals have 10% penalty.
- Savings → only to own spending.
- Spending accounts of other users display as the username of the owner.

Process:
- Select "From" account (source account)
    - Spending
    - Savings
- Select "To" account (destination account)
    - Spending
    - Savings
    - Username of other user
- Set "Amount"
- Set "Description"
- Click "Transfer"

====================
CREDIT ACTIONS
====================
- dashboard → borrow - Borrow from credit to spending (cannot exceed available limit).
- dashboard → pay - Pay from spending to credit.
- If minimum due is fully paid, past due status clears.

Borrow Process:
- Enter amount
- Click Draw Funds

Pay Process:
- Enter amount
- Click Pay

====================
CREDIT SCORE FACTORS
====================

Score can increase for:
- Paying full balance on time.
- Keeping utilization below 30%.
- Making strong partial payments.
- Responsible borrowing and repayment.

Score can decrease for:
- Missing minimum payment.
- Carrying high utilization (over 80%).
- Going over credit limit.
- Making very small payments toward large balances.

High utilization = balance above 80% of limit.
Low utilization = balance below 30% of limit.
Credit maturity does not change score.
New credit accounts does not change score.
Credit score updates on the due date.

====================
REWARD SYSTEM
====================

Users earn reward points for:
- Depositing into savings. (1 point for every $1.00)
- Making strong credit payments. (up to {MAX_POINTS} points monthly)
- Responsible credit utilization.

Full, responsible payment earns the highest reward.
Partial payments may earn partial rewards.

Rewards can be redeemed at dashboard → reward points → redeem.
Cash rewards deposit into spending account.
Reward points do not expire.

====================
SITE NAVIGATION
====================

dashboard (Account overview, transactions, credit info)
dashboard → transfer (Transfer money between accounts)
dashboard → borrow (Borrow from credit)
dashboard → pay (Pay credit balance) 
dashboard → credit score → history (View graph showing credit score history)
dashboard → reward points → redeem (Use reward points to redeem rewards)
dashboard → preferences (Update profile/password/2FA)
dashboard → help (Financial education/assistance)

When advising users, reference these routes naturally.

====================
BEHAVIOR INSTRUCTIONS
====================
- Be friendly and encouraging.
- Use simple language appropriate for children.
- Avoid technical financial jargon unless explained.
- Explain financial concepts simply.
- Personalize advice using ONLY provided values.
- If data is missing, say you do not have enough information.
- Never guess.
- Never fabricate.
- Never simulate unseen system behavior.
- Never mention backend systems, databases, or implementation. 
"""
    return context

        
@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    flash('File is too large. Maximum size is 15 MB.', 'error')
    return redirect(url_for('preferences'))
    
@app.errorhandler(429)
def ratelimit_handler(e):
    flash('Too many failed attempts, try again later', 'error')
    msg = f"Rate limit exceeded"
    log_user_auth(current_user, f"{fmt_auth('ALERT', msg, '', request.remote_addr)}")
    return redirect(url_for('index'))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
    
@app.route('/favicon.ico')
def favicon():
    return send_from_directory('static', 'favicon.ico')

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['POST'])
@limiter.limit("5 per minute")
def login():
    username = request.form.get('username')
    password = request.form.get('password')
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    user = User.query.filter_by(username=username).first()

    # ---- User not found ----
    if user is None:
        log_user_auth(user, f"{fmt_auth('FAIL', 'INVALID USER', username, request.remote_addr)}")

        flash('Invalid credentials', 'error')
        return redirect(url_for('index'))

    # ---- Wrong password ----
    if not check_password_hash(user.password_hash, password):
        log_user_auth(user, f"{fmt_auth('FAIL', 'BAD PASSWORD', username, request.remote_addr)}")

        flash('Invalid credentials', 'error')
        return redirect(url_for('index'))

    # ---- 2FA required ----
    if user.two_factor_enabled:
        session['pre_2fa_user'] = user.id
        log_user_auth(user, f"{fmt_auth('PENDING', '2FA VERIFICATION', username, request.remote_addr)}")

        return redirect(url_for('two_factor_verify'))

    # ---- Successful login ----
    login_user(user)
    log_user_auth(user, f"{fmt_auth('SUCCESS', 'LOGIN', username, request.remote_addr)}")

    db.session.refresh(user)
    return redirect(url_for('dashboard')) 

@app.route('/logout')
@login_required
def logout():
    log_user_auth(current_user, f"{fmt_auth('SUCCESS', 'LOGOUT', current_user.username, request.remote_addr)}")

    logout_user()
    return redirect(url_for('index'))
    
@app.route("/rewards")
@login_required
def rewards():
    reset_required = current_user.reset_password
    if reset_required:
        return redirect(url_for('reset_password'))
    return render_template("rewards.html", rewards=REWARDS, user=current_user)

@app.route("/redeem/<int:points>", methods=["POST"])
@login_required
def redeem(points):
    def fmt(action, path, amount, balance, desc=''):
        return (
            f"{action:<8} | "
            f"{path:<20} | "
            f"{amount:<8} | "
            f"{balance:<41}"
            f"{' | ' + desc if desc else ''}"
        )
            
    reward = next((r for r in REWARDS if r["points"] == points), None)
    if not reward:
        flash("Invalid reward.", "error")
        return redirect(url_for("rewards"))

    if current_user.reward_points < points:
        flash("Not enough reward points.", "error")
        return redirect(url_for("rewards"))

    current_user.reward_points -= points

    if reward["type"] == "cash":
        spending_account = Account.query.filter_by(user_id=current_user.id, type="spending").first()
        if spending_account:
            og_balance = spending_account.balance
            spending_account.balance += reward["amount"]
            tx = Transaction(
                from_account_id=None,
                to_account_id=spending_account.id,
                from_user_id=None,
                to_user_id=current_user.id,
                amount=reward["amount"],
                to_balance_after=spending_account.balance,
                description=f"Redeemed reward: {reward['name']}"
            )
            db.session.add(tx)
            
            log_user_transaction(
                current_user,
                fmt(
                    "REWARD",
                    f"Bank → {spending_account.type}",
                    f"${reward["amount"]}",
                    f"${og_balance:.2f} → ${spending_account.balance:.2f}",
                    'Redeemed reward points'
                )
            )
    db.session.commit()

    with open(LOG_FILE, "a") as f:
        log_entry = (
            f"\n============ {datetime.now():%m-%d-%Y %H:%M} =============\n"
            f" User      : {current_user.username}\n"
            f" Reward    : {reward['name']}\n"
            f" Points    : {points} points\n"
        )
        f.write(log_entry)
    flash(f"Successfully redeemed: {reward['name']}", "success")
    return redirect(url_for("rewards"))

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.reset_password:
        return redirect(url_for('reset_password'))

    accounts = Account.query.filter_by(user_id=current_user.id).all()

    transactions = (
        Transaction.query
        .filter(
            (Transaction.from_user_id == current_user.id) |
            (Transaction.to_user_id == current_user.id)
        )
        .order_by(
            Transaction.timestamp.desc(),
            Transaction.id.desc()
        )
        .all()
    )

    credit_info = {}
    credit_alerts = []
    today = date.today()

    for acc in accounts:
        if acc.type != 'credit' or not acc.due_date:
            continue

        due_date = date.fromisoformat(acc.due_date)

        start_cycle = due_date - timedelta(days=BILLING_CYCLE_DAYS - 1)
        start_dt = datetime.combine(start_cycle, datetime.min.time())
        end_dt = datetime.combine(due_date, datetime.max.time())

        # ---------- Transactions ----------
        draws = Transaction.query.filter(
            Transaction.from_account_id == acc.id,
            Transaction.description == 'Credit withdraw',
            Transaction.timestamp >= start_dt,
            Transaction.timestamp <= end_dt
        ).all()
        total_drawn = sum(tx.amount for tx in draws)

        payments = Transaction.query.filter(
            Transaction.to_account_id == acc.id,
            Transaction.description == 'Credit payment',
            Transaction.timestamp >= start_dt,
            Transaction.timestamp <= end_dt
        ).all()
        total_paid = sum(tx.amount for tx in payments)

        # ---------- Minimum Due ----------
        carried_balance = max(acc.past_amt, 0)
        borrowed_this_cycle = max(total_drawn - total_paid, 0)
        min_due = round(MIN_PAYMENT_AMT * carried_balance, 2)
        remaining_min_due = min_due
        paid_toward_min_due = 0.0

        for p in payments:
            if remaining_min_due <= 0:
                break
            applied = min(p.amount, remaining_min_due)
            paid_toward_min_due += applied
            remaining_min_due -= applied

        credit_info[acc.id] = {
            'due_date': acc.due_date,
            'min_due': min_due,
            'paid_toward_min_due': round(paid_toward_min_due, 2),
            'remaining_min_due': round(max(remaining_min_due, 0), 2)
        }

        # ---------- Alerts ----------
        if remaining_min_due > 0 and due_date <= today:
            credit_alerts.append({
                'past_due': acc.past_due,
                'account_id': acc.id,
                'balance': acc.balance,
                'due_date': due_date.strftime('%b %d, %Y'),
                'min_due': min_due,
                'remaining_min_due': round(max(remaining_min_due, 0), 2)
            })
        elif acc.past_due:
            credit_alerts.append({
                'past_due': acc.past_due,
                'account_id': acc.id,
                'balance': acc.balance,
                'due_date': (due_date - timedelta(days=30)).strftime('%b %d, %Y'),
                'min_due': min_due,
                'remaining_min_due': round(max(remaining_min_due, 0), 2)
            })

    return render_template(
        'dashboard.html',
        accounts=accounts,
        transactions=transactions,
        credit_info=credit_info,
        credit_alerts=credit_alerts,
        timestamp = datetime.now().strftime('%b %d, %Y')
    )

@app.route('/transfer', methods=['GET', 'POST'])
@login_required
def transfer():
    if current_user.reset_password:
        return redirect(url_for('reset_password'))
        
    def fmt(action, path, amount, balance, desc=''):
            return (
                f"{action:<8} | "
                f"{path:<20} | "
                f"{amount:<8} | "
                f"{balance:<41}"
                f"{' | ' + desc if desc else ''}"
            )

    if request.method == 'POST':
        from_raw = request.form['from_account']
        to_raw   = request.form['to_account']
        amount   = round(float(request.form['amount']), 2)
        desc     = request.form.get('description', '').strip()

        # ---- Parent-only Bank handling ----
        from_bank = from_raw == 'bank'
        to_bank   = to_raw == 'bank'

        if (from_bank or to_bank) and current_user.role != 'parent':
            abort(403)
            
        if from_bank and to_bank:
            flash('Cannot transfer to the same account', 'error')
            return redirect(url_for('transfer'))

        from_acc = None if from_bank else Account.query.get_or_404(int(from_raw))
        to_acc   = None if to_bank else Account.query.get_or_404(int(to_raw))
        og_from_balance = from_acc.balance if from_acc else None
        og_to_balance = to_acc.balance if to_acc else None

        # ---- Validation ----
        if not from_bank and not to_bank and from_acc.id == to_acc.id:
            flash('Cannot transfer to the same account', 'error')
            return redirect(url_for('transfer'))

        if not from_bank and from_acc.user_id != current_user.id and current_user.role != 'parent':
            abort(403)

        if amount <= 0:
            flash('Invalid transfer amount', 'error')
            return redirect(url_for('transfer'))

        if not from_bank and from_acc.type == 'credit':
            flash('Cannot transfer from credit accounts', 'error')
            return redirect(url_for('transfer'))

        if not to_bank and to_acc.type == 'credit':
            flash('Cannot transfer to credit accounts', 'error')
            return redirect(url_for('transfer'))

        # ---- Savings rules ----
        penalty = 0
        if not from_bank and from_acc.type == 'savings':
            if not (
                not to_bank and
                to_acc.user_id == from_acc.user_id and
                to_acc.type == 'spending'
            ):
                flash('Savings can only transfer to your own spending account', 'error')
                return redirect(url_for('transfer'))

            if amount < 1.00:
                flash('Minimum $1 transfer from savings required', 'error')
                return redirect(url_for('transfer'))

            penalty = round(amount * 0.10, 2)
            total = amount + penalty

            if from_acc.balance < total:
                flash(f'Insufficient funds including ${penalty:.2f} penalty', 'error')
                return redirect(url_for('transfer'))

            from_acc.balance -= penalty

            if penalty >= 0.01:
                db.session.add(Transaction(
                    from_account_id=from_acc.id,
                    to_account_id=None,
                    from_user_id=from_acc.user_id,
                    to_user_id=None,
                    amount=penalty,
                    from_balance_after=from_acc.balance,
                    to_balance_after=to_acc.balance,
                    description='Savings withdrawal penalty'
                ))
                log_user_transaction(
                    current_user,
                    fmt(
                        "PENALTY",
                        f"{from_acc.type} → Bank",
                        f"${penalty:.2f}",
                        f"${og_from_balance:.2f} → ${from_acc.balance:.2f}",
                        'Savings withdrawal penalty'
                    )
                )
                og_from_balance = from_acc.balance
                flash(f'Savings withdrawal penalty applied: ${penalty:.2f}', 'error')

        # ---- Debit source ----
        if not from_bank:
            if from_acc.balance < amount:
                flash('Insufficient funds', 'error')
                return redirect(url_for('transfer'))
            from_acc.balance -= amount

        # ---- Credit destination ----
        if not to_bank:
            to_acc.balance += amount

        # ---- Transaction log ----
        db.session.add(Transaction(
            from_account_id=None if from_bank else from_acc.id,
            to_account_id=None if to_bank else to_acc.id,
            from_user_id=current_user.id if from_bank else from_acc.user_id,
            to_user_id=None if to_bank else to_acc.user_id,
            amount=amount,
            from_balance_after=None if from_bank else from_acc.balance,
            to_balance_after=to_acc.balance,
            description=desc or (
                'Bank deposit' if from_bank else
                'Bank withdrawal' if to_bank else
                'Transfer'
            )
        ))

        # ---- Activity logs ----
        if from_bank:
            log_user_transaction(
                current_user,
                fmt(
                    "TRANSFER",
                    f"Bank → {to_acc.user.username}",
                    f"${amount:.2f}",
                    f"${og_to_balance:.2f} → ${to_acc.balance:.2f}",
                    desc
                )
            )

            log_user_transaction(
                to_acc.user,
                fmt(
                    "RECEIVED",
                    f"Bank → {to_acc.type}",
                    f"${amount:.2f}",
                    f"${og_to_balance:.2f} → ${to_acc.balance:.2f}",
                    desc
                )
            )

        elif to_bank:
            log_user_transaction(
                from_acc.user,
                fmt(
                    "TRANSFER",
                    f"{from_acc.type} → Bank",
                    f"${amount:.2f}",
                    f"${og_from_balance:.2f} → ${from_acc.balance:.2f}",
                    desc
                )
            )

        elif from_acc.user == to_acc.user:
            log_user_transaction(
                from_acc.user,
                fmt(
                    "TRANSFER",
                    f"{from_acc.type} → {to_acc.type}",
                    f"${amount:.2f}",
                    f"${og_from_balance:.2f} → ${from_acc.balance:.2f} ≡ "
                    f"${og_to_balance:.2f} → ${to_acc.balance:.2f}",
                    desc
                )
            )

        else:
            log_user_transaction(
                from_acc.user,
                fmt(
                    "TRANSFER",
                    f"{from_acc.type} → {to_acc.user.username}",
                    f"${amount:.2f}",
                    f"${og_from_balance:.2f} → ${from_acc.balance:.2f}",
                    desc
                )
            )

            log_user_transaction(
                to_acc.user,
                fmt(
                    "RECEIVED",
                    f"{from_acc.user.username} → {to_acc.type}",
                    f"${amount:.2f}",
                    f"${og_to_balance:.2f} → ${to_acc.balance:.2f}",
                    desc
                )
            )

        # ---- Rewards ----
        if not to_bank and to_acc.type == 'savings' and to_acc.user_id == current_user.id:
            points = int(amount * SAVINGS_REWARD_RATE)
            current_user.reward_points = (current_user.reward_points or 0) + points
            flash(f'Awarded {points} reward points for adding to savings!', 'success')

        db.session.commit()

        flash(f'Transfer of ${amount:.2f} completed successfully', 'success')
        return redirect(url_for('transfer'))

    # ---- Account lists ----
    if current_user.role == 'parent':
        accounts = Account.query.filter(Account.type.in_(['spending', 'savings'])).all()
    else:
        accounts = Account.query.filter_by(user_id=current_user.id)\
            .filter(Account.type.in_(['spending', 'savings'])).all()

    own_savings = Account.query.filter_by(user_id=current_user.id, type='savings').all()
    own_spending = Account.query.filter_by(user_id=current_user.id, type='spending').all()
    other_spending = Account.query.filter(
        Account.user_id != current_user.id,
        Account.type == 'spending'
    ).all()

    other_accounts = own_savings + own_spending + other_spending

    return render_template(
        'transfer.html',
        accounts=accounts,
        other_accounts=other_accounts
    )

@app.route('/credit/withdraw', methods=['GET','POST'])
@login_required
def credit_withdraw():
    reset_required = current_user.reset_password
    if reset_required:
        return redirect(url_for('reset_password'))
        
    def fmt(action, path, amount, balance, desc=''):
        return (
            f"{action:<8} | "
            f"{path:<20} | "
            f"{amount:<8} | "
            f"{balance:<41}"
            f"{' | ' + desc if desc else ''}"
        )
        
    credit = Account.query.filter_by(user_id=current_user.id, type='credit').first()
    spending = Account.query.filter_by(user_id=current_user.id, type='spending').first()
    og_from_balance = credit.balance if credit else None
    og_to_balance = spending.balance if spending else None
    
    if request.method == 'POST':
        amount = round(float(request.form['amount']), 2)
        if credit is None or spending is None:
            flash('Missing accounts', 'error')
            return redirect(url_for('dashboard'))
        available = credit.credit_limit - credit.balance
        if amount > available:
            flash('Amount exceeds credit limit', 'error')
            return redirect(url_for('credit_withdraw'))

        credit.balance += amount
        spending.balance += amount
        tx = Transaction(from_account_id=credit.id, to_account_id=spending.id,
                         from_user_id=current_user.id, to_user_id=current_user.id,
                         amount=amount, from_balance_after=credit.balance,
                         to_balance_after=spending.balance, description='Credit withdraw')
        db.session.add(tx)
        db.session.commit()
        log_user_transaction(
            current_user,
            fmt(
                "TRANSFER",
                f"{credit.type} → {spending.type}",
                f"${amount:.2f}",
                f"${og_from_balance:.2f} → ${credit.balance:.2f} ≡ "
                f"${og_to_balance:.2f} → ${spending.balance:.2f}",
                'Credit withdraw'
            )
        )
        flash(f"Borrowed ${amount:.2f} from credit", 'success')
        return redirect(url_for('credit_withdraw'))
    return render_template('credit_withdraw.html', credit=credit, spending=spending)

@app.route('/credit/pay', methods=['GET','POST'])
@login_required
def credit_pay():
    reset_required = current_user.reset_password
    if reset_required:
        return redirect(url_for('reset_password'))
        
    def fmt(action, path, amount, balance, desc=''):
        return (
            f"{action:<8} | "
            f"{path:<20} | "
            f"{amount:<8} | "
            f"{balance:<41}"
            f"{' | ' + desc if desc else ''}"
        )    
    
    credit = Account.query.filter_by(user_id=current_user.id, type='credit').first()
    spending = Account.query.filter_by(user_id=current_user.id, type='spending').first()
    og_from_balance = spending.balance if spending else None
    og_to_balance = credit.balance if credit else None

    if request.method == 'POST':
        amount = round(float(request.form['amount']), 2)

        if spending.balance < amount:
            flash('Insufficient funds in spending account', 'error')
            return redirect(url_for('credit_pay'))
        elif amount > credit.balance:
            flash('Amount exceeds balance due', 'error')
            return redirect(url_for('credit_pay'))

        carried_balance = max(credit.past_amt, 0)
        min_due = round(MIN_PAYMENT_AMT * carried_balance, 2)
        cycle_start = date.fromisoformat(credit.due_date) - timedelta(days=30)
        cycle_start_dt = datetime.combine(cycle_start, datetime.min.time())
        cycle_end_dt = datetime.combine(date.fromisoformat(credit.due_date), datetime.max.time())

        payments = Transaction.query.filter(
            Transaction.to_account_id == credit.id,
            Transaction.description == 'Credit payment',
            Transaction.timestamp >= cycle_start_dt,
            Transaction.timestamp <= cycle_end_dt
        ).all()

        already_paid = sum(tx.amount for tx in payments)
        remaining_min_due = round(max(min_due - already_paid, 0), 2)
        applied_to_min = min(amount, remaining_min_due)
        remaining_min_due -= applied_to_min

        if credit.past_due and remaining_min_due <= 0:
            credit.past_due = False
            flash('Your account is no longer past due 😃', 'success')

        spending.balance -= amount
        credit.balance -= amount
        

        tx = Transaction(
            from_account_id=spending.id,
            to_account_id=credit.id,
            from_user_id=spending.user_id,
            to_user_id=credit.user_id,
            amount=amount,
            from_balance_after=spending.balance,
            to_balance_after=credit.balance,
            description='Credit payment'
        )
        db.session.add(tx)

        db.session.commit()
        log_user_transaction(
            current_user,
            fmt(
                "PAYMENT",
                f"{spending.type} → {credit.type}",
                f"${amount:.2f}",
                f"${og_from_balance:.2f} → ${spending.balance:.2f} ≡ "
                f"${og_to_balance:.2f} → ${credit.balance:.2f}",
                "Credit payment"
            )
        )
        flash(f'Thank you for your payment! ${amount:.2f} applied to credit balance', 'success')
        return redirect(url_for('credit_pay'))

    return render_template('credit_pay.html', credit=credit, spending=spending)
    
@app.route("/credit-history")
@login_required
def credit_history():
    reset_required = current_user.reset_password
    if reset_required:
        return redirect(url_for('reset_password'))
        
    history = []

    if os.path.exists(CREDIT_HISTORY_FILE):
        with open(CREDIT_HISTORY_FILE, "r") as f:
            data = json.load(f)

            history = [
                entry for entry in data
                if entry["user_id"] == current_user.id
            ]

    history.sort(key=lambda x: x["timestamp"])

    return render_template(
        "credit_history.html",
        history=history
    )

@app.route('/admin', methods=['GET', 'POST'])
@login_required
@requires_role('parent')
def admin_panel():

    users = User.query.all()
    logs = {}

    def read_log(path):
        try:
            with open(path, 'r') as f:
                return ''.join(f.readlines())
        except FileNotFoundError:
            return "Log file not found."
        except Exception as e:
            return f"Error reading log: {e}"
            
    def fmt(action, path, amount, balance, desc=''):
        return (
            f"{action:<8} | "
            f"{path:<20} | "
            f"{amount:<8} | "
            f"{balance:<41}"
            f"{' | ' + desc if desc else ''}"
        )    

    logs['Rewards'] = read_log(LOG_FILE)
    logs['Credit'] = read_log('log/interest_history.log')
    logs['Authentication'] = read_log(AUTH_LOG_FILE)

    transaction_logs = {}
    for file_path in sorted(glob.glob('log/transactions/*')):
        filename = os.path.basename(file_path)
        transaction_logs[filename] = read_log(file_path)

    logs['Transactions'] = transaction_logs

    if request.method == 'POST':
        try:
            user_id = int(request.form.get('user_id', 0))
        except ValueError:
            abort(400)
        user = User.query.get(user_id)
        new_password = request.form.get('password')
        if new_password:
            user.password_hash = generate_password_hash(new_password)
            log_user_auth(user, f"{fmt_auth('ALERT', 'PASSWORD RESET', user.username, request.remote_addr)}")
            flash(f"Password reset required for {user.username}", "success")
            user.reset_password = True

        for acc_type in ['spending', 'savings', 'credit']:
            new_balance = request.form.get(f'{acc_type}_balance')
            if new_balance is not None and new_balance != '':
                acc = Account.query.filter_by(user_id=user.id, type=acc_type).first()
                if acc:
                    og_balance = acc.balance
                    acc.balance = float(new_balance)
                    if og_balance != acc.balance:
                        log_user_transaction(
                            acc.user,
                            fmt(
                                "MODIFIED",
                                f"{acc.user.username} {acc.type}",
                                f"${(acc.balance - og_balance):.2f}",
                                f"${og_balance:.2f} → ${acc.balance:.2f}",
                                f"Balance Changed by {current_user.username}"
                            )
                        )
                    

        new_credit_limit = request.form.get('credit_limit')
        if new_credit_limit is not None and new_credit_limit != '':
            credit_acc = Account.query.filter_by(user_id=user.id, type='credit').first()
            if credit_acc:
                credit_acc.credit_limit = float(new_credit_limit)

        new_interest_rate = request.form.get('interest_rate')
        if new_interest_rate is not None and new_interest_rate != '':
            credit_acc = Account.query.filter_by(user_id=user.id, type='credit').first()
            if credit_acc:
                credit_acc.interest_rate = float(new_interest_rate)

        new_rewards = request.form.get('reward_points')
        if new_rewards is not None and new_rewards != '':
            user.reward_points = int(new_rewards)
            
        new_score = request.form.get('credit_score')
        if new_score is not None and new_score != '':
            user.credit_score = max(300, min(850, int(new_score)))
            
        new_allowance = request.form.get('allowance_rate')
        if new_allowance is not None and new_allowance != '':
            user.allowance_rate = float(new_allowance)
            
        new_savings_rate = request.form.get('savings_apr')
        if new_savings_rate is not None and new_savings_rate != '':
            user.savings_apr = float(new_savings_rate)
            
        # --- 2FA toggle ---
        two_fa_requested = 'two_factor_enabled' in request.form
        if two_fa_requested == 1 and not user.two_factor_enabled:
            flash('You can only disable 2FA, setup must be performed by user', 'error')
            return redirect(url_for('admin_panel'))
        elif two_fa_requested == 0 and user.two_factor_enabled: 
            user.two_factor_enabled = False
            user.totp_secret = None

        db.session.commit()
        flash(f'Updated user {user.username}', 'success')
        return redirect(url_for('admin_panel'))

    return render_template('admin.html', users=users, logs=logs)

@app.route('/admin/create_user', methods=['GET','POST'])
@login_required
@requires_role('parent')
def admin_create_user():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        
        if User.query.filter_by(username=username).first():
            flash('Username exists', 'error')
            return redirect(url_for('admin_create_user'))
        u = User(username=username, password_hash=generate_password_hash(password), role=role)
        db.session.add(u)
        db.session.commit()

        for acc_type in ['spending','savings','credit']:
            acc = Account(user_id=u.id, type=acc_type, balance=0.0)
            if acc_type == 'credit':
                acc.credit_limit = 0.0
                acc.interest_rate = 0.022
                acc.due_date = (date.today() + timedelta(days=30)).isoformat()
            db.session.add(acc)
        db.session.commit()
        flash('User created', 'success')
        return redirect(url_for('admin_panel'))
    return render_template('admin_create_user.html')

@app.route('/reset-password', methods=['GET', 'POST'])
@login_required
def reset_password():
    if not current_user.reset_password:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if new_password != confirm_password:
            flash('New passwords do not match', 'error')
            return redirect(url_for('reset_password'))

        if len(new_password) < MIN_PASS_LENGTH:
            flash(f"Password must be at least {MIN_PASS_LENGTH} characters", 'error')
            return redirect(url_for('reset_password'))

        current_user.password_hash = generate_password_hash(new_password)
        current_user.reset_password = False
        db.session.commit()
        log_user_auth(current_user, f"{fmt_auth('ALERT', 'PASSWORD CHANGED', current_user.username, request.remote_addr)}")
        flash('Password updated successfully', 'success')
        return render_template('reset_password.html', next_url=url_for('dashboard'))

    return render_template('reset_password.html')
    
@app.route("/help")
@login_required
def help():
    credit_acc = Account.query.filter_by(user_id=current_user.id, type='credit').first()
    return render_template(
        "help.html",
        current_user=current_user,
        SAVINGS_REWARD_RATE=SAVINGS_REWARD_RATE,
        MAX_POINTS=MAX_POINTS,
        MIN_SCORE=MIN_SCORE,
        MAX_SCORE=MAX_SCORE,
        SAVINGS_RATE=current_user.savings_apr,
        CREDIT_RATE=credit_acc.interest_rate
    )

@app.route("/ai_help", methods=["POST"])
@login_required
def ai_help():
    message = request.json.get("message", "").strip()
    if not message:
        return {"response": "Please enter a question."}

    # Gather context
    accounts = Account.query.filter_by(user_id=current_user.id).all()
    transactions = Transaction.query.filter(
        (Transaction.from_user_id == current_user.id) |
        (Transaction.to_user_id == current_user.id)
    ).all()

    system_prompt = build_ai_system_prompt(current_user, accounts, transactions)

    try:
        response = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": "llama3.2:latest",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message}
                ],
                "stream": False,
                "options": {
                  "temperature": 0.0,
                  "top_p": 0.9,
                  "repeat_penalty": 1.05
                }
            },
            timeout=120
        )
        result = response.json()
        ai_reply = result["message"]["content"]
    except Exception:
        ai_reply = "AI assistant is currently unavailable."

    return {"response": ai_reply}


@app.route('/2fa/setup', methods=['GET', 'POST'])
@login_required
def two_factor_setup():
    if request.method == 'POST':
        token = request.form.get('token')
        totp = pyotp.TOTP(current_user.totp_secret)
        if totp.verify(token, valid_window=1):
            current_user.two_factor_enabled = True
            db.session.commit()
            log_user_auth(current_user, f"{fmt_auth('ALERT', '2FA ENABLED', current_user.username, request.remote_addr)}")
            flash('Two factor authentication enabled successfully', 'success')
            return redirect(url_for('preferences'))
        else:
            flash('Invalid token', 'error')
            return redirect(url_for('two_factor_setup'))

    if not current_user.totp_secret:
        current_user.totp_secret = pyotp.random_base32()
        db.session.commit()

    totp_uri = pyotp.totp.TOTP(current_user.totp_secret).provisioning_uri(
        name=current_user.username, issuer_name="My Home Bank"
    )

    img = qrcode.make(totp_uri)
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    qr_data = base64.b64encode(buffer.getvalue()).decode()

    return render_template('2fa_setup.html', qr_data=qr_data)
    
@app.route('/2fa/verify', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def two_factor_verify():
    user_id = session.get('pre_2fa_user')
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if not user_id:
        flash('Session expired, login again', 'error')
        return redirect(url_for('index'))

    user = User.query.get(user_id)

    if request.method == 'POST':
        token = request.form.get('token')
        totp = pyotp.TOTP(user.totp_secret)
        if totp.verify(token, valid_window=1):
            login_user(user)
            session.pop('pre_2fa_user', None)
            log_user_auth(user, f"{fmt_auth('SUCCESS', '2FA VERIFIED', user.username, request.remote_addr)}")
            return redirect(url_for('dashboard'))
        else:
            with open(AUTH_LOG_FILE, "a") as f:
                log_user_auth(user, f"{fmt_auth('FAIL', '2FA BAD CODE', user.username, request.remote_addr)}")
            flash('Invalid 2FA code', 'error')

    return render_template('2fa_verify.html')
    
@app.route('/2fa/disable', methods=['POST'])
@login_required
def two_factor_disable():
    current_user.two_factor_enabled = False
    current_user.totp_secret = None
    db.session.commit()
    log_user_auth(current_user, f"{fmt_auth('ALERT', '2FA DISABLED', current_user.username, request.remote_addr)}")
    flash('Two factor authentication disabled', 'success')
    return redirect(url_for('preferences'))

@app.route('/preferences', methods=['GET', 'POST'])
@login_required
def preferences():
    if current_user.reset_password:
        return redirect(url_for('reset_password'))

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'profile':
            # Username change
            new_username = request.form.get('username', '').strip()
            if not new_username:
                flash('Username cannot be empty', 'error')
                return redirect(url_for('preferences'))
                
            if len(new_username) > 30:
                flash('Username cannot be longer than 30 characters', 'error')
                return redirect(url_for('preferences'))

            existing = User.query.filter(
                User.username == new_username,
                User.id != current_user.id
            ).first()
            if existing:
                flash('Username already taken', 'error')
                return redirect(url_for('preferences'))

            current_user.username = new_username

            # Avatar upload
            file = request.files.get('avatar')
            if file and file.filename:
                if not allowed_file(file.filename):
                    flash('Invalid file type', 'error')
                    return redirect(url_for('preferences'))

                filename = secure_filename(
                    f"user_{current_user.id}.{file.filename.rsplit('.',1)[1].lower()}"
                )

                os.makedirs(app.config['AVATAR_FOLDER'], exist_ok=True)
                file_path = os.path.join(app.config['AVATAR_FOLDER'], filename)
                file.save(file_path)

                current_user.avatar = filename
                
            # Background upload
            bg_file = request.files.get('background')
            if bg_file and bg_file.filename:
                if not allowed_file(bg_file.filename):
                    flash('Invalid background file type', 'error')
                    return redirect(url_for('preferences'))

                bg_filename = secure_filename(
                    f"user_{current_user.id}.{bg_file.filename.rsplit('.',1)[1].lower()}"
                )
                os.makedirs(app.config['BG_FOLDER'], exist_ok=True)
                bg_file.save(os.path.join(app.config['BG_FOLDER'], bg_filename))
                current_user.background = bg_filename

            db.session.commit()
            flash('Profile updated successfully', 'success')

        # Password update
        elif action == 'password':
            password = request.form.get('password')
            confirm = request.form.get('confirm_password')

            if not password or not confirm:
                flash('Password fields cannot be empty', 'error')
                return redirect(url_for('preferences'))

            if password != confirm:
                flash('Passwords do not match', 'error')
                return redirect(url_for('preferences'))

            if len(password) < MIN_PASS_LENGTH:
                flash(f"Password must be at least {MIN_PASS_LENGTH} characters", 'error')
                return redirect(url_for('preferences'))

            current_user.password_hash = generate_password_hash(password)
            current_user.reset_password = False
            db.session.commit()
            flash('Password updated successfully', 'success')

        return redirect(url_for('preferences'))

    return render_template('preferences.html')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

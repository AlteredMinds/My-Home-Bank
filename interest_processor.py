import json
import math
import time
import os
from app import app
from config import *
from models import db, Account, Transaction, User
from datetime import datetime, timezone, date, timedelta

def get_interest_rate(account: Account):
    if not account or not account.interest_rate:
        return 0.0, 0.0
    apr = float(account.interest_rate)
    monthly_rate = round(apr / 12.0, 6)
    return apr, monthly_rate


def parse_date_iso(s):
    try:
        return date.fromisoformat(s) if s else None
    except Exception:
        return None


def log_credit_snapshot(user, credit_account):
    entry = {
        "user_id": user.id,
        "username": user.username,
        "account_id": credit_account.id,
        "balance": round(credit_account.balance, 2),
        "credit_limit": credit_account.credit_limit or 0,
        "credit_score": user.credit_score,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    if not os.path.exists(CREDIT_HISTORY_FILE):
        with open(CREDIT_HISTORY_FILE, "w") as f:
            json.dump([], f, indent=2)

    with open(CREDIT_HISTORY_FILE, "r+") as f:
        data = json.load(f)
        data.append(entry)
        f.seek(0)
        json.dump(data, f, indent=2)


def log_interest(message: str, new_cycle: bool = False):
    os.makedirs(os.path.dirname(INTEREST_LOG_FILE), exist_ok=True)
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%m-%d-%Y")

    with open(INTEREST_LOG_FILE, "a") as f:
        if new_cycle:
            f.write(
                "\n"
                + "=" * 72 + "\n"
                f"MONTHLY_BILLING_SUMMARY | DATE: {date_str}\n"
                + "=" * 72 + "\n"
            )
        f.write(
            f"{message.strip()}\n"
        )
        
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
        
def fmt(action, path, amount, balance, desc=''):
    return (
        f"{action:<8} | "
        f"{path:<20} | "
        f"{amount:<8} | "
        f"{balance:<41}"
        f"{' | ' + desc if desc else ''}"
    )


def apply_monthly_billing():
    today = date.today()
    old_due = None

    with app.app_context():
        credits = Account.query.filter_by(type='credit').all()

        for credit in credits:
            user = db.session.get(User, credit.user_id)
            due_date = parse_date_iso(credit.due_date)
            old_due = due_date
            fees = 0

            if not user or not due_date or today != due_date:
                continue

            # ---------- Billing Window ----------
            cycle_start = due_date - timedelta(days=BILLING_CYCLE_DAYS - 1)
            start_dt = datetime.combine(cycle_start, datetime.min.time())
            end_dt = datetime.combine(due_date, datetime.max.time())

            # ---------- Transactions ----------
            draws = Transaction.query.filter(
                Transaction.from_account_id == credit.id,
                Transaction.description == 'Credit withdraw',
                Transaction.timestamp.between(start_dt, end_dt)
            ).order_by(Transaction.timestamp).all()

            payments = Transaction.query.filter(
                Transaction.to_account_id == credit.id,
                Transaction.description == 'Credit payment',
                Transaction.timestamp.between(start_dt, end_dt)
            ).order_by(Transaction.timestamp).all()

            total_draws = round(sum(tx.amount for tx in draws), 2)
            total_payments = round(sum(tx.amount for tx in payments), 2)

            old_score = user.credit_score
            old_points = user.reward_points
            old_balance = credit.past_amt
            carried_balance = old_balance > 0
            note_parts = []

            # ---------- FIFO Draw → Payment Matching ----------
            draw_items = [{
                "original": d.amount,
                "remaining": d.amount,
                "timestamp": d.timestamp,
                "repaid_at": None
            } for d in draws]

            payment_items = [{
                "remaining": p.amount,
                "timestamp": p.timestamp
            } for p in payments]

            for p in payment_items:
                for d in draw_items:
                    if p["remaining"] <= 0:
                        break
                    if d["remaining"] <= 0:
                        continue
                    applied = round(min(d["remaining"], p["remaining"]), 2)
                    d["remaining"] = round(d["remaining"] - applied, 2)
                    p["remaining"] = round(p["remaining"] - applied, 2)
                    if d["remaining"] == 0 and d["repaid_at"] is None:
                        d["repaid_at"] = p["timestamp"]

            # ---------- Persistent vs Round-trip ----------
            persistent_draw_amount = max(credit.past_amt, 0)
            for d in draw_items:
                if d["remaining"] > 0:
                    persistent_draw_amount = round(persistent_draw_amount + d["remaining"], 2)
                    continue
                if d["repaid_at"] is not None:
                    days_outstanding = (d["repaid_at"].date() - d["timestamp"].date()).days
                    if days_outstanding >= MIN_DAYS_OUTSTANDING_FOR_FULL_POINTS:
                        persistent_draw_amount = round(persistent_draw_amount + d["original"], 2)

            persistent_fraction = min(1.0, persistent_draw_amount / total_draws) if total_draws > 0 else 0

            # ---------- Minimum Due ----------
            borrowed_this_cycle = total_draws
            min_due = round(MIN_PAYMENT_AMT * old_balance, 2)
            paid_toward_min_due = min(total_payments, min_due)
            remaining_min_due = round(max(min_due - paid_toward_min_due, 0), 2)

            # ---------- Credit Score Logic ----------
            if credit.credit_limit and credit.balance > credit.credit_limit:
                user.credit_score = max(MIN_SCORE, user.credit_score - OVER_LIMIT_PENALTY)
                note_parts.append(f"(Over limit; Score: -{OVER_LIMIT_PENALTY})")

            if total_draws > 0:
                if carried_balance and (total_payments - total_draws) >= old_balance:
                    if borrowed_this_cycle > 0:
                        utilization_factor = min(credit.credit_limit / borrowed_this_cycle, 1)
                    else:
                        utilization_factor = 1

                    score_gain = round(ON_TIME_PAYMENT_REWARD * utilization_factor)
                    user.credit_score = min(MAX_SCORE, user.credit_score + score_gain)
                    points = MAX_POINTS
                    user.reward_points += points
                    note_parts.append(f"(Full payment; Score: +{score_gain}; Points: +{points})")
                elif carried_balance and total_payments < min_due:
                    penalty = round(NO_PAYMENT_PENALTY * persistent_fraction) if persistent_fraction > 0 else NO_PAYMENT_PENALTY
                    user.credit_score = max(MIN_SCORE, user.credit_score - penalty)
                    pre_penalty = credit.balance
                    fees += NO_PAYMENT_FEE
                    credit.balance = round(credit.balance + NO_PAYMENT_FEE, 2)
                    credit.past_due = True
                    db.session.add(Transaction(
                        to_account_id=credit.id,
                        to_user_id=user.id,
                        amount=NO_PAYMENT_FEE,
                        to_balance_after=credit.balance,
                        description="Late payment fee"
                    ))
                    log_user_transaction(
                        user,
                        fmt(
                            "PENALTY",
                            f"Bank → {credit.type}",
                            f"${NO_PAYMENT_FEE:.2f}",
                            f"${pre_penalty:.2f} → ${credit.balance:.2f}",
                            "Late payment fee"
                        )
                    )
                    note_parts.append(f"(Late payment; Score: -{penalty}; Fee: ${NO_PAYMENT_FEE:.2f})")
                elif carried_balance and total_payments > 0:
                    fraction_paid = total_payments / ((credit.past_amt + min_due) / 2) if old_balance > 0 else 0
                    fraction_paid = max(0, min(2, fraction_paid))
                    penalty = round(NO_PAYMENT_PENALTY * (1 - fraction_paid))
                    user.credit_score = max(MIN_SCORE, user.credit_score - penalty)
                    points = min(MAX_POINTS, round(MAX_POINTS * fraction_paid))
                    user.reward_points += points
                    if penalty < 0:
                        note_parts.append(f"(Partial payment; Score: +{penalty * -1}; Points: +{points})")
                    else:
                        note_parts.append(f"(Partial payment; Score: -{penalty}; Points: +{points})")
            else:
                payment_effort = min(1.0, (total_payments - total_draws) / max(credit.past_amt, 1))
                if carried_balance and total_payments >= credit.past_amt:
                    score_gain = round(ON_TIME_PAYMENT_REWARD * min((credit.credit_limit / total_payments), 1))
                    user.credit_score = min(MAX_SCORE, user.credit_score + score_gain)
                    points = MAX_POINTS
                    user.reward_points += points
                    note_parts.append(f"(Full payment; Score: +{score_gain}; Points: +{points})")
                elif carried_balance and total_payments >= min_due:
                    fraction_paid = total_payments / ((credit.past_amt + min_due) / 2) if old_balance > 0 else 0
                    fraction_paid = max(0, min(2, fraction_paid))
                    penalty = round(NO_PAYMENT_PENALTY * (1 - fraction_paid))
                    user.credit_score = max(MIN_SCORE, user.credit_score - penalty)
                    points = min(MAX_POINTS, round(MAX_POINTS * fraction_paid))
                    user.reward_points += points
                    if penalty < 0:
                        note_parts.append(f"(Partial payment; Score: +{penalty * -1}; Points: +{points})")
                    else:
                        note_parts.append(f"(Partial payment; Score: -{penalty}; Points: +{points})")
                elif carried_balance and total_payments < min_due:
                    user.credit_score = max(MIN_SCORE, user.credit_score - NO_PAYMENT_PENALTY)
                    pre_penalty = credit.balance
                    fees += NO_PAYMENT_FEE
                    credit.balance = round(credit.balance + NO_PAYMENT_FEE, 2)
                    credit.past_due = True
                    db.session.add(Transaction(
                        to_account_id=credit.id,
                        to_user_id=user.id,
                        amount=NO_PAYMENT_FEE,
                        to_balance_after=credit.balance,
                        description="Late payment fee"
                    ))
                    log_user_transaction(
                        user,
                        fmt(
                            "PENALTY",
                            f"Bank → {credit.type}",
                            f"${NO_PAYMENT_FEE:.2f}",
                            f"${pre_penalty:.2f} → ${credit.balance:.2f}",
                            "Late payment fee"
                        )
                    )
                    note_parts.append(f"(Carried balance with insufficient payment; Score: -{NO_PAYMENT_PENALTY}; Fee: ${NO_PAYMENT_FEE:.2f})")

            # ---------- Utilization ----------
            if credit.credit_limit:
                utilization = credit.balance / credit.credit_limit

                if utilization > 0.8:
                    user.credit_score = max(MIN_SCORE, user.credit_score - HIGH_UTILIZATION_PENALTY)
                    note_parts.append(f"(High utilization; Score: -{HIGH_UTILIZATION_PENALTY})")
                elif utilization < 0.3 and (total_draws > 0 or carried_balance):
                    user.credit_score = min(MAX_SCORE, user.credit_score + LOW_UTILIZATION_REWARD)
                    points = 0
                    if remaining_min_due <= 0:
                        points = UTILIZATION_REWARD_EXPONENT
                        user.reward_points += points
                    note_parts.append(f"(Low utilization; Score: +{LOW_UTILIZATION_REWARD}; Points: +{points})")

                # ---------- No Utilization Penalty ----------
                if total_draws == 0 and not carried_balance:
                    user.credit_score = max(MIN_SCORE, user.credit_score - NO_UTILIZATION_PENALTY)
                    note_parts.append(f"(No utilization; Score: -{NO_UTILIZATION_PENALTY})")

            # ---------- Apply Interest ----------
            apr, monthly_rate = get_interest_rate(credit)
            interest = 0
            if credit.balance > 0:
                interest = round(credit.balance * monthly_rate, 2)
            if interest >= 0.01:
                pre_interest = credit.balance
                credit.balance = round(credit.balance + interest, 2)
                db.session.add(Transaction(
                    to_account_id=credit.id,
                    to_user_id=user.id,
                    amount=interest,
                    to_balance_after=credit.balance,
                    description="Credit interest charge"
                ))
                log_user_transaction(
                    user,
                    fmt(
                        "INTEREST",
                        f"Bank → {credit.type}",
                        f"${interest:.2f}",
                        f"${pre_interest:.2f} → ${credit.balance:.2f}",
                        "Credit interest charge"
                    )
                )

            # ---------- Advance Due Date ----------
            credit.due_date = (due_date + timedelta(days=BILLING_CYCLE_DAYS)).isoformat()
            credit.past_amt = credit.balance

            # ---------- Logging ----------
            log_credit_snapshot(user, credit)
            log_message = (
                    "\n"
                    f"Billing Cycle: {start_dt:%m-%d-%Y} → {end_dt:%m-%d-%Y}\n"
                    f"User: {user.username}\n\n"
                    
                    " --------------Account Activity-------------\n"
                    f"  Previous Balance : ${old_balance:.2f}\n"
                    f"  Draws            : ${total_draws:.2f}\n"
                    f"  Persistent Draws : ${persistent_draw_amount:.2f}\n"
                    f"  Payments         : ${total_payments:.2f}\n"
                    f"  Minimum Due      : ${min_due:.2f}\n"

                    "\n ------------Charges & Adjustments-----------\n"
                    f"  Interest         : ${interest:.2f}  ({apr * 100:.2f}% APR)\n"
                    f"  Fees             : ${fees:.2f}\n"
                    f"  Ending Balance   : ${old_balance:.2f} → ${credit.past_amt:.2f}\n"

                    "\n ---------------Credit Impact----------------\n"
                    f"  Credit Score     : {old_score} → {user.credit_score}\n"
                    f"  Reward Points    : {old_points} → {user.reward_points}\n"
                    f"\n  {', '.join(note_parts) or 'No change'}\n"
            )
            print(log_message)
            log_interest(log_message, True)

        db.session.commit()
        return old_due


def apply_monthly_savings_interest(due_date):
    today = date.today()

    with app.app_context():
        users = User.query.all()

        for user in users:
            credit_due_today = any(
                acc.type == 'credit' and due_date == today
                for acc in user.accounts)

            if not credit_due_today:
                continue

            for account in user.accounts:
                if account.type != 'savings' or account.balance <= 0:
                    continue

                interest = round(account.balance * (user.savings_apr / 12.0), 2)
                if interest < 0.01:
                    continue

                pre_interest = account.balance
                account.balance = round(account.balance + interest, 2)
                tx = Transaction(
                    from_account_id=None,
                    to_account_id=account.id,
                    from_user_id=None,
                    to_user_id=account.user_id,
                    amount=interest,
                    to_balance_after=account.balance,
                    description='Savings interest payment'
                )
                db.session.add(tx)
                log_user_transaction(
                    user,
                    fmt(
                        "INTEREST",
                        f"Bank → {account.type}",
                        f"${interest:.2f}",
                        f"${pre_interest:.2f} → ${account.balance:.2f}",
                        "Savings interest payment"
                    )
                )

        db.session.commit()

if __name__ == "__main__":
    #print(f"\n\n~--------Account Processing will begin in 50 seconds------------~\n")
    #time.sleep(50)
    print(
           f"\n------------------------------------------------------------------"
           f"\nCredit Summary -- {date.today()}"
           f"\n------------------------------------------------------------------"
         )
    due_date = apply_monthly_billing()
    apply_monthly_savings_interest(due_date)
    print(f"\n------------------------------------------------------------------")
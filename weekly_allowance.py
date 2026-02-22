import os
from app import app
from models import db, User, Account, Transaction
from datetime import datetime, timedelta, date

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

def give_allowance():
    with app.app_context():
        
        admin = User.query.filter_by(username='Admin').first()
        if not admin:
            admin = User(username='Admin', role='parent', password_hash='')
            db.session.add(admin)
            db.session.commit()
            print("Created 'Admin' system user.")

        # Get or create Admin's spending account
        admin_acc = Account.query.filter_by(user_id=admin.id, type='spending').first()
        if not admin_acc:
            admin_acc = Account(user_id=admin.id, type='spending', balance=100000.0)
            db.session.add(admin_acc)
            db.session.commit()
            print("Created 'Admin' spending account.")

        # Give allowance to kids
        users = User.query.filter(User.role == 'child').all()

        for user in users:
            ALLOWANCE_AMOUNT = user.allowance_rate
            spending = Account.query.filter_by(user_id=user.id, type='spending').first()
            if spending and ALLOWANCE_AMOUNT > 0:
                og_mom_balance = admin_acc.balance
                og_child_balance = spending.balance
                spending.balance += ALLOWANCE_AMOUNT
                admin_acc.balance -= ALLOWANCE_AMOUNT

                # Record transaction from Admin account
                tx = Transaction(
                    from_account_id=admin_acc.id,
                    to_account_id=spending.id,
                    from_user_id=admin.id,
                    to_user_id=user.id,
                    amount=ALLOWANCE_AMOUNT,
                    from_balance_after=admin_acc.balance,
                    to_balance_after=spending.balance,
                    description='Weekly allowance'
                )
                db.session.add(tx)
                
                # ---- Logs ----
                log_user_transaction(
                    admin,
                    fmt(
                        "TRANSFER",
                        f"Admin → {user.username}",
                        f"${ALLOWANCE_AMOUNT:.2f}",
                        f"${og_mom_balance:.2f} → ${admin_acc.balance:.2f}",
                        "Weekly allowance"
                    )
                )

                log_user_transaction(
                    user,
                    fmt(
                        "RECEIVED",
                        "Admin → spending",
                        f"${ALLOWANCE_AMOUNT:.2f}",
                        f"${og_child_balance:.2f} → ${spending.balance:.2f}",
                        "Weekly allowance"
                    )
                )

                print(f"{datetime.now()}: ${ALLOWANCE_AMOUNT:.2f} allowance added to {user.username} from Admin.")

        db.session.commit()
        print("Allowance distribution complete.")

if __name__ == '__main__':
    give_allowance()

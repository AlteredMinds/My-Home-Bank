from models import db, User, Account
from app import app
from config import *
from werkzeug.security import generate_password_hash
from datetime import date, timedelta

def initialize_admin():
    with app.app_context():
        if not User.query.filter_by(username='parent').first():
            admin = User(username='Admin', password_hash=generate_password_hash('Password01'), role='parent', savings_apr=0.0, credit_score=575, reset_password=False)
            db.session.add(admin)
            db.session.commit()

            for acc_type in ['spending','savings','credit']:
                acc = Account(user_id=admin.id, type=acc_type, balance=0.00)
                if acc_type=='credit':
                    acc.credit_limit = 0.00
                    acc.interest_rate = 0.0
                    acc.due_date = (date.today() + timedelta(days=30)).isoformat()
                    acc.past_due = False
                    acc.past_amt = 0.00
                db.session.add(acc)

            db.session.commit()
            print('Admin user created.')
        else:
            print('Admin user already exists.')

if __name__ == '__main__':
    initialize_admin()

import os

# ================= FILE PATHS =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDIT_HISTORY_FILE = os.path.join(BASE_DIR, "log/credit_history.json")
INTEREST_LOG_FILE = os.path.join(BASE_DIR, "log/interest_history.log")
AVATAR_FOLDER = os.path.join(BASE_DIR, 'static', 'avatar')
BG_FOLDER = os.path.join(BASE_DIR, 'static', 'bg')

# ================= SECURITY =================
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
MIN_PASS_LENGTH = 8

# ================= CREDIT SCORE =================
MAX_SCORE = 850
MIN_SCORE = 300

OVER_LIMIT_PENALTY = 10
HIGH_UTILIZATION_PENALTY = 10
LOW_UTILIZATION_REWARD = 12
ON_TIME_PAYMENT_REWARD = 20
NO_PAYMENT_PENALTY = 20
NO_PAYMENT_FEE = 5.00
MIN_PAYMENT_AMT = 0.08
NO_UTILIZATION_PENALTY = 0

UTILIZATION_REWARD_EXPONENT = 8
SAVINGS_REWARD_RATE = 1
MAX_POINTS = 80

# ================= BILLING =================
BILLING_CYCLE_DAYS = 30
MIN_DAYS_OUTSTANDING_FOR_FULL_POINTS = 5

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


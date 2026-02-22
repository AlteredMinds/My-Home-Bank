# My Home Bank

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-2.3-000000?logo=flask&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-3.41-003B57?logo=sqlite&logoColor=white)
![Status](https://img.shields.io/badge/Status-Active-success)
![Made with Love](https://img.shields.io/badge/Made%20with-%F0%9F%92%9B-pink)

**My Home Bank** is a self-hosted banking application designed specifically for families to manage allowances, savings, and credit in a secure and educational environment.  
It enables children to learn financial literacy while allowing parents to supervise, guide, and manage accounts responsibly.

---

## 🚀 Features

### 🔹 For Children & Users
- **Multiple Account Types:**  
  - **Spending Account:** for daily transactions, paying for purchases, and receiving redeemed rewards.  
  - **Savings Account:** earns monthly compound interest with withdrawal rules (minimum $1 and 10% penalty).  
  - **Credit Account:** allows borrowing within limits, tracks minimum payments, and manages credit utilization.
- **Allowance Management:** weekly deposits automatically made to savings.
- **Transfers:** move funds between own accounts or to other users’ spending accounts.  
  - Savings → only to own spending, with penalty applied for early withdrawal.  
  - Spending → can transfer to other users’ accounts safely.
- **Credit Operations:**  
  - Borrow funds from credit into spending (up to credit limit).  
  - Pay credit balance from spending.  
  - Automatic calculation of minimum due, remaining balance, and alerts for overdue payments.  
  - Credit utilization and available credit are always displayed.
- **Rewards System:**  
  - Earn points by saving money, paying credit responsibly, and maintaining good credit habits.  
  - Redeem points for cash rewards deposited directly into spending accounts.  
  - Points do not expire, encouraging long-term goal-setting.
- **AI Financial Assistant:**  
  - Child-friendly guidance for financial decisions.  
  - Provides explanations of balances, transactions, credit scores, and responsible spending.  
  - Personalized recommendations based only on real account data.
- **Credit Score Tracking:**  
  - View credit score history with a graph.  
  - Score classification from Very Poor (300–399) to Excellent (800–850).  
  - Encourages responsible use of credit and awareness of borrowing habits.

### 🔹 For Parents & Administrators
- **Full Account Oversight:**  
  - Manage balances for spending, savings, and credit accounts.  
  - Set or adjust allowances, credit limits, interest rates, and reward points.  
  - Reset passwords and control two-factor authentication (2FA) for children.
- **User Management:**  
  - Create and remove child accounts.  
  - Edit profiles and apply administrative changes securely.  
- **Transaction Monitoring:**  
  - View detailed logs of transactions, rewards redemptions, and credit payments.  
  - Access authentication logs to track login attempts and failed 2FA entries.  
- **Activity & Rewards Management:**  
  - Approve or adjust reward points based on responsible financial behavior.  
  - Ensure children are learning correct financial habits.

---

## 🛠️ Tech Stack

**Frontend:**
- HTML5 & CSS3 (Flexbox, Grid, responsive design)
- JavaScript (ES6+ for interactive elements)
- Jinja2 templates for dynamic content rendering

**Backend:**
- Python 3.11+ with Flask web framework
- SQLite for local, lightweight database storage
- `pyotp` for Two-Factor Authentication
- Flask-Login for secure session management

**Tools & Platforms:**
- Visual Studio Code
- Git & GitHub for version control
- Local hosting via Flask server
- QR code generation for 2FA setup
- Ollama for AI assistant

---

## 🔒 Security Highlights
- **Two-Factor Authentication (2FA):** via QR code and TOTP apps for secure logins.  
- **Password Hashing:** using secure cryptographic algorithms.  
- **Session Management:** session-based access with role-based restrictions.  
- **Rate Limiting:** prevents brute-force login and transaction abuse.  
- **File Upload Validation:** for avatars and backgrounds to prevent malicious files.  
- **Detailed Logging:** tracks all user actions, credit operations, and reward redemptions.

---

## 📊 Database Overview
- **Core Tables:** `users`, `accounts`, `transactions`, `reward_redemptions`, `auth_logs`
- **Account Relationships:** each user can have multiple account types (spending, savings, credit)  
- **Transactions:** logs all movements between accounts, including penalties and reward redemptions  
- **Normalization:** ensures efficient storage and minimal redundancy  
- **Indexes:** applied for quick queries on user balances, transaction history, and credit activity

---

## 🗂️ Navigation & User Flow

### Main Dashboard
- View account balances and recent transactions
- Access credit account status and credit score
- Track reward points

### Transfers
- Move money safely between own accounts
- Send funds to other users’ spending accounts
- Apply penalties for savings withdrawals when necessary

### Credit Operations
- Borrow from credit account to spending account
- Pay credit balance from spending account
- View past due status and minimum payment alerts

### Rewards
- Redeem earned points for cash rewards
- Monitor rewards earned from responsible financial behavior

### Preferences & Security
- Update profile details, avatar, and background
- Change password and manage 2FA
- Parental oversight through admin panel

### Help & Education
- Access AI assistant for friendly, child-appropriate financial guidance
- Learn about interest, savings, credit utilization, and responsible money management

---

## 📥 Installation & Setup

### 1️⃣ Clone Repository
```bash
git clone https://github.com/yourusername/my-home-bank.git
cd my-home-bank
````

### 2️⃣ Install Dependencies

```bash
pip install -r requirements.txt
```

### 3️⃣ Configure Environment

* Create a `.env` file with:

```bash
SECRET_KEY=your_secret_key_here
```

### 4️⃣ Install Ollama Model for AI Assistant

* Install the Ollama CLI following instructions for your OS: [https://ollama.com/docs/install](https://ollama.com/docs/install)
* Pull the local AI model (e.g., LLaMA 3) required for My Home Bank:

```bash
ollama pull llama3.2
```

* Confirm the model is available:

```bash
ollama list
```

* Ensure the Ollama API server is running locally:

```bash
ollama serve
```

### 5️⃣ Initialize Database

* Run ```create_admin.py```once to create tables and default admin user.

### 6️⃣ Start Server

```bash
python app.py
```

* Access the application at `http://localhost:5000`.

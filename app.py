import os
import json
import logging
import jwt
import pytz
from datetime import datetime, timedelta
from flask import Flask, request, flash, abort, render_template, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import select
from sqlalchemy.sql import text
from sqlalchemy.orm import DeclarativeBase
from linebot.v3.messaging.exceptions import ApiException
from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.exceptions import (
    InvalidSignatureError
)
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    MessagingApiBlob,
    ReplyMessageRequest,
    TextMessage,
    ImageMessage,
    FlexBubble,
    FlexImage,
    FlexMessage,
    FlexBox,
    FlexText,
    FlexButton,
    FlexSeparator,
    FlexContainer,
    PushMessageRequest,
    QuickReply,
    QuickReplyItem,
    MessageAction,
    PostbackAction, 
    DatetimePickerAction,
    URIAction
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    ImageMessageContent,
    PostbackEvent,
    AudioMessageContent
)
from gemini_processor import process_message, process_image, process_audio
from dotenv import load_dotenv
import logging,tempfile

from utils import create_transaction_flex_message, create_transaction_details_flex_message, create_quick_reply, create_transaction_tip_list, encrypt_aes
from google.cloud import speech
import io

load_dotenv()
class Base(DeclarativeBase):
    pass

if os.environ.get("GOOGLE_CREDENTIALS_STR"):
    key_path = "service-account.json"
    creds = os.environ["GOOGLE_CREDENTIALS_STR"]
    if creds.startswith('"') and creds.endswith('"'):
        creds = creds[1:-1]  
    import json
    try:
        creds_dict = json.loads(creds)
        if "private_key" in creds_dict:
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        with open(key_path, "w", encoding="utf-8") as f:
            json.dump(creds_dict, f, ensure_ascii=False)
    except Exception as e:
        raise
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath(key_path)



# 創建 Flask 應用
app = Flask(__name__)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DB_URL')  # 使用環境變數中的 PostgreSQL 連接字串
app.secret_key = os.environ.get('Flasksecret_key','default_secret_key')
db = SQLAlchemy(app)
configuration = Configuration(access_token=os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.environ.get('LINE_CHANNEL_SECRET'))
SECRET_KEY = os.environ.get('SECRET_KEY')
ADMIN_ID = os.environ.get('ADMIN_ID')
taipei_tz = pytz.timezone('Asia/Taipei')

# 定義一個函數來返回台北時區的當前時間
def get_now_date_time():
    return datetime.now(taipei_tz).strftime('%Y-%m-%d %H:%M:%S')
#datetime 格式 2025-03-26 16:44:31.588733+08:00

# 定義一個函數來獲取當前月份的開始和結束日期
def get_month_start_end(date):
    start_date = date.replace(day=1)  # 當月 1 日
    next_month = (start_date + timedelta(days=32)).replace(day=1)  # 跳到下個月 1 日
    end_date = (next_month - timedelta(days=1)).replace(
        hour=23, minute=59, second=59
    )  # 當月最後一天 23:59:59
    return start_date, end_date

# 分類相關函數和模型
# 定義類別模型
class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    transactions = db.relationship('Transaction', backref='category', lazy=True)

# 獲取或創建分類 ID
def get_or_create_categoryID(name):
    category = Category.query.filter_by(name=name).first()
    if not category:
        category = Category(name=name)
        db.session.add(category)
        db.session.commit()
    return category.id

# 通用的創建交易記錄函數
def create_transaction(user_id, display_name, description, amount, category_name, tx_type, date=None, items=None):
    """
    :param user_id: 用戶 ID
    :param display_name: 用戶顯示名稱
    :param description: 交易描述
    :param amount: 交易金額
    :param category_name: 類別名稱
    :param tx_type: 交易類型 ('收入' 或 '支出')
    :param date: 交易日期 (默認為當前時間)
    :param items: 交易細項 (默認為空列表)
    :return: 創建的交易記錄對象
    """
    if not date:
        date = get_now_date_time()

    # 獲取或創建類別
    category = Category.query.filter_by(name=category_name).first()
    if not category:
        category = Category(name=category_name)
        db.session.add(category)
        db.session.commit()

    # 將細項轉換為 JSON 格式
    items_json = json.dumps(items) if items else '[]'

    # 創建交易記錄
    transaction = Transaction(
        user_id=user_id,
        display_name=display_name,
        date=date,
        description=description,
        amount=amount,
        category_id=category.id,
        tx_type=tx_type,
        items=items_json
    )
    db.session.add(transaction)
    db.session.commit()

    app.logger.info(f"新增交易記錄: 用戶 {user_id}, 描述: {description}, 金額: {amount}, 類別: {category_name}, 類型: {tx_type}")
    return transaction

def add_transaction(user_id, display_name, date, description, amount, category_name, tx_type):
    """
    包裝通用的創建交易記錄函數，提供簡化的接口。
    """
    return create_transaction(
        user_id=user_id,
        display_name=display_name,
        description=description,
        amount=amount,
        category_name=category_name,
        tx_type=tx_type,
        date=date
    )

# 這個函數用於計算每月的結餘，並將其更新到資料庫中
def update_monthly_balance(user_id):
    with db.session.begin_nested():  # 使用資料庫交易
        app.logger.info(f"開始更新用戶 {user_id} 的每月結餘")
        # 鎖定用戶資料，防止其他操作同時修改
        db.session.execute(text("SET LOCAL lock_timeout = '10s'"))  # 設定鎖定超時為 10 秒
        user = db.session.execute(
            select(User).where(User.user_id == user_id).with_for_update()
        ).scalar_one_or_none()
        if not user:
            app.logger.warning(f"用戶 {user_id} 不存在，無法更新每月結餘")
            return

        # 獲取當前時間
        now = datetime.now(taipei_tz)
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_end = (current_month_start - timedelta(seconds=1)).replace(hour=23, minute=59, second=59, microsecond=999999)
        last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        app.logger.info(f"當前月份的開始日期: {current_month_start}, 上個月的開始日期: {last_month_start}, 上個月的結束日期: {last_month_end}")

        # 獲取用戶的上個月交易記錄
        transactions = Transaction.query.filter(
            Transaction.user_id == user_id,
            Transaction.date >= last_month_start,
            Transaction.date <= last_month_end
        ).all()

        if not transactions:
            app.logger.info(f"用戶 {user_id} 在上個月沒有交易記錄，將月結餘更新為 0")
            user.monthly_balance = 0
            db.session.commit()
            return

        # 計算上個月結餘
        monthly_balance = sum(
            t.amount if t.tx_type == '收入' else -t.amount for t in transactions
        )

        # 更新用戶的每月結餘
        user.monthly_balance = max(0, monthly_balance)
        # 更新user.monthly_balance
        stopp = False
        if user.monthly_balance_enabled and monthly_balance > 0 and stopp:
            add_transaction(
                user_id=user.user_id,
                display_name=user.display_name,
                date=current_month_start,
                description="月結餘",
                amount=monthly_balance,
                category_name="其他",
                tx_type='收入'
            )
        
        db.session.commit()
        app.logger.info(f"用戶 {user_id} 的每月結餘已更新為: {monthly_balance}")
# 定義用戶模型
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(64), unique=True, nullable=False)
    display_name = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=get_now_date_time) 
    transactions = db.relationship('Transaction', backref='user', lazy=True)
    monthly_balance  = db.Column(db.Float, nullable=True, default=0.0)
    monthly_balance_enabled = db.Column(db.Boolean, nullable=True, default=False)
    spending_goal_enabled = db.Column(db.Boolean, nullable=True, default=False)
    
# 定義交易模型
class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(64), db.ForeignKey('user.user_id'), nullable=False)
    display_name = db.Column(db.String(64), nullable=True)
    date = db.Column(db.DateTime, nullable=False, default=get_now_date_time)
    description = db.Column(db.String(256), nullable=False)  # 可存品牌/商店名稱
    amount = db.Column(db.Float, nullable=False)  # 總金額
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    tx_type = db.Column(db.String(32), nullable=False, default='支出')
    items = db.Column(db.Text, nullable=True)  # 存 JSON 格式的細項

class TransactionASE(db.Model):
    __tablename__ = 'transaction_ase'  # 使用不同的表名
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(64), db.ForeignKey('user.user_id'), nullable=False)
    display_name = db.Column(db.String(64), nullable=True)
    date = db.Column(db.DateTime, nullable=False, default=get_now_date_time)
    description = db.Column(db.String(256), nullable=False)  # 加密後的描述
    amount = db.Column(db.String(256), nullable=False)  # 加密後的金額
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    tx_type = db.Column(db.String(256), nullable=False, default='支出')  # 加密後的類型
    items = db.Column(db.Text, nullable=True)  # 加密後的 JSON 格式細項
    
# 定義意見回饋模型
class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False)
    feedback = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=get_now_date_time) 

# 更新公告模型
class Announcement(db.Model):
    __tablename__ = 'announcements'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128), nullable=False)  # 公告標題
    description = db.Column(db.Text, nullable=False)   # 公告敘述
    created_at = db.Column(db.DateTime, default=get_now_date_time)  # 公告建立時間


# 評論模型
class Comment(db.Model):
    __tablename__ = 'comments'
    id = db.Column(db.Integer, primary_key=True)
    user_name = db.Column(db.String(64), nullable=False)  # 使用者名稱
    message = db.Column(db.Text, nullable=False)          # 評論訊息
    created_at = db.Column(db.DateTime, default=get_now_date_time)  # 評論建立時間
    reply = db.Column(db.Text, nullable=True, default="")  # 管理員回覆訊息
    reply_at = db.Column(db.DateTime, nullable=True)  # 管理員回覆時間

# 定義支出目標模型
class SpendingGoal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(64), db.ForeignKey('user.user_id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)  # 目標金額
    created_at = db.Column(db.DateTime, default=get_now_date_time)  # 設定時間

# 確保所有模型都已經創建
with app.app_context():
    try:
        db.create_all()
        app.logger.info("成功連接到資料庫")
    except Exception as e:
        app.logger.error(f"資料庫連接失敗: {str(e)}")


@app.route("/")
def index():
    # 從資料庫讀取公告資料
    announcements = Announcement.query.order_by(Announcement.created_at.desc()).all()
    # 從資料庫讀取評論資料
    comments = Comment.query.order_by(Comment.created_at.desc()).all()

    # 將資料傳遞到前端模板
    return render_template("index.html", announcements=announcements, comments=comments)


@app.route("/callback", methods=['POST'])
def callback():
    # 獲取 X-Line-Signature 標頭值
    signature = request.headers['X-Line-Signature']

    # 獲取請求正文內容
    body = request.get_data(as_text=True)

    # 處理 webhook 請求正文
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("無效的簽名。請檢查您的頻道存取金鑰/頻道密鑰。")
        abort(400)

    return 'OK'

# 公告管理頁面
@app.route("/manage_announcements", methods=["GET", "POST"])
def manage_announcements():
    # 驗證是否為管理員
    token = request.args.get('token')
    if not token or not verify_jwt_token(token) or verify_jwt_token(token).get("user_id") != ADMIN_ID:
        flash("您無權訪問此頁面", "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
        # 新增公告
        title = request.form.get("title")
        description = request.form.get("description")
        if not title or not description:
            flash("標題和敘述不能為空", "danger")
            return redirect(url_for("manage_announcements", token=token))
        announcement = Announcement(title=title, description=description)
        db.session.add(announcement)
        db.session.commit()
        flash("公告新增成功", "success")
        return redirect(url_for("manage_announcements", token=token))

    # 獲取公告和留言資料
    announcements = Announcement.query.order_by(Announcement.created_at.desc()).all()
    comments = Comment.query.order_by(Comment.created_at.desc()).all()
    return render_template("manage_announcements.html", announcements=announcements, comments=comments, token=token)

@app.route('/reply_comment/<int:comment_id>', methods=['POST'])
def reply_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)

    # 獲取 AJAX 請求中的回覆內容
    data = request.get_json()
    reply_message = data.get('reply')

    if not reply_message:
        return jsonify({"error": "回覆內容不能為空"}), 400

    # 更新回覆內容和回覆時間
    comment.reply = reply_message
    comment.reply_at = get_now_date_time()  # 使用台北時區
    db.session.commit()

    # 返回 JSON 響應
    return jsonify({
        "message": "回覆成功",
        "reply": reply_message,
        "reply_at": comment.reply_at.isoformat()  # 返回 ISO 8601 格式
    })

@app.route('/add_announcement', methods=['POST'])
def add_announcement():
    title = request.form.get('title')
    description = request.form.get('description')
    token = request.form.get('token')  # 從表單中獲取 token

    if not title or not description:
        flash('標題和敘述不能為空', 'danger')
        return redirect(url_for('manage_announcements', token=token))

    # 新增公告到資料庫
    new_announcement = Announcement(title=title, description=description)
    db.session.add(new_announcement)
    db.session.commit()

    flash('公告新增成功', 'success')
    return redirect(url_for('manage_announcements', token=token))  # 重定向時附加 token

@app.route('/delete_announcement/<int:announcement_id>', methods=['DELETE'])
def delete_announcement(announcement_id):
    announcement = Announcement.query.get_or_404(announcement_id)
    db.session.delete(announcement)
    db.session.commit()
    return jsonify({"message": "公告已刪除"}), 200

@app.route('/edit_announcement/<int:announcement_id>', methods=['GET', 'POST'])
def edit_announcement(announcement_id):
    announcement = Announcement.query.get_or_404(announcement_id)

    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        token = request.form.get('token')  # 從表單中獲取 token

        if not title or not description:
            flash('標題和敘述不能為空', 'danger')
            return redirect(f'/edit_announcement/{announcement_id}')

        # 更新公告資料
        announcement.title = title
        announcement.description = description
        db.session.commit()

        flash('公告更新成功', 'success')
        # 重導向到 manage_announcements，並附加 token
        return redirect(url_for('manage_announcements', token=token))

    token = request.args.get('token')  # 從查詢參數中獲取 token
    return render_template('edit_announcement.html', announcement=announcement, token=token)


@app.route('/delete_comment/<int:comment_id>', methods=['DELETE'])
def delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    db.session.delete(comment)
    db.session.commit()
    return jsonify({"message": "留言已刪除"}), 200

@app.route('/delete_reply/<int:comment_id>', methods=['DELETE'])
def delete_reply(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    comment.reply = None
    comment.reply_at = None
    db.session.commit()
    return jsonify({"message": "回覆已刪除"}), 200



@app.route("/view_feedback")
def view_feedback():
    # 驗證是否為管理員
    token = request.args.get('token')
    if not token or not verify_jwt_token(token) or verify_jwt_token(token).get("user_id") != ADMIN_ID:
        flash("您無權訪問此頁面", "danger")
        return redirect(url_for("index"))

    # 獲取所有回饋資料
    feedbacks = Feedback.query.order_by(Feedback.created_at.desc()).all()
    return render_template("view_feedback.html", feedbacks=feedbacks, token=token)


# 回饋頁面
@app.route('/feedback', methods=['GET'])
def feedback():
    return render_template('feedback.html')

@app.route('/submit_feedback', methods=['POST'])
def submit_feedback():
    name = request.form['name']
    feedback_text = request.form['feedback']
    feedback = Feedback(name=name, feedback=feedback_text)
    db.session.add(feedback)
    db.session.commit()
    app.logger.info(f"收到回饋: {name} - {feedback_text}")
    return render_template('message.html', message="感謝您的意見！", success=True)

@app.route('/api/comments', methods=['GET', 'POST'])
def manage_comments():
    if request.method == 'GET':
        comments = Comment.query.order_by(Comment.created_at.desc()).all()
        result = [
            {
                'id': comment.id,
                'name': comment.user_name,
                'comment': comment.message,
                'reply': comment.reply,
                'created_at': comment.created_at.isoformat() if comment.created_at else None,  # 確保返回 ISO 格式
                'reply_at': comment.reply_at.isoformat() if comment.reply_at else None  # 確保返回 ISO 格式
            }
            for comment in comments
        ]
        return jsonify(result)

    if request.method == 'POST':
        data = request.get_json()
        user_name = data.get('name')
        message = data.get('comment')

        if not user_name or not message:
            return jsonify({'error': '名稱和評論不能為空'}), 400

        # 新增評論並確保 created_at 正確初始化
        comment = Comment(user_name=user_name, message=message, created_at=get_now_date_time())
        db.session.add(comment)
        db.session.commit()

        return jsonify({
            'id': comment.id,
            'name': comment.user_name,
            'comment': comment.message,
            'reply': comment.reply,
            'created_at': comment.created_at.isoformat()  # 返回 ISO 格式
        }), 201
    
@app.route('/api/announcements', methods=['GET'])
def get_announcements():
    announcements = Announcement.query.order_by(Announcement.created_at.desc()).all()
    result = [
        {
            'id': announcement.id,
            'title': announcement.title,
            'description': announcement.description,
            'created_at': announcement.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }
        for announcement in announcements
    ]
    return jsonify(result)



@app.route('/history')
def history():
    user_id = request.args.get('user_id')
    if not user_id:
        return redirect(url_for('index'))

    # 獲取用戶的交易記錄
    transactions = Transaction.query.filter_by(user_id=user_id).order_by(Transaction.date.desc()).all()

    # 處理交易記錄中的 items
    transaction_items = [
        {
            'transaction_id': transaction.id,
            'items': json.loads(transaction.items) if transaction.items else []
        }
        for transaction in transactions
    ]
    transaction_items_dict = {
        item['transaction_id']: item['items'] for item in transaction_items
    }

    # 把 items 取代原本 transactions 裡的 items
    for transaction in transactions:
        transaction.items = json.dumps(transaction_items_dict.get(transaction.id, []), ensure_ascii=False)

    # 獲取用戶的月結餘
    user = User.query.filter_by(user_id=user_id).first()
    monthly_balance = user.monthly_balance if user else 0.0

    # 傳遞 json 模組到模板
    return render_template('history.html', transactions=transactions, monthly_balance=monthly_balance, json=json)

@app.route('/analysis')
def analysis():
    user_id = request.args.get('user_id')
    time_range = request.args.get('time_range', 'all')
    user = User.query.filter_by(user_id=user_id).first()

    if not user:
        abort(404, description="User not found")
    
    # 根據時間範圍過濾交易記錄
    now = datetime.now(taipei_tz)

    if time_range == 'current_month':
        start_date, end_date = get_month_start_end(now)

    elif time_range == 'last_month':
        last_month = now.replace(day=1) - timedelta(days=1)
        start_date, end_date = get_month_start_end(last_month.replace(day=1))

    elif time_range == 'last_3_months':
        start_date = (now.replace(day=1) - timedelta(days=90)).replace(day=1)
        end_date = get_month_start_end(now)[1]

    elif time_range == 'last_6_months':
        start_date = (now.replace(day=1) - timedelta(days=180)).replace(day=1)
        end_date = get_month_start_end(now)[1]

    elif time_range == 'current_year':
        start_date = now.replace(month=1, day=1)
        end_date = now.replace(month=12, day=31, hour=23, minute=59, second=59)

    else:
        start_date = None
        end_date = None

    # 過濾交易數據
    if start_date and end_date:
        transactions = Transaction.query.filter(
            Transaction.user_id == user_id,
            Transaction.date >= start_date,
            Transaction.date <= end_date
        ).all()
    else:
        transactions = Transaction.query.filter_by(user_id=user_id).all()

    # 設置日期範圍文字
    date_range = f"{start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}" if start_date and end_date else "所有時間"

    # 數據初始化
    expense_categories = {}
    income_categories = {}
    monthly_data = {}

    for transaction in transactions:
        # 類別數據
        if transaction.tx_type == '支出':
            if transaction.category.name not in expense_categories:
                expense_categories[transaction.category.name] = 0
            expense_categories[transaction.category.name] += transaction.amount
        elif transaction.tx_type == '收入':
            if transaction.category.name not in income_categories:
                income_categories[transaction.category.name] = 0
            income_categories[transaction.category.name] += transaction.amount
        
        # 每月數據
        month_key = transaction.date.strftime('%Y-%m')
        if month_key not in monthly_data:
            monthly_data[month_key] = 0
        monthly_data[month_key] += transaction.amount

    # 計算當月的支出總額
    start_date, end_date = get_month_start_end(now)
    total_spent = db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.user_id == user_id,
        Transaction.date >= start_date,
        Transaction.date <= end_date,
        Transaction.tx_type == '支出'
    ).scalar() or 0

    # 獲取用戶的開支目標金額
    goal = SpendingGoal.query.filter_by(user_id=user_id).first()
    goal_amount = goal.amount if goal else 0

    return render_template(
        'analysis.html',
        user_id=user_id,
        time_range=time_range,
        spending_goal_enabled=user.spending_goal_enabled,  # 傳遞狀態
        expense_categories=json.dumps(expense_categories),
        income_categories=json.dumps(income_categories),
        monthly_data=json.dumps(monthly_data),
        date_range=date_range,
        goal_amount=goal_amount,  # 傳遞目標金額
        total_spent=total_spent  # 傳遞當月支出總額
    )

# 新增一個路由處理啟用/停用開支目標功能的請求
@app.route('/toggle_spending_goal', methods=['POST'])
def toggle_spending_goal():
    user_id = request.form['user_id']
    user = User.query.filter_by(user_id=user_id).first()

    if not user:
        abort(404, description="User not found")

    # 切換 spending_goal_enabled 狀態
    user.spending_goal_enabled = not user.spending_goal_enabled
    db.session.commit()

    flash('開支目標功能已更新！', 'success')
    return redirect(url_for('analysis', user_id=user_id))

# 編輯交易記錄
@app.route('/edit_transaction', methods=['GET', 'POST'])
def edit_transaction():
    transaction_id = request.args.get('transaction_id')
    transaction = Transaction.query.get(transaction_id)
    if request.method == 'POST':
        transaction.description = request.form['description']
        transaction.amount = float(request.form['amount'])
        transaction.tx_type = request.form['tx_type']

        # 更新日期
        new_date = datetime.strptime(request.form['date'], '%Y-%m-%d')
        transaction.date = transaction.date.replace(year=new_date.year, month=new_date.month, day=new_date.day)

        # 更新類別
        category_name = request.form['category']
        category = Category.query.filter_by(name=category_name).first()
        if not category:
            category = Category(name=category_name)
            db.session.add(category)
            db.session.commit()
        transaction.category_id = category.id

        # 更新細項
        items = []
        for i in range(len(request.form.getlist('sub_description'))):
            sub_description = request.form.getlist('sub_description')[i]
            sub_amount = float(request.form.getlist('sub_amount')[i])
            items.append({"sub_description": sub_description, "sub_amount": sub_amount})
        transaction.items = json.dumps(items, ensure_ascii=False)  # 使用 ensure_ascii=False 確保儲存明文
        app.logger.info(f"用戶 {transaction.user_id} 編輯了交易記錄: {transaction.description}，金額: {transaction.amount}，類別: {category_name}")

        db.session.commit()
        app.logger.info(f"用戶 {transaction.user_id} 編輯了交易記錄!")
        return redirect(url_for('history', user_id=transaction.user_id))

    # 將細項轉換為 Python 對象以供前端使用
    transaction_items = json.loads(transaction.items) if transaction.items else []
    categories = Category.query.all()
    return render_template('edit_transaction.html', transaction=transaction, categories=categories, items=transaction_items)

# 刪除交易記錄
@app.route('/delete_transaction', methods=['GET'])
def delete_transaction():
    transaction_id = request.args.get('transaction_id')
    transaction = Transaction.query.get(transaction_id)
    if transaction:
        app.logger.info(f"用戶 {transaction.user_id} 刪除了交易記錄!")
        db.session.delete(transaction)
        db.session.commit()
    return redirect(url_for('history', user_id=transaction.user_id))

# 獲取用戶的交易記錄
@app.route('/api/transactions')
def get_transactions():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"error": "缺少 user_id 參數"}), 400
        
    transactions = Transaction.query.filter_by(user_id=user_id).order_by(Transaction.date.desc()).all()
    result = []
    
    for transaction in transactions:
        result.append({
            'id': transaction.id,
            'date': transaction.date.strftime('%Y-%m-%d %H:%M'),
            'description': transaction.description,
            'amount': transaction.amount,
            'category': transaction.category.name,
            'type': transaction.tx_type
        })
    
    return jsonify(result)

@app.route('/adminsetting', methods=['POST'])
def adminsetting():
    token = request.form.get('token')
    if not token:
        return "無效的訪問，請重新嘗試。", 403

    # 驗證JWT令牌
    payload = verify_jwt_token(token)
    if not payload:
        return "無效或過期的令牌，無法訪問管理員頁面。", 403
    
    user_id = payload["user_id"]
    # 驗證是否為管理員
    if user_id != ADMIN_ID:
        return "您無權訪問此頁面。", 403
    app.logger.info(f"用戶 {user_id} 訪問管理員頁面")
    # 獲取所有用戶資料並返回管理頁面
    users = User.query.all()
    return render_template('adminsetting.html', users=users, token=token)

@app.route('/admin_link')
def admin_link():
    token = request.args.get('token')
    return render_template('admin_link.html', token=token)


@app.route('/delete_user', methods=['POST'])
def delete_user():
    user_id = request.form.get('user_id')
    token = request.form.get('token')
    app.logger.info(f"用戶 {user_id} 請求刪除用戶")
    if not user_id:
        return render_template('Admessage.html', message="缺少 user_id 參數", success=False, token=token)

    # 刪除用戶及其交易記錄
    user = User.query.filter_by(user_id=user_id).first()
    if user:
        # 刪除用戶的所有交易記錄
        Transaction.query.filter_by(user_id=user_id).delete()
        db.session.delete(user)
        db.session.commit()
        app.logger.info(f"用戶 {user_id} 已成功刪除")
        return render_template('Admessage.html', message="用戶已刪除", success=True, token=token)
    else:
        return render_template('Admessage.html', message="用戶不存在", success=False, token=token)


def google_speech_to_text(audio_path):
    client = speech.SpeechClient()
    with io.open(audio_path, "rb") as audio_file:
        content = audio_file.read()
    # 根據副檔名決定 encoding
    if audio_path.endswith('.mp3'):
        encoding = speech.RecognitionConfig.AudioEncoding.MP3
    elif audio_path.endswith('.wav'):
        encoding = speech.RecognitionConfig.AudioEncoding.LINEAR16
    else:
        encoding = speech.RecognitionConfig.AudioEncoding.ENCODING_UNSPECIFIED
    audio = speech.RecognitionAudio(content=content)
    config = speech.RecognitionConfig(
        encoding=encoding,
        sample_rate_hertz=16000,
        language_code="zh-TW",
    )
    response = client.recognize(config=config, audio=audio)
    result_text = ""
    for result in response.results:
        result_text += result.alternatives[0].transcript
    return result_text if result_text else "(無法辨識語音內容)"

# 處理圖片訊息
@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    try:
        with ApiClient(configuration) as api_client:
            user_id = event.source.user_id
            line_bot_api = MessagingApi(api_client)
            profile = line_bot_api.get_profile(user_id)
            display_name = profile.display_name
            user = User.query.filter_by(user_id=user_id).first()

            now = datetime.now(taipei_tz)
            if user:
                # 獲取用戶的最後一筆交易記錄
                last_transaction = Transaction.query.filter_by(user_id=user_id).order_by(Transaction.date.desc()).first()
                # 如果當前日期是每月的第一天，或者用戶的最後一筆交易記錄不是當前月份，則更新每月結餘
                if now.day == 1 or (last_transaction and last_transaction.date.strftime('%Y-%m') != now.strftime('%Y-%m')):
                    if user.monthly_balance_enabled:
                        update_monthly_balance(user_id) 
            else:
                createAT = get_now_date_time()
                user = User(user_id=user_id, display_name=display_name, created_at=createAT)
                db.session.add(user)
                db.session.commit()
                app.logger.info(f"用戶 {user_id} 創建了帳號")
            #app.logger.info(f"用戶 {user_id} 發送了一張圖片")
            message_id = event.message.id
            #image_path = f"ID: {message_id}"
    

            # 使用 MessagingApiBlob 取得圖片內容
            blob_api = MessagingApiBlob(api_client)
            content = blob_api.get_message_content(message_id)
            app.logger.info(f"獲取圖片內容成功: {message_id}")

            # 使用 Gemini 處理圖片
            image_data = content
            #app.logger.info(f"開始處理圖片: {image_path}")
            processed_data = process_image(image_data)

            try:
                # 使用 Gemini 處理訊息
                #app.logger.info(f"處理後的數據: {processed_data}")
                if processed_data:
                    if isinstance(processed_data, dict):
                        processed_data = [processed_data]

                    # 根據收入和支出排序
                    processed_data = sorted(processed_data, key=lambda x: x.get('type', '') != '收入')

                    # 初始化 Carousel Message
                    carousel_message = {
                        "type": "carousel",
                        "contents": []
                    }

                    for data in processed_data:
                        # 獲取或創建類別
                        category_name = data.get('category', '其他') or '其他'
                        category = Category.query.filter_by(name=category_name).first()
                        if not category:
                            category = Category(name=category_name)
                            db.session.add(category)
                            db.session.commit()  # 提交以獲取 category.id

                        if not category or not category.id:
                            app.logger.error(f"無法創建交易記錄，類別無效: {category_name}")
                            continue

                        items = data.get('items', [])
                        # 將細項轉換為 JSON 格式
                        items_json = json.dumps(items) if items else '[]'
                        # 檢查金額是否不匹配 amount_mismatch 如果為 True，則使用細項的金額
                        if data.get('amount_mismatch', False) and items:
                            total_amount = sum(item.get('sub_amount', 0) for item in items if isinstance(item.get('sub_amount', 0), (int, float)))
                            amount = total_amount if total_amount > 0 else data.get('amount', 0)
                        else:
                            amount = data.get('amount', 0)

                        # 創建交易記錄
                        transaction = create_transaction(
                            user_id=user_id,
                            display_name=display_name,
                            description=data.get('description', ''),
                            amount=amount,
                            category_name=category_name,
                            tx_type=data.get('type', '支出'),
                            date=get_now_date_time(),
                            items=items
                        )

                        db.session.add(transaction)
                        db.session.commit()

                        # 創建 Flex 訊息並加入 Carousel
                        flex_message = create_transaction_flex_message(transaction)

                        # 在日期下方新增 tip
                        if 'tip' in data and data['tip']:
                            create_transaction_tip_list(flex_message, data)
                        carousel_message['contents'].append(flex_message)

                    # 回覆 Carousel Message
                    pr_message = FlexMessage(alt_text="交易記錄", contents=FlexContainer.from_json(json.dumps(carousel_message)))
                    quick_reply = create_quick_reply(user_id)

                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                pr_message,
                                TextMessage(text="請選擇以下選項：", quick_reply=quick_reply)
                            ]
                        )
                    )
                else:
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                TextMessage(text="抱歉，我無法分析您的圖片，請嘗試其他帶有交易明細的圖片。")
                            ]
                        )
                    )
            except Exception as e:
                app.logger.error(f"處理訊息時發生錯誤: {str(e)}")
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[
                            TextMessage(text="抱歉，處理您的訊息時發生錯誤。請稍後再試。")
                        ]
                    )
                )
    except Exception as e:
        app.logger.error(f"處理圖片時發生錯誤: {str(e)}")
        with ApiClient(configuration) as api_client:
            messaging_api = MessagingApi(api_client)
            messaging_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="抱歉，處理您的圖片時發生錯誤。請稍後再試。")]
                )
            )
import subprocess
import shutil
# 處理音訊訊息
@handler.add(MessageEvent)
def handle_message(event):
    message = event.message
    if isinstance(message, AudioMessageContent):
        message_id = message.id
        # 把音訊內容存儲 並print檔案名
        with ApiClient(configuration) as api_client:
            blob_api = MessagingApiBlob(api_client)
            content = blob_api.get_message_content(message_id)            
            file_path = f"audio_{message_id}.m4a"
            with open(file_path, 'wb') as audio_file:
                audio_file.write(content)
            mp3_file_path = f"audio_{message_id}.mp3"
            convert_m4a_to_mp3(file_path, mp3_file_path)
            # Google 語音辨識
            try:
                recognized_text = google_speech_to_text(mp3_file_path)
            except Exception as e:
                recognized_text = f"語音辨識失敗: {e}"
            # Gemine文字處理
            if not recognized_text.startswith("語音辨識失敗:"):
                try:
                    processed_data = process_message(recognized_text, datetime.now(taipei_tz))
                    if processed_data:
                        if isinstance(processed_data, dict):
                            processed_data = [processed_data]
                        processed_data = sorted(processed_data, key=lambda x: x.get('type', '') != '收入')
                        carousel_message = {
                            "type": "carousel",
                            "contents": []
                        }
                        with ApiClient(configuration) as api_client2:
                            line_bot_api = MessagingApi(api_client2)
                            user_id = event.source.user_id
                            profile = line_bot_api.get_profile(user_id)
                            display_name = profile.display_name
                        for data in processed_data:
                            category_name = data.get('category', '其他') or '其他'
                            category = Category.query.filter_by(name=category_name).first()
                            if not category:
                                category = Category(name=category_name)
                                db.session.add(category)
                                db.session.commit()
                            items = data.get('items', [])
                            items_json = json.dumps(items) if items else '[]'
                            if data.get('amount_mismatch', False) and items:
                                amount = sum(item.get('sub_amount', 0) for item in items)
                            else:
                                amount = data.get('amount', 0)
                            transaction = create_transaction(
                                user_id=user_id,
                                display_name=display_name,
                                description=data.get('description', ''),
                                amount=amount,
                                category_name=category_name,
                                tx_type=data.get('type', '支出'),
                                date=get_now_date_time(),
                                items=items
                            )

                            db.session.add(transaction)
                            db.session.commit()
                            flex_message = create_transaction_flex_message(transaction)
                            if 'tip' in data and data['tip']:
                                create_transaction_tip_list(flex_message, data)
                            carousel_message['contents'].append(flex_message)
                        pr_message = FlexMessage(alt_text="交易記錄", contents=FlexContainer.from_json(json.dumps(carousel_message)))
                        quick_reply = create_quick_reply(user_id)
                        with ApiClient(configuration) as api_client2:
                            line_bot_api = MessagingApi(api_client2)
                            line_bot_api.reply_message(
                                ReplyMessageRequest(
                                    reply_token=event.reply_token,
                                    messages=[
                                        pr_message,
                                        TextMessage(text="請選擇以下選項：", quick_reply=quick_reply)
                                    ]
                                )
                            )
                        return
                    else:
                        with ApiClient(configuration) as api_client2:
                            line_bot_api = MessagingApi(api_client2)
                            line_bot_api.reply_message(
                                ReplyMessageRequest(
                                    reply_token=event.reply_token,
                                    messages=[TextMessage(text="語音內容已辨識，但無法進行記帳。")]
                                )
                            )
                        return
                except Exception as e:
                    with ApiClient(configuration) as api_client2:
                        line_bot_api = MessagingApi(api_client2)
                        line_bot_api.reply_message(
                            ReplyMessageRequest(
                                reply_token=event.reply_token,
                                messages=[TextMessage(text="語音內容已辨識，但記帳處理時發生錯誤。")]
                            )
                        )
                    return
            # 若語音辨識失敗
            with ApiClient(configuration) as api_client2:
                line_bot_api = MessagingApi(api_client2)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="語音辨識失敗，無法記帳。")]
                    )
                )
        return

def convert_m4a_to_mp3(input_path, output_path):
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise RuntimeError("ffmpeg 未安裝或未加入 PATH，請安裝 ffmpeg 並確保其在系統環境變數中。")
    command = [
        ffmpeg_path,
        '-i', input_path,
        '-codec:a', 'libmp3lame',
        '-qscale:a', '2',
        output_path
    ]
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError as e:
        raise RuntimeError(f"找不到 ffmpeg，請確認已安裝並在 PATH。詳細錯誤: {e}")
    except Exception as e:
        raise RuntimeError(f"轉檔時發生錯誤: {e}")






# 處理文字訊息
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    with ApiClient(configuration) as api_client:
        # 設置 LINE Bot API 的配置
        line_bot_api = MessagingApi(api_client)
        user_id = event.source.user_id
        profile = line_bot_api.get_profile(user_id)
        display_name = profile.display_name
        user = User.query.filter_by(user_id=user_id).first()

        now = datetime.now(taipei_tz)
        if user:
            # 獲取用戶的最後一筆交易記錄
            last_transaction = Transaction.query.filter_by(user_id=user_id).order_by(Transaction.date.desc()).first()
            # 如果當前日期是每月的第一天，或者用戶的最後一筆交易記錄不是當前月份，則更新每月結餘
            if now.day == 1 or (last_transaction and last_transaction.date.strftime('%Y-%m') != now.strftime('%Y-%m')):
                if user.monthly_balance_enabled:
                    update_monthly_balance(user_id)
                    
        else:
            createAT = get_now_date_time()
            user = User(user_id=user_id, display_name=display_name, created_at=createAT)
            db.session.add(user)
            db.session.commit()
            app.logger.info(f"用戶 {user_id} 創建了帳號")
        
        message_text = event.message.text
        # 若用戶輸入!admin，則檢查是否為開發者
        if message_text == "!admin" and user_id == ADMIN_ID:
            token = generate_jwt_token(user_id)
            flex_message = {
                "type": "bubble",
                "header": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": "管理員功能", "weight": "bold", "size": "xl", "color": "#ffffff"}
                    ],
                    "backgroundColor": "#27ACB2"
                },
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": "點擊下方按鈕進入管理員網頁", "size": "sm", "color": "#555555"},
                        {"type": "button", "action": {"type": "uri", "label": "管理員頁面", "uri": f"https://{request.host}/admin_link?token={token}"}, "style": "primary", "color": "#27ACB2"}
                    ]
                }
            }
            pr_message = FlexMessage(alt_text="管理員頁面", contents=FlexContainer.from_json(json.dumps(flex_message)))
            quick_reply = create_quick_reply(user_id)  # 新增 QuickReply
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        pr_message,
                        TextMessage(text="請選擇以下選項：", quick_reply=quick_reply)  # 回覆 QuickReply
                    ]
                )
            )
            return

        # 若用戶輸入!help，則顯示 QuickReply
        if message_text == "!help":
            quick_reply = create_quick_reply(user_id)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(text="請選擇以下選項：", quick_reply=quick_reply)
                    ]
                )
            )
            return
        
        # 若用戶輸入!Admin_update_monthly_balance!，則檢查是否為開發者，並更新指定用戶的月結餘
        if message_text.startswith("!Admin_update_monthly_balance!") and user_id == ADMIN_ID:
            try:
                # 解析指令，取得目標使用者 ID
                target_user_id = message_text.split("!")[2].strip()
                print(f"目標使用者 ID: {target_user_id}")
                if not target_user_id:
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text="請提供有效的使用者 ID。")]
                        )
                    )
                    return

                # 更新指定使用者的月結餘
                update_monthly_balance(target_user_id)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=f"已成功更新使用者 {target_user_id} 的月結餘。")]
                    )
                )
            except Exception as e:
                app.logger.error(f"更新月結餘時發生錯誤: {str(e)}")
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="更新月結餘時發生錯誤，請稍後再試。")]
                    )
                )
            return


        if message_text == "!migrate_transactions":
            if user_id != ADMIN_ID:
                with ApiClient(configuration) as api_client:
                    line_bot_api = MessagingApi(api_client)
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text="您無權執行此操作。")]
                        )
                    )
                return

        try:
            # 使用 Gemini 處理訊息
            processed_data = process_message(message_text, now)
            #app.logger.info(f"處理後的數據: {processed_data}")
            if processed_data:
                if isinstance(processed_data, dict):
                    processed_data = [processed_data]

                # 根據收入和支出排序
                processed_data = sorted(processed_data, key=lambda x: x.get('type', '') != '收入')

                # 初始化 Carousel Message
                carousel_message = {
                    "type": "carousel",
                    "contents": []
                }

                for data in processed_data:
                    # 獲取或創建類別
                    category_name = data.get('category', '其他') or '其他'
                    category = Category.query.filter_by(name=category_name).first()
                    if not category:
                        category = Category(name=category_name)
                        db.session.add(category)
                        db.session.commit()  # 提交以獲取 category.id

                    if not category or not category.id:
                        app.logger.error(f"無法創建交易記錄，類別無效: {category_name}")
                        continue

                    items = data.get('items', [])
                    # 將細項轉換為 JSON 格式
                    items_json = json.dumps(items) if items else '[]'
                    # 檢查金額是否不匹配 amount_mismatch 如果為 True，則使用細項的金額
                    if data.get('amount_mismatch', False) and items:
                        total_amount = sum(item.get('sub_amount', 0) for item in items if isinstance(item.get('sub_amount', 0), (int, float)))
                        amount = total_amount if total_amount > 0 else data.get('amount', 0)
                    else:
                        amount = data.get('amount', 0)

                    # 創建交易記錄
                    transaction = create_transaction(
                        user_id=user_id,
                        display_name=display_name,
                        description=data.get('description', ''),
                        amount=amount,
                        category_name=category_name,
                        tx_type=data.get('type', '支出'),
                        date=get_now_date_time(),
                        items=items
                    )
                    db.session.add(transaction)
                    db.session.commit()

                    # 創建 Flex 訊息並加入 Carousel
                    flex_message = create_transaction_flex_message(transaction)

                    # 在日期下方新增 tip
                    if 'tip' in data and data['tip']:
                        create_transaction_tip_list(flex_message, data)
                            

                    carousel_message['contents'].append(flex_message)

                # 回覆 Carousel Message
                pr_message = FlexMessage(alt_text="交易記錄", contents=FlexContainer.from_json(json.dumps(carousel_message)))
                quick_reply = create_quick_reply(user_id)

                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[
                            pr_message,
                            TextMessage(text="請選擇以下選項：", quick_reply=quick_reply)
                        ]
                    )
                )
            else:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[
                            TextMessage(text="抱歉，我無法理解您的訊息。請嘗試使用更清晰的語言來描述您的交易。\n例如:\n「午餐花了150元」\n或使用「!help」來查看快速選單。")
                        ]
                    )
                )
        except Exception as e:
            app.logger.error(f"處理訊息時發生錯誤: {str(e)}")
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(text="抱歉，處理您的訊息時發生錯誤。請稍後再試。")
                    ]
                )
            )

# 生成JWT令牌
def generate_jwt_token(user_id):
    expiration = datetime.utcnow() + timedelta(hours=1)
  # 設置令牌過期時間為1小時
    payload = {
        "user_id": user_id,
        "exp": expiration
    }
    return jwt.encode(payload, SECRET_KEY, algorithm='HS256')

# 驗證JWT令牌
def verify_jwt_token(token):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        return None  # 令牌已過期
    except jwt.InvalidTokenError:
        return None  # 無效的令牌

# 處理 Postback 事件
@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    user_id = event.source.user_id

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        # 查看明細功能
        if data.startswith("show_details_"):
            transaction_id = data.split("_")[-1]
            transaction = Transaction.query.get(transaction_id)

            if transaction:
                # 生成明細的 Flex Message
                details_flex_message = create_transaction_details_flex_message(transaction)
                pr_message = FlexMessage(alt_text="交易明細", contents=FlexContainer.from_json(json.dumps(details_flex_message)))

                # 在交易明細後新增 QuickReply
                quick_reply = create_quick_reply(user_id)

                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[
                            pr_message,
                            TextMessage(text="請選擇以下選項：", quick_reply=quick_reply)
                        ]
                    )
                )
            else:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="找不到該交易記錄的明細。")]
                    )
                )
        else:
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="無法處理的 Postback 資料。")]
                )
            )



@app.route('/settings', methods=['GET', 'POST'])
def settings():
    user_id = request.args.get('user_id')
    user = User.query.filter_by(user_id=user_id).first()

    if not user:
        app.logger.error(f"User not found for user_id: {user_id}")
        abort(404, description="User not found")

    if request.method == 'POST':
        # 檢查是否有輸入必要的欄位
        spending_goal_enabled = 'spending_goal_enabled' in request.form
        goal_amount = request.form.get('goal_amount', type=float)

        if spending_goal_enabled and not goal_amount:
            flash('請輸入目標金額！', 'danger')
            return redirect(url_for('settings', user_id=user_id))

        # 更新開支目標設定
        user.spending_goal_enabled = spending_goal_enabled

        if spending_goal_enabled:
            # 更新或新增開支目標
            goal = SpendingGoal.query.filter_by(user_id=user_id).first()
            if not goal:
                goal = SpendingGoal(user_id=user_id)
                db.session.add(goal)

            goal.amount = goal_amount

        else:
            # 如果停用，刪除現有的開支目標
            SpendingGoal.query.filter_by(user_id=user_id).delete()

        db.session.commit()
        flash('設置已更新！', 'success')
        return redirect(url_for('settings', user_id=user_id, success='true'))

    # 獲取現有設置
    goal = SpendingGoal.query.filter_by(user_id=user_id).first()
    return render_template(
        'settings.html',
        user_id=user_id,  # 傳遞 user_id 到模板
        spending_goal_enabled=user.spending_goal_enabled,
        goal_amount=goal.amount if goal else ''
    )

# 確認 LINE_CHANNEL_ACCESS_TOKEN 是否正確載入
if not configuration.access_token:
    app.logger.error("LINE_CHANNEL_ACCESS_TOKEN 未正確載入，請檢查環境變數。")
else:
    app.logger.info("LINE_CHANNEL_ACCESS_TOKEN 已成功載入。")

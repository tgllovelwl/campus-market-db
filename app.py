from __future__ import annotations

import logging
import os
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import closing
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, session, url_for


BASE_DIR = Path(__file__).resolve().parent
DATABASE = Path(os.environ.get("DATABASE_PATH", str(BASE_DIR / "campus_market.db"))).expanduser().resolve()
APP_ENV = os.environ.get("APP_ENV", "development").lower()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
MAX_TEXT_LEN = 100
ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{2,20}$")
LOGIN_WINDOW_SECONDS = int(os.environ.get("LOGIN_WINDOW_SECONDS", "300"))
LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_LOCK_SECONDS = int(os.environ.get("LOGIN_LOCK_SECONDS", "600"))
LOG_PATH = os.environ.get("LOG_PATH", str(BASE_DIR / "logs" / "app.log"))
START_TIME = time.time()


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "campus-market-demo-secret"
app.config["TEMPLATES_AUTO_RELOAD"] = APP_ENV != "production"
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = APP_ENV == "production"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("market_app")
logger.setLevel(logging.INFO)

log_file = Path(LOG_PATH)
log_file.parent.mkdir(parents=True, exist_ok=True)
if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
    file_handler = RotatingFileHandler(log_file, maxBytes=1_048_576, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s request_id=%(request_id)s %(message)s"))
    logger.addHandler(file_handler)


def log_event(level: int, message: str, **extra: Any) -> None:
    payload = {"request_id": getattr(g, "request_id", "-")}
    payload.update(extra)
    logger.log(level, f"{message} | {payload}", extra={"request_id": payload["request_id"]})


@app.after_request
def add_security_headers(response):  # type: ignore[no-untyped-def]
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'")
    log_event(logging.INFO, "request_completed", method=request.method, path=request.path, status=response.status_code)
    return response


def require_reset_token() -> None:
    if APP_ENV != "production":
        return
    expected = os.environ.get("RESET_TOKEN", "")
    provided = request.form.get("reset_token", "")
    if not expected or not secrets.compare_digest(expected, provided):
        abort(403)


def require_admin() -> None:
    if not session.get("is_admin", False):
        abort(403)


def get_client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def check_login_rate_limit() -> tuple[bool, str]:
    now = time.time()
    attempts: list[float] = session.get("admin_login_attempts", [])
    attempts = [t for t in attempts if now - t <= LOGIN_WINDOW_SECONDS]
    locked_until = float(session.get("admin_locked_until", 0.0))
    if now < locked_until:
        wait_seconds = int(locked_until - now)
        return False, f"管理员登录已临时锁定，请 {wait_seconds} 秒后再试。"
    if len(attempts) >= LOGIN_MAX_ATTEMPTS:
        session["admin_locked_until"] = now + LOGIN_LOCK_SECONDS
        session["admin_login_attempts"] = attempts
        return False, f"尝试次数过多，已锁定 {LOGIN_LOCK_SECONDS} 秒。"
    session["admin_login_attempts"] = attempts
    return True, ""


def record_login_failure() -> None:
    now = time.time()
    attempts: list[float] = session.get("admin_login_attempts", [])
    attempts = [t for t in attempts if now - t <= LOGIN_WINDOW_SECONDS]
    attempts.append(now)
    session["admin_login_attempts"] = attempts


def clear_login_limit_state() -> None:
    session["admin_login_attempts"] = []
    session["admin_locked_until"] = 0.0


def sanitize_text(value: str, field_name: str, max_len: int = MAX_TEXT_LEN) -> str:
    text = value.strip()
    if not text or len(text) > max_len:
        raise ValueError(f"{field_name}不能为空且长度不能超过{max_len}。")
    return text


def sanitize_id(value: str, field_name: str) -> str:
    candidate = value.strip()
    if not ID_PATTERN.match(candidate):
        raise ValueError(f"{field_name}格式不合法（2-20位字母数字下划线或横杠）。")
    return candidate


def sanitize_price(value: str, field_name: str = "价格") -> float:
    price = float(value)
    if price < 0 or price > 100000:
        raise ValueError(f"{field_name}必须在 0 到 100000 之间。")
    return price


def get_csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return str(token)


@app.before_request
def csrf_protect():  # type: ignore[no-untyped-def]
    g.request_id = str(uuid.uuid4())
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        sent = request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not expected or not sent or not secrets.compare_digest(str(expected), str(sent)):
            abort(403)
        # 单次 token：降低 token 泄露后的窗口期
        session["csrf_token"] = secrets.token_urlsafe(32)


@app.context_processor
def inject_globals():  # type: ignore[no-untyped-def]
    return {
        "csrf_token": get_csrf_token(),
        "app_env": APP_ENV,
        "is_admin": bool(session.get("is_admin", False)),
        "request_id": getattr(g, "request_id", "-"),
    }


@app.errorhandler(400)
def bad_request(_: Any):  # type: ignore[no-untyped-def]
    return render_template("400.html"), 400


@app.errorhandler(403)
def forbidden(_: Any):  # type: ignore[no-untyped-def]
    return render_template("403.html", app_env=APP_ENV), 403


@app.errorhandler(404)
def not_found(_: Any):  # type: ignore[no-untyped-def]
    return render_template("404.html"), 404


@app.errorhandler(500)
def server_error(_: Any):  # type: ignore[no-untyped-def]
    log_event(logging.ERROR, "internal_server_error", path=request.path, method=request.method)
    return render_template("500.html"), 500


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        ensure_database()
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(_: Any) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query_db(sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    return get_db().execute(sql, params).fetchall()


def execute_db(sql: str, params: tuple[Any, ...] = ()) -> None:
    db = get_db()
    db.execute(sql, params)
    db.commit()


def execute_db_rowcount(sql: str, params: tuple[Any, ...] = ()) -> int:
    db = get_db()
    cursor = db.execute(sql, params)
    db.commit()
    return cursor.rowcount


def init_db() -> None:
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DATABASE)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        schema = (BASE_DIR / "schema.sql").read_text(encoding="utf-8")
        seed = (BASE_DIR / "seed.sql").read_text(encoding="utf-8")
        conn.executescript(schema)
        conn.executescript(seed)
        conn.commit()


def ensure_database() -> None:
    if not DATABASE.exists():
        try:
            init_db()
        except sqlite3.OperationalError:
            # 并发启动时，可能有多个进程同时初始化；若另一个已完成则忽略即可。
            pass


def validate_runtime_config() -> None:
    if APP_ENV == "production":
        if app.config["SECRET_KEY"] == "campus-market-demo-secret":
            logger.warning(
                "Using default SECRET_KEY in production.",
                extra={"request_id": "-"},
            )
        if ADMIN_PASSWORD == "admin123":
            logger.warning(
                "Using default ADMIN_PASSWORD in production.",
                extra={"request_id": "-"},
            )


validate_runtime_config()


def perform_purchase(buyer_id: str, item_id: str) -> tuple[bool, str]:
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        item = db.execute(
            """
            SELECT item_id, item_name, status
            FROM item
            WHERE item_id = ?
            """,
            (item_id,),
        ).fetchone()

        if item is None:
            db.rollback()
            return False, "商品不存在。"
        if item["status"] == 1:
            db.rollback()
            return False, f"商品“{item['item_name']}”已售出，不能重复购买。"

        db.execute(
            """
            INSERT INTO orders (buyer_id, item_id, order_date)
            VALUES (?, ?, DATE('now'))
            """,
            (buyer_id, item_id),
        )
        db.execute("UPDATE item SET status = 1 WHERE item_id = ?", (item_id,))
        db.commit()
        return True, f"商品“{item['item_name']}”购买成功。"
    except sqlite3.IntegrityError:
        db.rollback()
        return False, "购买失败：该商品已被交易或买家信息无效。"
    except sqlite3.Error as exc:
        db.rollback()
        return False, f"购买失败：{exc}"


def fetch_dashboard_data() -> dict[str, Any]:
    return {
        "total_items": query_db("SELECT COUNT(*) AS total FROM item")[0]["total"],
        "sold_items": query_db("SELECT COUNT(*) AS total FROM item WHERE status = 1")[0]["total"],
        "unsold_items": query_db("SELECT COUNT(*) AS total FROM item WHERE status = 0")[0]["total"],
        "total_users": query_db("SELECT COUNT(*) AS total FROM user")[0]["total"],
        "total_orders": query_db("SELECT COUNT(*) AS total FROM orders")[0]["total"],
    }


@app.route("/admin/login", methods=["POST"])
def admin_login() -> str:
    allowed, reason = check_login_rate_limit()
    if not allowed:
        flash(reason, "error")
        log_event(logging.WARNING, "admin_login_rate_limited", ip=get_client_ip())
        return redirect(url_for("index"))

    password = request.form.get("admin_password", "")
    if secrets.compare_digest(password, ADMIN_PASSWORD):
        session["is_admin"] = True
        clear_login_limit_state()
        flash("管理员登录成功。", "success")
        log_event(logging.INFO, "admin_login_success", ip=get_client_ip())
    else:
        record_login_failure()
        flash("管理员口令错误。", "error")
        log_event(logging.WARNING, "admin_login_failed", ip=get_client_ip())
    return redirect(url_for("index"))


@app.route("/admin/logout", methods=["POST"])
def admin_logout() -> str:
    session["is_admin"] = False
    clear_login_limit_state()
    flash("已退出管理员模式。", "success")
    return redirect(url_for("index"))


@app.route("/")
def index() -> str:
    stats = fetch_dashboard_data()
    return render_template("index.html", stats=stats)


@app.route("/users")
def users() -> str:
    user_list = query_db("SELECT * FROM user ORDER BY user_id")
    return render_template("users.html", users=user_list)


@app.route("/items", methods=["GET", "POST"])
def items() -> str:
    if request.method == "POST":
        action = request.form.get("action", "")
        try:
            if action == "add":
                require_admin()
                item_id = sanitize_id(request.form["item_id"], "商品ID")
                execute_db(
                    """
                    INSERT INTO item (item_id, item_name, category, price, status, seller_id, description)
                    VALUES (?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        item_id,
                        sanitize_text(request.form["item_name"], "商品名"),
                        sanitize_text(request.form["category"], "类别", 30),
                        sanitize_price(request.form["price"]),
                        sanitize_id(request.form["seller_id"], "卖家ID"),
                        sanitize_text(request.form["description"], "描述", 300),
                    ),
                )
                flash("新商品已添加。", "success")
            elif action == "update_price":
                require_admin()
                target_item_id = sanitize_id(request.form.get("item_id", ""), "商品ID")
                changed = execute_db_rowcount(
                    "UPDATE item SET price = ? WHERE item_id = ?",
                    (sanitize_price(request.form["new_price"], "新价格"), target_item_id),
                )
                flash("商品价格已更新。" if changed else "未找到对应商品。", "success" if changed else "error")
            elif action == "delete":
                require_admin()
                target_item_id = sanitize_id(request.form.get("item_id", ""), "商品ID")
                changed = execute_db_rowcount(
                    "DELETE FROM item WHERE item_id = ? AND status = 0",
                    (target_item_id,),
                )
                flash(
                    "未售商品已删除。" if changed else "删除失败：商品不存在或该商品已售出。",
                    "success" if changed else "error",
                )
            elif action == "buy":
                buyer_id = sanitize_id(request.form.get("buyer_id", ""), "买家ID")
                item_id = sanitize_id(request.form.get("item_id", ""), "商品ID")
                seller_row = query_db("SELECT seller_id FROM item WHERE item_id = ?", (item_id,))
                if seller_row and seller_row[0]["seller_id"] == buyer_id:
                    flash("不能购买自己发布的商品。", "error")
                    return redirect(url_for("items"))
                success, message = perform_purchase(buyer_id, item_id)
                flash(message, "success" if success else "error")
            else:
                abort(400)
        except ValueError as exc:
            flash(f"输入校验失败：{exc}", "error")
        except sqlite3.IntegrityError as exc:
            flash(f"操作失败：{exc}", "error")

        return redirect(url_for("items"))

    item_list = query_db(
        """
        SELECT item.item_id, item.item_name, item.category, item.price, item.status,
               item.description, user.user_name AS seller_name, item.seller_id
        FROM item
        JOIN user ON item.seller_id = user.user_id
        ORDER BY item.item_id
        """
    )
    user_list = query_db("SELECT user_id, user_name FROM user ORDER BY user_id")
    return render_template("items.html", items=item_list, users=user_list)


@app.route("/orders")
def orders() -> str:
    order_list = query_db(
        """
        SELECT orders.order_id, orders.order_date, item.item_name,
               buyer.user_name AS buyer_name, seller.user_name AS seller_name
        FROM orders
        JOIN item ON orders.item_id = item.item_id
        JOIN user AS buyer ON orders.buyer_id = buyer.user_id
        JOIN user AS seller ON item.seller_id = seller.user_id
        ORDER BY orders.order_id
        """
    )
    return render_template("orders.html", orders=order_list)


@app.route("/queries")
def queries() -> str:
    basic_queries = {
        "所有未售商品": query_db("SELECT * FROM unsold_items_view ORDER BY item_id"),
        "价格大于 30 的商品": query_db("SELECT * FROM item WHERE price > 30 ORDER BY item_id"),
        "生活用品类商品": query_db("SELECT * FROM item WHERE category = '生活用品' ORDER BY item_id"),
        "u001 发布的所有商品": query_db("SELECT * FROM item WHERE seller_id = 'u001' ORDER BY item_id"),
    }

    join_queries = {
        "所有已售商品及其买家姓名": query_db(
            """
            SELECT item.item_name, user.user_name AS buyer_name
            FROM orders
            JOIN item ON orders.item_id = item.item_id
            JOIN user ON orders.buyer_id = user.user_id
            ORDER BY item.item_id
            """
        ),
        "每个订单：商品名 + 买家名 + 日期": query_db(
            """
            SELECT item.item_name, user.user_name AS buyer_name, orders.order_date
            FROM orders
            JOIN item ON orders.item_id = item.item_id
            JOIN user ON orders.buyer_id = user.user_id
            ORDER BY orders.order_id
            """
        ),
        "卖家是 u001 的商品是否被购买": query_db(
            """
            SELECT item.item_id, item.item_name,
                   CASE WHEN orders.order_id IS NULL THEN '未购买' ELSE '已购买' END AS purchase_status
            FROM item
            LEFT JOIN orders ON item.item_id = orders.item_id
            WHERE item.seller_id = 'u001'
            ORDER BY item.item_id
            """
        ),
    }

    aggregate_queries = {
        "商品总数": query_db("SELECT COUNT(*) AS 商品总数 FROM item"),
        "每类商品数量": query_db(
            "SELECT category AS 类别, COUNT(*) AS 数量 FROM item GROUP BY category ORDER BY category"
        ),
        "所有商品平均价格": query_db("SELECT ROUND(AVG(price), 2) AS 平均价格 FROM item"),
        "发布商品数量最多的用户": query_db(
            """
            SELECT user.user_id, user.user_name, COUNT(item.item_id) AS 商品数量
            FROM user
            JOIN item ON user.user_id = item.seller_id
            GROUP BY user.user_id, user.user_name
            ORDER BY 商品数量 DESC, user.user_id ASC
            LIMIT 1
            """
        ),
    }

    view_queries = {
        "已售商品视图（商品名 + 买家 ID）": query_db("SELECT * FROM sold_items_view ORDER BY item_name"),
        "未售商品视图": query_db("SELECT * FROM unsold_items_view ORDER BY item_id"),
    }

    return render_template(
        "queries.html",
        basic_queries=basic_queries,
        join_queries=join_queries,
        aggregate_queries=aggregate_queries,
        view_queries=view_queries,
    )


@app.route("/report")
def report() -> str:
    return render_template("report.html")


@app.route("/healthz")
def healthz():
    db_status = "ok"
    try:
        query_db("SELECT 1")
    except sqlite3.Error:
        db_status = "error"
    status_code = 200 if db_status == "ok" else 503
    return (
        jsonify(
            {
                "status": "ok" if db_status == "ok" else "degraded",
                "db": db_status,
                "env": APP_ENV,
                "uptime_seconds": int(time.time() - START_TIME),
            }
        ),
        status_code,
    )


@app.route("/reset", methods=["POST"])
def reset() -> str:
    require_admin()
    require_reset_token()
    init_db()
    flash("数据库已重置为初始数据。", "success")
    return redirect(url_for("index"))


if __name__ == "__main__":
    validate_runtime_config()
    ensure_database()
    app.run(debug=APP_ENV != "production")

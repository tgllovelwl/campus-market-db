DROP VIEW IF EXISTS sold_items_view;
DROP VIEW IF EXISTS unsold_items_view;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS item;
DROP TABLE IF EXISTS user;

CREATE TABLE user (
    user_id TEXT PRIMARY KEY,
    user_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE
);

CREATE TABLE item (
    item_id TEXT PRIMARY KEY,
    item_name TEXT NOT NULL,
    category TEXT NOT NULL,
    price REAL NOT NULL CHECK (price >= 0),
    status INTEGER NOT NULL DEFAULT 0 CHECK (status IN (0, 1)),
    seller_id TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (DATE('now')),
    FOREIGN KEY (seller_id) REFERENCES user(user_id)
);

CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
    buyer_id TEXT NOT NULL,
    item_id TEXT NOT NULL UNIQUE,
    order_date TEXT NOT NULL,
    FOREIGN KEY (buyer_id) REFERENCES user(user_id),
    FOREIGN KEY (item_id) REFERENCES item(item_id)
);

-- 性能优化：常用查询索引
CREATE INDEX idx_item_status ON item(status);
CREATE INDEX idx_item_category ON item(category);
CREATE INDEX idx_item_seller ON item(seller_id);
CREATE INDEX idx_orders_buyer ON orders(buyer_id);

-- 一致性兜底（数据库层面强制作业规则）
-- 1) 已售商品不能再次购买（禁止对 status=1 的商品插入订单）
CREATE TRIGGER trg_orders_insert_only_unsold
BEFORE INSERT ON orders
FOR EACH ROW
BEGIN
    SELECT
        CASE
            WHEN (SELECT status FROM item WHERE item_id = NEW.item_id) = 1
            THEN RAISE(ABORT, 'item already sold')
        END;
END;

-- 2) 只要商品出现在 orders 中，item.status 必须为 1（插入订单后自动更新）
CREATE TRIGGER trg_orders_after_insert_mark_sold
AFTER INSERT ON orders
FOR EACH ROW
BEGIN
    UPDATE item SET status = 1 WHERE item_id = NEW.item_id;
END;

-- 3) 若商品已在 orders 中，则不允许把 status 改回 0
CREATE TRIGGER trg_item_no_unsold_if_ordered
BEFORE UPDATE OF status ON item
FOR EACH ROW
WHEN NEW.status = 0 AND EXISTS (SELECT 1 FROM orders WHERE item_id = OLD.item_id)
BEGIN
    SELECT RAISE(ABORT, 'cannot set status=0 when ordered');
END;

-- 4) 若商品已在 orders 中，则不允许删除该商品
CREATE TRIGGER trg_item_no_delete_if_ordered
BEFORE DELETE ON item
FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM orders WHERE item_id = OLD.item_id)
BEGIN
    SELECT RAISE(ABORT, 'cannot delete ordered item');
END;

CREATE VIEW sold_items_view AS
SELECT item.item_name, orders.buyer_id
FROM item
JOIN orders ON item.item_id = orders.item_id
WHERE item.status = 1;

CREATE VIEW unsold_items_view AS
SELECT item_id, item_name, category, price, seller_id, description
FROM item
WHERE status = 0;

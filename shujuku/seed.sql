INSERT INTO user (user_id, user_name, phone, email) VALUES
('u001', '张明', '13800000001', 'zhangming@example.com'),
('u002', '李华', '13800000002', 'lihua@example.com'),
('u003', '王芳', '13800000003', 'wangfang@example.com'),
('u004', '赵强', '13800000004', 'zhaoqiang@example.com');

INSERT INTO item (item_id, item_name, category, price, status, seller_id, description, created_at) VALUES
('i001', '高数教材', '学习用品', 25.00, 0, 'u001', '九成新，适合大一学生。', '2026-04-10'),
('i002', '二手台灯', '生活用品', 35.00, 0, 'u001', '宿舍护眼台灯，功能正常。', '2026-04-09'),
('i003', '羽毛球拍', '体育用品', 48.00, 0, 'u002', '含拍套，轻微使用痕迹。', '2026-04-11'),
('i004', '收纳箱', '生活用品', 18.00, 0, 'u003', '适合宿舍衣物收纳。', '2026-04-08'),
('i005', '机械键盘', '电子产品', 88.00, 0, 'u004', '青轴，灯光正常。', '2026-04-12'),
('i006', '保温杯', '生活用品', 29.90, 0, 'u002', '500ml，不漏水。', '2026-04-13');

INSERT INTO orders (buyer_id, item_id, order_date) VALUES
('u002', 'i002', '2026-04-14'),
('u003', 'i005', '2026-04-15');

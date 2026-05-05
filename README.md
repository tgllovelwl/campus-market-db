# 校园二手交易平台数据库系统

这是一个基于 `Flask + SQLite` 的数据库课程作业项目，覆盖以下要求：

- 首页、商品列表、用户列表、订单列表页面
- 页面展示真实数据库数据
- 新增商品、修改价格、删除未售商品
- 基本查询、连接查询、聚合与分组
- 已售商品视图、未售商品视图
- 购买商品业务逻辑
- 安全性说明、并发与恢复说明

## 本地运行

1. 安装 Python 3.10 及以上版本
2. 安装依赖：

```bash
pip install -r requirements.txt
```

3. 启动项目：

```bash
python app.py
```

4. 浏览器访问：

```text
http://127.0.0.1:5000
```

## 项目结构

```text
shujuku/
├── app.py
├── schema.sql
├── seed.sql
├── campus_market.db
├── requirements.txt
├── README.md
├── static/
│   └── style.css
└── templates/
    ├── base.html
    ├── index.html
    ├── items.html
    ├── users.html
    ├── orders.html
    ├── queries.html
    └── report.html
```

## 说明

- 首次运行会自动初始化数据库。
- 首页提供“重置数据库为初始数据”按钮，方便录屏和重复演示。
- 购买商品时会自动写入 `orders` 表并更新 `item.status = 1`。
- `orders.item_id` 唯一，保证每个商品最多交易一次。
- 首页已经整理为“作业提交版首页”，可直接按页面导览顺序进行截图和录屏。
- `docs/项目说明文档模板.md` 可直接作为提交说明文档的写作模板。

## 部署建议

推荐部署到 Render（最省事）。本项目已包含：

- `render.yaml`：Render 一键部署配置（含 1GB 持久化磁盘）
- `Procfile`：进程启动命令
- `runtime.txt`：Python 版本

部署后数据库会保存在 Render 磁盘 `/var/data/campus_market.db`，不会因为重新发布而丢失。

### Render 部署最短步骤

1. 把整个项目上传到 GitHub 仓库
2. 在 Render 选择 “Blueprint”，导入该仓库（会自动识别 `render.yaml`）
3. 部署完成后获得在线网址
4. 在 Render 的 Environment 里建议设置：
   - `APP_ENV=production`
   - `SECRET_KEY=（随机长字符串）`
   - `RESET_TOKEN=（可选，用来保护重置数据库）`
   - `ADMIN_PASSWORD=（管理员口令，用于启用新增/改价/删除/重置）`
   - `LOGIN_MAX_ATTEMPTS=5`（管理员登录窗口内最大失败次数）
   - `LOGIN_WINDOW_SECONDS=300`（统计失败次数的时间窗口）
   - `LOGIN_LOCK_SECONDS=600`（触发限速后锁定时长）
   - `LOG_PATH=/var/data/app.log`（可选，日志文件路径）

## 安全与审计增强（已实现）

- 管理员/普通用户模式：普通用户仅查询与购买，新增/改价/删除/重置仅管理员可执行
- CSRF 防护：所有写操作必须携带 `csrf_token`
- 业务边界：禁止购买自己发布的商品
- 输入校验：ID 格式、文本长度、价格范围在后端统一校验
- 请求日志：每个请求生成追踪 ID，并输出基础访问日志与异常日志
- 登录限速：管理员登录支持失败次数限制与临时锁定，降低口令撞库风险
- 健康检查：提供 `/healthz` 供部署平台探活与监控使用

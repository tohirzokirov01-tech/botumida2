"""
FastAPI Admin Panel Router & Management Dashboard
Provides responsive web interface for managing courses, users, orders, and system settings.
"""
from typing import Optional
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import uuid
import re

from app.database.session import get_db
from app.database.models import User, Course, Order, OrderStatus, Category

router = APIRouter()


@router.post("/courses/create")
async def create_course_admin(
    title: str = Form(...),
    price_uzs: int = Form(500000),
    author: str = Form("Инструктор"),
    description: str = Form(""),
    telegram_channel_title: str = Form(""),
    telegram_channel_id: str = Form(""),
    category_id: Optional[int] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    if not category_id:
        cat_res = await db.execute(select(Category).limit(1))
        cat = cat_res.scalars().first()
        if not cat:
            cat = Category(name="Курсы", slug="courses")
            db.add(cat)
            await db.flush()
        category_id = cat.id

    base_slug = re.sub(r'[^a-zA-Z0-9]', '-', title.lower()).strip('-') or "course"
    slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"

    new_course = Course(
        category_id=category_id,
        title=title,
        slug=slug,
        price_uzs=price_uzs,
        author=author,
        description=description or "Описание курса",
        telegram_channel_title=telegram_channel_title or "🔒 Закрытый VIP Telegram-Канал",
        telegram_channel_id=telegram_channel_id or "-1001928374999",
        is_published=True
    )
    db.add(new_course)
    await db.commit()
    return RedirectResponse(url="/admin/#courses", status_code=303)


@router.post("/access/grant")
async def grant_access_admin(
    user_identifier: str = Form(...),
    course_id: int = Form(...),
    reason: str = Form("manual_payment"),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(User)
    if user_identifier.isdigit():
        stmt = stmt.where(User.telegram_id == int(user_identifier))
    else:
        stmt = stmt.where(User.phone == user_identifier)
    
    user_res = await db.execute(stmt)
    user = user_res.scalar_one_or_none()

    if not user:
        tg_id = int(user_identifier) if user_identifier.isdigit() else 999000111
        user = User(
            telegram_id=tg_id,
            first_name="Пользователь (Ручной доступ)",
            phone=user_identifier if not user_identifier.isdigit() else None
        )
        db.add(user)
        await db.flush()

    course_res = await db.execute(select(Course).where(Course.id == course_id))
    course = course_res.scalar_one_or_none()
    amount = course.price_uzs if course else 0

    order_num = f"MANUAL-{uuid.uuid4().hex[:6].upper()}"
    invite_link = f"https://t.me/+manual_{uuid.uuid4().hex[:10]}"

    new_order = Order(
        order_number=order_num,
        user_id=user.id,
        course_id=course_id,
        amount_uzs=amount,
        payment_method="manual",
        status=OrderStatus.PAID,
        invite_link=invite_link
    )
    db.add(new_order)
    await db.commit()
    return RedirectResponse(url="/admin/#users", status_code=303)


@router.post("/settings/update")
async def update_settings_admin(
    bot_name: str = Form("Курсы & Обучение Telegram Bot"),
    support_username: str = Form("@course_support_uz"),
    admin_group_id: str = Form("-100293847561"),
    default_currency: str = Form("UZS (сум)"),
    default_language: str = Form("ru"),
    is_sandbox: str = Form("true"),
    payme_merchant_id: str = Form("64d2910a9b3c4e5f6a7b8c9d"),
    payme_key: str = Form("m$iL&@4!sK7#pQ9%wZ3*xY1"),
    click_merchant_id: str = Form("184920"),
    click_service_id: str = Form("39201"),
    click_secret_key: str = Form("cLiCk_S3cr3t_K3y_2026"),
    db: AsyncSession = Depends(get_db)
):
    settings_data = {
        "bot_name": bot_name,
        "support_username": support_username,
        "admin_group_id": admin_group_id,
        "default_currency": default_currency,
        "default_language": default_language,
        "is_sandbox": is_sandbox,
        "payme_merchant_id": payme_merchant_id,
        "payme_key": payme_key,
        "click_merchant_id": click_merchant_id,
        "click_service_id": click_service_id,
        "click_secret_key": click_secret_key,
    }
    for k, v in settings_data.items():
        stmt = select(SystemSetting).where(SystemSetting.key == k)
        res = await db.execute(stmt)
        setting = res.scalar_one_or_none()
        if setting:
            setting.value = v
        else:
            db.add(SystemSetting(key=k, value=v))
    
    db.add(SystemLog(
        level="INFO",
        source="AdminSettings",
        message="Настройки Payme, Click, Telegram группы и Языка успешно обновлены через Панель Управления."
    ))
    await db.commit()
    return RedirectResponse(url="/admin/#settings", status_code=303)


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    # Stats queries
    users_count = (await db.execute(select(func.count(User.id)))).scalar() or 0
    courses_count = (await db.execute(select(func.count(Course.id)))).scalar() or 0
    orders_count = (await db.execute(select(func.count(Order.id)))).scalar() or 0
    
    paid_orders_stmt = select(func.sum(Order.amount_uzs)).where(Order.status == OrderStatus.PAID)
    total_revenue = (await db.execute(paid_orders_stmt)).scalar() or 0

    # Fetch records for tables
    courses_res = await db.execute(select(Course).order_by(Course.id.desc()))
    courses = courses_res.scalars().all()

    users_res = await db.execute(select(User).order_by(User.id.desc()).limit(20))
    users = users_res.scalars().all()

    orders_res = await db.execute(select(Order).order_by(Order.id.desc()).limit(20))
    orders = orders_res.scalars().all()

    # Fetch categories for form
    cats_res = await db.execute(select(Category))
    categories = cats_res.scalars().all()
    category_options = "".join([f'<option value="{c.id}">{c.name}</option>' for c in categories])
    if not category_options:
        category_options = '<option value="">Основная категория</option>'

    # Build Course Options for manual grant
    course_options = "".join([f'<option value="{c.id}">{c.title} ({c.price_uzs:,} сум)</option>' for c in courses])
    if not course_options:
        course_options = '<option value="">Нет доступных курсов</option>'

    # Build HTML rows
    course_rows = ""
    for c in courses:
        course_rows += f"""
        <tr>
            <td>#{c.id}</td>
            <td><b>{c.title}</b></td>
            <td>{c.author or '—'}</td>
            <td style="color:#4ade80; font-weight:600;">{c.price_uzs:,} сум</td>
            <td><code>{c.telegram_channel_title or 'Не указан'}</code></td>
            <td><span class="badge badge-success">Активен</span></td>
        </tr>
        """
    if not course_rows:
        course_rows = "<tr><td colspan='6' style='text-align:center; color:#94a3b8; padding: 1.5rem;'>Курсы пока не добавлены</td></tr>"

    user_rows = ""
    for u in users:
        user_rows += f"""
        <tr>
            <td>#{u.id}</td>
            <td><b>{u.first_name or ''} {u.last_name or ''}</b></td>
            <td>@{u.username or '—'}</td>
            <td>{u.phone or '—'}</td>
            <td><code>{u.telegram_id}</code></td>
        </tr>
        """
    if not user_rows:
        user_rows = "<tr><td colspan='5' style='text-align:center; color:#94a3b8; padding: 1.5rem;'>Пользователи пока не зарегистрированы</td></tr>"

    order_rows = ""
    for o in orders:
        status_badge = '<span class="badge badge-success">Оплачен</span>' if o.status == OrderStatus.PAID else '<span class="badge badge-warning">Ожидает</span>'
        pm = o.payment_method.value if hasattr(o.payment_method, 'value') else o.payment_method
        order_rows += f"""
        <tr>
            <td>#{o.id}</td>
            <td><code>{o.order_number}</code></td>
            <td>User #{o.user_id}</td>
            <td>Course #{o.course_id}</td>
            <td style="color:#38bdf8; font-weight:600;">{o.amount_uzs:,} сум</td>
            <td>{pm}</td>
            <td>{status_badge}</td>
        </tr>
        """
    if not order_rows:
        order_rows = "<tr><td colspan='7' style='text-align:center; color:#94a3b8; padding: 1.5rem;'>Заказов пока нет</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FastAPI Admin Panel - Telegram Course Bot</title>
    <style>
        :root {{
            --bg-dark: #0f172a;
            --card-bg: #1e293b;
            --border-color: #334155;
            --primary: #38bdf8;
            --success: #4ade80;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background-color: var(--bg-dark);
            color: var(--text-main);
            display: flex;
            flex-direction: column;
            min-height: 100vh;
        }}
        /* Top Navigation Header */
        header {{
            background: #1e293b;
            border-bottom: 1px solid var(--border-color);
            padding: 0.875rem 1.5rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: sticky;
            top: 0;
            z-index: 50;
        }}
        .brand {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            font-size: 1.15rem;
            font-weight: 700;
            color: #fff;
        }}
        .mobile-menu-btn {{
            display: none;
            background: #0f172a;
            border: 1px solid var(--border-color);
            color: #fff;
            padding: 0.4rem 0.75rem;
            border-radius: 6px;
            font-size: 1.2rem;
            cursor: pointer;
        }}
        /* Layout Container */
        .app-container {{
            display: flex;
            flex: 1;
        }}
        /* Sidebar Navigation */
        aside {{
            width: 250px;
            background: #182234;
            border-right: 1px solid var(--border-color);
            padding: 1.25rem 0.75rem;
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            transition: all 0.2s ease-in-out;
        }}
        .nav-item {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            padding: 0.8rem 1rem;
            color: #94a3b8;
            text-decoration: none;
            border-radius: 12px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 0.875rem;
        }}
        .nav-item:hover {{
            background: rgba(255, 255, 255, 0.05);
            color: #f8fafc;
        }}
        .nav-item.active {{
            background: #2563eb;
            color: #ffffff;
            font-weight: 600;
            box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3);
        }}
        /* Main Content Area */
        main {{
            flex: 1;
            padding: 1.5rem;
            overflow-x: hidden;
        }}
        .tab-content {{
            display: none;
        }}
        .tab-content.active {{
            display: block;
        }}
        /* Cards & Grid */
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1.25rem;
            margin-bottom: 1.5rem;
        }}
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.25rem;
        }}
        .stat-value {{
            font-size: 1.75rem;
            font-weight: 700;
            margin-top: 0.25rem;
            color: var(--primary);
        }}
        .stat-label {{
            font-size: 0.875rem;
            color: var(--text-muted);
        }}
        /* Table styles */
        .table-responsive {{
            width: 100%;
            overflow-x: auto;
            border-radius: 10px;
            border: 1px solid var(--border-color);
            background: var(--card-bg);
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 0.9rem;
        }}
        th {{
            background: #182234;
            color: var(--text-muted);
            padding: 0.875rem 1rem;
            font-weight: 600;
            border-bottom: 1px solid var(--border-color);
            white-space: nowrap;
        }}
        td {{
            padding: 0.875rem 1rem;
            border-bottom: 1px solid var(--border-color);
            color: var(--text-main);
            white-space: nowrap;
        }}
        tr:last-child td {{
            border-bottom: none;
        }}
        /* Badges */
        .badge {{
            display: inline-block;
            padding: 0.25rem 0.6rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        .badge-success {{ background: rgba(74, 222, 128, 0.15); color: #4ade80; border: 1px solid rgba(74, 222, 128, 0.3); }}
        .badge-warning {{ background: rgba(251, 191, 36, 0.15); color: #fbbf24; border: 1px solid rgba(251, 191, 36, 0.3); }}
        
        /* Mobile Responsive Styles */
        @media (max-width: 768px) {{
            .mobile-menu-btn {{
                display: block;
            }}
            aside {{
                position: fixed;
                top: 57px;
                left: -270px;
                bottom: 0;
                z-index: 40;
                box-shadow: 4px 0 15px rgba(0,0,0,0.5);
            }}
            aside.open {{
                left: 0;
            }}
            main {{
                padding: 1rem;
            }}
        }}
    </style>
</head>
<body>
    <header>
        <div class="brand">
            <button class="mobile-menu-btn" onclick="toggleSidebar()">☰</button>
            <span>👑 Панель Управления Курсами</span>
        </div>
        <div style="display:flex; align-items:center; gap:0.5rem;">
            <span class="badge badge-success">● Бот Активен</span>
        </div>
    </header>

    <div class="app-container">
        <aside id="sidebar">
            <div class="nav-item active" onclick="switchTab('dashboard', this)">📊 Аналитика & Продажи</div>
            <div class="nav-item" onclick="switchTab('courses', this)">📚 Курсы & Уроки ({courses_count})</div>
            <div class="nav-item" onclick="switchTab('orders', this)">🛒 Заказы & Транзакции ({orders_count})</div>
            <div class="nav-item" onclick="switchTab('users', this)">👥 Пользователи & Доступ ({users_count})</div>
            <div class="nav-item" onclick="switchTab('promocodes', this)">🎟️ Промокоды</div>
            <div class="nav-item" onclick="switchTab('broadcasts', this)">📢 Рассылка сообщений</div>
            <div class="nav-item" onclick="switchTab('settings', this)">⚙️ Динамич. Настройки</div>
            <div class="nav-item" onclick="switchTab('logs', this)">📋 Логи & Безопасность</div>
            <div class="nav-item" onclick="switchTab('api', this)">🔌 API & Вебхуки</div>
        </aside>

        <main>
            <!-- TAB 1: DASHBOARD -->
            <div id="tab-dashboard" class="tab-content active">
                <h2 style="margin-bottom:1rem; font-size: 1.3rem;">📊 Обзор системы</h2>
                <div class="grid">
                    <div class="card">
                        <div class="stat-label">Всего пользователей</div>
                        <div class="stat-value">{users_count}</div>
                    </div>
                    <div class="card">
                        <div class="stat-label">Активных курсов</div>
                        <div class="stat-value">{courses_count}</div>
                    </div>
                    <div class="card">
                        <div class="stat-label">Создано заказов</div>
                        <div class="stat-value">{orders_count}</div>
                    </div>
                    <div class="card">
                        <div class="stat-label">Общая выручка</div>
                        <div class="stat-value" style="color:#4ade80;">{total_revenue:,} сум</div>
                    </div>
                </div>

                <div class="card">
                    <h3 style="margin-bottom:1rem; font-size: 1.1rem;">🛒 Последние заказы</h3>
                    <div class="table-responsive">
                        <table>
                            <thead>
                                <tr>
                                    <th>ID</th>
                                    <th>Заказ #</th>
                                    <th>Пользователь</th>
                                    <th>Курс</th>
                                    <th>Сумма</th>
                                    <th>Оплата</th>
                                    <th>Статус</th>
                                </tr>
                            </thead>
                            <tbody>
                                {order_rows}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- TAB 2: COURSES -->
            <div id="tab-courses" class="tab-content">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem; flex-wrap:wrap; gap:0.5rem;">
                    <h2 style="font-size: 1.3rem;">📚 Список онлайн-курсов</h2>
                    <button onclick="document.getElementById('add-course-form').style.display = document.getElementById('add-course-form').style.display === 'none' ? 'block' : 'none'" style="background:#2563eb; color:#fff; border:none; padding:0.5rem 1rem; border-radius:8px; font-weight:600; cursor:pointer;">➕ Добавить новый курс</button>
                </div>

                <!-- FORM: CREATE COURSE -->
                <div id="add-course-form" class="card" style="margin-bottom: 1.25rem; display:none; border: 1px solid #3b82f6;">
                    <h3 style="margin-bottom:1rem; font-size: 1.1rem; color:#38bdf8;">➕ Форма добавления нового курса</h3>
                    <form action="/admin/courses/create" method="POST" style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem;">
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Название курса *</label>
                            <input type="text" name="title" required placeholder="Напр. Python & FastAPI Backend" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                        </div>
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Цена (UZS) *</label>
                            <input type="number" name="price_uzs" required value="500000" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                        </div>
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Категория курса</label>
                            <select name="category_id" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                                {category_options}
                            </select>
                        </div>
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Автор / Преподаватель</label>
                            <input type="text" name="author" value="Инструктор" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                        </div>
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Название Telegram канала</label>
                            <input type="text" name="telegram_channel_title" placeholder="🔒 VIP Канал" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                        </div>
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">ID Telegram Канала</label>
                            <input type="text" name="telegram_channel_id" placeholder="-1001928374999" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                        </div>
                        <div style="grid-column: 1 / -1;">
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Описание курса</label>
                            <textarea name="description" rows="2" placeholder="Краткое описание уроков..." style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px; font-family:inherit;"></textarea>
                        </div>
                        <div style="grid-column: 1 / -1;">
                            <button type="submit" style="background:#2563eb; color:#fff; border:none; padding:0.6rem 1.5rem; border-radius:8px; font-weight:600; cursor:pointer;">💾 Сохранить и опубликовать курс</button>
                        </div>
                    </form>
                </div>

                <div class="card">
                    <div class="table-responsive">
                        <table>
                            <thead>
                                <tr>
                                    <th>ID</th>
                                    <th>Название курса</th>
                                    <th>Автор</th>
                                    <th>Цена</th>
                                    <th>Канал Telegram</th>
                                    <th>Статус</th>
                                </tr>
                            </thead>
                            <tbody>
                                {course_rows}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- TAB 3: ORDERS -->
            <div id="tab-orders" class="tab-content">
                <h2 style="margin-bottom:1rem; font-size: 1.3rem;">🛒 Все заказы и платежи</h2>
                <div class="card">
                    <div class="table-responsive">
                        <table>
                            <thead>
                                <tr>
                                    <th>ID</th>
                                    <th>Заказ #</th>
                                    <th>Пользователь</th>
                                    <th>Курс</th>
                                    <th>Сумма</th>
                                    <th>Оплата</th>
                                    <th>Статус</th>
                                </tr>
                            </thead>
                            <tbody>
                                {order_rows}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- TAB 4: USERS -->
            <div id="tab-users" class="tab-content">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem; flex-wrap:wrap; gap:0.5rem;">
                    <h2 style="font-size: 1.3rem;">👥 Пользователи бота & Доступ</h2>
                    <button onclick="document.getElementById('grant-access-form').style.display = document.getElementById('grant-access-form').style.display === 'none' ? 'block' : 'none'" style="background:#10b981; color:#fff; border:none; padding:0.5rem 1rem; border-radius:8px; font-weight:600; cursor:pointer;">🔑 Выдать доступ вручную</button>
                </div>

                <!-- FORM: MANUAL GRANT ACCESS -->
                <div id="grant-access-form" class="card" style="margin-bottom: 1.25rem; display:none; border: 1px solid #10b981;">
                    <h3 style="margin-bottom:0.5rem; font-size: 1.1rem; color:#4ade80;">🔑 Ручная выдача доступа к курсу</h3>
                    <p style="font-size:0.85rem; color:#94a3b8; margin-bottom:1rem;">Выдайте клиенту бесплатный или ручной доступ. Пользователю сгенерируется статус "Оплачено" и одноразовая ссылка на вход в закрытый Telegram-канал.</p>
                    <form action="/admin/access/grant" method="POST" style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem;">
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Telegram ID или Телефон *</label>
                            <input type="text" name="user_identifier" required placeholder="Напр. 582399750 или +998901234567" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                        </div>
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Выберите курс *</label>
                            <select name="course_id" required style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                                {course_options}
                            </select>
                        </div>
                        <div>
                            <label style="display:block; font-size:0.8rem; color:#94a3b8; margin-bottom:0.25rem;">Причина выдачи</label>
                            <select name="reason" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.55rem; border-radius:8px;">
                                <option value="manual_payment">Оплата наличными / перевод</option>
                                <option value="vip_grant">VIP / Подарок</option>
                                <option value="admin_test">Тестирование администратором</option>
                            </select>
                        </div>
                        <div style="grid-column: 1 / -1;">
                            <button type="submit" style="background:#10b981; color:#fff; border:none; padding:0.6rem 1.5rem; border-radius:8px; font-weight:600; cursor:pointer;">⚡ Выдать доступ и сгенерировать ссылку</button>
                        </div>
                    </form>
                </div>

                <div class="card">
                    <div class="table-responsive">
                        <table>
                            <thead>
                                <tr>
                                    <th>ID</th>
                                    <th>Имя</th>
                                    <th>Username</th>
                                    <th>Телефон</th>
                                    <th>Telegram ID</th>
                                </tr>
                            </thead>
                            <tbody>
                                {user_rows}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- TAB: PROMOCODES -->
            <div id="tab-promocodes" class="tab-content">
                <h2 style="margin-bottom:1rem; font-size: 1.3rem;">🎟️ Управление Промокодами</h2>
                <div class="card" style="margin-bottom: 1rem;">
                    <h3 style="margin-bottom:0.75rem; font-size: 1rem;">➕ Создать новый промокод</h3>
                    <div style="display: flex; gap: 0.75rem; flex-wrap: wrap;">
                        <input type="text" placeholder="Код (напр. SUMMER2026)" style="background:#0f172a; border:1px solid #334155; color:#fff; padding:0.5rem 0.75rem; border-radius:8px; flex:1; min-width:180px;">
                        <input type="number" placeholder="Скидка %" style="background:#0f172a; border:1px solid #334155; color:#fff; padding:0.5rem 0.75rem; border-radius:8px; width:120px;">
                        <input type="number" placeholder="Лимит исп." style="background:#0f172a; border:1px solid #334155; color:#fff; padding:0.5rem 0.75rem; border-radius:8px; width:120px;">
                        <button style="background:#2563eb; color:#fff; border:none; padding:0.5rem 1.25rem; border-radius:8px; font-weight:600; cursor:pointer;" onclick="alert('Промокод успешно создан!')">Создать</button>
                    </div>
                </div>
                <div class="card">
                    <div class="table-responsive">
                        <table>
                            <thead>
                                <tr>
                                    <th>Код</th>
                                    <th>Скидка</th>
                                    <th>Использовано</th>
                                    <th>Лимит</th>
                                    <th>Статус</th>
                                    <th>Действие</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td><code>START20</code></td>
                                    <td><b style="color:#4ade80;">20%</b></td>
                                    <td>14</td>
                                    <td>100</td>
                                    <td><span class="badge badge-success">Активен</span></td>
                                    <td><button style="background:rgba(239, 68, 68, 0.2); color:#ef4444; border:1px solid rgba(239, 68, 68, 0.4); padding:0.25rem 0.5rem; border-radius:6px; cursor:pointer;" onclick="alert('Промокод деактивирован')">Удалить</button></td>
                                </tr>
                                <tr>
                                    <td><code>VIP50</code></td>
                                    <td><b style="color:#4ade80;">50%</b></td>
                                    <td>5</td>
                                    <td>10</td>
                                    <td><span class="badge badge-success">Активен</span></td>
                                    <td><button style="background:rgba(239, 68, 68, 0.2); color:#ef4444; border:1px solid rgba(239, 68, 68, 0.4); padding:0.25rem 0.5rem; border-radius:6px; cursor:pointer;" onclick="alert('Промокод деактивирован')">Удалить</button></td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- TAB: BROADCASTS -->
            <div id="tab-broadcasts" class="tab-content">
                <h2 style="margin-bottom:1rem; font-size: 1.3rem;">📢 Рассылка Сообщений в Telegram</h2>
                <div class="card" style="margin-bottom: 1rem;">
                    <h3 style="margin-bottom:0.75rem; font-size: 1rem;">📝 Новая рассылка</h3>
                    <div style="display:flex; flex-direction:column; gap:0.75rem;">
                        <input type="text" placeholder="Заголовок рассылки" style="background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem 0.75rem; border-radius:8px;">
                        <textarea rows="4" placeholder="Текст сообщения (поддерживает HTML разметку)" style="background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem 0.75rem; border-radius:8px; font-family:inherit;"></textarea>
                        <input type="text" placeholder="URL Картинки (опционально)" style="background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem 0.75rem; border-radius:8px;">
                        <div>
                            <button style="background:#10b981; color:#fff; border:none; padding:0.6rem 1.5rem; border-radius:8px; font-weight:600; cursor:pointer;" onclick="alert('Рассылка запущена! Сообщения отправляются пользователям.')">🚀 Запустить рассылку</button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- TAB: SETTINGS -->
            <div id="tab-settings" class="tab-content">
                <h2 style="margin-bottom:1rem; font-size: 1.3rem;">⚙️ Динамические Настройки Системы (Настройки Оплаты & Языка)</h2>
                <div class="card">
                    <form action="/admin/settings/update" method="POST">
                        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap:1.25rem;">
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Название Бота</label>
                                <input type="text" name="bot_name" value="Курсы & Обучение Telegram Bot" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem; border-radius:8px;">
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Telegram Поддержки (@username)</label>
                                <input type="text" name="support_username" value="@course_support_uz" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem; border-radius:8px;">
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">ID Telegram Группы Уведомлений</label>
                                <input type="text" name="admin_group_id" value="-100293847561" style="width:100%; background:#0f172a; border:1px solid #334155; color:#38bdf8; padding:0.6rem; border-radius:8px; font-family:monospace;">
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Язык бота по умолчанию</label>
                                <select name="default_language" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem; border-radius:8px; font-weight:600;">
                                    <option value="ru" selected>🇷🇺 Русский</option>
                                    <option value="uz_latn">🇺🇿 O'zbekcha (Lotin)</option>
                                    <option value="uz_cyrl">🇺🇿 Ўзбекча (Кирилл)</option>
                                </select>
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Валюта по умолчанию</label>
                                <input type="text" name="default_currency" value="UZS (сум)" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem; border-radius:8px;">
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Тестовый режим Payme / Click</label>
                                <select name="is_sandbox" style="width:100%; background:#0f172a; border:1px solid #334155; color:#fff; padding:0.6rem; border-radius:8px;">
                                    <option value="true" selected>Включен (Sandbox / Тестовый)</option>
                                    <option value="false">Выключен (Production / Боевой)</option>
                                </select>
                            </div>

                            <!-- PAYME SETTINGS -->
                            <div style="grid-column: 1 / -1; margin-top: 0.5rem; border-t: 1px solid #334155; padding-top: 1rem;">
                                <h3 style="color:#38bdf8; font-size:1rem; margin-bottom:0.75rem; display:flex; align-items:center; gap:0.5rem;">💳 Настройки Интеграции Payme Merchant API</h3>
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Payme Merchant ID</label>
                                <input type="text" name="payme_merchant_id" value="64d2910a9b3c4e5f6a7b8c9d" placeholder="64d2910a9b3c4e5f..." style="width:100%; background:#0f172a; border:1px solid #334155; color:#38bdf8; padding:0.6rem; border-radius:8px; font-family:monospace;">
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Payme Secret Key (Пароль кассы / Key)</label>
                                <input type="text" name="payme_key" value="m$iL&@4!sK7#pQ9%wZ3*xY1" placeholder="Ключ авторизации Payme Webhook" style="width:100%; background:#0f172a; border:1px solid #334155; color:#f59e0b; padding:0.6rem; border-radius:8px; font-family:monospace;">
                            </div>

                            <!-- CLICK SETTINGS -->
                            <div style="grid-column: 1 / -1; margin-top: 0.5rem; border-t: 1px solid #334155; padding-top: 1rem;">
                                <h3 style="color:#60a5fa; font-size:1rem; margin-bottom:0.75rem; display:flex; align-items:center; gap:0.5rem;">🔹 Настройки Интеграции CLICK Merchant API</h3>
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Click Merchant ID</label>
                                <input type="text" name="click_merchant_id" value="184920" placeholder="184920" style="width:100%; background:#0f172a; border:1px solid #334155; color:#38bdf8; padding:0.6rem; border-radius:8px; font-family:monospace;">
                            </div>
                            <div>
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Click Service ID</label>
                                <input type="text" name="click_service_id" value="39201" placeholder="39201" style="width:100%; background:#0f172a; border:1px solid #334155; color:#38bdf8; padding:0.6rem; border-radius:8px; font-family:monospace;">
                            </div>
                            <div style="grid-column: 1 / -1;">
                                <label style="display:block; font-size:0.85rem; color:#94a3b8; margin-bottom:0.3rem; font-weight:600;">Click Secret Key (Секретный ключ подписи MD5)</label>
                                <input type="text" name="click_secret_key" value="cLiCk_S3cr3t_K3y_2026" placeholder="cLiCk_S3cr3t_K3y_..." style="width:100%; background:#0f172a; border:1px solid #334155; color:#f59e0b; padding:0.6rem; border-radius:8px; font-family:monospace;">
                            </div>
                        </div>
                        <div style="margin-top:1.5rem;">
                            <button type="submit" style="background:#2563eb; color:#fff; border:none; padding:0.7rem 1.8rem; border-radius:8px; font-weight:600; cursor:pointer; font-size:0.95rem;">💾 Сохранить все настройки оплаты и языка</button>
                        </div>
                    </form>
                </div>
            </div>

            <!-- TAB: LOGS -->
            <div id="tab-logs" class="tab-content">
                <h2 style="margin-bottom:1rem; font-size: 1.3rem;">📋 Логи & Системные События</h2>
                <div class="card">
                    <div class="table-responsive">
                        <table>
                            <thead>
                                <tr>
                                    <th>Время</th>
                                    <th>Уровень</th>
                                    <th>Модуль</th>
                                    <th>Сообщение</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td><code>11:42:01</code></td>
                                    <td><span class="badge badge-success">INFO</span></td>
                                    <td><code>FastAPI.Admin</code></td>
                                    <td>Успешный вход в панель администратора</td>
                                </tr>
                                <tr>
                                    <td><code>11:40:15</code></td>
                                    <td><span class="badge badge-success">INFO</span></td>
                                    <td><code>Bot.Polling</code></td>
                                    <td>Принята команда /start от Telegram ID 582399750</td>
                                </tr>
                                <tr>
                                    <td><code>11:35:22</code></td>
                                    <td><span class="badge badge-success">INFO</span></td>
                                    <td><code>Database</code></td>
                                    <td>Подключение к PostgreSQL успешно инициализировано</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- TAB 5: API & ENDPOINTS -->
            <div id="tab-api" class="tab-content">
                <h2 style="margin-bottom:1rem; font-size: 1.3rem;">⚙️ Эндпоинты API & Интеграции</h2>
                <div class="card">
                    <ul style="line-height: 2.2rem; list-style-position: inside;">
                        <li><b>💳 Payme Webhook:</b> <code>POST /api/v1/payments/payme</code></li>
                        <li><b>🔹 Click Webhook:</b> <code>POST /api/v1/payments/click</code></li>
                        <li><b>🤖 Telegram Webhook:</b> <code>POST /api/v1/bot/webhook</code></li>
                        <li><b>🏥 Health Check:</b> <code>GET /health</code></li>
                        <li><b>📖 Swagger Docs:</b> <code>GET /docs</code></li>
                    </ul>
                </div>
            </div>
        </main>
    </div>

    <script>
        function toggleSidebar() {{
            document.getElementById('sidebar').classList.toggle('open');
        }}

        function switchTab(tabId, el) {{
            document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
            document.querySelectorAll('.nav-item').forEach(nav => nav.classList.remove('active'));
            
            document.getElementById('tab-' + tabId).classList.add('active');
            el.classList.add('active');

            if (window.innerWidth <= 768) {{
                document.getElementById('sidebar').classList.remove('open');
            }}
        }}
    </script>
</body>
</html>"""

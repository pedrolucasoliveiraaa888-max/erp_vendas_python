import os
import sqlite3
import json
import urllib.parse
import shutil
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from starlette.middleware.sessions import SessionMiddleware
import uvicorn

os.makedirs("static/uploads", exist_ok=True)

# ==========================================
# 1. BANCO DE DADOS & MIGRAÇÃO
# ==========================================
def get_db():
    conn = sqlite3.connect("erp_database.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS stores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, city TEXT DEFAULT 'Matriz', password TEXT DEFAULT '1234', logo_text TEXT DEFAULT 'CERBERUS-SISTEM'
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE, password_hash TEXT, name TEXT, role TEXT DEFAULT 'ADMIN', store_id INTEGER DEFAULT 1
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT, barcode TEXT DEFAULT '', name TEXT, category TEXT DEFAULT 'Geral', 
        sale_price REAL DEFAULT 0, cost_price REAL DEFAULT 0, stock_quantity REAL DEFAULT 0, 
        min_stock REAL DEFAULT 5, photo_url TEXT DEFAULT '', store_id INTEGER DEFAULT 1
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, document TEXT DEFAULT '', phone TEXT DEFAULT '', credit_limit REAL DEFAULT 1000, 
        city TEXT DEFAULT '', notes TEXT DEFAULT '', store_id INTEGER DEFAULT 1
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS receivables (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_id INTEGER DEFAULT 1, sale_id INTEGER DEFAULT 0, customer_name TEXT, 
        total_amount REAL DEFAULT 0, due_date TEXT, status TEXT DEFAULT 'PENDENTE'
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_id INTEGER DEFAULT 1, sale_number TEXT, created_at TEXT, 
        seller_name TEXT, customer_name TEXT, subtotal REAL DEFAULT 0, 
        discount REAL DEFAULT 0, total REAL DEFAULT 0, payment_method TEXT DEFAULT 'DINHEIRO'
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS sale_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER, product_id INTEGER, product_name TEXT, 
        quantity REAL DEFAULT 1, unit_price REAL DEFAULT 0, subtotal REAL DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS suppliers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, cnpj TEXT DEFAULT '', phone TEXT DEFAULT '', store_id INTEGER DEFAULT 1
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        description TEXT, amount REAL DEFAULT 0, category TEXT DEFAULT 'Geral', date TEXT, store_id INTEGER DEFAULT 1
    )""")

    # Inicialização das Lojas padrão
    if not c.execute("SELECT * FROM stores WHERE id = 1").fetchone():
        c.execute("INSERT INTO stores (id, name, city, password, logo_text) VALUES (1, 'Matriz Principal', 'Centro', '1234', 'CERBERUS MATRIZ')")
        c.execute("INSERT INTO stores (id, name, city, password, logo_text) VALUES (2, 'Filial 01', 'Zona Sul', '1234', 'CERBERUS FILIAL 1')")

    # Usuários Padrão
    if not c.execute("SELECT * FROM users WHERE username = 'admin'").fetchone():
        c.execute("INSERT INTO users (username, password_hash, name, role, store_id) VALUES ('admin', 'admin123', 'Administrador', 'ADMIN', 1)")
        c.execute("INSERT INTO users (username, password_hash, name, role, store_id) VALUES ('vendedor', '123456', 'Vendedor Teste', 'VENDEDOR', 1)")

    # Produtos de Exemplo
    if not c.execute("SELECT * FROM products").fetchone():
        c.execute("INSERT INTO products (code, barcode, name, category, sale_price, cost_price, stock_quantity, min_stock, store_id) VALUES ('101', '78910001', 'Camiseta Básica Preta', 'Vestuário', 49.90, 22.00, 25, 5, 1)")
        c.execute("INSERT INTO products (code, barcode, name, category, sale_price, cost_price, stock_quantity, min_stock, store_id) VALUES ('102', '78910002', 'Tênis Esportivo Pro', 'Calçados', 189.00, 95.00, 8, 3, 1)")

    conn.commit()
    conn.close()

init_db()

app = FastAPI(title="CERBERUS-SISTEM")
app.add_middleware(SessionMiddleware, secret_key="cerberus_secret_pro_key_2026")

@app.get("/manifest.json")
async def manifest():
    return JSONResponse({
        "name": "CERBERUS-SISTEM ERP",
        "short_name": "CERBERUS",
        "start_url": "/dashboard",
        "display": "standalone",
        "background_color": "#040814",
        "theme_color": "#0284c7"
    })

@app.get("/sw.js")
async def service_worker():
    return Response(content="// sw.js offline placeholder", media_type="application/javascript")

@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)

def get_user(request: Request):
    return request.session.get("user")

# ==========================================
# 2. LOGO E LAYOUT COM SEGURANÇA POR PERFIL
# ==========================================
def get_logo_svg(size=36):
    return f'''<svg viewBox="0 0 200 200" width="{size}" height="{size}" class="shrink-0 drop-shadow-[0_0_8px_rgba(56,189,248,0.6)]" fill="none">
        <circle cx="100" cy="100" r="90" stroke="#38bdf8" stroke-width="5" fill="#050a14"/>
        <path d="M40 70 L65 30 L85 65 L95 100 L70 130 L40 115 Z" fill="#0d1f3d" stroke="#0284c7" stroke-width="1.5"/>
        <path d="M160 70 L135 30 L115 65 L105 100 L130 130 L160 115 Z" fill="#0d1f3d" stroke="#0284c7" stroke-width="1.5"/>
        <path d="M75 40 L100 20 L125 40 L135 85 L100 135 L65 85 Z" fill="#0e2448" stroke="#38bdf8" stroke-width="2"/>
        <circle cx="90" cy="65" r="3" fill="#38bdf8"/><circle cx="110" cy="65" r="3" fill="#38bdf8"/>
        <circle cx="55" cy="70" r="2.5" fill="#38bdf8"/><circle cx="145" cy="70" r="2.5" fill="#38bdf8"/>
    </svg>'''

def render_layout(request: Request, content: str, title: str = "CERBERUS-SISTEM", active_tab: str = "dashboard", msg: str = ""):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login?msg=Por+favor,+faca+login+para+acessar", status_code=303)

    is_admin = (user.get("role") == "ADMIN")
    conn = get_db()
    stores = conn.execute("SELECT * FROM stores").fetchall()
    current_store = conn.execute("SELECT * FROM stores WHERE id = ?", (user.get("store_id", 1),)).fetchone()
    conn.close()

    store_name = current_store["name"] if current_store else "Matriz Principal"
    store_options = "".join([f'<option value="{s["id"]}" {"selected" if s["id"] == user.get("store_id", 1) else ""}>🏢 {s["name"]}</option>' for s in stores])
    alert_box = f'<div class="mb-4 p-3 bg-sky-500/20 border border-sky-500/40 text-sky-300 rounded-xl font-bold text-xs flex justify-between items-center"><span>{msg}</span><button onclick="this.parentElement.remove()" class="text-sky-200">✕</button></div>' if msg else ""

    def tc(t): return "bg-blue-600 text-white font-bold shadow-lg shadow-blue-900/40" if active_tab == t else "text-slate-400 hover:text-white hover:bg-slate-800/60"

    # Se for ADMIN: botão para trocar de loja com senha
    # Se for VENDEDOR: fixo na loja designada
    if is_admin:
        store_selector_html = f'''
        <button type="button" onclick="document.getElementById('switch_store_modal').classList.remove('hidden')" class="flex items-center gap-2 bg-slate-900 hover:bg-slate-800 border border-slate-700 text-sky-300 font-bold px-3 py-1.5 rounded-xl text-xs cursor-pointer transition-all">
            <span>🏢 {store_name}</span>
            <span class="text-[10px] text-slate-400">🔄 Trocar</span>
        </button>
        '''
    else:
        store_selector_html = f'''
        <div class="flex items-center gap-2 bg-slate-900/80 border border-slate-800 text-sky-300 font-bold px-3 py-1.5 rounded-xl text-xs">
            <span>🏢 {store_name}</span>
            <span class="text-[10px] bg-slate-800 text-slate-400 px-1.5 py-0.5 rounded">Fixo</span>
        </div>
        '''

    menu_stores_users = f'<a href="/stores-users" class="flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-semibold {tc("stores_users")}">⚙️ <span>Lojas & Funcionários</span></a>' if is_admin else ''

    html = f"""<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - CERBERUS-SISTEM</title>
    <link rel="manifest" href="/manifest.json">
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/html5-qrcode"></script>
</head>
<body class="bg-[#040814] text-slate-100 min-h-screen flex font-sans antialiased">
    <aside class="w-64 bg-[#060b17] border-r border-[#0e1a33] flex flex-col shrink-0 min-h-screen">
        <div class="p-4 border-b border-[#0e1a33] flex items-center gap-3">
            {get_logo_svg(36)}
            <div>
                <div class="font-black text-sm uppercase tracking-wider"><span class="text-white">CERBERUS</span><span class="text-sky-400">-SISTEM</span></div>
                <span class="text-[9px] text-slate-400 font-semibold uppercase block">O guardião da sua gestão</span>
            </div>
        </div>
        <nav class="flex-1 p-3 space-y-1 overflow-y-auto">
            <a href="/dashboard" class="flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-semibold {tc('dashboard')}">📊 <span>Painel Geral</span></a>
            <a href="/pdv" class="flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-semibold {tc('pdv')}">🛒 <span>Frente de Caixa (PDV)</span></a>
            <a href="/products" class="flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-semibold {tc('products')}">📦 <span>Produtos & Estoque</span></a>
            <a href="/customers" class="flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-semibold {tc('customers')}">👥 <span>Clientes & Crediário</span></a>
            <a href="/receivables" class="flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-semibold {tc('receivables')}">💳 <span>Contas a Receber</span></a>
            <a href="/expenses" class="flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-semibold {tc('expenses')}">💸 <span>Despesas & Contas</span></a>
            <a href="/suppliers" class="flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-semibold {tc('suppliers')}">🏬 <span>Fornecedores</span></a>
            <a href="/import-pdf" class="flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-semibold {tc('import_pdf')}">📄 <span>Importar PDF / OCR</span></a>
            <a href="/reports" class="flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-semibold {tc('reports')}">📈 <span>Relatórios & DRE</span></a>
            {menu_stores_users}
        </nav>
        <div class="p-3 border-t border-[#0e1a33] text-center">
            <p class="text-[10px] text-slate-500 font-bold">CERBERUS-SISTEM v2.0</p>
        </div>
    </aside>

    <div class="flex-1 flex flex-col min-w-0 min-h-screen">
        <header class="h-14 bg-[#070d1e] border-b border-[#0e1a33] px-6 flex items-center justify-between sticky top-0 z-40">
            <div class="flex items-center gap-3">
                <span class="text-xs font-bold text-sky-400 bg-sky-500/10 border border-sky-500/30 px-3 py-1 rounded-xl">🏢 {store_name}</span>
                <span class="text-[10px] font-bold px-2 py-0.5 rounded {'bg-blue-500/20 text-blue-300 border border-blue-500/30' if is_admin else 'bg-slate-800 text-slate-400'}">{user.get('role', 'OPERADOR')}</span>
            </div>
            <div class="flex items-center gap-4">
                {store_selector_html}
                <div class="flex items-center gap-3 pl-3 border-l border-slate-800">
                    <div class="w-8 h-8 rounded-xl bg-blue-600 flex items-center justify-center text-white font-bold text-xs">{user['name'][0].upper()}</div>
                    <span class="text-xs font-bold text-white">{user['name']}</span>
                    <a href="/logout" title="Encerrar Sessão" class="text-xs bg-rose-950/40 hover:bg-rose-600 border border-rose-800/40 text-rose-300 hover:text-white px-2.5 py-1 rounded-xl font-bold flex items-center gap-1 transition-all cursor-pointer">
                        🚪 Sair
                    </a>
                </div>
            </div>
        </header>
        <main class="flex-1 p-6 max-w-[1600px] w-full mx-auto space-y-6">
            {alert_box}
            {content}
        </main>
    </div>

    <!-- MODAL DE TROCA DE LOJA (EXIGE SENHA DA LOJA PARA O ADMIN) -->
    <div id="switch_store_modal" class="hidden fixed inset-0 bg-black/80 flex items-center justify-center p-4 z-50">
        <div class="bg-[#0b1329] border border-slate-700 rounded-2xl max-w-sm w-full p-6 space-y-4 shadow-2xl">
            <div class="flex justify-between items-center border-b border-slate-800 pb-2">
                <h3 class="text-sm font-bold text-white">🔄 Alternar Loja / Filial</h3>
                <button type="button" onclick="document.getElementById('switch_store_modal').classList.add('hidden')" class="text-slate-400 hover:text-white">✕</button>
            </div>
            <p class="text-xs text-slate-400">Selecione a loja e informe a <b>senha de acesso da loja</b>:</p>
            <form action="/change-store-direct" method="POST" class="space-y-3 text-xs font-bold">
                <div>
                    <label class="block text-slate-300 mb-1">Loja de Destino:</label>
                    <select name="store_id" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-sky-300 font-bold">
                        {store_options}
                    </select>
                </div>
                <div>
                    <label class="block text-slate-300 mb-1">🔒 Senha da Loja:</label>
                    <input type="password" name="store_password" required placeholder="Digite a senha da loja" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white font-mono">
                </div>
                <div class="flex justify-end gap-2 pt-2">
                    <button type="button" onclick="document.getElementById('switch_store_modal').classList.add('hidden')" class="px-4 py-2 bg-slate-800 text-slate-300 rounded-xl">Cancelar</button>
                    <button type="submit" class="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded-xl cursor-pointer">Confirmar Acesso</button>
                </div>
            </form>
        </div>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)

# ==========================================
# 3. AUTENTICAÇÃO COM DUPLA VALIDAÇÃO
# ==========================================
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, msg: str = ""):
    user = get_user(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=303)

    conn = get_db()
    stores = conn.execute("SELECT * FROM stores ORDER BY id ASC").fetchall()
    conn.close()

    store_options = "".join([f'<option value="{s["id"]}">🏢 {s["name"]}</option>' for s in stores])
    alert_box = f'<div class="mb-4 p-3 bg-rose-500/20 border border-rose-500/40 text-rose-300 rounded-xl font-bold text-xs flex justify-between items-center"><span>{msg}</span><button onclick="this.parentElement.remove()" class="text-rose-200">✕</button></div>' if msg else ""

    html = f"""<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Acesso ao Sistema - CERBERUS-SISTEM</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-[#040814] text-slate-100 min-h-screen flex items-center justify-center p-4 font-sans antialiased relative overflow-hidden">
    <div class="w-full max-w-md bg-[#0b1329]/95 border border-slate-800 rounded-3xl p-8 shadow-2xl backdrop-blur relative z-10 space-y-6">
        <div class="flex flex-col items-center text-center space-y-3">
            {get_logo_svg(60)}
            <div>
                <h1 class="text-xl font-black uppercase tracking-wider text-white">CERBERUS<span class="text-sky-400">-SISTEM</span></h1>
                <p class="text-xs text-slate-400 font-semibold uppercase tracking-wider">O guardião da sua gestão</p>
            </div>
        </div>

        {alert_box}

        <form action="/login" method="POST" class="space-y-4">
            <div>
                <label class="block text-xs font-bold text-slate-300 uppercase mb-1.5">🏢 Loja / Filial Selecionada</label>
                <select name="store_id" class="w-full bg-[#060b17] border border-slate-700 text-sky-300 font-bold rounded-xl px-3.5 py-3 text-xs focus:outline-none focus:border-sky-500 cursor-pointer">
                    {store_options}
                </select>
            </div>

            <div>
                <label class="block text-xs font-bold text-slate-300 uppercase mb-1.5">👤 Usuário / Login</label>
                <input type="text" name="username" required autofocus placeholder="Digite seu usuário" class="w-full bg-[#060b17] border border-slate-700 rounded-xl px-3.5 py-3 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-sky-500 font-medium">
            </div>

            <div>
                <label class="block text-xs font-bold text-slate-300 uppercase mb-1.5">🔒 Senha do Usuário</label>
                <input type="password" id="login_password" name="password" required placeholder="Digite sua senha" class="w-full bg-[#060b17] border border-slate-700 rounded-xl px-3.5 py-3 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-sky-500 font-mono">
            </div>

            <div>
                <label class="block text-xs font-bold text-slate-300 uppercase mb-1.5">🔑 Senha da Loja (Segurança)</label>
                <input type="password" name="store_password" required placeholder="Senha de acesso da loja" class="w-full bg-[#060b17] border border-slate-700 rounded-xl px-3.5 py-3 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-sky-500 font-mono">
            </div>

            <button type="submit" class="w-full py-3.5 bg-blue-600 hover:bg-blue-500 font-bold text-white text-xs uppercase tracking-wider rounded-xl shadow-lg shadow-blue-900/40 transition-all cursor-pointer flex items-center justify-center gap-2">
                <span>🛡️ Acessar Sistema</span>
            </button>
        </form>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)

@app.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...), store_id: int = Form(1), store_password: str = Form("")):
    clean_user = username.strip()
    clean_pass = password.strip()
    clean_store_pass = store_password.strip()

    conn = get_db()
    u = conn.execute("SELECT * FROM users WHERE username = ? AND password_hash = ?", (clean_user, clean_pass)).fetchone()
    store = conn.execute("SELECT * FROM stores WHERE id = ?", (store_id,)).fetchone()
    conn.close()

    if not u:
        return RedirectResponse(url="/login?msg=Usuario+ou+senha+incorretos!+Tente+novamente.", status_code=303)

    if not store:
        return RedirectResponse(url="/login?msg=Loja+selecionada+invalida.", status_code=303)

    # 1. Validação da Senha da Loja
    expected_store_pass = store["password"] or "1234"
    if clean_store_pass != expected_store_pass:
        return RedirectResponse(url="/login?msg=Senha+da+loja+incorreta!+Acesso+negado.", status_code=303)

    # 2. Se for FUNCIONÁRIO (VENDEDOR), NÃO pode acessar loja diferente da designada
    user_role = u["role"]
    user_assigned_store = int(u["store_id"] or 1)
    
    if user_role != "ADMIN" and int(store_id) != user_assigned_store:
        return RedirectResponse(url="/login?msg=Acesso+negado!+Seu+usuario+so+tem+permissao+para+acessar+a+sua+loja+designada.", status_code=303)

    request.session["user"] = {
        "id": u["id"],
        "username": u["username"],
        "name": u["name"],
        "role": u["role"],
        "store_id": int(store_id) if user_role == "ADMIN" else user_assigned_store
    }
    return RedirectResponse(url=f"/dashboard?msg=Bem-vindo,+{urllib.parse.quote(u['name'])}!", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login?msg=Sessao+encerrada+com+sucesso!", status_code=303)

@app.get("/", response_class=HTMLResponse)
def index_redirect(request: Request):
    user = get_user(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=303)
    return RedirectResponse(url="/login", status_code=303)

@app.post("/change-store-direct")
def change_store_direct(request: Request, store_id: int = Form(...), store_password: str = Form(...)):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    # Apenas ADMIN pode alternar entre lojas
    if user.get("role") != "ADMIN":
        return RedirectResponse(url="/dashboard?msg=Acesso+negado!+Apenas+administradores+podem+alternar+entre+lojas.", status_code=303)

    conn = get_db()
    target_store = conn.execute("SELECT * FROM stores WHERE id = ?", (store_id,)).fetchone()
    conn.close()

    if not target_store:
        return RedirectResponse(url="/dashboard?msg=Loja+inexistente.", status_code=303)

    expected_pass = target_store["password"] or "1234"
    if store_password.strip() != expected_pass:
        return RedirectResponse(url="/dashboard?msg=Senha+da+loja+incorreta!+Nao+foi+possivel+alternar.", status_code=303)

    user["store_id"] = int(store_id)
    request.session["user"] = user
    return RedirectResponse(url=f"/dashboard?msg=Loja+alterada+para+{urllib.parse.quote(target_store['name'])}+com+sucesso!", status_code=303)

# ==========================================
# 4. DASHBOARD / PAINEL GERAL
# ==========================================
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, msg: str = ""):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login?msg=Por+favor,+faca+login+para+acessar", status_code=303)
    sid = user.get("store_id", 1)

    conn = get_db()
    total_sales = conn.execute("SELECT COALESCE(SUM(total), 0) FROM sales WHERE store_id = ?", (sid,)).fetchone()[0] or 0.0
    sales_count = conn.execute("SELECT COUNT(*) FROM sales WHERE store_id = ?", (sid,)).fetchone()[0] or 0
    cash_sales = conn.execute("SELECT COALESCE(SUM(total), 0) FROM sales WHERE store_id = ? AND payment_method != 'CREDIARIO'", (sid,)).fetchone()[0] or 0.0
    paid_debts = conn.execute("SELECT COALESCE(SUM(total_amount), 0) FROM receivables WHERE store_id = ? AND status = 'PAGO'", (sid,)).fetchone()[0] or 0.0
    total_received = cash_sales + paid_debts
    pending_debts = conn.execute("SELECT COALESCE(SUM(total_amount), 0) FROM receivables WHERE store_id = ? AND status = 'PENDENTE'", (sid,)).fetchone()[0] or 0.0
    pending_count = conn.execute("SELECT COUNT(*) FROM receivables WHERE store_id = ? AND status = 'PENDENTE'", (sid,)).fetchone()[0] or 0
    total_expenses = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE store_id = ?", (sid,)).fetchone()[0] or 0.0
    low_stock = conn.execute("SELECT COUNT(*) FROM products WHERE store_id = ? AND stock_quantity <= min_stock", (sid,)).fetchone()[0] or 0
    total_prods = conn.execute("SELECT COUNT(*) FROM products WHERE store_id = ?", (sid,)).fetchone()[0] or 0
    recent_sales = conn.execute("SELECT * FROM sales WHERE store_id = ? ORDER BY id DESC LIMIT 6", (sid,)).fetchall()
    conn.close()

    t_medio = (total_sales / sales_count) if sales_count > 0 else 0.0
    lucro_liquido = total_received - total_expenses

    sales_rows = "".join([f"""<tr class="border-b border-slate-800 text-xs">
        <td class="py-3 font-mono text-sky-400 font-bold">{s['sale_number']}</td>
        <td class="py-3 text-white font-medium">{s['customer_name']}</td>
        <td class="py-3 text-slate-400 font-mono">{s['created_at']}</td>
        <td class="py-3 font-bold text-white">R$ {s['total']:.2f}</td>
        <td class="py-3 text-slate-300">{s['payment_method']}</td>
        <td class="py-3 text-center"><span class="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-semibold text-[10px]">Concluída</span></td>
        <td class="py-3 text-right">
            <form action="/sale-delete" method="POST" class="inline" onsubmit="return confirm('Excluir esta venda e estornar o estoque?')">
                <input type="hidden" name="id" value="{s['id']}">
                <button type="submit" class="bg-rose-950/60 hover:bg-rose-600 text-rose-300 hover:text-white px-2 py-0.5 rounded text-[10px] font-bold cursor-pointer transition-all">Excluir</button>
            </form>
        </td>
    </tr>""" for s in recent_sales]) or '<tr><td colspan="7" class="p-6 text-center text-slate-500 text-xs">Nenhuma venda registrada ainda.</td></tr>'

    content = f"""
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div class="bg-[#0b1329] border border-slate-800 p-5 rounded-2xl shadow-lg">
            <span class="text-[11px] font-bold text-slate-400 uppercase">VENDAS TOTAIS</span>
            <p class="text-2xl font-black text-white mt-1">R$ {total_sales:,.2f}</p>
            <span class="text-[11px] text-emerald-400 font-semibold">{sales_count} Vendas Realizadas</span>
        </div>
        <div class="bg-[#0b1329] border border-slate-800 p-5 rounded-2xl shadow-lg">
            <span class="text-[11px] font-bold text-slate-400 uppercase">ENTRADAS NO CAIXA</span>
            <p class="text-2xl font-black text-emerald-400 mt-1">R$ {total_received:,.2f}</p>
            <span class="text-[11px] text-slate-400 font-semibold">À Vista + Contas Pagas</span>
        </div>
        <div class="bg-[#0b1329] border border-slate-800 p-5 rounded-2xl shadow-lg">
            <span class="text-[11px] font-bold text-slate-400 uppercase">CONTAS A RECEBER</span>
            <p class="text-2xl font-black text-amber-400 mt-1">R$ {pending_debts:,.2f}</p>
            <span class="text-[11px] text-amber-400/80 font-semibold">{pending_count} Débitos Pendentes</span>
        </div>
        <div class="bg-[#0b1329] border border-slate-800 p-5 rounded-2xl shadow-lg">
            <span class="text-[11px] font-bold text-slate-400 uppercase">RESULTADO LÍQUIDO</span>
            <p class="text-2xl font-black {"text-sky-400" if lucro_liquido >= 0 else "text-rose-400"} mt-1">R$ {lucro_liquido:,.2f}</p>
            <span class="text-[11px] text-slate-400 font-semibold">Entradas - Despesas</span>
        </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div class="lg:col-span-8 bg-[#0b1329] border border-slate-800 p-6 rounded-2xl space-y-4">
            <div class="flex justify-between items-center border-b border-slate-800 pb-3">
                <h3 class="text-sm font-bold text-white uppercase">Últimas Vendas Realizadas</h3>
                <a href="/pdv" class="text-xs bg-blue-600 hover:bg-blue-500 text-white font-bold px-3 py-1.5 rounded-xl">+ Nova Venda</a>
            </div>
            <div class="overflow-x-auto">
                <table class="w-full text-left text-xs">
                    <thead><tr class="text-sky-400 font-bold border-b border-slate-800 pb-2"><th class="pb-2">Nº Venda</th><th class="pb-2">Cliente</th><th class="pb-2">Data & Hora</th><th class="pb-2">Total</th><th class="pb-2">Pagamento</th><th class="pb-2 text-center">Status</th><th class="pb-2 text-right">Ação</th></tr></thead>
                    <tbody class="divide-y divide-slate-800/60">{sales_rows}</tbody>
                </table>
            </div>
        </div>

        <div class="lg:col-span-4 bg-[#0b1329] border border-slate-800 p-6 rounded-2xl space-y-4">
            <h3 class="text-sm font-bold text-white uppercase border-b border-slate-800 pb-3">Alertas & Ações Rápidas</h3>
            <a href="/receivables" class="p-3.5 bg-amber-500/10 border border-amber-500/20 rounded-xl flex items-center justify-between block hover:border-amber-500/40">
                <div>
                    <p class="text-xs font-bold text-amber-300">{pending_count} Cobranças Pendentes</p>
                    <p class="text-[11px] text-slate-400">Total a receber: R$ {pending_debts:,.2f}</p>
                </div>
                <span class="text-xs text-sky-400 font-bold">Cobrar 📲</span>
            </a>
            <a href="/products" class="p-3.5 bg-rose-500/10 border border-rose-500/20 rounded-xl flex items-center justify-between block hover:border-rose-500/40">
                <div>
                    <p class="text-xs font-bold text-rose-300">{low_stock} Produtos com Estoque Baixo</p>
                    <p class="text-[11px] text-slate-400">De {total_prods} cadastrados</p>
                </div>
                <span class="text-xs text-sky-400 font-bold">Repor 📦</span>
            </a>
            <div class="p-3.5 bg-slate-900/60 border border-slate-800 rounded-xl flex justify-between items-center text-xs">
                <span class="text-slate-400 font-bold">Ticket Médio:</span>
                <span class="text-white font-bold">R$ {t_medio:,.2f}</span>
            </div>
            <a href="/pdv" class="w-full py-3 bg-blue-600 hover:bg-blue-500 text-center font-bold text-white text-xs rounded-xl block shadow-lg">
                🛒 Abrir Frente de Caixa (PDV)
            </a>
        </div>
    </div>
    """
    return render_layout(request, content, "Painel Geral", "dashboard", msg)
# ==========================================
# 5. PRODUTOS (COM CADASTRO, EDIÇÃO E EXCLUSÃO)
# ==========================================
@app.get("/products", response_class=HTMLResponse)
def products_page(request: Request, msg: str = ""):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login?msg=Por+favor,+faca+login+para+acessar", status_code=303)
    sid = user.get("store_id", 1)

    conn = get_db()
    prods = conn.execute("SELECT * FROM products WHERE store_id = ? ORDER BY id DESC", (sid,)).fetchall()
    conn.close()

    rows = []
    for p in prods:
        p_json = json.dumps({
            "id": p["id"], "code": p["code"], "barcode": p["barcode"] or "", "name": p["name"],
            "category": p["category"], "sale_price": p["sale_price"], "cost_price": p["cost_price"],
            "stock_quantity": p["stock_quantity"], "min_stock": p["min_stock"]
        })
        photo_el = f'<img src="{p["photo_url"]}" class="w-8 h-8 rounded-lg object-cover">' if p['photo_url'] else '<div class="w-8 h-8 rounded-lg bg-slate-800 flex items-center justify-center text-xs">📦</div>'
        
        rows.append(f"""<tr class="border-b border-slate-800 text-xs">
            <td class="p-3 font-mono text-sky-400 font-bold">{p['code']}</td>
            <td class="p-3 text-slate-400 font-mono">{p['barcode'] or '-'}</td>
            <td class="p-3 font-bold text-white flex items-center gap-2">
                {photo_el}
                <span>{p['name']}</span>
            </td>
            <td class="p-3 text-slate-300">{p['category']}</td>
            <td class="p-3 text-right font-bold text-slate-200">R$ {p['sale_price']:.2f}</td>
            <td class="p-3 text-right font-bold {"text-rose-400" if p['stock_quantity'] <= p['min_stock'] else "text-slate-300"}">{p['stock_quantity']} (Mín: {p['min_stock']})</td>
            <td class="p-3 text-center flex items-center justify-center gap-2">
                <button type="button" onclick='openEditProductModal({p_json})' class="bg-blue-600/30 hover:bg-blue-600 text-blue-300 hover:text-white px-2.5 py-1 rounded text-xs font-bold cursor-pointer">✏️ Editar</button>
                <form action="/product-delete" method="POST" class="inline" onsubmit="return confirm('Excluir este produto?')">
                    <input type="hidden" name="id" value="{p['id']}">
                    <button type="submit" class="bg-rose-950/60 hover:bg-rose-600 text-rose-300 px-2.5 py-1 rounded text-xs font-bold cursor-pointer">🗑️ Excluir</button>
                </form>
            </td>
        </tr>""")

    rendered_rows = "".join(rows) if rows else '<tr><td colspan="7" class="p-6 text-center text-slate-500">Nenhum produto cadastrado.</td></tr>'

    content = f"""
    <div class="space-y-6">
        <div class="flex justify-between items-center">
            <h2 class="text-xl font-bold text-white">📦 Catálogo de Produtos & Estoque ({len(prods)})</h2>
            <button onclick="document.getElementById('add_product_form').classList.toggle('hidden')" class="bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs px-4 py-2 rounded-xl cursor-pointer">
                + Novo Produto
            </button>
        </div>

        <div id="add_product_form" class="bg-[#0b1329] border border-slate-800 p-6 rounded-2xl space-y-4">
            <h3 class="text-xs font-bold text-sky-400 uppercase">+ Cadastrar Novo Produto</h3>
            <form action="/product-add" method="POST" enctype="multipart/form-data" class="grid grid-cols-1 sm:grid-cols-4 gap-3 text-xs font-bold">
                <div>
                    <label class="block text-slate-300 mb-1">Código Interno *</label>
                    <input type="text" name="code" placeholder="Ex: 101" required class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                </div>
                <div>
                    <label class="block text-slate-300 mb-1">Código de Barras (EAN-13)</label>
                    <input type="text" name="barcode" placeholder="Ex: 7891234567890" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                </div>
                <div class="sm:col-span-2">
                    <label class="block text-slate-300 mb-1">Nome do Produto *</label>
                    <input type="text" name="name" placeholder="Ex: Camiseta Básica Algodão" required class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                </div>
                <div>
                    <label class="block text-slate-300 mb-1">Categoria</label>
                    <input type="text" name="category" value="Geral" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                </div>
                <div>
                    <label class="block text-slate-300 mb-1">Preço de Venda (R$) *</label>
                    <input type="number" step="0.01" name="sale_price" placeholder="0.00" required class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                </div>
                <div>
                    <label class="block text-slate-300 mb-1">Preço de Custo (R$)</label>
                    <input type="number" step="0.01" name="cost_price" placeholder="0.00" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                </div>
                <div>
                    <label class="block text-slate-300 mb-1">Estoque Inicial</label>
                    <input type="number" name="stock_quantity" value="10" required class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                </div>
                <div>
                    <label class="block text-slate-300 mb-1">Estoque Mínimo</label>
                    <input type="number" name="min_stock" value="5" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                </div>
                <div class="sm:col-span-2">
                    <label class="block text-slate-300 mb-1">Foto do Produto (Opcional)</label>
                    <input type="file" name="photo_file" accept="image/*" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-2 text-xs text-slate-300">
                </div>
                <div class="sm:col-span-1 flex items-end">
                    <button type="submit" class="w-full py-3 bg-blue-600 hover:bg-blue-500 font-bold text-white rounded-xl cursor-pointer">Salvar Produto</button>
                </div>
            </form>
        </div>

        <div class="bg-[#0b1329] border border-slate-800 rounded-2xl overflow-hidden">
            <table class="w-full text-left text-xs">
                <thead class="bg-[#060b17] text-slate-400 border-b border-slate-800 font-bold">
                    <tr><th class="p-3">Código</th><th class="p-3">Barras</th><th class="p-3">Produto</th><th class="p-3">Categoria</th><th class="p-3 text-right">Preço Venda</th><th class="p-3 text-right">Estoque</th><th class="p-3 text-center">Ações</th></tr>
                </thead>
                <tbody>{rendered_rows}</tbody>
            </table>
        </div>
    </div>

    <!-- MODAL DE EDIÇÃO DE PRODUTO -->
    <div id="edit_product_modal" class="hidden fixed inset-0 bg-black/80 flex items-center justify-center p-4 z-50">
        <div class="bg-[#0b1329] border border-slate-700 rounded-2xl max-w-lg w-full p-6 space-y-4">
            <div class="flex justify-between items-center border-b border-slate-800 pb-3">
                <h3 class="text-sm font-bold text-white">✏️ Editar Informações do Produto</h3>
                <button type="button" onclick="closeEditProductModal()" class="text-slate-400 hover:text-white">✕</button>
            </div>
            <form action="/product-edit" method="POST" enctype="multipart/form-data" class="space-y-3 text-xs font-bold">
                <input type="hidden" id="edit_p_id" name="id">
                <div class="grid grid-cols-2 gap-3">
                    <div>
                        <label class="block text-slate-300 mb-1">Código Interno</label>
                        <input type="text" id="edit_p_code" name="code" required class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-2.5 text-white">
                    </div>
                    <div>
                        <label class="block text-slate-300 mb-1">Código de Barras</label>
                        <input type="text" id="edit_p_barcode" name="barcode" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-2.5 text-white">
                    </div>
                </div>
                <div>
                    <label class="block text-slate-300 mb-1">Nome do Produto</label>
                    <input type="text" id="edit_p_name" name="name" required class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-2.5 text-white">
                </div>
                <div class="grid grid-cols-2 gap-3">
                    <div>
                        <label class="block text-slate-300 mb-1">Categoria</label>
                        <input type="text" id="edit_p_category" name="category" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-2.5 text-white">
                    </div>
                    <div>
                        <label class="block text-slate-300 mb-1">Preço Venda (R$)</label>
                        <input type="number" step="0.01" id="edit_p_sale_price" name="sale_price" required class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-2.5 text-white">
                    </div>
                </div>
                <div class="grid grid-cols-3 gap-3">
                    <div>
                        <label class="block text-slate-300 mb-1">Preço Custo</label>
                        <input type="number" step="0.01" id="edit_p_cost_price" name="cost_price" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-2.5 text-white">
                    </div>
                    <div>
                        <label class="block text-slate-300 mb-1">Estoque</label>
                        <input type="number" id="edit_p_stock_quantity" name="stock_quantity" required class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-2.5 text-white">
                    </div>
                    <div>
                        <label class="block text-slate-300 mb-1">Estoque Mínimo</label>
                        <input type="number" id="edit_p_min_stock" name="min_stock" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-2.5 text-white">
                    </div>
                </div>
                <div>
                    <label class="block text-slate-300 mb-1">Atualizar Foto (Opcional)</label>
                    <input type="file" name="photo_file" accept="image/*" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-2 text-slate-300">
                </div>
                <div class="flex justify-end gap-2 pt-3 border-t border-slate-800">
                    <button type="button" onclick="closeEditProductModal()" class="px-4 py-2 bg-slate-800 text-slate-300 rounded-xl">Cancelar</button>
                    <button type="submit" class="px-5 py-2 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded-xl cursor-pointer">Salvar Alterações</button>
                </div>
            </form>
        </div>
    </div>

    <script>
    function openEditProductModal(p) {{
        document.getElementById('edit_p_id').value = p.id;
        document.getElementById('edit_p_code').value = p.code;
        document.getElementById('edit_p_barcode').value = p.barcode || '';
        document.getElementById('edit_p_name').value = p.name;
        document.getElementById('edit_p_category').value = p.category;
        document.getElementById('edit_p_sale_price').value = p.sale_price;
        document.getElementById('edit_p_cost_price').value = p.cost_price;
        document.getElementById('edit_p_stock_quantity').value = p.stock_quantity;
        document.getElementById('edit_p_min_stock').value = p.min_stock;
        document.getElementById('edit_product_modal').classList.remove('hidden');
    }}
    function closeEditProductModal() {{
        document.getElementById('edit_product_modal').classList.add('hidden');
    }}
    </script>
    """
    return render_layout(request, content, "Produtos", "products", msg)

@app.post("/product-add")
async def product_add(request: Request, code: str = Form(...), barcode: str = Form(""), name: str = Form(...), category: str = Form("Geral"), sale_price: float = Form(...), cost_price: float = Form(0), stock_quantity: float = Form(10), min_stock: float = Form(5), photo_file: UploadFile = File(None)):
    user = get_user(request)
    sid = user.get("store_id", 1)
    photo_url = ""
    if photo_file and photo_file.filename:
        fn = f"p_{int(datetime.now().timestamp())}_{photo_file.filename}"
        fp = os.path.join("static/uploads", fn)
        with open(fp, "wb") as buf: shutil.copyfileobj(photo_file.file, buf)
        photo_url = f"/{fp}"
    conn = get_db()
    conn.execute("INSERT INTO products (code, barcode, name, category, sale_price, cost_price, stock_quantity, min_stock, photo_url, store_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (code, barcode or code, name, category, sale_price, cost_price, stock_quantity, min_stock, photo_url, sid))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/products?msg=Produto+cadastrado+com+sucesso!", status_code=303)

@app.post("/product-edit")
async def product_edit(request: Request, id: int = Form(...), code: str = Form(...), barcode: str = Form(""), name: str = Form(...), category: str = Form("Geral"), sale_price: float = Form(...), cost_price: float = Form(0), stock_quantity: float = Form(...), min_stock: float = Form(5), photo_file: UploadFile = File(None)):
    conn = get_db()
    if photo_file and photo_file.filename:
        fn = f"p_{int(datetime.now().timestamp())}_{photo_file.filename}"
        fp = os.path.join("static/uploads", fn)
        with open(fp, "wb") as buf: shutil.copyfileobj(photo_file.file, buf)
        photo_url = f"/{fp}"
        conn.execute("UPDATE products SET code = ?, barcode = ?, name = ?, category = ?, sale_price = ?, cost_price = ?, stock_quantity = ?, min_stock = ?, photo_url = ? WHERE id = ?",
            (code, barcode or code, name, category, sale_price, cost_price, stock_quantity, min_stock, photo_url, id))
    else:
        conn.execute("UPDATE products SET code = ?, barcode = ?, name = ?, category = ?, sale_price = ?, cost_price = ?, stock_quantity = ?, min_stock = ? WHERE id = ?",
            (code, barcode or code, name, category, sale_price, cost_price, stock_quantity, min_stock, id))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/products?msg=Produto+atualizado+com+sucesso!", status_code=303)

@app.post("/product-delete")
def product_delete(id: int = Form(...)):
    conn = get_db()
    conn.execute("DELETE FROM products WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/products?msg=Produto+excluido+com+sucesso!", status_code=303)

# ==========================================
# 6. CLIENTES (COM CADASTRO, EDIÇÃO E EXCLUSÃO)
# ==========================================
@app.get("/customers", response_class=HTMLResponse)
def customers_page(request: Request, msg: str = ""):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login?msg=Por+favor,+faca+login+para+acessar", status_code=303)
    sid = user.get("store_id", 1)

    conn = get_db()
    custs = conn.execute("SELECT * FROM customers WHERE store_id = ? ORDER BY id DESC", (sid,)).fetchall()
    conn.close()

    rows = []
    for c in custs:
        c_json = json.dumps({
            "id": c["id"], "name": c["name"], "phone": c["phone"] or "", "document": c["document"] or "",
            "city": c["city"] or "", "credit_limit": c["credit_limit"] or 1000.0, "notes": c["notes"] or ""
        })
        rows.append(f"""<tr class="border-b border-slate-800 text-xs">
            <td class="p-3 font-bold text-white">{c['name']}</td>
            <td class="p-3 text-slate-300 font-mono">{c['phone'] or '-'}</td>
            <td class="p-3 text-slate-400 font-mono">{c['document'] or '-'}</td>
            <td class="p-3 text-slate-300">{c['city'] or '-'}</td>
            <td class="p-3 text-sky-400 font-bold text-right">R$ {(c['credit_limit'] or 1000):.2f}</td>
            <td class="p-3 text-center flex items-center justify-center gap-2">
                <button type="button" onclick='openEditCustomerModal({c_json})' class="bg-blue-600/30 hover:bg-blue-600 text-blue-300 hover:text-white px-2.5 py-1 rounded text-xs font-bold cursor-pointer">✏️ Editar</button>
                <form action="/customer-delete" method="POST" class="inline" onsubmit="return confirm('Excluir este cliente?')">
                    <input type="hidden" name="id" value="{c['id']}">
                    <button type="submit" class="bg-rose-950/60 hover:bg-rose-600 text-rose-300 px-2.5 py-1 rounded text-xs font-bold cursor-pointer">🗑️ Excluir</button>
                </form>
            </td>
        </tr>""")

    rendered_rows = "".join(rows) if rows else '<tr><td colspan="6" class="p-6 text-center text-slate-500">Nenhum cliente cadastrado.</td></tr>'

    content = f"""
    <div class="space-y-6">
        <div class="flex justify-between items-center">
            <h2 class="text-xl font-bold text-white">👥 Base de Clientes ({len(custs)})</h2>
            <button onclick="document.getElementById('add_customer_form').classList.toggle('hidden')" class="bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs px-4 py-2 rounded-xl cursor-pointer">
                + Novo Cliente
            </button>
        </div>

        <div id="add_customer_form" class="bg-[#0b1329] border border-slate-800 p-6 rounded-2xl space-y-4">
            <h3 class="text-xs font-bold text-sky-400 uppercase">+ Cadastrar Novo Cliente</h3>
            <form action="/customer-add" method="POST" class="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs font-bold">
                <div>
                    <label class="block text-slate-300 mb-1">Nome Completo *</label>
                    <input type="text" name="name" placeholder="Nome do Cliente" required class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                </div>
                <div>
                    <label class="block text-slate-300 mb-1">WhatsApp / Telefone</label>
                    <input type="text" name="phone" placeholder="(DDD) 99999-9999" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                </div>
                <div>
                    <label class="block text-slate-300 mb-1">CPF ou CNPJ</label>
                    <input type="text" name="document" placeholder="000.000.000-00" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                </div>
                <div>
                    <label class="block text-slate-300 mb-1">Cidade</label>
                    <input type="text" name="city" placeholder="Cidade / Estado" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                </div>
                <div>
                    <label class="block text-slate-300 mb-1">Limite de Crediário (R$)</label>
                    <input type="number" step="0.01" name="credit_limit" value="1000" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                </div>
                <div class="flex items-end">
                    <button type="submit" class="w-full py-3 bg-blue-600 hover:bg-blue-500 font-bold text-white rounded-xl cursor-pointer">Salvar Cliente</button>
                </div>
            </form>
        </div>

        <div class="bg-[#0b1329] border border-slate-800 rounded-2xl overflow-hidden">
            <table class="w-full text-left text-xs">
                <thead class="bg-[#060b17] text-slate-400 border-b border-slate-800 font-bold">
                    <tr><th class="p-3">Nome</th><th class="p-3">WhatsApp / Tel</th><th class="p-3">Documento</th><th class="p-3">Cidade</th><th class="p-3 text-right">Limite Crediário</th><th class="p-3 text-center">Ações</th></tr>
                </thead>
                <tbody>{rendered_rows}</tbody>
            </table>
        </div>
    </div>

    <!-- MODAL DE EDIÇÃO DE CLIENTE -->
    <div id="edit_customer_modal" class="hidden fixed inset-0 bg-black/80 flex items-center justify-center p-4 z-50">
        <div class="bg-[#0b1329] border border-slate-700 rounded-2xl max-w-md w-full p-6 space-y-4">
            <div class="flex justify-between items-center border-b border-slate-800 pb-3">
                <h3 class="text-sm font-bold text-white">✏️ Editar Informações do Cliente</h3>
                <button type="button" onclick="closeEditCustomerModal()" class="text-slate-400 hover:text-white">✕</button>
            </div>
            <form action="/customer-edit" method="POST" class="space-y-3 text-xs font-bold">
                <input type="hidden" id="edit_c_id" name="id">
                <div>
                    <label class="block text-slate-300 mb-1">Nome Completo</label>
                    <input type="text" id="edit_c_name" name="name" required class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-2.5 text-white">
                </div>
                <div class="grid grid-cols-2 gap-3">
                    <div>
                        <label class="block text-slate-300 mb-1">Telefone / WhatsApp</label>
                        <input type="text" id="edit_c_phone" name="phone" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-2.5 text-white">
                    </div>
                    <div>
                        <label class="block text-slate-300 mb-1">Documento (CPF/CNPJ)</label>
                        <input type="text" id="edit_c_document" name="document" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-2.5 text-white">
                    </div>
                </div>
                <div class="grid grid-cols-2 gap-3">
                    <div>
                        <label class="block text-slate-300 mb-1">Cidade</label>
                        <input type="text" id="edit_c_city" name="city" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-2.5 text-white">
                    </div>
                    <div>
                        <label class="block text-slate-300 mb-1">Limite Crediário (R$)</label>
                        <input type="number" step="0.01" id="edit_c_credit_limit" name="credit_limit" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-2.5 text-white">
                    </div>
                </div>
                <div class="flex justify-end gap-2 pt-3 border-t border-slate-800">
                    <button type="button" onclick="closeEditCustomerModal()" class="px-4 py-2 bg-slate-800 text-slate-300 rounded-xl">Cancelar</button>
                    <button type="submit" class="px-5 py-2 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded-xl cursor-pointer">Salvar Alterações</button>
                </div>
            </form>
        </div>
    </div>

    <script>
    function openEditCustomerModal(c) {{
        document.getElementById('edit_c_id').value = c.id;
        document.getElementById('edit_c_name').value = c.name;
        document.getElementById('edit_c_phone').value = c.phone || '';
        document.getElementById('edit_c_document').value = c.document || '';
        document.getElementById('edit_c_city').value = c.city || '';
        document.getElementById('edit_c_credit_limit').value = c.credit_limit || 1000;
        document.getElementById('edit_customer_modal').classList.remove('hidden');
    }}
    function closeEditCustomerModal() {{
        document.getElementById('edit_customer_modal').classList.add('hidden');
    }}
    </script>
    """
    return render_layout(request, content, "Clientes", "customers", msg)

@app.post("/customer-add")
def customer_add(request: Request, name: str = Form(...), phone: str = Form(""), document: str = Form(""), city: str = Form(""), credit_limit: float = Form(1000)):
    user = get_user(request)
    sid = user.get("store_id", 1)
    conn = get_db()
    conn.execute("INSERT INTO customers (name, phone, document, city, credit_limit, store_id) VALUES (?, ?, ?, ?, ?, ?)", (name, phone, document, city, credit_limit, sid))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/customers?msg=Cliente+cadastrado+com+sucesso!", status_code=303)

@app.post("/customer-edit")
def customer_edit(id: int = Form(...), name: str = Form(...), phone: str = Form(""), document: str = Form(""), city: str = Form(""), credit_limit: float = Form(1000)):
    conn = get_db()
    conn.execute("UPDATE customers SET name = ?, phone = ?, document = ?, city = ?, credit_limit = ? WHERE id = ?",
        (name, phone, document, city, credit_limit, id))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/customers?msg=Cliente+atualizado+com+sucesso!", status_code=303)

@app.post("/customer-delete")
def customer_delete(id: int = Form(...)):
    conn = get_db()
    conn.execute("DELETE FROM customers WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/customers?msg=Cliente+excluido+com+sucesso!", status_code=303)

# ==========================================
# 7. FRENTE DE CAIXA / PDV
# ==========================================
@app.get("/pdv", response_class=HTMLResponse)
def pdv(request: Request, msg: str = ""):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login?msg=Por+favor,+faca+login+para+acessar", status_code=303)
    sid = user.get("store_id", 1)

    conn = get_db()
    products = conn.execute("SELECT * FROM products WHERE store_id = ? ORDER BY name ASC", (sid,)).fetchall()
    customers = conn.execute("SELECT * FROM customers WHERE store_id = ? ORDER BY name ASC", (sid,)).fetchall()
    conn.close()

    prods_json = json.dumps([{
        "id": p["id"], "code": p["code"], "barcode": p["barcode"] or p["code"], 
        "name": p["name"], "price": p["sale_price"], "stock": p["stock_quantity"],
        "photo": p["photo_url"] or ""
    } for p in products])

    cust_opts = "".join([f'<option value="{c["name"]}">{c["name"]}</option>' for c in customers])

    content = f"""
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div class="lg:col-span-2 bg-[#0b1329] border border-slate-800 p-6 rounded-2xl space-y-4">
            <div class="flex items-center justify-between">
                <div>
                    <h2 class="text-xl font-bold text-white">🛒 Frente de Caixa & PDV</h2>
                    <p class="text-xs text-slate-400">Bipe com o leitor USB ou use a câmera</p>
                </div>
                <button type="button" onclick="toggleCameraScanner()" class="px-4 py-2 bg-sky-600/20 hover:bg-sky-600 text-sky-300 hover:text-white border border-sky-500/30 rounded-xl text-xs font-bold cursor-pointer">
                    📷 Câmera / Leitor
                </button>
            </div>

            <div id="camera_container" class="hidden bg-[#060b17] border border-sky-500/40 rounded-2xl p-4 space-y-3">
                <div class="flex justify-between items-center">
                    <span class="text-xs font-bold text-sky-400">📷 Aponte para o Código de Barras:</span>
                    <button type="button" onclick="toggleCameraScanner()" class="text-rose-400 font-bold text-xs cursor-pointer">✕ Fechar</button>
                </div>
                <div id="reader" class="w-full max-w-sm mx-auto rounded-xl overflow-hidden"></div>
            </div>

            <div class="space-y-3 font-bold text-xs">
                <div>
                    <label class="block text-sky-400 mb-1">🔍 Bipar Código de Barras ou Digitar Nome (F2):</label>
                    <div class="flex gap-2">
                        <input type="text" id="barcode_input" autofocus onkeydown="handleBarcodeInput(event)" placeholder="Bipe o código ou digite o nome..." class="w-full bg-[#060b17] border border-sky-500/40 rounded-xl p-3 text-sky-300 font-mono text-sm focus:outline-none">
                        <input type="number" id="pdv_qty" value="1" min="1" class="w-24 bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white text-center text-sm font-bold">
                    </div>
                </div>
                <div id="search_preview" class="max-h-48 overflow-y-auto space-y-1 divide-y divide-slate-800/80 bg-[#060b17] border border-slate-800 rounded-xl p-2 hidden"></div>
            </div>

            <div class="border border-slate-800 rounded-xl overflow-hidden mt-4">
                <table class="w-full text-left text-xs">
                    <thead class="bg-[#060b17] text-slate-400 border-b border-slate-800 font-bold">
                        <tr><th class="p-3">Foto / Produto</th><th class="p-3 text-center">Qtd</th><th class="p-3 text-right">Unitário</th><th class="p-3 text-right">Subtotal</th><th class="p-3 text-center">Ação</th></tr>
                    </thead>
                    <tbody id="cart_body"><tr><td colspan="5" class="p-6 text-center text-slate-500">Carrinho vazio.</td></tr></tbody>
                </table>
            </div>
        </div>

        <div class="bg-[#0b1329] border border-slate-800 p-6 rounded-2xl space-y-6 flex flex-col justify-between">
            <div class="space-y-4">
                <h3 class="text-lg font-bold text-white border-b border-slate-800 pb-2">Finalização da Venda</h3>
                <div class="space-y-3 font-bold text-xs">
                    <div>
                        <label class="block text-slate-300 mb-1">Cliente (F4):</label>
                        <select id="pdv_customer" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                            <option value="Cliente Avulso">Cliente Avulso</option>
                            {cust_opts}
                        </select>
                    </div>
                    <div>
                        <label class="block text-slate-300 mb-1">Forma de Pagamento:</label>
                        <select id="pdv_payment" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-sky-400 font-bold">
                            <option value="DINHEIRO">💵 DINHEIRO</option>
                            <option value="PIX">⚡ PIX</option>
                            <option value="CARTAO_CREDITO">💳 CARTÃO DE CRÉDITO</option>
                            <option value="CARTAO_DEBITO">💳 CARTÃO DE DÉBITO</option>
                            <option value="CREDIARIO">📄 CREDIÁRIO / FIADO (30 dias)</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-slate-300 mb-1">Desconto (R$):</label>
                        <input type="number" id="pdv_discount" value="0" min="0" oninput="updateTotal()" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                    </div>
                </div>
                <div class="bg-[#060b17] p-5 rounded-2xl space-y-1 text-right border border-slate-800">
                    <span class="text-xs text-slate-400 font-bold uppercase block">TOTAL A PAGAR</span>
                    <div id="pdv_total" class="text-3xl font-black text-sky-400">R$ 0,00</div>
                </div>
            </div>
            <button type="button" onclick="checkout()" class="w-full py-4 bg-blue-600 hover:bg-blue-500 font-bold text-white rounded-xl shadow-xl cursor-pointer text-sm uppercase tracking-wider">
                ✅ Finalizar Venda & Recibo (F8)
            </button>
        </div>
    </div>

    <script>
    const catalog = {prods_json};
    let cart = [];
    let qrScanner = null;

    window.addEventListener('keydown', (e) => {{
        if (e.key === 'F2') {{ e.preventDefault(); document.getElementById('barcode_input').focus(); }}
        if (e.key === 'F4') {{ e.preventDefault(); document.getElementById('pdv_customer').focus(); }}
        if (e.key === 'F8') {{ e.preventDefault(); checkout(); }}
    }});

    function handleBarcodeInput(e) {{
        const term = e.target.value.trim().toLowerCase();
        if (e.key === 'Enter') {{
            e.preventDefault();
            const f = catalog.find(p => p.code.toLowerCase() === term || p.barcode.toLowerCase() === term || p.name.toLowerCase() === term);
            if (f) {{
                addToCart(f);
                e.target.value = '';
                document.getElementById('search_preview').classList.add('hidden');
            }} else {{
                alert('Produto não encontrado!');
            }}
            return;
        }}
        if (term.length >= 2) {{
            const matches = catalog.filter(p => p.name.toLowerCase().includes(term) || p.code.toLowerCase().includes(term) || p.barcode.toLowerCase().includes(term));
            const prev = document.getElementById('search_preview');
            if (matches.length > 0) {{
                prev.innerHTML = matches.slice(0, 6).map(p => `
                    <div onclick="selectProduct(${{p.id}})" class="p-2 hover:bg-slate-800 rounded-lg cursor-pointer flex justify-between items-center text-xs">
                        <span class="text-white font-bold">${{p.name}} (${{p.code}})</span>
                        <span class="text-sky-400 font-bold">R$ ${{p.price.toFixed(2)}}</span>
                    </div>
                `).join('');
                prev.classList.remove('hidden');
            }} else {{
                prev.classList.add('hidden');
            }}
        }} else {{
            document.getElementById('search_preview').classList.add('hidden');
        }}
    }}

    function selectProduct(id) {{
        const p = catalog.find(x => x.id === id);
        if (p) addToCart(p);
        document.getElementById('barcode_input').value = '';
        document.getElementById('search_preview').classList.add('hidden');
        document.getElementById('barcode_input').focus();
    }}

    function addToCart(prod) {{
        const qty = parseFloat(document.getElementById('pdv_qty').value) || 1;
        const exist = cart.find(i => i.id === prod.id);
        if (exist) exist.qty += qty;
        else cart.push({{ id: prod.id, name: prod.name, price: prod.price, qty: qty, photo: prod.photo }});
        document.getElementById('pdv_qty').value = 1;
        renderCart();
    }}

    function removeFromCart(idx) {{
        cart.splice(idx, 1);
        renderCart();
    }}

    function renderCart() {{
        const tb = document.getElementById('cart_body');
        if (cart.length === 0) {{
            tb.innerHTML = '<tr><td colspan="5" class="p-6 text-center text-slate-500">Carrinho vazio.</td></tr>';
            updateTotal();
            return;
        }}
        tb.innerHTML = cart.map((item, idx) => `
            <tr class="border-b border-slate-800">
                <td class="p-3 text-white font-bold flex items-center gap-2">
                    ${{item.photo ? `<img src="${{item.photo}}" class="w-8 h-8 rounded-lg object-cover">` : `<div class="w-8 h-8 rounded-lg bg-slate-800 flex items-center justify-center text-xs">📦</div>`}}
                    <span>${{item.name}}</span>
                </td>
                <td class="p-3 text-center text-white font-bold">${{item.qty}}</td>
                <td class="p-3 text-right text-slate-300">R$ ${{item.price.toFixed(2)}}</td>
                <td class="p-3 text-right font-bold text-sky-400">R$ ${{(item.price * item.qty).toFixed(2)}}</td>
                <td class="p-3 text-center"><button onclick="removeFromCart(${{idx}})" class="text-rose-400 font-bold cursor-pointer">✕</button></td>
            </tr>
        `).join('');
        updateTotal();
    }}

    function updateTotal() {{
        const sub = cart.reduce((acc, i) => acc + (i.price * i.qty), 0);
        const disc = parseFloat(document.getElementById('pdv_discount').value) || 0;
        const tot = Math.max(0, sub - disc);
        document.getElementById('pdv_total').innerText = 'R$ ' + tot.toFixed(2).replace('.', ',');
    }}

    function toggleCameraScanner() {{
        const b = document.getElementById('camera_container');
        if (b.classList.contains('hidden')) {{
            b.classList.remove('hidden');
            qrScanner = new Html5Qrcode("reader");
            qrScanner.start({{ facingMode: "environment" }}, {{ fps: 10, qrbox: {{ width: 250, height: 150 }} }}, (txt) => {{
                const found = catalog.find(p => p.code === txt || p.barcode === txt);
                if (found) {{ addToCart(found); alert('✅ Bipado: ' + found.name); }}
                else alert('Código não cadastrado: ' + txt);
            }}, () => {{}});
        }} else {{
            b.classList.add('hidden');
            if (qrScanner) qrScanner.stop().catch(console.error);
        }}
    }}

    async function checkout() {{
        if (cart.length === 0) return alert('Adicione produtos no carrinho!');
        const res = await fetch('/pdv-checkout', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{
                items: cart,
                customer_name: document.getElementById('pdv_customer').value,
                payment_method: document.getElementById('pdv_payment').value,
                discount: parseFloat(document.getElementById('pdv_discount').value) || 0
            }})
        }});
        const data = await res.json();
        if (data.success) {{
            alert('✅ Venda realizada com sucesso!');
            if (data.whatsapp_msg) window.open('https://api.whatsapp.com/send?text=' + data.whatsapp_msg, '_blank');
            window.location.reload();
        }} else {{
            alert('Erro: ' + data.error);
        }}
    }}
    </script>
    """
    return render_layout(request, content, "PDV", "pdv", msg)

@app.post("/pdv-checkout")
async def pdv_checkout(request: Request):
    user = get_user(request)
    try:
        data = await request.json()
        items = data.get("items", [])
        c_name = str(data.get("customer_name", "Cliente Avulso")).strip() or "Cliente Avulso"
        p_method = str(data.get("payment_method", "DINHEIRO")).strip() or "DINHEIRO"
        discount = float(data.get("discount", 0) or 0)
        sid = int(user.get("store_id", 1))

        if not items: return JSONResponse({"success": False, "error": "Carrinho vazio"}, status_code=400)

        subtotal = sum([float(i["price"]) * float(i["qty"]) for i in items])
        total = max(0.0, subtotal - discount)
        sale_num = f"#{int(datetime.now().timestamp()) % 1000000:06d}"
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")

        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO sales (store_id, sale_number, created_at, seller_name, customer_name, subtotal, discount, total, payment_method) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, sale_num, now_str, user.get("name", "Administrador"), c_name, subtotal, discount, total, p_method))
        sale_id = cur.lastrowid

        for it in items:
            cur.execute("INSERT INTO sale_items (sale_id, product_id, product_name, quantity, unit_price, subtotal) VALUES (?, ?, ?, ?, ?, ?)",
                (sale_id, it["id"], it["name"], it["qty"], it["price"], it["price"] * it["qty"]))
            if it["id"] > 0:
                cur.execute("UPDATE products SET stock_quantity = MAX(0, stock_quantity - ?) WHERE id = ?", (it["qty"], it["id"]))

        if p_method == "CREDIARIO":
            due_date = (datetime.now() + timedelta(days=30)).strftime("%d/%m/%Y")
            cur.execute("INSERT INTO receivables (store_id, sale_id, customer_name, total_amount, due_date, status) VALUES (?, ?, ?, ?, ?, 'PENDENTE')",
                (sid, sale_id, c_name, total, due_date))

        conn.commit()
        conn.close()

        rec = f"🛡️ *CERBERUS-SISTEM - COMPROVANTE*\nNº Venda: *{sale_num}*\nData: {now_str}\nCliente: {c_name}\n\n*Itens:*\n"
        for it in items:
            rec += f"• {it['qty']}x {it['name']} (R$ {float(it['price']):.2f})\n"
        rec += f"\n*TOTAL:* R$ {total:.2f} ({p_method})\nObrigado pela preferência!"

        return JSONResponse({"success": True, "whatsapp_msg": urllib.parse.quote(rec)})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.post("/sale-delete")
def delete_sale(request: Request, id: int = Form(...)):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login?msg=Por+favor,+faca+login+para+acessar", status_code=303)
    conn = get_db()
    cur = conn.cursor()
    
    items = cur.execute("SELECT product_id, quantity FROM sale_items WHERE sale_id = ?", (id,)).fetchall()
    for it in items:
        if it["product_id"] and it["product_id"] > 0:
            cur.execute("UPDATE products SET stock_quantity = stock_quantity + ? WHERE id = ?", (it["quantity"], it["product_id"]))
            
    cur.execute("DELETE FROM sale_items WHERE sale_id = ?", (id,))
    cur.execute("DELETE FROM receivables WHERE sale_id = ?", (id,))
    cur.execute("DELETE FROM sales WHERE id = ?", (id,))
    
    conn.commit()
    conn.close()
    return RedirectResponse(url="/dashboard?msg=Venda+excluida+e+estoque+estornado+com+sucesso!", status_code=303)

# ==========================================
# 8. CONTAS A RECEBER & COBRANÇAS WHATSAPP
# ==========================================
@app.get("/receivables", response_class=HTMLResponse)
def receivables_page(request: Request, msg: str = ""):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login?msg=Por+favor,+faca+login+para+acessar", status_code=303)
    sid = user.get("store_id", 1)

    conn = get_db()
    debts = conn.execute("SELECT * FROM receivables WHERE store_id = ? ORDER BY id DESC", (sid,)).fetchall()
    customers = conn.execute("SELECT name, phone FROM customers WHERE store_id = ?", (sid,)).fetchall()
    conn.close()

    cust_phones = {c["name"]: (c["phone"] or "") for c in customers}
    rows = []

    for d in debts:
        cp = cust_phones.get(d['customer_name'], "")
        clean_p = "".join(filter(str.isdigit, cp))
        wa_msg = f"Olá {d['customer_name']}! Lembramos do seu saldo pendente no valor de R$ {d['total_amount']:.2f} com vencimento em {d['due_date']}. Como prefere efetuar o pagamento?"
        wa_url = f"https://api.whatsapp.com/send?phone=55{clean_p}&text={urllib.parse.quote(wa_msg)}" if clean_p else "#"
        wa_btn = f'<a href="{wa_url}" target="_blank" class="px-2.5 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-bold">📲 WhatsApp</a>' if clean_p else '<span class="text-[10px] text-slate-500">(Sem WhatsApp)</span>'

        pay_form = f"""<form action="/pay-receivable" method="POST" class="flex items-center gap-1 inline-block">
            <input type="hidden" name="id" value="{d['id']}">
            <input type="number" step="0.01" name="paid_amount" placeholder="R$" required class="w-16 bg-[#060b17] border border-slate-700 rounded px-1 text-xs text-sky-400 font-bold">
            <button type="submit" class="bg-blue-600 hover:bg-blue-500 text-white px-2 py-0.5 rounded text-xs font-bold cursor-pointer">✓ Pagar</button>
        </form>""" if d['status'] == 'PENDENTE' else '<span class="text-xs text-emerald-400 font-bold">✓ Quitado</span>'

        rows.append(f"""<tr class="border-b border-slate-800 text-xs">
            <td class="p-3 font-bold text-white">{d['customer_name']}</td>
            <td class="p-3 text-amber-400 font-bold">R$ {d['total_amount']:.2f}</td>
            <td class="p-3 text-slate-300 font-mono">{d['due_date']}</td>
            <td class="p-3 text-center"><span class="px-2 py-0.5 rounded {'bg-emerald-500/20 text-emerald-300' if d['status'] == 'PAGO' else 'bg-amber-500/20 text-amber-300'} text-[10px] font-bold">{d['status']}</span></td>
            <td class="p-3 text-center">{wa_btn}</td>
            <td class="p-3 text-center">{pay_form}</td>
            <td class="p-3 text-center">
                <form action="/receivable-delete" method="POST" class="inline" onsubmit="return confirm('Excluir este lançamento?')">
                    <input type="hidden" name="id" value="{d['id']}">
                    <button type="submit" class="text-xs bg-rose-950/60 hover:bg-rose-600 text-rose-300 px-2 py-1 rounded cursor-pointer">🗑️</button>
                </form>
            </td>
        </tr>""")

    rendered_rows = "".join(rows) if rows else '<tr><td colspan="7" class="p-6 text-center text-slate-500">Nenhuma dívida pendente.</td></tr>'

    content = f"""
    <div class="space-y-6">
        <div class="flex justify-between items-center">
            <h2 class="text-xl font-bold text-white">💳 Contas a Receber & Cobrança WhatsApp ({len(debts)})</h2>
            <button onclick="document.getElementById('add_debt_form').classList.toggle('hidden')" class="bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs px-4 py-2 rounded-xl cursor-pointer">+ Lançar Dívida</button>
        </div>

        <div id="add_debt_form" class="bg-[#0b1329] border border-slate-800 p-6 rounded-2xl space-y-4">
            <h3 class="text-xs font-bold text-sky-400 uppercase">+ Lançar Conta a Receber Manual</h3>
            <form action="/receivable-add" method="POST" class="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs font-bold">
                <input type="text" name="customer_name" placeholder="Nome do Cliente *" required class="bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                <input type="number" step="0.01" name="total_amount" placeholder="Valor (R$) *" required class="bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                <input type="text" name="due_date" value="{(datetime.now() + timedelta(days=30)).strftime('%d/%m/%Y')}" placeholder="Vencimento (DD/MM/AAAA)" required class="bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                <button type="submit" class="sm:col-span-3 py-2.5 bg-blue-600 hover:bg-blue-500 font-bold text-white rounded-xl cursor-pointer">Salvar Dívida</button>
            </form>
        </div>

        <div class="bg-[#0b1329] border border-slate-800 rounded-2xl overflow-hidden">
            <table class="w-full text-left text-xs">
                <thead class="bg-[#060b17] text-slate-400 border-b border-slate-800 font-bold">
                    <tr><th class="p-3">Cliente</th><th class="p-3">Saldo</th><th class="p-3">Vencimento</th><th class="p-3 text-center">Status</th><th class="p-3 text-center">WhatsApp</th><th class="p-3 text-center">Abater</th><th class="p-3 text-center">Ação</th></tr>
                </thead>
                <tbody>{rendered_rows}</tbody>
            </table>
        </div>
    </div>
    """
    return render_layout(request, content, "Contas a Receber", "receivables", msg)

@app.post("/pay-receivable")
def pay_receivable(id: int = Form(...), paid_amount: float = Form(...)):
    conn = get_db()
    rec = conn.execute("SELECT * FROM receivables WHERE id = ?", (id,)).fetchone()
    if rec:
        cur_amt = float(rec["total_amount"])
        new_amt = cur_amt - paid_amount
        if new_amt <= 0:
            conn.execute("UPDATE receivables SET total_amount = 0, status = 'PAGO' WHERE id = ?", (id,))
            msg = "Conta+quitada+com+sucesso!"
        else:
            conn.execute("UPDATE receivables SET total_amount = ? WHERE id = ?", (new_amt, id))
            msg = f"Abatimento+de+R$+{paid_amount:.2f}+realizado!+Saldo:+R$+{new_amt:.2f}"
        conn.commit()
    conn.close()
    return RedirectResponse(url=f"/receivables?msg={msg}", status_code=303)

@app.post("/receivable-add")
def receivable_add(request: Request, customer_name: str = Form(...), total_amount: float = Form(...), due_date: str = Form(...)):
    user = get_user(request)
    sid = user.get("store_id", 1)
    conn = get_db()
    conn.execute("INSERT INTO receivables (customer_name, total_amount, due_date, status, store_id) VALUES (?, ?, ?, 'PENDENTE', ?)",
        (customer_name, total_amount, due_date, sid))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/receivables?msg=Divida+lancada+com+sucesso!", status_code=303)

@app.post("/receivable-delete")
def receivable_delete(id: int = Form(...)):
    conn = get_db()
    conn.execute("DELETE FROM receivables WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/receivables?msg=Lancamento+excluido!", status_code=303)

# ==========================================
# 9. DESPESAS, FORNECEDORES & RELATÓRIOS
# ==========================================
@app.get("/expenses", response_class=HTMLResponse)
def expenses_page(request: Request, msg: str = ""):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login?msg=Por+favor,+faca+login+para+acessar", status_code=303)
    sid = user.get("store_id", 1)
    conn = get_db()
    exps = conn.execute("SELECT * FROM expenses WHERE store_id = ? ORDER BY id DESC", (sid,)).fetchall()
    total_exp = sum([float(e["amount"]) for e in exps])
    conn.close()

    rows = "".join([f"""<tr class="border-b border-slate-800 text-xs">
        <td class="p-3 font-bold text-white">{e['description']}</td>
        <td class="p-3 text-slate-300">{e['category']}</td>
        <td class="p-3 font-mono text-slate-400">{e['date']}</td>
        <td class="p-3 text-rose-400 font-bold text-right">R$ {e['amount']:.2f}</td>
        <td class="p-3 text-center">
            <form action="/expense-delete" method="POST" class="inline" onsubmit="return confirm('Excluir despesa?')">
                <input type="hidden" name="id" value="{e['id']}">
                <button type="submit" class="text-xs bg-rose-950/60 hover:bg-rose-600 text-rose-300 px-2 py-1 rounded cursor-pointer">🗑️</button>
            </form>
        </td>
    </tr>""" for e in exps]) or '<tr><td colspan="5" class="p-6 text-center text-slate-500">Nenhuma despesa registrada.</td></tr>'

    content = f"""
    <div class="space-y-6">
        <div class="flex justify-between items-center">
            <h2 class="text-xl font-bold text-white">💸 Despesas & Contas Operacionais</h2>
            <span class="text-xs font-bold text-rose-400 bg-rose-500/10 border border-rose-500/30 px-3 py-1.5 rounded-xl">Total: R$ {total_exp:,.2f}</span>
        </div>
        <div class="bg-[#0b1329] border border-slate-800 p-6 rounded-2xl space-y-4">
            <h3 class="text-xs font-bold text-sky-400 uppercase">+ Lançar Despesa</h3>
            <form action="/expense-add" method="POST" class="grid grid-cols-1 sm:grid-cols-4 gap-3 text-xs font-bold">
                <input type="text" name="description" placeholder="Descrição (ex: Aluguel, Energia) *" required class="bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white sm:col-span-2">
                <input type="number" step="0.01" name="amount" placeholder="Valor (R$) *" required class="bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                <input type="text" name="category" placeholder="Categoria" value="Fixo" class="bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                <button type="submit" class="sm:col-span-4 py-2.5 bg-blue-600 hover:bg-blue-500 font-bold text-white rounded-xl cursor-pointer">Salvar Despesa</button>
            </form>
        </div>
        <div class="bg-[#0b1329] border border-slate-800 rounded-2xl overflow-hidden">
            <table class="w-full text-left text-xs">
                <thead class="bg-[#060b17] text-slate-400 border-b border-slate-800 font-bold">
                    <tr><th class="p-3">Descrição</th><th class="p-3">Categoria</th><th class="p-3">Data</th><th class="p-3 text-right">Valor</th><th class="p-3 text-center">Ação</th></tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
    </div>
    """
    return render_layout(request, content, "Despesas", "expenses", msg)

@app.post("/expense-add")
def expense_add(request: Request, description: str = Form(...), amount: float = Form(...), category: str = Form("Fixo")):
    user = get_user(request)
    sid = user.get("store_id", 1)
    conn = get_db()
    conn.execute("INSERT INTO expenses (description, amount, category, date, store_id) VALUES (?, ?, ?, ?, ?)",
        (description, amount, category, datetime.now().strftime("%d/%m/%Y"), sid))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/expenses?msg=Despesa+salva+com+sucesso!", status_code=303)

@app.post("/expense-delete")
def expense_delete(id: int = Form(...)):
    conn = get_db()
    conn.execute("DELETE FROM expenses WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/expenses?msg=Despesa+excluida!", status_code=303)

@app.get("/suppliers", response_class=HTMLResponse)
def suppliers_page(request: Request, msg: str = ""):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login?msg=Por+favor,+faca+login+para+acessar", status_code=303)
    sid = user.get("store_id", 1)
    conn = get_db()
    sups = conn.execute("SELECT * FROM suppliers WHERE store_id = ? ORDER BY id DESC", (sid,)).fetchall()
    conn.close()

    rows = "".join([f"""<tr class="border-b border-slate-800 text-xs">
        <td class="p-3 font-bold text-white">{s['name']}</td>
        <td class="p-3 text-slate-300 font-mono">{s['cnpj'] or '-'}</td>
        <td class="p-3 text-slate-400 font-mono">{s['phone'] or '-'}</td>
        <td class="p-3 text-center">
            <form action="/supplier-delete" method="POST" class="inline" onsubmit="return confirm('Excluir?')">
                <input type="hidden" name="id" value="{s['id']}">
                <button type="submit" class="text-xs bg-rose-950/60 hover:bg-rose-600 text-rose-300 px-2 py-1 rounded cursor-pointer">🗑️</button>
            </form>
        </td>
    </tr>""" for s in sups]) or '<tr><td colspan="4" class="p-6 text-center text-slate-500">Nenhum fornecedor cadastrado.</td></tr>'

    content = f"""
    <div class="space-y-6">
        <h2 class="text-xl font-bold text-white">🏬 Fornecedores ({len(sups)})</h2>
        <div class="bg-[#0b1329] border border-slate-800 p-6 rounded-2xl space-y-4">
            <h3 class="text-xs font-bold text-sky-400 uppercase">+ Cadastrar Fornecedor</h3>
            <form action="/supplier-add" method="POST" class="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs font-bold">
                <input type="text" name="name" placeholder="Razão Social / Nome *" required class="bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                <input type="text" name="cnpj" placeholder="CNPJ" class="bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                <input type="text" name="phone" placeholder="Telefone / Contato" class="bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                <button type="submit" class="sm:col-span-3 py-2.5 bg-blue-600 hover:bg-blue-500 font-bold text-white rounded-xl cursor-pointer">Salvar Fornecedor</button>
            </form>
        </div>
        <div class="bg-[#0b1329] border border-slate-800 rounded-2xl overflow-hidden">
            <table class="w-full text-left text-xs">
                <thead class="bg-[#060b17] text-slate-400 border-b border-slate-800 font-bold">
                    <tr><th class="p-3">Nome</th><th class="p-3">CNPJ</th><th class="p-3">Telefone</th><th class="p-3 text-center">Ação</th></tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
    </div>
    """
    return render_layout(request, content, "Fornecedores", "suppliers", msg)

@app.post("/supplier-add")
def supplier_add(request: Request, name: str = Form(...), cnpj: str = Form(""), phone: str = Form("")):
    user = get_user(request)
    sid = user.get("store_id", 1)
    conn = get_db()
    conn.execute("INSERT INTO suppliers (name, cnpj, phone, store_id) VALUES (?, ?, ?, ?)", (name, cnpj, phone, sid))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/suppliers?msg=Fornecedor+salvo!", status_code=303)

@app.post("/supplier-delete")
def supplier_delete(id: int = Form(...)):
    conn = get_db()
    conn.execute("DELETE FROM suppliers WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/suppliers?msg=Fornecedor+excluido!", status_code=303)

@app.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request, msg: str = ""):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login?msg=Por+favor,+faca+login+para+acessar", status_code=303)
    sid = user.get("store_id", 1)

    conn = get_db()
    total_sales = conn.execute("SELECT COALESCE(SUM(total), 0) FROM sales WHERE store_id = ?", (sid,)).fetchone()[0] or 0.0
    cash_sales = conn.execute("SELECT COALESCE(SUM(total), 0) FROM sales WHERE store_id = ? AND payment_method != 'CREDIARIO'", (sid,)).fetchone()[0] or 0.0
    paid_debts = conn.execute("SELECT COALESCE(SUM(total_amount), 0) FROM receivables WHERE store_id = ? AND status = 'PAGO'", (sid,)).fetchone()[0] or 0.0
    total_received = cash_sales + paid_debts
    total_expenses = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE store_id = ?", (sid,)).fetchone()[0] or 0.0
    total_receivables = conn.execute("SELECT COALESCE(SUM(total_amount), 0) FROM receivables WHERE store_id = ? AND status = 'PENDENTE'", (sid,)).fetchone()[0] or 0.0
    conn.close()

    lucro_operacional = total_received - total_expenses

    content = f"""
    <div class="space-y-6">
        <h2 class="text-xl font-bold text-white">📈 Demonstrativo de Resultados & Relatórios</h2>
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div class="bg-[#0b1329] border border-slate-800 p-5 rounded-2xl">
                <span class="text-xs font-bold text-slate-400 uppercase">Receita Efetiva no Caixa</span>
                <p class="text-2xl font-black text-emerald-400 mt-1">R$ {total_received:,.2f}</p>
                <span class="text-[11px] text-slate-400">Total Vendas Brutas: R$ {total_sales:,.2f}</span>
            </div>
            <div class="bg-[#0b1329] border border-slate-800 p-5 rounded-2xl">
                <span class="text-xs font-bold text-slate-400 uppercase">Despesas Totais</span>
                <p class="text-2xl font-black text-rose-400 mt-1">R$ {total_expenses:,.2f}</p>
                <span class="text-[11px] text-slate-400">Custos operacionais</span>
            </div>
            <div class="bg-[#0b1329] border border-slate-800 p-5 rounded-2xl">
                <span class="text-xs font-bold text-slate-400 uppercase">Lucro Líquido Real</span>
                <p class="text-2xl font-black text-sky-400 mt-1">R$ {lucro_operacional:,.2f}</p>
                <span class="text-[11px] text-slate-400">Recebimentos - Despesas</span>
            </div>
        </div>
        <div class="bg-[#0b1329] border border-slate-800 p-6 rounded-2xl space-y-2">
            <h3 class="text-sm font-bold text-white">Resumo de Inadimplência / Crediário Aberto</h3>
            <p class="text-xs text-slate-400">Total a receber em haver no fiado: <b class="text-amber-400 font-mono">R$ {total_receivables:,.2f}</b></p>
        </div>
    </div>
    """
    return render_layout(request, content, "Relatórios", "reports", msg)

@app.get("/import-pdf", response_class=HTMLResponse)
def import_pdf_page(request: Request, msg: str = ""):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login?msg=Por+favor,+faca+login+para+acessar", status_code=303)
    sid = user.get("store_id", 1)

    content = f"""
    <div class="space-y-6">
        <div>
            <h2 class="text-xl font-bold text-white">📄 Importador Inteligente (PDF / Imagem / CSV / Texto)</h2>
            <p class="text-xs text-slate-400">Importe múltiplos produtos ou clientes colando o texto extraído do seu PDF/Nota ou arquivo</p>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div class="bg-[#0b1329] border border-slate-800 p-6 rounded-2xl space-y-4">
                <h3 class="text-xs font-bold text-sky-400 uppercase">📦 Importação em Lote de Produtos</h3>
                <p class="text-xs text-slate-400">Cole uma lista no formato: <code class="text-emerald-400">Codigo;Nome;Preco;Estoque</code> (um por linha)</p>
                <form action="/import-products-batch" method="POST" class="space-y-3">
                    <textarea name="raw_data" rows="8" placeholder="101;Camiseta Basica;49.90;20&#10;102;Tenis Pro;189.00;10" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-xs font-mono text-white"></textarea>
                    <button type="submit" class="w-full py-3 bg-blue-600 hover:bg-blue-500 font-bold text-white text-xs rounded-xl cursor-pointer">Processar & Importar Produtos</button>
                </form>
            </div>

            <div class="bg-[#0b1329] border border-slate-800 p-6 rounded-2xl space-y-4">
                <h3 class="text-xs font-bold text-sky-400 uppercase">👥 Importação em Lote de Clientes</h3>
                <p class="text-xs text-slate-400">Cole uma lista no formato: <code class="text-emerald-400">Nome;Telefone;Documento;Cidade</code> (um por linha)</p>
                <form action="/import-customers-batch" method="POST" class="space-y-3">
                    <textarea name="raw_data" rows="8" placeholder="João Silva;11999998888;123.456.789-00;São Paulo&#10;Maria Santos;21988887777;987.654.321-11;Rio de Janeiro" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-xs font-mono text-white"></textarea>
                    <button type="submit" class="w-full py-3 bg-emerald-600 hover:bg-emerald-500 font-bold text-white text-xs rounded-xl cursor-pointer">Processar & Importar Clientes</button>
                </form>
            </div>
        </div>
    </div>
    """
    return render_layout(request, content, "Importar PDF", "import_pdf", msg)

@app.post("/import-products-batch")
def import_products_batch(request: Request, raw_data: str = Form(...)):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    sid = user.get("store_id", 1)
    
    conn = get_db()
    count = 0
    for line in raw_data.strip().split("\n"):
        parts = [p.strip() for p in line.split(";") if p.strip()]
        if len(parts) >= 3:
            code = parts[0]
            name = parts[1]
            try:
                price = float(parts[2].replace(",", ".").replace("R$", "").strip())
            except Exception:
                price = 0.0
            try:
                stock = float(parts[3].replace(",", ".").strip()) if len(parts) > 3 else 10.0
            except Exception:
                stock = 10.0
            conn.execute("INSERT INTO products (code, barcode, name, sale_price, stock_quantity, store_id) VALUES (?, ?, ?, ?, ?, ?)",
                         (code, code, name, price, stock, sid))
            count += 1
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/products?msg={count}+produtos+importados+com+sucesso!", status_code=303)

@app.post("/import-customers-batch")
def import_customers_batch(request: Request, raw_data: str = Form(...)):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    sid = user.get("store_id", 1)
    
    conn = get_db()
    count = 0
    for line in raw_data.strip().split("\n"):
        parts = [p.strip() for p in line.split(";") if p.strip()]
        if len(parts) >= 1:
            name = parts[0]
            phone = parts[1] if len(parts) > 1 else ""
            doc = parts[2] if len(parts) > 2 else ""
            city = parts[3] if len(parts) > 3 else ""
            conn.execute("INSERT INTO customers (name, phone, document, city, store_id) VALUES (?, ?, ?, ?, ?)",
                         (name, phone, doc, city, sid))
            count += 1
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/customers?msg={count}+clientes+importados+com+sucesso!", status_code=303)

# ==========================================
# 10. GESTÃO DE LOJAS & FUNCIONÁRIOS (ADMIN ONLY)
# ==========================================
@app.get("/stores-users", response_class=HTMLResponse)
def stores_users_page(request: Request, msg: str = ""):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login?msg=Por+favor,+faca+login+para+acessar", status_code=303)
    
    if user.get("role") != "ADMIN":
        return RedirectResponse(url="/dashboard?msg=Acesso+restrito+a+administradores!", status_code=303)

    conn = get_db()
    stores = conn.execute("SELECT * FROM stores ORDER BY id ASC").fetchall()
    users_list = conn.execute("""
        SELECT u.*, s.name as store_name 
        FROM users u 
        LEFT JOIN stores s ON u.store_id = s.id 
        ORDER BY u.id ASC
    """).fetchall()
    conn.close()

    store_options = "".join([f'<option value="{s["id"]}">🏢 {s["name"]}</option>' for s in stores])

    store_rows = "".join([f"""<tr class="border-b border-slate-800 text-xs">
        <td class="p-3 font-bold text-white">#{s['id']}</td>
        <td class="p-3 font-bold text-sky-400">🏢 {s['name']}</td>
        <td class="p-3 text-slate-300">{s['city'] or 'Matriz'}</td>
        <td class="p-3 font-mono text-emerald-400 font-bold">🔒 {s['password'] or '1234'}</td>
        <td class="p-3 text-center">
            <button onclick="editStore({s['id']}, '{s['name']}', '{s['password'] or '1234'}')" class="text-xs bg-sky-950/60 hover:bg-sky-600 text-sky-300 px-2.5 py-1 rounded cursor-pointer">✏️ Alterar Senha</button>
        </td>
    </tr>""" for s in stores])

    user_rows = "".join([f"""<tr class="border-b border-slate-800 text-xs">
        <td class="p-3 font-bold text-white">{u['name']}</td>
        <td class="p-3 font-mono text-slate-300">@{u['username']}</td>
        <td class="p-3"><span class="px-2 py-0.5 rounded text-[10px] font-bold {'bg-blue-500/20 text-blue-300 border border-blue-500/30' if u['role'] == 'ADMIN' else 'bg-slate-800 text-slate-300'}">{u['role']}</span></td>
        <td class="p-3 text-sky-400 font-bold">🏢 {u['store_name'] or 'Todas (Admin)'}</td>
        <td class="p-3 font-mono text-slate-400">{'••••••' if u['role'] == 'ADMIN' and user['id'] != u['id'] else u['password_hash']}</td>
        <td class="p-3 text-center">
            <form action="/user-delete" method="POST" class="inline" onsubmit="return confirm('Excluir usuário?')">
                <input type="hidden" name="id" value="{u['id']}">
                <button type="submit" class="text-xs bg-rose-950/60 hover:bg-rose-600 text-rose-300 px-2 py-1 rounded cursor-pointer" {'disabled' if u['username'] == 'admin' else ''}>🗑️</button>
            </form>
        </td>
    </tr>""" for u in users_list])

    content = f"""
    <div class="space-y-6">
        <div>
            <h2 class="text-xl font-bold text-white">⚙️ Gestão de Lojas, Filiais e Funcionários</h2>
            <p class="text-xs text-slate-400">Controle de senhas das lojas e vinculação de funcionários exclusivos por filial</p>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div class="space-y-4">
                <div class="bg-[#0b1329] border border-slate-800 p-6 rounded-2xl space-y-3">
                    <h3 class="text-xs font-bold text-sky-400 uppercase">+ Cadastrar Nova Filial / Loja</h3>
                    <form action="/store-add" method="POST" class="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs font-bold">
                        <input type="text" name="name" placeholder="Nome da Loja *" required class="bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                        <input type="text" name="city" placeholder="Cidade / Bairro" class="bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                        <input type="password" name="password" placeholder="Senha da Loja *" required class="bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white font-mono">
                        <button type="submit" class="sm:col-span-3 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded-xl cursor-pointer">Salvar Loja</button>
                    </form>
                </div>

                <div class="bg-[#0b1329] border border-slate-800 rounded-2xl overflow-hidden">
                    <div class="p-3 bg-[#060b17] border-b border-slate-800 font-bold text-xs text-white">🏢 Lojas & Senhas de Acesso</div>
                    <table class="w-full text-left text-xs">
                        <thead class="bg-[#060b17] text-slate-400 border-b border-slate-800 font-bold">
                            <tr><th class="p-3">ID</th><th class="p-3">Loja</th><th class="p-3">Cidade</th><th class="p-3">Senha</th><th class="p-3 text-center">Ação</th></tr>
                        </thead>
                        <tbody>{store_rows}</tbody>
                    </table>
                </div>
            </div>

            <div class="space-y-4">
                <div class="bg-[#0b1329] border border-slate-800 p-6 rounded-2xl space-y-3">
                    <h3 class="text-xs font-bold text-sky-400 uppercase">+ Cadastrar Funcionário / Vendedor</h3>
                    <form action="/user-add" method="POST" class="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs font-bold">
                        <input type="text" name="name" placeholder="Nome Completo *" required class="bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white sm:col-span-2">
                        <input type="text" name="username" placeholder="Login / Usuário *" required class="bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white">
                        <input type="password" name="password" placeholder="Senha do Usuário *" required class="bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white font-mono">
                        <div>
                            <label class="block text-slate-400 mb-1">Loja de Atuação:</label>
                            <select name="store_id" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-sky-300 font-bold cursor-pointer">
                                {store_options}
                            </select>
                        </div>
                        <div>
                            <label class="block text-slate-400 mb-1">Perfil de Acesso:</label>
                            <select name="role" class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white font-bold cursor-pointer">
                                <option value="VENDEDOR">Vendedor / Operador (Preso à loja)</option>
                                <option value="ADMIN">Administrador (Acesso total)</option>
                            </select>
                        </div>
                        <button type="submit" class="sm:col-span-2 py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-xl cursor-pointer">Cadastrar Funcionário</button>
                    </form>
                </div>

                <div class="bg-[#0b1329] border border-slate-800 rounded-2xl overflow-hidden">
                    <div class="p-3 bg-[#060b17] border-b border-slate-800 font-bold text-xs text-white">👥 Usuários & Vínculos de Loja</div>
                    <table class="w-full text-left text-xs">
                        <thead class="bg-[#060b17] text-slate-400 border-b border-slate-800 font-bold">
                            <tr><th class="p-3">Nome</th><th class="p-3">Login</th><th class="p-3">Cargo</th><th class="p-3">Loja</th><th class="p-3">Senha</th><th class="p-3 text-center">Ação</th></tr>
                        </thead>
                        <tbody>{user_rows}</tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <!-- MODAL EDITAR SENHA DA LOJA -->
    <div id="edit_store_modal" class="hidden fixed inset-0 bg-black/80 flex items-center justify-center p-4 z-50">
        <div class="bg-[#0b1329] border border-slate-700 rounded-2xl max-w-sm w-full p-6 space-y-4 shadow-2xl">
            <h3 class="text-sm font-bold text-white">🔒 Alterar Senha da Loja</h3>
            <form action="/store-update-password" method="POST" class="space-y-3 text-xs font-bold">
                <input type="hidden" id="edit_store_id" name="id">
                <div>
                    <label class="block text-slate-400 mb-1">Nome da Loja:</label>
                    <input type="text" id="edit_store_name" readonly class="w-full bg-[#060b17] border border-slate-800 rounded-xl p-3 text-slate-400">
                </div>
                <div>
                    <label class="block text-slate-400 mb-1">Nova Senha da Loja:</label>
                    <input type="password" id="edit_store_password" name="password" required class="w-full bg-[#060b17] border border-slate-700 rounded-xl p-3 text-white font-mono">
                </div>
                <div class="flex justify-end gap-2 pt-2">
                    <button type="button" onclick="document.getElementById('edit_store_modal').classList.add('hidden')" class="px-4 py-2 bg-slate-800 text-slate-300 rounded-xl">Cancelar</button>
                    <button type="submit" class="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded-xl cursor-pointer">Salvar Nova Senha</button>
                </div>
            </form>
        </div>
    </div>

    <script>
    function editStore(id, name, pass) {
        document.getElementById('edit_store_id').value = id;
        document.getElementById('edit_store_name').value = name;
        document.getElementById('edit_store_password').value = pass;
        document.getElementById('edit_store_modal').classList.remove('hidden');
    }
    </script>
    """
    return render_layout(request, content, "Lojas & Funcionários", "stores_users", msg)

@app.post("/store-add")
def store_add(request: Request, name: str = Form(...), city: str = Form(""), password: str = Form("1234")):
    user = get_user(request)
    if not user or user.get("role") != "ADMIN":
        return RedirectResponse(url="/dashboard?msg=Acesso+negado", status_code=303)
    conn = get_db()
    conn.execute("INSERT INTO stores (name, city, password) VALUES (?, ?, ?)", (name.strip(), city.strip(), password.strip()))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/stores-users?msg=Loja+cadastrada+com+sucesso!", status_code=303)

@app.post("/store-update-password")
def store_update_password(request: Request, id: int = Form(...), password: str = Form(...)):
    user = get_user(request)
    if not user or user.get("role") != "ADMIN":
        return RedirectResponse(url="/dashboard?msg=Acesso+negado", status_code=303)
    conn = get_db()
    conn.execute("UPDATE stores SET password = ? WHERE id = ?", (password.strip(), id))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/stores-users?msg=Senha+da+loja+atualizada+com+sucesso!", status_code=303)

@app.post("/user-add")
def user_add(request: Request, name: str = Form(...), username: str = Form(...), password: str = Form(...), store_id: int = Form(1), role: str = Form("VENDEDOR")):
    user = get_user(request)
    if not user or user.get("role") != "ADMIN":
        return RedirectResponse(url="/dashboard?msg=Acesso+negado", status_code=303)
    conn = get_db()
    try:
        conn.execute("INSERT INTO users (name, username, password_hash, role, store_id) VALUES (?, ?, ?, ?, ?)",
                     (name.strip(), username.strip(), password.strip(), role.strip(), store_id))
        conn.commit()
        msg = "Funcionario+cadastrado+com+sucesso!"
    except Exception:
        msg = "Erro+ao+cadastrar:+login+ja+existente+ou+invalido."
    conn.close()
    return RedirectResponse(url=f"/stores-users?msg={msg}", status_code=303)

@app.post("/user-delete")
def user_delete(request: Request, id: int = Form(...)):
    user = get_user(request)
    if not user or user.get("role") != "ADMIN":
        return RedirectResponse(url="/dashboard?msg=Acesso+negado", status_code=303)
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id = ? AND username != 'admin'", (id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/stores-users?msg=Funcionario+removido!", status_code=303)

# ==========================================
# 11. INICIALIZAÇÃO SERVIDOR
# ==========================================
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from starlette.middleware.sessions import SessionMiddleware
import uvicorn
import sqlite3
import urllib.parse
from datetime import datetime, timedelta

# ==========================================
# 1. BANCO DE DADOS E MIGRAÇÃO AUTOMÁTICA
# ==========================================
def get_db():
    conn = sqlite3.connect("erp_database.db")
    conn.row_factory = sqlite3.Row
    return conn

def check_and_add_column(conn, table_name, column_name, column_type):
    cursor = conn.cursor()
    try:
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in cursor.fetchall()]
        if column_name not in columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
    except Exception:
        pass

def init_db():
    conn = get_db()
    
    conn.execute("""
    CREATE TABLE IF NOT EXISTS stores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, password TEXT DEFAULT '1234', logo_text TEXT DEFAULT 'ERP LOJA'
    )""")
    
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE, password_hash TEXT, name TEXT, role TEXT DEFAULT 'VENDEDOR', store_id INTEGER DEFAULT 1,
        can_give_discount INTEGER DEFAULT 1, can_cancel_sales INTEGER DEFAULT 0,
        can_manage_products INTEGER DEFAULT 1, can_view_reports INTEGER DEFAULT 1
    )""")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT, name TEXT, category TEXT DEFAULT 'Geral', sale_price REAL DEFAULT 0, cost_price REAL DEFAULT 0, stock_quantity REAL DEFAULT 0, store_id INTEGER DEFAULT 1
    )""")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, document TEXT, phone TEXT, credit_limit REAL DEFAULT 1000, address TEXT, neighborhood TEXT, city TEXT, notes TEXT, store_id INTEGER DEFAULT 1
    )""")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS receivables (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_id INTEGER DEFAULT 1, sale_id INTEGER DEFAULT 0, customer_name TEXT, total_amount REAL DEFAULT 0, due_date TEXT, status TEXT DEFAULT 'PENDENTE'
    )""")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_id INTEGER DEFAULT 1, sale_number TEXT, created_at TEXT, seller_name TEXT, customer_name TEXT, subtotal REAL DEFAULT 0, discount REAL DEFAULT 0, total REAL DEFAULT 0, payment_method TEXT DEFAULT 'DINHEIRO'
    )""")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS sale_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER, product_id INTEGER, product_name TEXT, quantity REAL DEFAULT 1, unit_price REAL DEFAULT 0, subtotal REAL DEFAULT 0
    )""")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS suppliers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, cnpj TEXT, phone TEXT, email TEXT, store_id INTEGER DEFAULT 1
    )""")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        description TEXT, amount REAL DEFAULT 0, category TEXT DEFAULT 'Geral', date TEXT, store_id INTEGER DEFAULT 1
    )""")

    cols_to_ensure = {
        "stores": [("password", "TEXT DEFAULT '1234'"), ("logo_text", "TEXT DEFAULT 'ERP LOJA'")],
        "users": [("username", "TEXT"), ("password_hash", "TEXT"), ("name", "TEXT"), ("role", "TEXT DEFAULT 'VENDEDOR'"), ("store_id", "INTEGER DEFAULT 1")],
        "products": [("code", "TEXT"), ("name", "TEXT"), ("category", "TEXT DEFAULT 'Geral'"), ("sale_price", "REAL DEFAULT 0"), ("cost_price", "REAL DEFAULT 0"), ("stock_quantity", "REAL DEFAULT 0"), ("store_id", "INTEGER DEFAULT 1")],
        "customers": [("name", "TEXT"), ("document", "TEXT"), ("phone", "TEXT"), ("credit_limit", "REAL DEFAULT 1000"), ("address", "TEXT"), ("neighborhood", "TEXT"), ("city", "TEXT"), ("notes", "TEXT"), ("store_id", "INTEGER DEFAULT 1")],
        "receivables": [("store_id", "INTEGER DEFAULT 1"), ("sale_id", "INTEGER DEFAULT 0"), ("customer_name", "TEXT"), ("total_amount", "REAL DEFAULT 0"), ("due_date", "TEXT"), ("status", "TEXT DEFAULT 'PENDENTE'")],
        "sales": [("store_id", "INTEGER DEFAULT 1"), ("sale_number", "TEXT"), ("created_at", "TEXT"), ("seller_name", "TEXT"), ("customer_name", "TEXT"), ("subtotal", "REAL DEFAULT 0"), ("discount", "REAL DEFAULT 0"), ("total", "REAL DEFAULT 0"), ("payment_method", "TEXT DEFAULT 'DINHEIRO'")],
        "sale_items": [("sale_id", "INTEGER"), ("product_id", "INTEGER"), ("product_name", "TEXT"), ("quantity", "REAL DEFAULT 1"), ("unit_price", "REAL DEFAULT 0"), ("subtotal", "REAL DEFAULT 0")],
        "suppliers": [("name", "TEXT"), ("cnpj", "TEXT"), ("phone", "TEXT"), ("email", "TEXT"), ("store_id", "INTEGER DEFAULT 1")],
        "expenses": [("description", "TEXT"), ("amount", "REAL DEFAULT 0"), ("category", "TEXT DEFAULT 'Geral'"), ("date", "TEXT"), ("store_id", "INTEGER DEFAULT 1")]
    }

    for tbl, cols in cols_to_ensure.items():
        for col_name, col_type in cols:
            check_and_add_column(conn, tbl, col_name, col_type)

    store = conn.execute("SELECT * FROM stores WHERE id = 1").fetchone()
    if not store:
        conn.execute("INSERT INTO stores (id, name, password, logo_text) VALUES (1, 'Matriz Principal', '1234', 'ERP MATRIZ')")
        conn.execute("INSERT INTO stores (id, name, password, logo_text) VALUES (2, 'Filial 01', '1234', 'FILIAL 1')")

    admin = conn.execute("SELECT * FROM users WHERE username = 'admin'").fetchone()
    if not admin:
        conn.execute("INSERT INTO users (username, password_hash, name, role, store_id) VALUES ('admin', 'admin123', 'Administrador', 'ADMIN', 1)")
        conn.execute("INSERT INTO users (username, password_hash, name, role, store_id) VALUES ('vendedor', '123456', 'Vendedor Teste', 'VENDEDOR', 1)")

    conn.commit()
    conn.close()

init_db()

app = FastAPI(title="ERP Multi-Loja Completo")
app.add_middleware(SessionMiddleware, secret_key="chave_secreta_super_segura_erp")

def get_user(request: Request):
    return request.session.get("user")

# ==========================================
# 2. LAYOUT BASE COM SUPORTE PWA/OFFLINE
# ==========================================
def render_layout(request: Request, content: str, title: str = "ERP Vendas", active_tab: str = "dashboard", msg: str = ""):
    user = get_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db()
    stores = conn.execute("SELECT * FROM stores").fetchall()
    current_store = conn.execute("SELECT * FROM stores WHERE id = ?", (user.get("store_id", 1),)).fetchone()
    conn.close()

    store_name = current_store["name"] if current_store else "Loja Principal"
    store_options = "".join([f'<option value="{s["id"]}" {"selected" if s["id"] == user.get("store_id", 1) else ""}>{s["name"]}</option>' for s in stores])
    alert = f'<div class="mb-6 p-4 bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 rounded-xl font-bold text-sm">{msg}</div>' if msg else ""

    def tab_cls(name):
        return "bg-emerald-600 text-white font-bold" if active_tab == name else "bg-slate-800/80 text-slate-300 hover:bg-slate-800"

    admin_tab = f'<a href="/stores-users" class="px-3 py-2 rounded-xl {tab_cls("stores_users")}">⚙️ Lojas & Equipe</a>' if user.get("role") == "ADMIN" else ""

    html = f"""
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta name="theme-color" content="#0f172a">
        <link rel="manifest" href="/manifest.json">
        <title>{title}</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script>
          if ('serviceWorker' in navigator) {{
            window.addEventListener('load', () => {{
              navigator.serviceWorker.register('/sw.js');
            }});
          }}
        </script>
    </head>
    <body class="bg-slate-950 text-slate-100 min-h-screen">
        <header class="bg-slate-900 border-b border-slate-800 px-6 py-4 flex flex-wrap items-center justify-between gap-4 sticky top-0 z-50">
            <div class="flex items-center gap-3">
                <span class="text-2xl">⚡</span>
                <div>
                    <h1 class="text-lg font-bold text-emerald-400">ERP Vendas - {store_name}</h1>
                    <span class="text-[11px] text-slate-400 font-medium">Usuário: <b class="text-slate-200">{user['name']}</b> ({user['role']})</span>
                </div>
            </div>

            <div class="flex items-center gap-3">
                <form action="/change-store-auth" method="POST" class="flex items-center gap-2">
                    <label class="text-xs text-slate-400 font-bold">Alternar Loja:</label>
                    <select name="store_id" class="bg-slate-950 border border-slate-700 rounded-lg px-2 py-1 text-xs text-emerald-400 font-bold">
                        {store_options}
                    </select>
                    <input type="password" name="store_password" placeholder="Senha da Loja" required class="bg-slate-950 border border-slate-700 rounded-lg px-2 py-1 text-xs text-white w-28">
                    <button type="submit" class="bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold px-3 py-1 rounded-lg">OK</button>
                </form>

                <a href="/logout" class="px-3 py-1 bg-rose-950/60 hover:bg-rose-600 text-rose-300 hover:text-white rounded-lg text-xs font-bold border border-rose-800">
                    🚪 Sair
                </a>
            </div>
        </header>

        <div class="bg-slate-900/50 border-b border-slate-800/80 px-6 py-2 overflow-x-auto">
            <nav class="max-w-7xl mx-auto flex items-center gap-2 text-xs sm:text-sm font-medium whitespace-nowrap">
                <a href="/dashboard" class="px-3 py-2 rounded-xl {tab_cls('dashboard')}">📊 Dashboard</a>
                <a href="/pdv" class="px-3 py-2 rounded-xl {tab_cls('pdv')}">🛒 PDV / Caixa</a>
                <a href="/products" class="px-3 py-2 rounded-xl {tab_cls('products')}">📦 Produtos</a>
                <a href="/customers" class="px-3 py-2 rounded-xl {tab_cls('customers')}">👥 Clientes</a>
                <a href="/receivables" class="px-3 py-2 rounded-xl {tab_cls('receivables')}">📄 Fiado / Cobrança</a>
                <a href="/suppliers" class="px-3 py-2 rounded-xl {tab_cls('suppliers')}">🏬 Fornecedores</a>
                <a href="/expenses" class="px-3 py-2 rounded-xl {tab_cls('expenses')}">💸 Despesas</a>
                {admin_tab}
                <a href="/reports" class="px-3 py-2 rounded-xl {tab_cls('reports')}">📈 Relatórios</a>
                <a href="/import-pdf" class="px-3 py-2 rounded-xl bg-amber-600/20 hover:bg-amber-600/40 text-amber-300 font-bold border border-amber-500/30">📥 Importar Dados</a>
            </nav>
        </div>

        <main class="max-w-7xl mx-auto p-6">
            {alert}
            {content}
        </main>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

# ==========================================
# 3. ROTAS PWA / OFFLINE (MANIFEST & SERVICE WORKER)
# ==========================================
@app.get("/manifest.json")
def manifest():
    return FileResponse("manifest.json", media_type="application/json")

@app.get("/sw.js")
def service_worker():
    return FileResponse("sw.js", media_type="application/javascript")

# ==========================================
# 4. AUTENTICAÇÃO
# ==========================================
@app.get("/", response_class=HTMLResponse)
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    user = get_user(request)
    if user: return RedirectResponse(url="/dashboard", status_code=303)

    conn = get_db()
    stores = conn.execute("SELECT * FROM stores").fetchall()
    conn.close()

    options = "".join([f'<option value="{s["id"]}">{s["name"]}</option>' for s in stores])
    err_html = f'<div class="p-3 bg-rose-500/20 border border-rose-500/40 text-rose-300 text-xs font-bold rounded-xl">{error}</div>' if error else ""

    html = f"""
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta name="theme-color" content="#0f172a">
        <link rel="manifest" href="/manifest.json">
        <title>Login - ERP Vendas</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script>
          if ('serviceWorker' in navigator) {{
            window.addEventListener('load', () => {{
              navigator.serviceWorker.register('/sw.js');
            }});
          }}
        </script>
    </head>
    <body class="bg-slate-950 text-slate-100 flex items-center justify-center min-h-screen p-4">
        <div class="w-full max-w-md bg-slate-900 border border-slate-800 p-8 rounded-2xl shadow-2xl space-y-6">
            <div class="text-center space-y-2">
                <span class="text-4xl">⚡</span>
                <h1 class="text-2xl font-bold text-white">ERP Multi-Loja</h1>
                <p class="text-xs text-slate-400">Entre com suas credenciais de acesso</p>
            </div>

            {err_html}

            <form action="/login-post" method="POST" class="space-y-4 text-xs font-bold">
                <div>
                    <label class="block text-slate-300 mb-1">Selecione a Loja:</label>
                    <select name="store_id" class="w-full bg-slate-950 border border-slate-700 rounded-xl p-3 text-emerald-400 focus:outline-none">
                        {options}
                    </select>
                </div>

                <div>
                    <label class="block text-slate-300 mb-1">Usuário:</label>
                    <input type="text" name="username" placeholder="Digite seu usuário" required class="w-full bg-slate-950 border border-slate-700 rounded-xl p-3 text-white focus:outline-none">
                </div>

                <div>
                    <label class="block text-slate-300 mb-1">Senha do Usuário:</label>
                    <input type="password" name="password" placeholder="Digite sua senha" required class="w-full bg-slate-950 border border-slate-700 rounded-xl p-3 text-white focus:outline-none">
                </div>

                <button type="submit" class="w-full py-3 bg-emerald-600 hover:bg-emerald-500 font-bold text-white text-sm rounded-xl shadow-lg cursor-pointer">
                    Entrar no Sistema
                </button>
            </form>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.post("/login-post")
def login_post(request: Request, username: str = Form(...), password: str = Form(...), store_id: int = Form(1)):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ? AND password_hash = ?", (username, password)).fetchone()
    conn.close()

    if user:
        u_dict = dict(user)
        request.session["user"] = {
            "id": u_dict["id"], "username": u_dict["username"], "name": u_dict["name"],
            "role": u_dict["role"], "store_id": store_id
        }
        return RedirectResponse(url="/dashboard", status_code=303)
    
    return login_page(request, error="Usuário ou senha inválidos!")

@app.post("/change-store-auth")
def change_store_auth(request: Request, store_id: int = Form(...), store_password: str = Form(...)):
    user = get_user(request)
    if not user: return RedirectResponse(url="/login", status_code=303)

    conn = get_db()
    target_store = conn.execute("SELECT * FROM stores WHERE id = ?", (store_id,)).fetchone()
    conn.close()

    if target_store and (target_store["password"] == store_password or user["role"] == "ADMIN"):
        user["store_id"] = store_id
        request.session["user"] = user
        return RedirectResponse(url=f"/dashboard?msg={urllib.parse.quote('Loja alterada com sucesso!')}", status_code=303)

    return RedirectResponse(url=f"/dashboard?msg={urllib.parse.quote('Senha incorreta para a loja selecionada!')}", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)

# ==========================================
# 5. DASHBOARD E EXCLUSÃO DE VENDAS
# ==========================================
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, msg: str = ""):
    user = get_user(request)
    if not user: return RedirectResponse(url="/login", status_code=303)
    store_id = user.get("store_id", 1)

    conn = get_db()
    total_prods = conn.execute("SELECT COUNT(*) FROM products WHERE store_id = ?", (store_id,)).fetchone()[0]
    total_sales = conn.execute("SELECT COALESCE(SUM(total), 0) FROM sales WHERE store_id = ?", (store_id,)).fetchone()[0]
    total_custs = conn.execute("SELECT COUNT(*) FROM customers WHERE store_id = ?", (store_id,)).fetchone()[0]
    total_debts = conn.execute("SELECT COALESCE(SUM(total_amount), 0) FROM receivables WHERE store_id = ? AND status = 'PENDENTE'", (store_id,)).fetchone()[0]
    recent_sales = conn.execute("SELECT * FROM sales WHERE store_id = ? ORDER BY id DESC LIMIT 10", (store_id,)).fetchall()
    conn.close()

    sales_rows = "".join([f"""
    <tr class="border-b border-slate-800/80">
        <td class="p-3 font-mono text-emerald-400 font-bold">{s['sale_number']}</td>
        <td class="p-3 text-slate-300">{s['created_at']}</td>
        <td class="p-3 font-bold text-white">{s['customer_name']}</td>
        <td class="p-3 text-right font-bold text-emerald-400">R$ {s['total']:.2f}</td>
        <td class="p-3 text-center"><span class="px-2 py-0.5 rounded bg-slate-800 text-[10px] font-bold text-slate-300">{s['payment_method']}</span></td>
        <td class="p-3 text-center">
            <form action="/delete-item" method="POST" class="inline">
                <input type="hidden" name="item_type" value="sale">
                <input type="hidden" name="item_id" value="{s['id']}">
                <button type="submit" onclick="return confirm('Excluir esta venda permanentemente? O estoque será estornado.');" class="text-xs bg-rose-950/60 hover:bg-rose-600 text-rose-300 hover:text-white px-2 py-1 rounded transition-colors cursor-pointer font-bold">🗑️ Excluir Venda</button>
            </form>
        </td>
    </tr>""" for s in recent_sales])

    content = f"""
    <div class="space-y-6">
        <div class="flex items-center justify-between">
            <h2 class="text-2xl font-bold text-white">Dashboard do Sistema</h2>
            <a href="/pdv" class="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-500 font-bold text-white text-xs rounded-xl shadow-lg shadow-emerald-900/30">🛒 Abrir Caixa / PDV</a>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl">
                <span class="text-xs font-bold text-slate-400 uppercase">Produtos</span>
                <div class="text-3xl font-bold text-emerald-400 mt-1">{total_prods}</div>
            </div>
            <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl">
                <span class="text-xs font-bold text-slate-400 uppercase">Vendas Realizadas</span>
                <div class="text-3xl font-bold text-emerald-400 mt-1">R$ {total_sales:.2f}</div>
            </div>
            <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl">
                <span class="text-xs font-bold text-slate-400 uppercase">Clientes</span>
                <div class="text-3xl font-bold text-blue-400 mt-1">{total_custs}</div>
            </div>
            <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl">
                <span class="text-xs font-bold text-slate-400 uppercase">Fiado Pendente</span>
                <div class="text-3xl font-bold text-amber-400 mt-1">R$ {total_debts:.2f}</div>
            </div>
        </div>

        <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
            <h3 class="font-bold text-slate-200 text-sm">🧾 Últimas Vendas Realizadas</h3>
            <div class="overflow-x-auto">
                <table class="w-full text-left text-xs sm:text-sm">
                    <thead class="bg-slate-950 text-slate-400 border-b border-slate-800 font-bold">
                        <tr><th class="p-3">Nº Venda</th><th class="p-3">Data</th><th class="p-3">Cliente</th><th class="p-3 text-right">Total</th><th class="p-3 text-center">Pagamento</th><th class="p-3 text-center">Ação</th></tr>
                    </thead>
                    <tbody>{sales_rows or '<tr><td colspan="6" class="p-4 text-center text-slate-500">Nenhuma venda registrada ainda.</td></tr>'}</tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return render_layout(request, content, "Dashboard", "dashboard", msg)

# ==========================================
# 6. PDV / CAIXA COM LUPAS DE PESQUISA
# ==========================================
@app.get("/pdv", response_class=HTMLResponse)
def pdv(request: Request, msg: str = ""):
    user = get_user(request)
    if not user: return RedirectResponse(url="/login", status_code=303)
    store_id = user.get("store_id", 1)

    conn = get_db()
    products = conn.execute("SELECT * FROM products WHERE store_id = ? ORDER BY name ASC", (store_id,)).fetchall()
    customers = conn.execute("SELECT * FROM customers WHERE store_id = ? ORDER BY name ASC", (store_id,)).fetchall()
    conn.close()

    prod_options = "".join([f'<option value="{p["id"]}" data-price="{p["sale_price"]}" data-name="{p["name"]}">{p["code"]} - {p["name"]} (R$ {p["sale_price"]:.2f}) - Estq: {p["stock_quantity"]}</option>' for p in products])
    cust_options = "".join([f'<option value="{c["name"]}">{c["name"]}</option>' for c in customers])

    content = f"""
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div class="lg:col-span-2 bg-slate-900 border border-slate-800 p-6 rounded-2xl space-y-4">
            <div class="flex items-center justify-between">
                <h2 class="text-xl font-bold text-white">🛒 Caixa e Frente de Loja (PDV)</h2>
                <button type="button" onclick="openProductModal()" class="px-3 py-1.5 bg-emerald-600/20 hover:bg-emerald-600 text-emerald-300 hover:text-white border border-emerald-500/30 rounded-xl text-xs font-bold flex items-center gap-1.5 cursor-pointer">
                    🔍 Pesquisar Produto por Lupa
                </button>
            </div>
            
            <div class="space-y-3 font-bold text-xs">
                <div class="relative">
                    <label class="block text-slate-300 mb-1">🔍 Digite o código ou nome do produto:</label>
                    <input type="text" id="pdv_search_input" oninput="filterProducts()" placeholder="🔍 Pesquisar produto..." class="w-full bg-slate-950 border border-emerald-500/40 rounded-xl p-3 text-emerald-400 font-mono text-sm focus:outline-none mb-2">
                    
                    <select id="pdv_product" class="w-full bg-slate-950 border border-slate-700 rounded-xl p-3 text-emerald-400 font-bold focus:outline-none">
                        <option value="">-- Escolha o produto na lista --</option>
                        {prod_options}
                    </select>
                </div>

                <div class="flex gap-3">
                    <div class="w-1/2">
                        <label class="block text-slate-300 mb-1">Quantidade:</label>
                        <input type="number" id="pdv_qty" value="1" min="1" class="w-full bg-slate-950 border border-slate-700 rounded-xl p-3 text-white focus:outline-none">
                    </div>
                    <div class="w-1/2 flex items-end">
                        <button type="button" onclick="addToCart()" class="w-full py-3 bg-emerald-600 hover:bg-emerald-500 font-bold text-white rounded-xl shadow-lg cursor-pointer">
                            + Adicionar ao Carrinho
                        </button>
                    </div>
                </div>
            </div>

            <div class="border border-slate-800 rounded-xl overflow-hidden mt-4">
                <table class="w-full text-left text-xs">
                    <thead class="bg-slate-950 text-slate-400 border-b border-slate-800 font-bold">
                        <tr><th class="p-3">Produto</th><th class="p-3 text-center">Qtd</th><th class="p-3 text-right">Preço</th><th class="p-3 text-right">Subtotal</th><th class="p-3 text-center">Rem</th></tr>
                    </thead>
                    <tbody id="cart_body">
                        <tr><td colspan="5" class="p-4 text-center text-slate-500">Carrinho vazio.</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <div class="bg-slate-900 border border-slate-800 p-6 rounded-2xl space-y-6 flex flex-col justify-between">
            <div class="space-y-4">
                <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                    <h3 class="text-lg font-bold text-white">Resumo da Compra</h3>
                    <button type="button" onclick="openCustomerModal()" class="px-2.5 py-1 bg-blue-600/20 hover:bg-blue-600 text-blue-300 hover:text-white border border-blue-500/30 rounded-lg text-xs font-bold flex items-center gap-1 cursor-pointer">
                        🔍 Buscar Cliente
                    </button>
                </div>
                
                <div class="space-y-2 font-bold text-xs">
                    <div>
                        <label class="block text-slate-300 mb-1">Cliente Selecionado:</label>
                        <select id="pdv_customer" class="w-full bg-slate-950 border border-slate-700 rounded-xl p-2.5 text-white">
                            <option value="Cliente Avulso">Cliente Avulso</option>
                            {cust_options}
                        </select>
                    </div>

                    <div>
                        <label class="block text-slate-300 mb-1">Forma de Pagamento:</label>
                        <select id="pdv_payment" class="w-full bg-slate-950 border border-slate-700 rounded-xl p-2.5 text-emerald-400 font-bold">
                            <option value="DINHEIRO">💵 DINHEIRO</option>
                            <option value="PIX">⚡ PIX</option>
                            <option value="CARTAO_CREDITO">💳 CARTÃO DE CRÉDITO</option>
                            <option value="CREDIARIO">📄 CREDIÁRIO / FIADO (30 dias)</option>
                        </select>
                    </div>

                    <div>
                        <label class="block text-slate-300 mb-1">Desconto (R$):</label>
                        <input type="number" id="pdv_discount" value="0" min="0" oninput="updateTotal()" class="w-full bg-slate-950 border border-slate-700 rounded-xl p-2.5 text-white">
                    </div>
                </div>

                <div class="bg-slate-950 p-4 rounded-xl space-y-1 text-right">
                    <span class="text-xs text-slate-400 font-bold uppercase block">Total a Pagar</span>
                    <div id="pdv_total" class="text-3xl font-bold text-emerald-400">R$ 0,00</div>
                </div>
            </div>

            <button type="button" onclick="checkout()" class="w-full py-4 bg-emerald-600 hover:bg-emerald-500 font-bold text-white rounded-xl shadow-xl transition-transform active:scale-95 cursor-pointer text-sm">
                ✅ Finalizar Venda & Emitir Recibo
            </button>
        </div>
    </div>

    <!-- MODAL LUPA CLIENTE -->
    <div id="modal_customer" class="fixed inset-0 bg-slate-950/80 backdrop-blur-sm hidden items-center justify-center p-4 z-50">
        <div class="bg-slate-900 border border-slate-800 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl">
            <div class="flex justify-between items-center pb-2 border-b border-slate-800">
                <h3 class="text-base font-bold text-white">🔍 Pesquisar Cliente (Lupa)</h3>
                <button type="button" onclick="closeCustomerModal()" class="text-slate-400 hover:text-white font-bold text-lg">✕</button>
            </div>
            <input type="text" id="cust_search_input" oninput="filterCustomerList()" placeholder="Digite nome, CPF ou telefone..." class="w-full bg-slate-950 border border-slate-700 rounded-xl p-3 text-xs text-white focus:outline-none">
            <div id="cust_search_results" class="max-h-60 overflow-y-auto space-y-1 divide-y divide-slate-800">
            </div>
        </div>
    </div>

    <!-- MODAL LUPA PRODUTO -->
    <div id="modal_product" class="fixed inset-0 bg-slate-950/80 backdrop-blur-sm hidden items-center justify-center p-4 z-50">
        <div class="bg-slate-900 border border-slate-800 rounded-2xl max-w-lg w-full p-6 space-y-4 shadow-2xl">
            <div class="flex justify-between items-center pb-2 border-b border-slate-800">
                <h3 class="text-base font-bold text-white">🔍 Catálogo de Produtos (Lupa)</h3>
                <button type="button" onclick="closeProductModal()" class="text-slate-400 hover:text-white font-bold text-lg">✕</button>
            </div>
            <input type="text" id="prod_modal_search" oninput="filterProductCatalog()" placeholder="Digite código ou nome do produto..." class="w-full bg-slate-950 border border-slate-700 rounded-xl p-3 text-xs text-emerald-400 font-bold focus:outline-none">
            <div id="prod_search_results" class="max-h-72 overflow-y-auto space-y-1.5">
            </div>
        </div>
    </div>

    <script>
    let cart = [];
    const allProducts = Array.from(document.querySelectorAll('#pdv_product option')).map(opt => ({{
        id: opt.value,
        name: opt.getAttribute('data-name'),
        price: parseFloat(opt.getAttribute('data-price')) || 0,
        text: opt.innerText
    }})).filter(p => p.id !== "");

    const allCustomers = Array.from(document.querySelectorAll('#pdv_customer option')).map(opt => opt.value);

    function filterProducts() {{
        const query = document.getElementById('pdv_search_input').value.toLowerCase().trim();
        const select = document.getElementById('pdv_product');
        Array.from(select.options).forEach(opt => {{
            if (!opt.value) return;
            const text = opt.innerText.toLowerCase();
            opt.style.display = text.includes(query) ? '' : 'none';
        }});
    }}

    function openCustomerModal() {{
        document.getElementById('modal_customer').classList.remove('hidden');
        document.getElementById('modal_customer').classList.add('flex');
        filterCustomerList();
    }}
    function closeCustomerModal() {{
        document.getElementById('modal_customer').classList.add('hidden');
        document.getElementById('modal_customer').classList.remove('flex');
    }}

    function filterCustomerList() {{
        const term = document.getElementById('cust_search_input').value.toLowerCase();
        const container = document.getElementById('cust_search_results');
        const matches = allCustomers.filter(c => c.toLowerCase().includes(term));
        container.innerHTML = matches.map(c => `
            <div onclick="selectCustomer('${{c}}')" class="p-2.5 hover:bg-slate-800 rounded-lg cursor-pointer font-bold text-xs text-white flex justify-between items-center">
                <span>${{c}}</span>
                <span class="text-emerald-400 text-[10px]">Selecionar</span>
            </div>
        `).join('') || '<p class="text-xs text-slate-500 p-3 text-center">Nenhum cliente encontrado.</p>';
    }}

    function selectCustomer(name) {{
        document.getElementById('pdv_customer').value = name;
        closeCustomerModal();
    }}

    function openProductModal() {{
        document.getElementById('modal_product').classList.remove('hidden');
        document.getElementById('modal_product').classList.add('flex');
        filterProductCatalog();
    }}
    function closeProductModal() {{
        document.getElementById('modal_product').classList.add('hidden');
        document.getElementById('modal_product').classList.remove('flex');
    }}

    function filterProductCatalog() {{
        const term = document.getElementById('prod_modal_search').value.toLowerCase();
        const container = document.getElementById('prod_search_results');
        const matches = allProducts.filter(p => p.text.toLowerCase().includes(term));
        container.innerHTML = matches.map(p => `
            <div onclick="selectProductFromModal('${{p.id}}')" class="p-3 bg-slate-950 hover:bg-slate-800 border border-slate-800 rounded-xl cursor-pointer flex justify-between items-center text-xs">
                <div>
                    <span class="font-bold text-white block">${{p.name}}</span>
                    <span class="text-[10px] text-emerald-400 font-bold">R$ ${{p.price.toFixed(2)}}</span>
                </div>
                <button type="button" class="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded font-bold text-[10px]">
                    + Adicionar
                </button>
            </div>
        `).join('') || '<p class="text-xs text-slate-500 p-3 text-center">Nenhum produto encontrado.</p>';
    }}

    function selectProductFromModal(id) {{
        document.getElementById('pdv_product').value = id;
        addToCart();
        closeProductModal();
    }}

    function addToCart() {{
        const select = document.getElementById('pdv_product');
        const id = select.value;
        if (!id) return alert('Selecione um produto!');
        
        const option = select.options[select.selectedIndex];
        const name = option.getAttribute('data-name');
        const price = parseFloat(option.getAttribute('data-price')) || 0;
        const qty = parseFloat(document.getElementById('pdv_qty').value) || 1;

        const existing = cart.find(i => i.id === id);
        if (existing) {{
            existing.qty += qty;
        }} else {{
            cart.push({{ id, name, price, qty }});
        }}

        renderCart();
    }}

    function removeFromCart(index) {{
        cart.splice(index, 1);
        renderCart();
    }}

    function renderCart() {{
        const tbody = document.getElementById('cart_body');
        if (cart.length === 0) {{
            tbody.innerHTML = '<tr><td colspan="5" class="p-4 text-center text-slate-500">Carrinho vazio.</td></tr>';
            updateTotal();
            return;
        }}

        tbody.innerHTML = cart.map((item, idx) => `
            <tr class="border-b border-slate-800">
                <td class="p-3 font-bold text-white">${{item.name}}</td>
                <td class="p-3 text-center">${{item.qty}}</td>
                <td class="p-3 text-right">R$ ${{item.price.toFixed(2)}}</td>
                <td class="p-3 text-right font-bold text-emerald-400">R$ ${{(item.price * item.qty).toFixed(2)}}</td>
                <td class="p-3 text-center">
                    <button onclick="removeFromCart(${{idx}})" class="text-rose-400 hover:text-rose-300 font-bold">✕</button>
                </td>
            </tr>
        `).join('');

        updateTotal();
    }}

    function updateTotal() {{
        const subtotal = cart.reduce((acc, item) => acc + (item.price * item.qty), 0);
        const discount = parseFloat(document.getElementById('pdv_discount').value) || 0;
        const total = Math.max(0, subtotal - discount);
        document.getElementById('pdv_total').innerText = 'R$ ' + total.toFixed(2).replace('.', ',');
    }}

    async function checkout() {{
        if (cart.length === 0) return alert('O carrinho está vazio!');

        const customer_name = document.getElementById('pdv_customer').value;
        const payment_method = document.getElementById('pdv_payment').value;
        const discount = parseFloat(document.getElementById('pdv_discount').value) || 0;

        try {{
            const response = await fetch('/pdv-checkout', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ items: cart, customer_name, payment_method, discount }})
            }});

            const result = await response.json();
            if (result.success) {{
                alert('✅ Venda realizada com sucesso!');
                if (result.whatsapp_msg) {{
                    window.open('https://api.whatsapp.com/send?text=' + result.whatsapp_msg, '_blank');
                }}
                window.location.reload();
            }} else {{
                alert('Erro ao finalizar venda: ' + (result.error || 'Verifique os dados'));
            }}
        }} catch (e) {{
            alert('Erro de conexão ao processar venda.');
        }}
    }}
    </script>
    """
    return render_layout(request, content, "PDV - Caixa", "pdv", msg)

@app.post("/pdv-checkout")
async def pdv_checkout(request: Request):
    user = get_user(request)
    if not user: return JSONResponse({"success": False, "error": "Não autenticado"}, status_code=401)
    
    try:
        data = await request.json()
        items = data.get("items", [])
        customer_name = str(data.get("customer_name", "Cliente Avulso")).strip() or "Cliente Avulso"
        payment_method = str(data.get("payment_method", "DINHEIRO")).strip() or "DINHEIRO"
        discount = float(data.get("discount", 0) or 0)
        store_id = int(user.get("store_id", 1))

        if not items:
            return JSONResponse({"success": False, "error": "Carrinho vazio"}, status_code=400)

        subtotal = 0.0
        parsed_items = []
        for it in items:
            p_id = int(it.get("id", 0) or 0)
            p_name = str(it.get("name", "Produto"))
            p_price = float(it.get("price", 0) or 0)
            p_qty = float(it.get("qty", 1) or 1)
            p_subtotal = p_price * p_qty
            subtotal += p_subtotal
            parsed_items.append({"id": p_id, "name": p_name, "price": p_price, "qty": p_qty, "subtotal": p_subtotal})

        total = max(0.0, subtotal - discount)
        sale_number = f"VND{int(datetime.now().timestamp())}"
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")

        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute(
            "INSERT INTO sales (store_id, sale_number, created_at, seller_name, customer_name, subtotal, discount, total, payment_method) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (store_id, sale_number, now_str, user.get("name", "Vendedor"), customer_name, subtotal, discount, total, payment_method)
        )
        sale_id = cursor.lastrowid

        for item in parsed_items:
            cursor.execute(
                "INSERT INTO sale_items (sale_id, product_id, product_name, quantity, unit_price, subtotal) VALUES (?, ?, ?, ?, ?, ?)",
                (sale_id, item["id"], item["name"], item["qty"], item["price"], item["subtotal"])
            )
            if item["id"] > 0:
                cursor.execute("UPDATE products SET stock_quantity = MAX(0, stock_quantity - ?) WHERE id = ?", (item["qty"], item["id"]))

        if payment_method == "CREDIARIO":
            due_date = (datetime.now() + timedelta(days=30)).strftime("%d/%m/%Y")
            cursor.execute(
                "INSERT INTO receivables (store_id, sale_id, customer_name, total_amount, due_date, status) VALUES (?, ?, ?, ?, ?, 'PENDENTE')",
                (store_id, sale_id, customer_name, total, due_date)
            )

        conn.commit()
        conn.close()

        receipt_text = f"🧾 *COMPROVANTE DE COMPRA*\nNº: *{sale_number}*\nData: {now_str}\nCliente: {customer_name}\n\n*Itens:*\n"
        for item in parsed_items:
            receipt_text += f"• {item['qty']}x {item['name']} (R$ {item['price']:.2f})\n"
        receipt_text += f"\n*TOTAL PAGO:* R$ {total:.2f} ({payment_method})\nObrigado pela preferência!"

        return JSONResponse({"success": True, "whatsapp_msg": urllib.parse.quote(receipt_text)})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

# ==========================================
# 7. EXCLUSÃO GERAL
# ==========================================
@app.post("/delete-item")
def delete_item(request: Request, item_type: str = Form(...), item_id: int = Form(...)):
    conn = get_db()
    redirect_url = "/dashboard"
    msg = "Item removido com sucesso!"

    if item_type == "sale":
        sale_items = conn.execute("SELECT product_id, quantity FROM sale_items WHERE sale_id = ?", (item_id,)).fetchall()
        for item in sale_items:
            p_id = item["product_id"]
            qty = float(item["quantity"] or 0)
            if p_id and p_id > 0 and qty > 0:
                conn.execute("UPDATE products SET stock_quantity = stock_quantity + ? WHERE id = ?", (qty, p_id))

        conn.execute("DELETE FROM sale_items WHERE sale_id = ?", (item_id,))
        conn.execute("DELETE FROM receivables WHERE sale_id = ?", (item_id,))
        conn.execute("DELETE FROM sales WHERE id = ?", (item_id,))
        msg = "🗑️ Venda excluída com sucesso e estoque estornado!"
        redirect_url = "/dashboard"

    elif item_type == "product":
        conn.execute("DELETE FROM products WHERE id = ?", (item_id,))
        redirect_url = "/products"
    elif item_type == "customer":
        conn.execute("DELETE FROM customers WHERE id = ?", (item_id,))
        redirect_url = "/customers"
    elif item_type == "receivable":
        conn.execute("DELETE FROM receivables WHERE id = ?", (item_id,))
        redirect_url = "/receivables"
    elif item_type == "supplier":
        conn.execute("DELETE FROM suppliers WHERE id = ?", (item_id,))
        redirect_url = "/suppliers"
    elif item_type == "expense":
        conn.execute("DELETE FROM expenses WHERE id = ?", (item_id,))
        redirect_url = "/expenses"

    conn.commit()
    conn.close()
    return RedirectResponse(url=f"{redirect_url}?msg={urllib.parse.quote(msg)}", status_code=303)

# ==========================================
# 8. OUTROS MÓDULOS
# ==========================================
@app.get("/receivables", response_class=HTMLResponse)
def receivables_list(request: Request, msg: str = ""):
    user = get_user(request)
    if not user: return RedirectResponse(url="/login", status_code=303)
    store_id = user.get("store_id", 1)

    conn = get_db()
    store = conn.execute("SELECT name FROM stores WHERE id = ?", (store_id,)).fetchone()
    store_name = store["name"] if store else "Nossa Loja"
    debts = conn.execute("SELECT * FROM receivables WHERE store_id = ? ORDER BY id DESC", (store_id,)).fetchall()
    customers = conn.execute("SELECT name, phone FROM customers WHERE store_id = ?", (store_id,)).fetchall()
    conn.close()

    cust_phones = {c["name"]: (c["phone"] or "") for c in customers}

    rows = []
    for d in debts:
        c_phone = cust_phones.get(d['customer_name'], "")
        clean_phone = "".join(filter(str.isdigit, c_phone))
        
        msg_text = f"Olá {d['customer_name']}! Lembramos do seu débito pendente na loja {store_name} no valor de R$ {d['total_amount']:.2f} com vencimento em {d['due_date']}. Qualquer dúvida estamos à disposição!"
        wa_url = f"https://api.whatsapp.com/send?phone=55{clean_phone}&text={urllib.parse.quote(msg_text)}" if clean_phone else "#"

        wa_button = f'<a href="{wa_url}" target="_blank" class="px-2 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-xs font-bold font-mono inline-flex items-center gap-1">📲 WhatsApp</a>' if clean_phone else '<span class="text-[10px] text-slate-500">(Sem tel)</span>'

        pay_form = f"""
        <form action="/pay-receivable" method="POST" class="flex items-center gap-1 inline-block">
            <input type="hidden" name="id" value="{d['id']}">
            <input type="number" step="0.01" name="paid_amount" placeholder="Qtd R$" required class="w-16 bg-slate-950 border border-slate-700 rounded px-1.5 py-0.5 text-xs text-emerald-400 font-bold">
            <button type="submit" class="bg-emerald-600 hover:bg-emerald-500 text-white px-2 py-0.5 rounded text-xs font-bold">✓ Pagar</button>
        </form>
        """ if d['status'] == 'PENDENTE' else '<span class="text-xs text-emerald-400 font-bold">✓ Quitado</span>'

        rows.append(f"""
        <tr class="border-b border-slate-800 text-xs sm:text-sm">
            <td class="p-3 font-bold text-white">{d['customer_name']}</td>
            <td class="p-3 text-amber-400 font-bold">R$ {d['total_amount']:.2f}</td>
            <td class="p-3 text-slate-300 font-mono">{d['due_date']}</td>
            <td class="p-3 text-center"><span class="px-2 py-0.5 rounded {"bg-emerald-500/20 text-emerald-300" if d['status'] == "PAGO" else "bg-amber-500/20 text-amber-300"} text-[10px] font-bold">{d['status']}</span></td>
            <td class="p-3 text-center">{wa_button}</td>
            <td class="p-3 text-center">{pay_form}</td>
            <td class="p-3 text-center">
                <form action="/delete-item" method="POST" class="inline">
                    <input type="hidden" name="item_type" value="receivable">
                    <input type="hidden" name="item_id" value="{d['id']}">
                    <button type="submit" onclick="return confirm('Excluir esta dívida?');" class="text-xs bg-rose-950/60 hover:bg-rose-600 text-rose-300 px-2 py-1 rounded">🗑️</button>
                </form>
            </td>
        </tr>
        """)

    content = f"""
    <div class="space-y-6">
        <div class="flex items-center justify-between">
            <h2 class="text-2xl font-bold text-white">📄 Fiado & Cobrança WhatsApp ({len(debts)})</h2>
            <a href="/import-pdf" class="px-4 py-2 bg-amber-600/20 text-amber-300 border border-amber-500/30 font-bold rounded-xl text-xs">+ Importar em Lote</a>
        </div>

        <div class="bg-slate-900 border border-slate-800 p-6 rounded-2xl space-y-4">
            <h3 class="text-sm font-bold text-amber-400 uppercase">+ Lançar Fiado Manualmente</h3>
            <form action="/receivable-add" method="POST" class="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs font-bold">
                <input type="text" name="customer_name" placeholder="Nome do Cliente" required class="bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                <input type="number" step="0.01" name="total_amount" placeholder="Valor (R$)" required class="bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                <input type="text" name="due_date" placeholder="Vencimento (ex: 20/09/2026)" value="{(datetime.now() + timedelta(days=30)).strftime('%d/%m/%Y')}" required class="bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                <div class="sm:col-span-3 text-right">
                    <button type="submit" class="px-6 py-2.5 bg-amber-600 hover:bg-amber-500 font-bold text-white rounded-xl cursor-pointer">Salvar Fiado</button>
                </div>
            </form>
        </div>

        <div class="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
            <table class="w-full text-left text-xs sm:text-sm">
                <thead class="bg-slate-950 text-slate-400 border-b border-slate-800 font-bold">
                    <tr><th class="p-3">Cliente</th><th class="p-3">Saldo Devedor</th><th class="p-3">Vencimento</th><th class="p-3 text-center">Status</th><th class="p-3 text-center">Cobrança</th><th class="p-3 text-center">Abater / Quitar</th><th class="p-3 text-center">Rem</th></tr>
                </thead>
                <tbody>{"".join(rows) or '<tr><td colspan="7" class="p-4 text-center text-slate-500">Nenhuma dívida cadastrada.</td></tr>'}</tbody>
            </table>
        </div>
    </div>
    """
    return render_layout(request, content, "Dívidas & Cobrança", "receivables", msg)

@app.post("/pay-receivable")
def pay_receivable(request: Request, id: int = Form(...), paid_amount: float = Form(...)):
    conn = get_db()
    rec = conn.execute("SELECT * FROM receivables WHERE id = ?", (id,)).fetchone()
    if rec:
        current_amount = float(rec["total_amount"])
        new_amount = current_amount - paid_amount
        if new_amount <= 0:
            conn.execute("UPDATE receivables SET total_amount = 0, status = 'PAGO' WHERE id = ?", (id,))
            msg = "Dívida quitada integralmente com sucesso!"
        else:
            conn.execute("UPDATE receivables SET total_amount = ? WHERE id = ?", (new_amount, id))
            msg = f"Abatimento de R$ {paid_amount:.2f} realizado! Saldo restante: R$ {new_amount:.2f}"
        conn.commit()
    conn.close()
    return RedirectResponse(url=f"/receivables?msg={urllib.parse.quote(msg)}", status_code=303)

@app.post("/receivable-add")
def receivable_add(request: Request, customer_name: str = Form(...), total_amount: float = Form(...), due_date: str = Form(...)):
    user = get_user(request)
    store_id = user.get("store_id", 1) if user else 1
    conn = get_db()
    conn.execute("INSERT INTO receivables (customer_name, total_amount, due_date, status, store_id) VALUES (?, ?, ?, 'PENDENTE', ?)", (customer_name, total_amount, due_date, store_id))
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/receivables?msg={urllib.parse.quote('Dívida cadastrada com sucesso!')}", status_code=303)

@app.get("/customers", response_class=HTMLResponse)
def customers_list(request: Request, msg: str = ""):
    user = get_user(request)
    if not user: return RedirectResponse(url="/login", status_code=303)
    store_id = user.get("store_id", 1)

    conn = get_db()
    custs = conn.execute("SELECT * FROM customers WHERE store_id = ? ORDER BY id DESC", (store_id,)).fetchall()
    conn.close()

    rows = "".join([f"""
    <tr class="border-b border-slate-800 text-xs">
        <td class="p-3 font-bold text-white">{c['name']}</td>
        <td class="p-3 text-slate-300 font-mono">{c['phone'] or '-'}</td>
        <td class="p-3 text-slate-400 font-mono">{c['document'] or '-'}</td>
        <td class="p-3 text-slate-300">{c['address'] or ''} {c['neighborhood'] or ''} {c['city'] or ''}</td>
        <td class="p-3 text-emerald-400 font-bold text-right">R$ {(c['credit_limit'] or 1000):.2f}</td>
        <td class="p-3 text-center">
            <form action="/delete-item" method="POST" class="inline">
                <input type="hidden" name="item_type" value="customer">
                <input type="hidden" name="item_id" value="{c['id']}">
                <button type="submit" onclick="return confirm('Excluir este cliente?');" class="text-xs bg-rose-950/60 hover:bg-rose-600 text-rose-300 px-2 py-1 rounded">🗑️ Rem</button>
            </form>
        </td>
    </tr>""" for c in custs])

    content = f"""
    <div class="space-y-6">
        <div class="flex items-center justify-between">
            <h2 class="text-2xl font-bold text-white">👥 Clientes ({len(custs)})</h2>
            <a href="/import-pdf" class="px-4 py-2 bg-amber-600/20 text-amber-300 border border-amber-500/30 font-bold rounded-xl text-xs">+ Importar em Lote</a>
        </div>

        <div class="bg-slate-900 border border-slate-800 p-6 rounded-2xl space-y-4">
            <h3 class="text-sm font-bold text-blue-400 uppercase">+ Cadastrar Novo Cliente Detalhado</h3>
            <form action="/customer-add" method="POST" class="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs font-bold">
                <input type="text" name="name" placeholder="Nome Completo *" required class="bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                <input type="text" name="phone" placeholder="Telefone / WhatsApp (ex: 11999998888)" class="bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                <input type="text" name="document" placeholder="CPF ou CNPJ" class="bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                
                <input type="text" name="address" placeholder="Endereço / Rua e Nº" class="bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                <input type="text" name="neighborhood" placeholder="Bairro" class="bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                <input type="text" name="city" placeholder="Cidade" class="bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                
                <input type="number" step="0.01" name="credit_limit" value="1000" placeholder="Limite de Crediário (R$)" class="bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                <input type="text" name="notes" placeholder="Observações" class="sm:col-span-2 bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                
                <div class="sm:col-span-3 text-right">
                    <button type="submit" class="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 font-bold text-white rounded-xl shadow-lg cursor-pointer">Salvar Cliente</button>
                </div>
            </form>
        </div>

        <div class="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
            <table class="w-full text-left text-xs sm:text-sm">
                <thead class="bg-slate-950 text-slate-400 border-b border-slate-800 font-bold">
                    <tr><th class="p-3">Nome</th><th class="p-3">Telefone</th><th class="p-3">Documento</th><th class="p-3">Endereço / Local</th><th class="p-3 text-right">Limite</th><th class="p-3 text-center">Ação</th></tr>
                </thead>
                <tbody>{rows or '<tr><td colspan="6" class="p-4 text-center text-slate-500">Nenhum cliente cadastrado.</td></tr>'}</tbody>
            </table>
        </div>
    </div>
    """
    return render_layout(request, content, "Clientes", "customers", msg)

@app.post("/customer-add")
def customer_add(request: Request, name: str = Form(...), phone: str = Form(""), document: str = Form(""), address: str = Form(""), neighborhood: str = Form(""), city: str = Form(""), credit_limit: float = Form(1000), notes: str = Form("")):
    user = get_user(request)
    store_id = user.get("store_id", 1) if user else 1
    conn = get_db()
    conn.execute(
        "INSERT INTO customers (name, phone, document, address, neighborhood, city, credit_limit, notes, store_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (name, phone, document, address, neighborhood, city, credit_limit, notes, store_id)
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/customers?msg={urllib.parse.quote('Cliente cadastrado!')}", status_code=303)

@app.get("/stores-users", response_class=HTMLResponse)
def stores_users_page(request: Request, msg: str = ""):
    user = get_user(request)
    if not user: 
        return RedirectResponse(url="/login", status_code=303)
    
    if user.get("role") != "ADMIN":
        return RedirectResponse(url=f"/dashboard?msg={urllib.parse.quote('Acesso restrito ao Administrador!')}", status_code=303)

    conn = get_db()
    stores = conn.execute("SELECT * FROM stores").fetchall()
    users = conn.execute("SELECT u.*, s.name as store_name FROM users u LEFT JOIN stores s ON u.store_id = s.id").fetchall()
    conn.close()

    store_rows = "".join([f"""
    <tr class="border-b border-slate-800 text-xs">
        <td class="p-3 font-mono text-emerald-400 font-bold">#{s['id']}</td>
        <td class="p-3 font-bold text-white">{s['name']}</td>
        <td class="p-3 text-slate-400 font-mono">Senha: <b>{s['password']}</b></td>
    </tr>""" for s in stores])

    user_rows = "".join([f"""
    <tr class="border-b border-slate-800 text-xs">
        <td class="p-3 font-bold text-white">{u['name']}</td>
        <td class="p-3 font-mono text-emerald-400">{u['username']}</td>
        <td class="p-3 text-slate-300 font-bold">{u['role']}</td>
        <td class="p-3 text-slate-400">{u['store_name'] or 'Matriz'}</td>
    </tr>""" for u in users])

    store_select_options = "".join([f'<option value="{s["id"]}">{s["name"]}</option>' for s in stores])

    content = f"""
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div class="space-y-4">
            <h2 class="text-xl font-bold text-white">🏬 Lojas do Sistema</h2>
            <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl space-y-3">
                <h3 class="text-xs font-bold text-emerald-400 uppercase">+ Cadastrar Nova Loja / Filial</h3>
                <form action="/store-add" method="POST" class="space-y-3 text-xs font-bold">
                    <input type="text" name="name" placeholder="Nome da Loja (ex: Filial Centro)" required class="w-full bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                    <input type="password" name="password" placeholder="Senha para Acessar a Loja" required class="w-full bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                    <button type="submit" class="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 font-bold text-white rounded-xl">Criar Loja</button>
                </form>
            </div>

            <div class="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
                <table class="w-full text-left">
                    <thead class="bg-slate-950 text-slate-400 border-b border-slate-800 text-xs font-bold">
                        <tr><th class="p-3">ID</th><th class="p-3">Nome da Loja</th><th class="p-3">Senha</th></tr>
                    </thead>
                    <tbody>{store_rows}</tbody>
                </table>
            </div>
        </div>

        <div class="space-y-4">
            <h2 class="text-xl font-bold text-white">👥 Equipe & Funcionários</h2>
            <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl space-y-3">
                <h3 class="text-xs font-bold text-blue-400 uppercase">+ Cadastrar Funcionário / Vendedor</h3>
                <form action="/user-add" method="POST" class="space-y-3 text-xs font-bold">
                    <input type="text" name="name" placeholder="Nome do Funcionário" required class="w-full bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                    <div class="flex gap-2">
                        <input type="text" name="username" placeholder="Usuário para Login" required class="w-1/2 bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                        <input type="password" name="password" placeholder="Senha do Usuário" required class="w-1/2 bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                    </div>
                    <div class="flex gap-2">
                        <select name="role" class="w-1/2 bg-slate-950 border border-slate-700 rounded-xl p-3 text-emerald-400">
                            <option value="VENDEDOR">VENDEDOR / CAIXA</option>
                            <option value="GERENTE">GERENTE</option>
                            <option value="ADMIN">ADMINISTRADOR</option>
                        </select>
                        <select name="store_id" class="w-1/2 bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                            {store_select_options}
                        </select>
                    </div>
                    <button type="submit" class="w-full py-2.5 bg-blue-600 hover:bg-blue-500 font-bold text-white rounded-xl">Criar Usuário</button>
                </form>
            </div>

            <div class="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
                <table class="w-full text-left">
                    <thead class="bg-slate-950 text-slate-400 border-b border-slate-800 text-xs font-bold">
                        <tr><th class="p-3">Nome</th><th class="p-3">Usuário</th><th class="p-3">Cargo</th><th class="p-3">Loja</th></tr>
                    </thead>
                    <tbody>{user_rows}</tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return render_layout(request, content, "Lojas & Equipe", "stores_users", msg)

@app.post("/store-add")
def store_add(request: Request, name: str = Form(...), password: str = Form(...)):
    user = get_user(request)
    if not user or user.get("role") != "ADMIN":
        return RedirectResponse(url="/dashboard?msg=Acesso+negado", status_code=303)

    conn = get_db()
    conn.execute("INSERT INTO stores (name, password, logo_text) VALUES (?, ?, ?)", (name, password, f"ERP {name.upper()}"))
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/stores-users?msg={urllib.parse.quote('Nova loja cadastrada com sucesso!')}", status_code=303)

@app.post("/user-add")
def user_add(request: Request, name: str = Form(...), username: str = Form(...), password: str = Form(...), role: str = Form("VENDEDOR"), store_id: int = Form(1)):
    user = get_user(request)
    if not user or user.get("role") != "ADMIN":
        return RedirectResponse(url="/dashboard?msg=Acesso+negado", status_code=303)

    conn = get_db()
    try:
        conn.execute("INSERT INTO users (name, username, password_hash, role, store_id) VALUES (?, ?, ?, ?, ?)", (name, username, password, role, store_id))
        conn.commit()
        msg = "Funcionário cadastrado!"
    except sqlite3.IntegrityError:
        msg = "Erro: Este nome de usuário já existe!"
    conn.close()
    return RedirectResponse(url=f"/stores-users?msg={urllib.parse.quote(msg)}", status_code=303)

@app.get("/products", response_class=HTMLResponse)
def products_list(request: Request, msg: str = ""):
    user = get_user(request)
    if not user: return RedirectResponse(url="/login", status_code=303)
    store_id = user.get("store_id", 1)

    conn = get_db()
    prods = conn.execute("SELECT * FROM products WHERE store_id = ? ORDER BY id DESC", (store_id,)).fetchall()
    conn.close()

    rows = "".join([f"""
    <tr class="border-b border-slate-800">
        <td class="p-3 font-mono text-emerald-400 font-bold">{p['code']}</td>
        <td class="p-3 font-bold text-white">{p['name']}</td>
        <td class="p-3 text-right font-bold text-slate-200">R$ {p['sale_price']:.2f}</td>
        <td class="p-3 text-right font-bold text-slate-300">{p['stock_quantity']}</td>
        <td class="p-3 text-center">
            <form action="/delete-item" method="POST" class="inline">
                <input type="hidden" name="item_type" value="product">
                <input type="hidden" name="item_id" value="{p['id']}">
                <button type="submit" onclick="return confirm('Excluir este produto?');" class="text-xs bg-rose-950/60 hover:bg-rose-600 text-rose-300 px-2 py-1 rounded">🗑️ Rem</button>
            </form>
        </td>
    </tr>""" for p in prods])

    content = f"""
    <div class="space-y-6">
        <div class="flex items-center justify-between">
            <h2 class="text-2xl font-bold text-white">📦 Produtos ({len(prods)})</h2>
            <a href="/import-pdf" class="px-4 py-2 bg-amber-600/20 text-amber-300 border border-amber-500/30 font-bold rounded-xl text-xs">+ Importar em Lote</a>
        </div>

        <div class="bg-slate-900 border border-slate-800 p-6 rounded-2xl space-y-4">
            <h3 class="text-sm font-bold text-emerald-400 uppercase">+ Cadastrar Novo Produto</h3>
            <form action="/product-add" method="POST" class="grid grid-cols-1 sm:grid-cols-4 gap-3 text-xs font-bold">
                <input type="text" name="code" placeholder="Código (ex: P001)" required class="bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                <input type="text" name="name" placeholder="Nome do Produto" required class="bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                <input type="number" step="0.01" name="sale_price" placeholder="Preço (R$)" required class="bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                <input type="number" name="stock_quantity" placeholder="Estoque Início" value="10" required class="bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                <div class="sm:col-span-4 text-right">
                    <button type="submit" class="px-6 py-2.5 bg-emerald-600 hover:bg-emerald-500 font-bold text-white rounded-xl">Salvar Produto</button>
                </div>
            </form>
        </div>

        <div class="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
            <table class="w-full text-left text-xs sm:text-sm">
                <thead class="bg-slate-950 text-slate-400 border-b border-slate-800 font-bold">
                    <tr><th class="p-3">Código</th><th class="p-3">Nome</th><th class="p-3 text-right">Preço</th><th class="p-3 text-right">Estoque</th><th class="p-3 text-center">Ação</th></tr>
                </thead>
                <tbody>{rows or '<tr><td colspan="5" class="p-4 text-center text-slate-500">Nenhum produto cadastrado.</td></tr>'}</tbody>
            </table>
        </div>
    </div>
    """
    return render_layout(request, content, "Produtos", "products", msg)

@app.post("/product-add")
def product_add(request: Request, code: str = Form(...), name: str = Form(...), sale_price: float = Form(...), stock_quantity: float = Form(10)):
    user = get_user(request)
    store_id = user.get("store_id", 1) if user else 1
    conn = get_db()
    conn.execute("INSERT INTO products (code, name, sale_price, stock_quantity, store_id) VALUES (?, ?, ?, ?, ?)", (code, name, sale_price, stock_quantity, store_id))
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/products?msg={urllib.parse.quote('Produto cadastrado!')}", status_code=303)

@app.get("/suppliers", response_class=HTMLResponse)
def suppliers_list(request: Request, msg: str = ""):
    user = get_user(request)
    if not user: return RedirectResponse(url="/login", status_code=303)
    store_id = user.get("store_id", 1)

    conn = get_db()
    sups = conn.execute("SELECT * FROM suppliers WHERE store_id = ? ORDER BY id DESC", (store_id,)).fetchall()
    conn.close()

    rows = "".join([f"""
    <tr class="border-b border-slate-800">
        <td class="p-3 font-bold text-white">{s['name']}</td>
        <td class="p-3 text-slate-300 font-mono">{s['cnpj'] or '-'}</td>
        <td class="p-3 text-slate-400 font-mono">{s['phone'] or '-'}</td>
        <td class="p-3 text-center">
            <form action="/delete-item" method="POST" class="inline">
                <input type="hidden" name="item_type" value="supplier">
                <input type="hidden" name="item_id" value="{s['id']}">
                <button type="submit" onclick="return confirm('Excluir fornecedor?');" class="text-xs bg-rose-950/60 hover:bg-rose-600 text-rose-300 px-2 py-1 rounded">🗑️ Rem</button>
            </form>
        </td>
    </tr>""" for s in sups])

    content = f"""
    <div class="space-y-6">
        <div class="flex items-center justify-between">
            <h2 class="text-2xl font-bold text-white">🏬 Fornecedores ({len(sups)})</h2>
        </div>

        <div class="bg-slate-900 border border-slate-800 p-6 rounded-2xl space-y-4">
            <h3 class="text-sm font-bold text-purple-400 uppercase">+ Cadastrar Fornecedor</h3>
            <form action="/supplier-add" method="POST" class="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs font-bold">
                <input type="text" name="name" placeholder="Razão Social / Nome" required class="bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                <input type="text" name="cnpj" placeholder="CNPJ" class="bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                <input type="text" name="phone" placeholder="Telefone" class="bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                <div class="sm:col-span-3 text-right">
                    <button type="submit" class="px-6 py-2.5 bg-purple-600 hover:bg-purple-500 font-bold text-white rounded-xl">Salvar Fornecedor</button>
                </div>
            </form>
        </div>

        <div class="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
            <table class="w-full text-left text-xs sm:text-sm">
                <thead class="bg-slate-950 text-slate-400 border-b border-slate-800 font-bold">
                    <tr><th class="p-3">Nome</th><th class="p-3">CNPJ</th><th class="p-3">Telefone</th><th class="p-3 text-center">Ação</th></tr>
                </thead>
                <tbody>{rows or '<tr><td colspan="4" class="p-4 text-center text-slate-500">Nenhum fornecedor cadastrado.</td></tr>'}</tbody>
            </table>
        </div>
    </div>
    """
    return render_layout(request, content, "Fornecedores", "suppliers", msg)

@app.post("/supplier-add")
def supplier_add(request: Request, name: str = Form(...), cnpj: str = Form(""), phone: str = Form("")):
    user = get_user(request)
    store_id = user.get("store_id", 1) if user else 1
    conn = get_db()
    conn.execute("INSERT INTO suppliers (name, cnpj, phone, store_id) VALUES (?, ?, ?, ?)", (name, cnpj, phone, store_id))
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/suppliers?msg={urllib.parse.quote('Fornecedor cadastrado!')}", status_code=303)

@app.get("/expenses", response_class=HTMLResponse)
def expenses_list(request: Request, msg: str = ""):
    user = get_user(request)
    if not user: return RedirectResponse(url="/login", status_code=303)
    store_id = user.get("store_id", 1)

    conn = get_db()
    exps = conn.execute("SELECT * FROM expenses WHERE store_id = ? ORDER BY id DESC", (store_id,)).fetchall()
    conn.close()

    rows = "".join([f"""
    <tr class="border-b border-slate-800">
        <td class="p-3 font-bold text-white">{e['description']}</td>
        <td class="p-3 text-slate-300">{e['category']}</td>
        <td class="p-3 text-right font-bold text-rose-400">R$ {e['amount']:.2f}</td>
        <td class="p-3 text-center">
            <form action="/delete-item" method="POST" class="inline">
                <input type="hidden" name="item_type" value="expense">
                <input type="hidden" name="item_id" value="{e['id']}">
                <button type="submit" onclick="return confirm('Excluir despesa?');" class="text-xs bg-rose-950/60 hover:bg-rose-600 text-rose-300 px-2 py-1 rounded">🗑️ Rem</button>
            </form>
        </td>
    </tr>""" for e in exps])

    content = f"""
    <div class="space-y-6">
        <div class="flex items-center justify-between">
            <h2 class="text-2xl font-bold text-white">💸 Despesas ({len(exps)})</h2>
        </div>

        <div class="bg-slate-900 border border-slate-800 p-6 rounded-2xl space-y-4">
            <h3 class="text-sm font-bold text-rose-400 uppercase">+ Lançar Nova Despesa</h3>
            <form action="/expense-add" method="POST" class="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs font-bold">
                <input type="text" name="description" placeholder="Descrição (ex: Aluguel)" required class="bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                <input type="number" step="0.01" name="amount" placeholder="Valor (R$)" required class="bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                <input type="text" name="category" placeholder="Categoria (ex: Contas Fixas)" value="Geral" class="bg-slate-950 border border-slate-700 rounded-xl p-3 text-white">
                <div class="sm:col-span-3 text-right">
                    <button type="submit" class="px-6 py-2.5 bg-rose-600 hover:bg-rose-500 font-bold text-white rounded-xl">Salvar Despesa</button>
                </div>
            </form>
        </div>

        <div class="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
            <table class="w-full text-left text-xs sm:text-sm">
                <thead class="bg-slate-950 text-slate-400 border-b border-slate-800 font-bold">
                    <tr><th class="p-3">Descrição</th><th class="p-3">Categoria</th><th class="p-3 text-right">Valor</th><th class="p-3 text-center">Ação</th></tr>
                </thead>
                <tbody>{rows or '<tr><td colspan="4" class="p-4 text-center text-slate-500">Nenhuma despesa lançada.</td></tr>'}</tbody>
            </table>
        </div>
    </div>
    """
    return render_layout(request, content, "Despesas", "expenses", msg)

@app.post("/expense-add")
def expense_add(request: Request, description: str = Form(...), amount: float = Form(...), category: str = Form("Geral")):
    user = get_user(request)
    store_id = user.get("store_id", 1) if user else 1
    conn = get_db()
    conn.execute("INSERT INTO expenses (description, amount, category, date, store_id) VALUES (?, ?, ?, ?, ?)", (description, amount, category, datetime.now().strftime("%d/%m/%Y"), store_id))
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/expenses?msg={urllib.parse.quote('Despesa lançada!')}", status_code=303)

@app.get("/reports", response_class=HTMLResponse)
def reports(request: Request):
    user = get_user(request)
    if not user: return RedirectResponse(url="/login", status_code=303)
    store_id = user.get("store_id", 1)

    conn = get_db()
    total_val = conn.execute("SELECT COALESCE(SUM(total), 0) FROM sales WHERE store_id = ?", (store_id,)).fetchone()[0]
    total_exp = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE store_id = ?", (store_id,)).fetchone()[0]
    lucro_liq = total_val - total_exp
    conn.close()

    content = f"""
    <div class="space-y-6">
        <div class="flex items-center justify-between">
            <h2 class="text-2xl font-bold text-white">📈 Relatório Financeiro (DRE)</h2>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl">
                <span class="text-xs font-bold text-slate-400 uppercase">Faturamento Bruto</span>
                <div class="text-3xl font-bold text-emerald-400 mt-1">R$ {total_val:.2f}</div>
            </div>
            <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl">
                <span class="text-xs font-bold text-slate-400 uppercase">Total Despesas</span>
                <div class="text-3xl font-bold text-rose-400 mt-1">R$ {total_exp:.2f}</div>
            </div>
            <div class="bg-slate-900 border border-slate-800 p-5 rounded-2xl">
                <span class="text-xs font-bold text-slate-400 uppercase">Resultado Líquido</span>
                <div class="text-3xl font-bold {"text-emerald-400" if lucro_liq >= 0 else "text-rose-500"} mt-1">R$ {lucro_liq:.2f}</div>
            </div>
        </div>
    </div>
    """
    return render_layout(request, content, "Relatórios", "reports")

@app.get("/import-pdf", response_class=HTMLResponse)
def import_pdf(request: Request, msg: str = ""):
    content = f"""
    <div class="space-y-6">
        <div>
            <h2 class="text-2xl font-bold text-white">📥 Importação Inteligente de Dados</h2>
            <p class="text-xs text-slate-400 mt-1">Selecione no menu o tipo do cadastro para importar em lote.</p>
        </div>

        <div class="bg-slate-900 border border-slate-800 p-6 rounded-2xl space-y-4">
            <form action="/import-process" method="POST" class="space-y-4 text-xs font-bold">
                <div>
                    <label class="block text-slate-300 mb-1">Como você deseja cadastrar essas informações?</label>
                    <select name="import_type" class="w-full bg-slate-950 border border-slate-700 rounded-xl p-3 text-emerald-400 font-bold focus:outline-none">
                        <option value="PRODUTO">📦 Cadastrar como PRODUTOS (Código, Nome, Preço Venda, Quantidade)</option>
                        <option value="CLIENTE">👥 Cadastrar como CLIENTES (Nome, Telefone, Documento/CPF)</option>
                        <option value="DIVIDA">📄 Cadastrar como DÍVIDAS / FIADO (Nome Cliente, Valor, Vencimento)</option>
                    </select>
                </div>

                <div>
                    <label class="block text-slate-300 mb-1">Cole a lista aqui (uma por linha, separada por vírgula):</label>
                    <textarea name="import_data" rows="8" placeholder="Exemplo Produtos:
101, Camiseta Esportiva M, 49.90, 15
102, Bermuda Jeans 42, 89.00, 10

Exemplo Clientes:
João da Silva, 11999998888, 123.456.789-00

Exemplo Dívidas:
João da Silva, 150.00, 20/09/2026" class="w-full bg-slate-950 border border-slate-800 rounded-xl p-3 font-mono text-emerald-300 text-sm focus:outline-none"></textarea>
                </div>

                <button type="submit" class="px-6 py-3 bg-emerald-600 hover:bg-emerald-500 font-bold text-white text-sm rounded-xl shadow-lg">
                    ⚡ Cadastrar Informações no ERP
                </button>
            </form>
        </div>

        <div class="bg-slate-900 border border-slate-800 p-6 rounded-2xl space-y-4">
            <h3 class="text-xs font-bold text-rose-400 uppercase">🗑️ Gerenciador de Exclusão (Apagar Registros)</h3>
            <p class="text-xs text-slate-400">Importou algo errado por engano? Apague itens em lote por categoria com 1 clique:</p>

            <div class="flex flex-wrap gap-3">
                <form action="/clear-data" method="POST">
                    <input type="hidden" name="target" value="products">
                    <button type="submit" onclick="return confirm('Apagar TODOS os produtos?');" class="px-4 py-2 bg-rose-950/40 hover:bg-rose-900 border border-rose-800 text-rose-300 font-bold text-xs rounded-xl">
                        📦 Apagar Todos os Produtos
                    </button>
                </form>

                <form action="/clear-data" method="POST">
                    <input type="hidden" name="target" value="customers">
                    <button type="submit" onclick="return confirm('Apagar TODOS os clientes?');" class="px-4 py-2 bg-rose-950/40 hover:bg-rose-900 border border-rose-800 text-rose-300 font-bold text-xs rounded-xl">
                        👥 Apagar Todos os Clientes
                    </button>
                </form>

                <form action="/clear-data" method="POST">
                    <input type="hidden" name="target" value="receivables">
                    <button type="submit" onclick="return confirm('Apagar TODAS as dívidas?');" class="px-4 py-2 bg-rose-950/40 hover:bg-rose-900 border border-rose-800 text-rose-300 font-bold text-xs rounded-xl">
                        📄 Apagar Todas as Dívidas
                    </button>
                </form>

                <form action="/clear-data" method="POST">
                    <input type="hidden" name="target" value="all">
                    <button type="submit" onclick="return confirm('⚠️ Deseja ZERAR TODO o banco de dados?');" class="px-4 py-2 bg-rose-600 hover:bg-rose-500 text-white font-bold text-xs rounded-xl">
                        ⚠️ Zerar Tudo do ERP
                    </button>
                </form>
            </div>
        </div>
    </div>
    """
    return render_layout(request, content, "Importação", "import-pdf", msg)

@app.post("/import-process")
def import_process(request: Request, import_data: str = Form(""), import_type: str = Form("PRODUTO")):
    user = get_user(request)
    store_id = user.get("store_id", 1) if user else 1

    lines = [line.strip() for line in import_data.split("\n") if line.strip()]
    count = 0
    conn = get_db()

    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        if not parts or not parts[0]: continue

        if import_type == "CLIENTE":
            name = parts[0]
            phone = parts[1] if len(parts) >= 2 else ""
            doc = parts[2] if len(parts) >= 3 else ""
            conn.execute("INSERT INTO customers (name, document, phone, store_id) VALUES (?, ?, ?, ?)", (name, doc, phone, store_id))
            count += 1

        elif import_type == "DIVIDA":
            c_name = parts[0]
            try:
                debt_val = float(parts[1].replace("R$", "").replace(",", ".").strip()) if len(parts) >= 2 else 100.0
                due_date = parts[2] if len(parts) >= 3 else datetime.now().strftime("%d/%m/%Y")
            except ValueError:
                debt_val = 100.0
                due_date = datetime.now().strftime("%d/%m/%Y")

            conn.execute("INSERT INTO receivables (store_id, customer_name, total_amount, due_date, status) VALUES (?, ?, ?, ?, 'PENDENTE')", (store_id, c_name, debt_val, due_date))
            count += 1

        else: # PRODUTO
            code = parts[0]
            name = parts[1] if len(parts) >= 2 else f"Produto {code}"
            try:
                price = float(parts[2].replace("R$", "").replace(",", ".").strip()) if len(parts) >= 3 else 10.0
                qty = float(parts[3]) if len(parts) >= 4 else 10.0
            except ValueError:
                price, qty = 10.0, 10.0

            conn.execute("INSERT INTO products (code, name, category, sale_price, cost_price, stock_quantity, store_id) VALUES (?, ?, 'Geral', ?, 0, ?, ?)", (code, name, price, qty, store_id))
            count += 1

    conn.commit()
    conn.close()

    return RedirectResponse(url=f"/import-pdf?msg={urllib.parse.quote(f'✅ {count} registro(s) cadastrados como {import_type}!')}", status_code=303)

@app.post("/clear-data")
def clear_data(request: Request, target: str = Form(...)):
    user = get_user(request)
    store_id = user.get("store_id", 1) if user else 1

    conn = get_db()
    msg = ""
    if target == "products":
        conn.execute("DELETE FROM products WHERE store_id = ?", (store_id,))
        msg = "🗑️ Produtos apagados!"
    elif target == "customers":
        conn.execute("DELETE FROM customers WHERE store_id = ?", (store_id,))
        msg = "🗑️ Clientes apagados!"
    elif target == "receivables":
        conn.execute("DELETE FROM receivables WHERE store_id = ?", (store_id,))
        msg = "🗑️ Dívidas apagadas!"
    elif target == "all":
        conn.execute("DELETE FROM products WHERE store_id = ?", (store_id,))
        conn.execute("DELETE FROM customers WHERE store_id = ?", (store_id,))
        conn.execute("DELETE FROM receivables WHERE store_id = ?", (store_id,))
        msg = "⚠️ Banco de dados zerado!"

    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/import-pdf?msg={urllib.parse.quote(msg)}", status_code=303)

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
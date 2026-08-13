import sqlite3

def get_db():
    conn = sqlite3.connect("erp.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Tabela de Lojas
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        code TEXT,
        document TEXT,
        phone TEXT,
        password TEXT DEFAULT '',
        theme_color TEXT DEFAULT 'emerald',
        font_family TEXT DEFAULT 'sans',
        logo_text TEXT,
        slogan TEXT,
        bg_style TEXT DEFAULT 'slate'
    )
    """)

    # Tabela de Usuários com Tabela de Permissões
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_id INTEGER DEFAULT 1,
        username TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT DEFAULT 'VENDEDOR',
        can_give_discount INTEGER DEFAULT 1,
        can_cancel_sales INTEGER DEFAULT 0,
        can_manage_products INTEGER DEFAULT 0,
        can_view_reports INTEGER DEFAULT 0,
        FOREIGN KEY(store_id) REFERENCES stores(id)
    )
    """)

    # Tabela de Produtos
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_id INTEGER DEFAULT 1,
        code TEXT NOT NULL,
        name TEXT NOT NULL,
        category TEXT DEFAULT 'Geral',
        sale_price REAL NOT NULL,
        cost_price REAL DEFAULT 0,
        stock_quantity REAL DEFAULT 0,
        photo_url TEXT DEFAULT '',
        FOREIGN KEY(store_id) REFERENCES stores(id)
    )
    """)

    # Tabela de Clientes
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_id INTEGER DEFAULT 1,
        name TEXT NOT NULL,
        document TEXT,
        phone TEXT,
        credit_limit REAL DEFAULT 1000,
        blocked INTEGER DEFAULT 0,
        FOREIGN KEY(store_id) REFERENCES stores(id)
    )
    """)

    # Tabela de Vendas
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_id INTEGER DEFAULT 1,
        sale_number TEXT UNIQUE NOT NULL,
        created_at TEXT NOT NULL,
        seller_name TEXT NOT NULL,
        customer_name TEXT NOT NULL,
        subtotal REAL NOT NULL,
        discount REAL DEFAULT 0,
        total REAL NOT NULL,
        payment_method TEXT NOT NULL,
        FOREIGN KEY(store_id) REFERENCES stores(id)
    )
    """)

    # Itens da Venda
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sale_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        product_name TEXT NOT NULL,
        quantity REAL NOT NULL,
        unit_price REAL NOT NULL,
        subtotal REAL NOT NULL,
        FOREIGN KEY(sale_id) REFERENCES sales(id)
    )
    """)

    # Contas a Receber / Promissórias
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS receivables (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_id INTEGER DEFAULT 1,
        sale_id INTEGER,
        customer_name TEXT NOT NULL,
        total_amount REAL NOT NULL,
        due_date TEXT NOT NULL,
        status TEXT DEFAULT 'PENDENTE',
        FOREIGN KEY(store_id) REFERENCES stores(id)
    )
    """)

    # Migrações seguras de colunas caso o banco já exista
    migrations = [
        "ALTER TABLE stores ADD COLUMN password TEXT DEFAULT ''",
        "ALTER TABLE products ADD COLUMN photo_url TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN can_give_discount INTEGER DEFAULT 1",
        "ALTER TABLE users ADD COLUMN can_cancel_sales INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN can_manage_products INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN can_view_reports INTEGER DEFAULT 0",
    ]

    for mig in migrations:
        try:
            cursor.execute(mig)
        except sqlite3.OperationalError:
            pass

    # Criar Loja Matriz Inicial se não existir
    if cursor.execute("SELECT COUNT(*) FROM stores").fetchone()[0] == 0:
        cursor.execute("INSERT INTO stores (name, code, logo_text) VALUES ('Loja Matriz Centro', 'MATRIZ-01', 'MATRIZ CENTRO')")
    
    # Criar Usuário Admin se não existir
    if cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        cursor.execute("INSERT INTO users (store_id, username, name, password_hash, role) VALUES (1, 'admin', 'Administrador Principal', 'admin123', 'ADMIN')")

    conn.commit()
    conn.close()
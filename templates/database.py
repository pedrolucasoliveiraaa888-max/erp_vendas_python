import sqlite3

DB_NAME = "erp.db"

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Lojas / Filiais
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            document TEXT,
            phone TEXT,
            address TEXT
        )
    ''')

    # Usuários / Vendedores
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            store_id INTEGER DEFAULT 1
        )
    ''')

    # Produtos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER DEFAULT 1,
            code TEXT NOT NULL,
            barcode TEXT,
            name TEXT NOT NULL,
            category TEXT DEFAULT 'Geral',
            cost_price REAL DEFAULT 0,
            sale_price REAL NOT NULL,
            stock_quantity REAL DEFAULT 0,
            min_stock REAL DEFAULT 5,
            unit TEXT DEFAULT 'UN'
        )
    ''')

    # Clientes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER DEFAULT 1,
            name TEXT NOT NULL,
            document TEXT,
            phone TEXT,
            credit_limit REAL DEFAULT 1000,
            blocked INTEGER DEFAULT 0,
            block_reason TEXT
        )
    ''')

    # Fornecedores
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            document TEXT,
            phone TEXT,
            email TEXT
        )
    ''')

    # Caixa (Abertura/Fechamento)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cash_registers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER DEFAULT 1,
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            user_name TEXT NOT NULL,
            initial_balance REAL NOT NULL,
            status TEXT DEFAULT 'ABERTO'
        )
    ''')

    # Movimentações de Caixa
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cash_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cash_id INTEGER,
            type TEXT NOT NULL,
            amount REAL NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL
        )
    ''')

    # Vendas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER DEFAULT 1,
            sale_number TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            seller_name TEXT NOT NULL,
            customer_name TEXT,
            subtotal REAL NOT NULL,
            discount REAL DEFAULT 0,
            total REAL NOT NULL,
            payment_method TEXT NOT NULL,
            cash_register_id INTEGER
        )
    ''')

    # Itens da Venda
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sale_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER,
            product_id INTEGER,
            product_name TEXT,
            quantity REAL,
            unit_price REAL,
            subtotal REAL
        )
    ''')

    # Contas a Receber / Crediário
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS receivables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER DEFAULT 1,
            sale_id INTEGER,
            customer_name TEXT,
            total_amount REAL,
            due_date TEXT,
            status TEXT DEFAULT 'PENDENTE'
        )
    ''')

    # Despesas Operacionais
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER DEFAULT 1,
            description TEXT NOT NULL,
            category TEXT,
            amount REAL NOT NULL,
            date TEXT NOT NULL
        )
    ''')

    # Criar Loja Matriz Padrão se não existir
    cursor.execute("SELECT id FROM stores WHERE id = 1")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO stores (id, name, document, phone, address) VALUES (1, 'Loja Matriz Central', '00.000.000/0001-00', '(11) 99999-0000', 'Rua Principal, 100')")

    # Criar Usuário Admin Padrão
    cursor.execute("SELECT id FROM users WHERE username = 'admin'")
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO users (username, name, password_hash, role, store_id) VALUES (?, ?, ?, ?, ?)",
            ('admin', 'Administrador do Sistema', 'admin123', 'ADMIN', 1)
        )

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("✅ Banco de dados atualizado com suporte a Multi-Lojas!")
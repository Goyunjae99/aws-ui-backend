import sys

# Check psycopg2 module
try:
    import psycopg2
except ImportError:
    print("[ERROR] 'psycopg2' (or psycopg2-binary) module not found. Please run: pip install psycopg2-binary")
    sys.exit(1)

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# SSH Tunnel: localhost:15432 -> ... -> 192.168.40.15:5432
SQLALCHEMY_DATABASE_URL = "postgresql://admin:Soldesk1.@localhost:15432/cmp_db"

print(f"[INFO] Connecting to database via SSH tunnel: {SQLALCHEMY_DATABASE_URL}")

try:
    # Set connect timeout to 5 seconds
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"connect_timeout": 5})
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    # 1. Check DB Version
    version = db.execute(text("SELECT version();")).fetchone()
    print(f"[SUCCESS] Connection Successful!")
    print(f"   DB Version: {version[0]}")
    
    # 2. List Tables
    tables = db.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public';")).fetchall()
    table_list = [row[0] for row in tables]
    print(f"[INFO] Found Tables ({len(table_list)}): {', '.join(table_list)}")
    
    # 3. Check SystemSetting table
    if 'settings' in table_list:
        settings = db.execute(text("SELECT * FROM settings LIMIT 1;")).fetchone()
        if settings:
             print(f"[INFO] System Settings found: {settings}")
        else:
             print(f"[INFO] System Settings table is empty.")

    db.close()
except Exception as e:
    print(f"[ERROR] Connection Failed: {e}")
    print("\n[Tip] Make sure your SSH tunnel is running:")
    print("      ssh -L 15432:192.168.40.15:5432 root@172.16.6.77")

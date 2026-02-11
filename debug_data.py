from sqlalchemy import create_engine, Column, Integer, String, Boolean
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

# 1. DB 연결 (터널링)
SQLALCHEMY_DATABASE_URL = "postgresql://postgres:Soldesk1.@localhost:15432/cmp_db"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# 2. 모델 정의
class WorkloadTestPool(Base):
    __tablename__ = "workload_test_pool"
    id = Column(Integer, primary_key=True)
    vm_name = Column(String)
    ip_address = Column(String)
    is_used = Column(Boolean)    
    project_id = Column(Integer)
    occupy_user = Column(String)

# 3. 데이터 조회 테스트
db = SessionLocal()
try:
    print("--- [Debugging Start] ---")
    
    # 1. Check User 'admin'
    target_user = "admin"
    print(f"Target User: '{target_user}'")

    # 2. Query Specific
    my_vms = db.query(WorkloadTestPool).filter(
        WorkloadTestPool.occupy_user == target_user,
        WorkloadTestPool.is_used == True
    ).all()
    
    print(f"Query Result Count: {len(my_vms)}")
    
    if len(my_vms) == 0:
        print("\n❌ No VMs found for 'admin'. Checking ALL rows...")
        all_rows = db.query(WorkloadTestPool).all()
        for row in all_rows:
            print(f"  - ID: {row.id}, Name: {row.vm_name}, User: '{row.occupy_user}', Used: {row.is_used}")
    else:
        print("\n✅ Found VMs:")
        for vm in my_vms:
            print(f"  - [{vm.vm_name}] ({vm.ip_address})")

    print("--- [Debugging End] ---")

except Exception as e:
    print(f"ERROR: {e}")
finally:
    db.close()

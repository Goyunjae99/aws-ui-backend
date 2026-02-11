import subprocess
import os
import json
import random
import logging
import sys
import asyncio
import requests
from datetime import datetime
from typing import Dict, Any, Optional

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, JSON, DateTime, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from cryptography.fernet import Fernet

# ==========================================
# 0. 암호화 설정
# ==========================================

ENCRYPT_KEY = b'U7a9ulzi1i_3CPtT0DK6c76CGSHum7Bi2ujtqIzmwIc='
cipher_suite = Fernet(ENCRYPT_KEY)

def encrypt_password(password: str) -> str:
    return cipher_suite.encrypt(password.encode()).decode()

def decrypt_password(encrypted_password: str) -> str:
    return cipher_suite.decrypt(encrypted_password.encode()).decode()

# ==========================================
# 1. 데이터베이스 설정 (PostgreSQL + SSH Tunnel)
# ==========================================

logging.basicConfig(level=logging.INFO)
db_logger = logging.getLogger("uvicorn")
ans_logger = logging.getLogger("uvicorn.error")

# [변경] SSH 터널링을 통한 로컬 접속 (15432 포트)
SQLALCHEMY_DATABASE_URL = "postgresql://admin:Soldesk1.@localhost:15432/cmp_db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    pool_size=20, 
    max_overflow=10, 
    pool_pre_ping=True, 
    connect_args={"connect_timeout": 5}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ==========================================
# 2. DB 테이블 모델
# ==========================================
class ProjectHistory(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    service_name = Column(String, index=True)
    status = Column(String, default="PROVISIONED")
    assigned_ip = Column(String)
    template_type = Column(String)
    created_at = Column(DateTime, default=datetime.now)
    details = Column(JSON) 

class SystemSetting(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True, index=True)
    vcenter_ip = Column(String)
    esxi_ip = Column(String, default="192.168.0.200")
    maintenance_mode = Column(Boolean, default=False)
    max_vcpu = Column(Integer, default=100)
    max_memory = Column(Integer, default=256)
    system_notice = Column(String, default="") 
    admin_password = Column(String, default="1234")
    vcenter_user = Column(String)
    vcenter_password = Column(String)

# [변경] 실제 DB 스키마에 맞춘 WorkloadTestPool
class WorkloadTestPool(Base):
    __tablename__ = "workload_test_pool"
    id = Column(Integer, primary_key=True, index=True)
    vm_name = Column(String)     # WKLD-20
    ip_address = Column(String)  # 192.168.40.20
    is_used = Column(Boolean)    # t/f
    project_id = Column(Integer, nullable=True)
    occupy_user = Column(String, nullable=True)

Base.metadata.create_all(bind=engine)

# ==========================================
# 3. 데이터 모델
# ==========================================
class ProjectRequest(BaseModel):
    serviceName: str
    userName: str
    config: Dict[str, Any]
    targetInfra: Dict[str, Any]

class LoginRequest(BaseModel):
    user_id: str
    password: str

class SettingsUpdateRequest(BaseModel):
    vcenter_ip: Optional[str] = ""
    esxi_ip: Optional[str] = ""
    maintenance_mode: bool = False
    max_vcpu: int = 100
    max_memory: int = 256
    system_notice: Optional[str] = ""
    admin_password: str 

# ==========================================
# 4. 앱 및 Ansible 설정
# ==========================================
app = FastAPI()
app.mount("/templates", StaticFiles(directory="templates"), name="templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        if not db.query(SystemSetting).first():
            # 초기 설정이 없으면 생성
            pass 
        yield db
    except Exception as e:
        db_logger.error(f"🚨 [DB 연결 에러]: {str(e)}")
        raise
    finally:
        db.close()

# Ansible Task (로컬 시뮬레이션용으로 유지/수정 가능하나 핵심 로직은 아님)
def run_ansible_task(playbook_name: str, extra_vars: dict, project_id: int):
    # (생략: 실제 배포 로직이 필요하다면 기존 코드 복구 가능)
    pass

# ==========================================
# 5. API 엔드포인트
# ==========================================

@app.post("/api/login")
async def login(req: LoginRequest, db: Session = Depends(get_db)):
    setting = db.query(SystemSetting).first()
    real_pw = setting.admin_password if setting else "1234"
    if req.user_id == "admin" and req.password == real_pw:
        return {"status": "success", "message": "Login Approved"}
    raise HTTPException(status_code=401, detail="아이디/비번 불일치")

TEMPLATE_MAP = {
    "single": 1,        
    "standard": 3,      
    "enterprise": 5,    
    "k8s_small": 3,     
}

# [신규] Prometheus 데이터 조회 함수
def query_prometheus(query: str):
    # SSH 터널링된 로컬 포트 사용 (19090)
    PROMETHEUS_URL = "http://localhost:19090/api/v1/query"
    try:
        response = requests.get(PROMETHEUS_URL, params={'query': query}, timeout=2)
        if response.status_code == 200:
            data = response.json()
            if data['status'] == 'success':
                return data['data']['result']
    except Exception as e:
        print(f"⚠️ Prometheus Query Error: {e}")
    return []

@app.get("/api/monitoring/my-resources")
async def get_my_resources(db: Session = Depends(get_db)):
    """
    현재 로그인한 사용자(admin 고정)의 VM 목록을 DB에서 가져오고,
    각 VM의 실시간 CPU/Memory 사용량을 Prometheus에서 조회하여 반환
    """
    current_user = "admin"
    
    # 1. DB에서 사용자 자원 조회 (WorkloadTestPool 사용)
    my_vms = db.query(WorkloadTestPool).filter(
        WorkloadTestPool.occupy_user == current_user,
        WorkloadTestPool.is_used == True
    ).all()
    
    if not my_vms:
        return []

    # 2. Prometheus 쿼리 준비
    # (1) CPU Usage: (1 - idle) * 100
    # (2) Memory Usage: (1 - available/total) * 100
    # instance 라벨은 보통 "IP:9100" 형태라고 가정
    
    cpu_query = '100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)'
    mem_query = '(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100'

    cpu_data = query_prometheus(cpu_query)
    mem_data = query_prometheus(mem_query)

    # 3. 데이터 매핑 (Instance IP -> Metrics)
    metrics_map = {}
    
    def parse_metrics(results, metric_type):
        for res in results:
            # instance="192.168.40.20:9100" -> extract "192.168.40.20"
            instance = res['metric'].get('instance', '')
            ip = instance.split(':')[0]
            val = float(res['value'][1])
            
            if ip not in metrics_map: metrics_map[ip] = {}
            metrics_map[ip][metric_type] = round(val, 1)

    parse_metrics(cpu_data, 'cpu')
    parse_metrics(mem_data, 'memory')

    result = []
    for vm in my_vms:
        # 프로젝트 이름 조회
        project_name = "Unknown Project"
        if vm.project_id:
            proj = db.query(ProjectHistory).filter(ProjectHistory.id == vm.project_id).first()
            if proj: project_name = proj.service_name

        # 매핑된 메트릭 값 가져오기 (없으면 0)
        usage = metrics_map.get(vm.ip_address, {})
        
        result.append({
            "vm_name": vm.vm_name,
            "ip_address": vm.ip_address,
            "project_name": project_name,
            "cpu_usage": usage.get('cpu', 0),     # Prometheus 값 or 0
            "memory_usage": usage.get('memory', 0), # Prometheus 값 or 0
            "status": "Running"
        })

    return result

@app.post("/api/provision")
async def create_infrastructure(request: ProjectRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    # (간소화: 기존 로직과 유사하게 구현하되 WorkloadTestPool 사용)
    user_template = request.config.get('template', 'single')
    needed_count = TEMPLATE_MAP.get(user_template, 1)

    # 가용 자원 조회
    vms = db.query(WorkloadTestPool).filter(WorkloadTestPool.is_used == False).order_by(WorkloadTestPool.id.asc()).limit(needed_count).all()
    if len(vms) < needed_count:
        return {"status": "error", "message": "가용 자원 부족"}

    assigned_ips = [vm.ip_address for vm in vms]
    
    # 프로젝트 생성
    new_project = ProjectHistory(
        service_name=request.serviceName,
        status="CONFIGURING",
        assigned_ip=", ".join(assigned_ips),
        template_type=user_template,
        details={"config": request.config, "infra": request.targetInfra}
    )
    db.add(new_project)
    db.commit()
    db.refresh(new_project)

    # 자원 할당
    for vm in vms:
        vm.is_used = True
        vm.project_id = new_project.id
        vm.occupy_user = "admin" # request.userName 대신 고정
    db.commit()

    return {"status": "success", "message": f"프로젝트 #{new_project.id} 생성 완료"}

@app.delete("/api/provision/{project_id}")
async def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = db.query(ProjectHistory).filter(ProjectHistory.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Not Found")
    
    # 자원 반납 (WorkloadTestPool)
    # assigned_ip 문자열 파싱보다는 project_id로 찾는게 정확함
    vms = db.query(WorkloadTestPool).filter(WorkloadTestPool.project_id == project_id).all()
    for vm in vms:
        vm.is_used = False
        vm.project_id = None
        vm.occupy_user = None
    
    db.delete(project)
    db.commit()
    return {"status": "success", "message": "삭제 완료"}

# ... 기타 기존 페이지 라우트 ...
@app.get("/")
async def read_index(): return FileResponse('templates/omakase_final.html')

@app.get("/history")
async def read_history(): return FileResponse('templates/history.html')

@app.get("/monitoring")
async def read_monitoring(): return FileResponse('templates/monitoring.html')

@app.get("/api/api/history") # (오타 방지용)
@app.get("/api/history")
async def get_history(db: Session = Depends(get_db)):
    return db.query(ProjectHistory).order_by(ProjectHistory.id.desc()).all()

@app.get("/api/public/settings")
async def get_public_settings(db: Session = Depends(get_db)):
    s = db.query(SystemSetting).first()
    # 없을 경우 대비
    return {"system_notice": s.system_notice if s else "", "maintenance_mode": s.maintenance_mode if s else False}

# 서버 실행
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
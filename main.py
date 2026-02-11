import subprocess
import os
import json
import random
import logging
import sys
import asyncio
import requests
from datetime import datetime
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, JSON, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from cryptography.fernet import Fernet

from config import CONFIG
from services.runners.mock_runner import run_mock_provisioning_task

# ==========================================
# 0. 암호화 설정
# ==========================================
# HARDCODED CONFIG START -- 나중에 실제 키/암호화 설정으로 교체
ENCRYPT_KEY = b'U7a9ulzi1i_3CPtT0DK6c76CGSHum7Bi2ujtqIzmwIc='
cipher_suite = Fernet(ENCRYPT_KEY)
# HARDCODED CONFIG END

def encrypt_password(password: str) -> str:
    return cipher_suite.encrypt(password.encode()).decode()

def decrypt_password(encrypted_password: str) -> str:
    return cipher_suite.decrypt(encrypted_password.encode()).decode()

# ==========================================
# 1. 데이터베이스 설정 (PostgreSQL + SSH Tunnel)
# 연결 실패 시 SQLite 로컬 파일로 자동 폴백하여 앱이 계속 실행되게 함.
# ==========================================

logging.basicConfig(level=logging.INFO)
db_logger = logging.getLogger("uvicorn")
ans_logger = logging.getLogger("uvicorn.error")

# HARDCODED CONFIG START -- TODO: 나중에 실제 DB 정보(vCenter/AWS/운영 DB)로 교체
SQLALCHEMY_DATABASE_URL = "postgresql://admin:Soldesk1.@localhost:15432/cmp_db"
SQLITE_FALLBACK_URL = "sqlite:///./app.db"
# HARDCODED CONFIG END

Base = declarative_base()


def _create_engine_with_fallback():
    """
    우선 PostgreSQL(하드코딩 URL)로 연결 시도.
    실패 시(예: Connection refused) 호스트/포트와 사유를 로그에 남기고
    SQLite(app.db)로 임시 전환하여 앱이 죽지 않게 함.
    """
    primary = SQLALCHEMY_DATABASE_URL
    try:
        engine = create_engine(
            primary,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 5},
        )
        with engine.connect() as _:
            pass
        return engine
    except Exception as e:
        host, port = "localhost", "15432"
        try:
            parsed = urlparse(primary)
            if parsed.hostname:
                host = parsed.hostname
            if parsed.port is not None:
                port = str(parsed.port)
            else:
                # postgresql://user:pass@host:15432/db 형태에서 host:port 추출
                netloc = getattr(parsed, "netloc", "") or ""
                if "@" in netloc:
                    _, hostport = netloc.rsplit("@", 1)
                    if ":" in hostport:
                        host, port = hostport.rsplit(":", 1)
                        port = str(port)
        except Exception:
            pass
        db_logger.warning(
            "DB 연결 실패 (host=%s, port=%s, 사유: %s) → SQLite로 임시 전환",
            host, port, e,
        )
        print("DB 연결 실패 → SQLite로 임시 전환")  # 콘솔에 명확히 출력
        # SQLite는 pool_size/connect_timeout 등 불필요; 단순 생성
        return create_engine(SQLITE_FALLBACK_URL, connect_args={"check_same_thread": False})


engine = _create_engine_with_fallback()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

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

# 하드코딩 설정은 config.CONFIG 에서 참조 (기존 코드 호환용 별칭)
TEMPLATE_MAP = CONFIG["template_map"]

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

# [신규] Prometheus 데이터 조회 함수
# HARDCODED CONFIG START -- TODO: 나중에 실제 Prometheus URL로 교체
def query_prometheus(query: str):
    PROMETHEUS_URL = "http://localhost:19090/api/v1/query"  # SSH 터널링된 로컬 포트 가정
    try:
        response = requests.get(PROMETHEUS_URL, params={'query': query}, timeout=2)
        if response.status_code == 200:
            data = response.json()
            if data['status'] == 'success':
                return data['data']['result']
    except Exception as e:
        print(f"⚠️ Prometheus Query Error: {e}")
    return []
# HARDCODED CONFIG END


def _my_resources_from_mock_projects(db: Session) -> List[Dict[str, Any]]:
    """ProjectHistory.details.resources 가 있는 프로젝트를 my-resources 형식으로 변환 (DB 기반)."""
    rows = []
    projects = db.query(ProjectHistory).filter(ProjectHistory.details.isnot(None)).all()
    for proj in projects:
        details = proj.details if isinstance(proj.details, dict) else {}
        res = details.get("resources")
        status_detail = details.get("status", proj.status or "")
        if not res:
            continue
        project_name = proj.service_name or "Unknown Project"
        # alb_ip
        alb = res.get("alb_ip")
        if alb:
            rows.append({
                "vm_name": "ALB",
                "ip_address": alb,
                "project_name": project_name,
                "cpu_usage": 0,
                "memory_usage": 0,
                "status": "Running" if status_detail == CONFIG["status_completed"] else status_detail,
            })
        # web_url (주소처럼 표시)
        web = res.get("web_url")
        if web:
            rows.append({
                "vm_name": "Web",
                "ip_address": web,
                "project_name": project_name,
                "cpu_usage": 0,
                "memory_usage": 0,
                "status": "Running" if status_detail == CONFIG["status_completed"] else status_detail,
            })
        # db_vip
        dbv = res.get("db_vip")
        if dbv:
            rows.append({
                "vm_name": "DB",
                "ip_address": dbv,
                "project_name": project_name,
                "cpu_usage": 0,
                "memory_usage": 0,
                "status": "Running" if status_detail == CONFIG["status_completed"] else status_detail,
            })
        # ssh_targets
        for i, t in enumerate(res.get("ssh_targets") or []):
            host = t.get("host") if isinstance(t, dict) else str(t)
            if host:
                rows.append({
                    "vm_name": f"SSH-{i + 1}",
                    "ip_address": host,
                    "project_name": project_name,
                    "cpu_usage": 0,
                    "memory_usage": 0,
                    "status": "Running" if status_detail == CONFIG["status_completed"] else status_detail,
                })
    return rows


@app.get("/api/monitoring/my-resources")
async def get_my_resources(db: Session = Depends(get_db)):
    """
    현재 로그인한 사용자(admin 고정)의 VM 목록을 DB에서 가져오고,
    Mock 프로젝트의 details.resources 도 함께 반환. Prometheus 연동은 선택.
    """
    current_user = "admin"
    result: List[Dict[str, Any]] = []

    # 1. WorkloadTestPool 기반 자원 (기존 동작 유지)
    my_vms = db.query(WorkloadTestPool).filter(
        WorkloadTestPool.occupy_user == current_user,
        WorkloadTestPool.is_used == True
    ).all()

    cpu_query = '100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)'
    mem_query = '(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100'
    cpu_data = query_prometheus(cpu_query)
    mem_data = query_prometheus(mem_query)
    metrics_map = {}

    def parse_metrics(results, metric_type):
        for res in results:
            instance = res['metric'].get('instance', '')
            ip = instance.split(':')[0]
            val = float(res['value'][1])
            if ip not in metrics_map:
                metrics_map[ip] = {}
            metrics_map[ip][metric_type] = round(val, 1)

    parse_metrics(cpu_data, 'cpu')
    parse_metrics(mem_data, 'memory')

    for vm in my_vms:
        project_name = "Unknown Project"
        if vm.project_id:
            proj = db.query(ProjectHistory).filter(ProjectHistory.id == vm.project_id).first()
            if proj:
                project_name = proj.service_name
        usage = metrics_map.get(vm.ip_address, {})
        result.append({
            "vm_name": vm.vm_name,
            "ip_address": vm.ip_address,
            "project_name": project_name,
            "cpu_usage": usage.get('cpu', 0),
            "memory_usage": usage.get('memory', 0),
            "status": "Running"
        })

    # 2. Mock 프로젝트의 details.resources 기반 항목 추가 (DB 기반)
    result.extend(_my_resources_from_mock_projects(db))
    return result


@app.post("/api/provision")
async def create_infrastructure(request: ProjectRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Mock Runner: DB에 PENDING 프로젝트 생성 후 즉시 응답, 백그라운드에서 Mock provisioning 실행.
    """
    user_template = request.config.get('template', 'single')
    input_payload = {
        "serviceName": request.serviceName,
        "userName": request.userName,
        "config": request.config,
        "targetInfra": request.targetInfra,
    }
    details = {
        "input": input_payload,
        "config": request.config,
        "infra": request.targetInfra,
        "status": CONFIG["status_pending"],
        "logs": [],
        "resources": None,
        "error": None,
    }
    new_project = ProjectHistory(
        service_name=request.serviceName,
        status=CONFIG["status_pending"],
        assigned_ip="",
        template_type=user_template,
        details=details,
    )
    db.add(new_project)
    db.commit()
    db.refresh(new_project)

    background_tasks.add_task(run_mock_provisioning_task, new_project.id, input_payload)
    return {"status": "success", "message": f"프로젝트 #{new_project.id} 생성 시작", "project_id": new_project.id}


@app.delete("/api/provision/{project_id}")
async def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = db.query(ProjectHistory).filter(ProjectHistory.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Not Found")
    
    vms = db.query(WorkloadTestPool).filter(WorkloadTestPool.project_id == project_id).all()
    for vm in vms:
        vm.is_used = False
        vm.project_id = None
        vm.occupy_user = None
    
    db.delete(project)
    db.commit()
    return {"status": "success", "message": "삭제 완료"}

# ... 기타 기존 페이지 라우트 ...
# 템플릿 경로: main.py 기준으로 고정 (작업 디렉터리 영향 없음)
_TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

@app.get("/")
async def read_index():
    """첫 화면: 인프라 선택 페이지 (select_infra)"""
    return FileResponse(os.path.join(_TEMPLATES_DIR, "select_infra(1).html"))

@app.get("/configure")
async def read_configure():
    """AWS 선택 후: Configure & Provision 페이지 (omakase_final)"""
    return FileResponse(os.path.join(_TEMPLATES_DIR, "omakase_final.html"))

@app.get("/history")
async def read_history(): return FileResponse(os.path.join(_TEMPLATES_DIR, "history.html"))

@app.get("/monitoring")
async def read_monitoring(): return FileResponse(os.path.join(_TEMPLATES_DIR, "monitoring.html"))

@app.get("/main_ui")
async def read_main_ui():
    """Expert Mode / Operations: main_ui.html"""
    return FileResponse(os.path.join(_TEMPLATES_DIR, "main_ui.html"))

@app.get("/api/api/history") # (오타 방지용)
@app.get("/api/history")
async def get_history(db: Session = Depends(get_db)):
    return db.query(ProjectHistory).order_by(ProjectHistory.id.desc()).all()

@app.get("/api/public/settings")
async def get_public_settings(db: Session = Depends(get_db)):
    s = db.query(SystemSetting).first()
    return {"system_notice": s.system_notice if s else "", "maintenance_mode": s.maintenance_mode if s else False}

# 서버 실행
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

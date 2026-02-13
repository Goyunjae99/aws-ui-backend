# H-CMP 백엔드 DB 구성

**대상:** public_version_(2) FastAPI 백엔드  
**ORM:** SQLAlchemy 2.x (declarative_base from sqlalchemy.orm)

---

## 1. 연결 설정

### 1.1 URL

| 구분 | URL | 비고 |
|------|-----|------|
| **기본(우선)** | `postgresql://admin:Soldesk1.@localhost:15432/cmp_db` | SSH 터널 등으로 로컬 15432 포트 접속 가정 |
| **폴백** | `sqlite:///./app.db` | PostgreSQL 연결 실패 시 자동 전환, 로컬 파일 |

- 설정 위치: `main.py` 내 `SQLALCHEMY_DATABASE_URL`, `SQLITE_FALLBACK_URL` (HARDCODED CONFIG 구간).
- 폴백 시 콘솔에 `"DB 연결 실패 → SQLite로 임시 전환"` 출력.

### 1.2 엔진·세션

- **엔진:** `_create_engine_with_fallback()` 로 생성. PostgreSQL 성공 시 `pool_size=20`, `max_overflow=10`, `pool_pre_ping=True`, `connect_timeout=5` 적용. 폴백 시 SQLite 단순 생성(`check_same_thread=False`).
- **세션:** `SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)`.
- **테이블 생성:** 앱 기동 시 `Base.metadata.create_all(bind=engine)` 로 정의된 테이블 자동 생성.

---

## 2. 테이블 목록

| 테이블명(실제) | ORM 클래스 | 용도 |
|----------------|------------|------|
| **projects** | `ProjectHistory` | 프로비저닝 이력, 상태·로그·리소스(details JSON) |
| **settings** | `SystemSetting` | 시스템 설정(vCenter, ESXi, 관리자 비밀번호, 공지 등) |
| **workload_test_pool** | `WorkloadTestPool` | 테스트용 VM 풀(이름, IP, 사용 여부, 연결된 project_id) |

---

## 3. 테이블 스키마

### 3.1 projects (ProjectHistory)

| 컬럼 | 타입 | 비고 |
|------|------|------|
| id | Integer, PK, index | 자동 증가 |
| service_name | String, index | 서비스(프로젝트) 이름 |
| status | String | 기본값 `"PROVISIONED"`. Mock Runner 사용 시 PENDING → RUNNING → COMPLETED / FAILED |
| assigned_ip | String | 할당된 IP 요약(쉼표 구분 등). Mock 완료 시 details.resources 기준으로 채움 |
| template_type | String | 템플릿 타입(single, standard, enterprise 등) |
| created_at | DateTime | 생성 시각, 기본값 `datetime.now` |
| details | JSON | 프로비저닝 입력·상태·로그·리소스·에러. 스키마는 아래 4절 참고 |

**사용처:** POST /api/provision(생성), GET /api/history(목록), GET /api/monitoring/my-resources(Mock 리소스 병합), DELETE /api/provision/{id}(삭제). Mock Runner가 `details`와 `status`/`assigned_ip` 갱신.

### 3.2 settings (SystemSetting)

| 컬럼 | 타입 | 비고 |
|------|------|------|
| id | Integer, PK, index | |
| vcenter_ip | String | vCenter IP |
| esxi_ip | String | 기본값 `"192.168.0.200"` |
| maintenance_mode | Boolean | 기본값 False |
| max_vcpu | Integer | 기본값 100 |
| max_memory | Integer | 기본값 256 |
| system_notice | String | 기본값 `""` (공지 문구) |
| admin_password | String | 기본값 `"1234"` (로그인 검증용) |
| vcenter_user | String | |
| vcenter_password | String | |

**사용처:** POST /api/login(admin_password 비교), GET /api/public/settings(system_notice, maintenance_mode 반환). 단일 행 가정.

### 3.3 workload_test_pool (WorkloadTestPool)

| 컬럼 | 타입 | 비고 |
|------|------|------|
| id | Integer, PK, index | |
| vm_name | String | 예: WKLD-20 |
| ip_address | String | 예: 192.168.40.20 |
| is_used | Boolean | 사용 여부 |
| project_id | Integer, nullable | 연결된 projects.id. 미사용 시 NULL |
| occupy_user | String, nullable | 사용자(예: admin). 미사용 시 NULL |

**사용처:** 실제 VM 풀 기반 프로비저닝 시 자원 할당/반납. GET /api/monitoring/my-resources 에서 `occupy_user == current_user` 인 행 조회. Mock 전용 프로젝트는 이 테이블을 쓰지 않음.

---

## 4. projects.details (JSON) 스키마

Mock Runner·프로비저닝 상태 저장용. `services/provisioner.update_provision_status()` 에서 갱신.

```json
{
  "input": {
    "serviceName": "...",
    "userName": "...",
    "config": { "template": "...", ... },
    "targetInfra": { ... }
  },
  "config": { ... },
  "infra": { ... },
  "status": "PENDING | RUNNING | COMPLETED | FAILED",
  "logs": [ "Allocating IP...", "Creating Web tier...", ... ],
  "resources": {
    "alb_ip": "...",
    "web_url": "...",
    "db_vip": "...",
    "ssh_targets": [ { "host": "...", "port": 22, "user": "..." }, ... ]
  },
  "error": { "message": "..." }
}
```

- **input:** API 요청 원본.
- **config / infra:** UI 설정·인프라 정보(히스토리/프론트 호환용).
- **status:** 프로비저닝 상태. DB 컬럼 `projects.status` 와 동기화.
- **logs:** 단계별 로그 배열.
- **resources:** Mock 완료 시 채워지는 가짜 리소스. GET /api/monitoring/my-resources 에서 ALB/Web/DB/SSH 항목으로 변환.
- **error:** 실패 시에만 설정.

---

## 5. 테이블 간 관계

- **projects ↔ workload_test_pool:** `workload_test_pool.project_id` → `projects.id` (선택적). 한 프로젝트가 여러 VM 행을 가질 수 있음. Mock 전용 프로젝트는 project_id 미사용.
- **settings:** 단일 행으로 사용, 다른 테이블과 FK 없음.

---

## 6. 세션 사용

- **요청 단위:** `get_db()` (Depends) 로 `SessionLocal()` 생성 후 yield, finally 에서 `db.close()`.
- **백그라운드(Mock Runner):** 태스크 내부에서 `SessionLocal()` 로 새 세션 생성, 작업 후 `db.close()`.
- **읽기/쓰기:** 위 세션으로 `db.query(ProjectHistory)` 등 조회·추가·수정·삭제 후 `db.commit()` / `db.refresh()` 사용.

---

## 7. 요약

| 항목 | 내용 |
|------|------|
| DB | PostgreSQL(cmp_db) 우선, 실패 시 SQLite(app.db) 폴백 |
| 테이블 | projects, settings, workload_test_pool |
| 프로비저닝 이력 | projects + details(JSON). Mock은 details에 status/logs/resources 저장 |
| 설정 | settings 단일 행. 로그인·공지·점검 모드 등 |
| VM 풀 | workload_test_pool. 실제 VM 할당 시 사용, Mock과 병행 가능 |

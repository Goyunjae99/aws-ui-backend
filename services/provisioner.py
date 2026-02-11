# -*- coding: utf-8 -*-
"""
Provisioning 상태 전이 및 details(JSON) 저장.
DB 세션은 호출 측에서 주입 (백그라운드 태스크에서는 새 세션 생성).
"""
from typing import Dict, Any, Optional, List

from config import CONFIG


def _get_details_copy(project) -> dict:
    """프로젝트 details 딕셔너리 복사 (없으면 기본 구조)."""
    d = project.details
    if isinstance(d, dict):
        return dict(d)
    return {
        "input": {},
        "status": CONFIG["status_pending"],
        "logs": [],
        "resources": None,
        "error": None,
        "config": {},
        "infra": {},
    }


def update_provision_status(
    db,
    project_id: int,
    status: str,
    project_model,  # ProjectHistory 등 ORM 클래스 (순환 import 방지)
    logs_append: Optional[List[str]] = None,
    resources: Optional[Dict[str, Any]] = None,
    error: Optional[Dict[str, str]] = None,
    assigned_ip: Optional[str] = None,
):
    """
    프로젝트의 provisioning 상태를 갱신하고 details에 반영.
    - status: PENDING / RUNNING / COMPLETED / FAILED
    - logs_append: 추가할 로그 라인 리스트 (기존 logs에 append)
    - resources: 최종 리소스 JSON (alb_ip, web_url, db_vip, ssh_targets 등)
    - error: 실패 시 { "message": "..." }
    - assigned_ip: ProjectHistory.assigned_ip 에 쓸 값 (리소스 요약용)
    """
    project = db.query(project_model).filter(project_model.id == project_id).first()
    if not project:
        return

    details = _get_details_copy(project)
    details["status"] = status
    if logs_append is not None:
        details["logs"] = details.get("logs") or []
        details["logs"].extend(logs_append)
    if resources is not None:
        details["resources"] = resources
    if error is not None:
        details["error"] = error

    project.details = details
    project.status = status
    if assigned_ip is not None:
        project.assigned_ip = assigned_ip
    db.commit()


def get_project_details(db, project_id: int, project_model) -> Optional[Dict[str, Any]]:
    """프로젝트의 details JSON 반환."""
    project = db.query(project_model).filter(project_model.id == project_id).first()
    if not project:
        return None
    d = project.details
    if isinstance(d, dict):
        return d
    return None

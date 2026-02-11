# -*- coding: utf-8 -*-
"""
Mock Provisioning Runner.
실제 Ansible/배포 대신 단계별 로그와 가짜 리소스를 생성.
나중에 Real Runner로 교체할 수 있도록 인터페이스 유지.
"""
import asyncio
import random
from typing import Dict, Any

from config import CONFIG
from services.provisioner import update_provision_status


def _make_mock_resources(service_name: str, project_id: int, template: str) -> Dict[str, Any]:
    """하드코딩 설정으로 가짜 리소스 dict 생성."""
    base = CONFIG["mock_ip_base"]
    second = CONFIG["mock_ip_second"]
    slug = (service_name or "svc").replace(" ", "-").lower()[:20]
    web_url = CONFIG["mock_web_url_template"].format(service_slug=slug)
    db_vip = f"db-{slug}{CONFIG['mock_db_vip_suffix']}"

    count = CONFIG["template_map"].get(template, 1)
    ips = [f"{base}.{second}.{random.randint(1, 254)}" for _ in range(max(1, count))]
    alb_ip = ips[0] if ips else f"{base}.{second}.1"
    ssh_targets = [{"host": ip, "port": 22, "user": "ubuntu"} for ip in ips]

    return {
        "alb_ip": alb_ip,
        "web_url": web_url,
        "db_vip": db_vip,
        "ssh_targets": ssh_targets,
    }


async def run_mock_provisioning_async(project_id: int, input_spec: Dict[str, Any]) -> None:
    """
    비동기 Mock provisioning 실행.
    DB 갱신을 위해 실행 시점에 main에서 SessionLocal, ProjectHistory 를 import.
    """
    from main import SessionLocal, ProjectHistory

    db = SessionLocal()
    try:
        status_run = CONFIG["status_running"]
        status_ok = CONFIG["status_completed"]
        status_fail = CONFIG["status_failed"]
        steps = CONFIG["mock_log_steps"]
        delay = CONFIG["mock_step_delay_seconds"]

        update_provision_status(
            db, project_id, status_run,
            project_model=ProjectHistory,
            logs_append=[steps[0]],
            assigned_ip="",
        )
        await asyncio.sleep(delay)

        for i, msg in enumerate(steps[1:], 1):
            update_provision_status(
                db, project_id, status_run,
                project_model=ProjectHistory,
                logs_append=[msg],
            )
            await asyncio.sleep(delay)

        service_name = (input_spec.get("serviceName") or "Service")
        config = input_spec.get("config") or {}
        template = config.get("template", "single")
        resources = _make_mock_resources(service_name, project_id, template)
        assigned_ip = resources.get("alb_ip", "")

        update_provision_status(
            db, project_id, status_ok,
            project_model=ProjectHistory,
            logs_append=[],
            resources=resources,
            assigned_ip=assigned_ip,
        )
    except Exception as e:
        update_provision_status(
            db, project_id, CONFIG["status_failed"],
            project_model=ProjectHistory,
            logs_append=[f"Error: {str(e)}"],
            error={"message": str(e)},
            assigned_ip="",
        )
    finally:
        db.close()


def run_mock_provisioning_task(project_id: int, input_spec: Dict[str, Any]) -> None:
    """
    동기 래퍼: FastAPI BackgroundTasks 에서 호출.
    asyncio.run 으로 비동기 Mock 실행.
    """
    asyncio.run(run_mock_provisioning_async(project_id, input_spec))

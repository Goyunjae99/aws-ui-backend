# -*- coding: utf-8 -*-
"""
하드코딩 기반 Mock Runner 설정.
실제 vCenter/Ansible 연동 전까지 사용하며, 나중에 Real Runner로 교체 시 참고용.
"""

# 템플릿별 VM(또는 노드) 수
TEMPLATE_MAP = {
    "single": 1,
    "standard": 3,
    "enterprise": 5,
    "k8s_small": 3,
}

# Mock IP 대역 (가짜 할당용)
MOCK_IP_BASE = "10.99"
MOCK_IP_SECOND_OCTET = "0"

# Mock URL 규칙 (서비스명 기반)
MOCK_WEB_URL_TEMPLATE = "https://{service_slug}.mock.example.com"
MOCK_DB_VIP_SUFFIX = ".vip.mock.local"

# Mock 단계별 로그 메시지
MOCK_LOG_STEPS = [
    "Allocating IP...",
    "Creating Web tier...",
    "Creating DB tier...",
    "Configuring ALB...",
    "Registering SSH targets...",
    "Completed",
]

# Mock 각 단계 대기 시간(초) - 시뮬레이션
MOCK_STEP_DELAY_SECONDS = 0.8

# 상태값 (기존 UI 배지와 맞춤: COMPLETED=녹색, FAILED=빨강)
STATUS_PENDING = "PENDING"
STATUS_RUNNING = "RUNNING"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"

CONFIG = {
    "template_map": TEMPLATE_MAP,
    "mock_ip_base": MOCK_IP_BASE,
    "mock_ip_second": MOCK_IP_SECOND_OCTET,
    "mock_web_url_template": MOCK_WEB_URL_TEMPLATE,
    "mock_db_vip_suffix": MOCK_DB_VIP_SUFFIX,
    "mock_log_steps": MOCK_LOG_STEPS,
    "mock_step_delay_seconds": MOCK_STEP_DELAY_SECONDS,
    "status_pending": STATUS_PENDING,
    "status_running": STATUS_RUNNING,
    "status_completed": STATUS_COMPLETED,
    "status_failed": STATUS_FAILED,
}

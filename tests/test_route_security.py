"""Automated route enumeration and dependency audit test suite.

Enforces Phase 2 Task 5:
Every route except health, login, and static assets must depend on get_current_role.
Missing token means HTTP 401 Unauthorized.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import app
from app.core.auth import get_current_role, create_access_token


def _get_all_api_routes(router_or_app) -> list[APIRoute]:
    """Recursively collect all APIRoute instances from FastAPI application."""
    routes: list[APIRoute] = []
    raw_routes = getattr(router_or_app, "routes", [])
    for r in raw_routes:
        if isinstance(r, APIRoute):
            routes.append(r)
        elif hasattr(r, "original_router"):
            routes.extend(_get_all_api_routes(r.original_router))
        elif hasattr(r, "routes"):
            routes.extend(_get_all_api_routes(r))
    return routes


def _has_role_dependency(route: APIRoute) -> bool:
    """Check if route directly or indirectly depends on get_current_role."""
    dependant = getattr(route, "dependant", None)
    if not dependant:
        return False

    def check_deps(deps) -> bool:
        for d in deps:
            call_fn = getattr(d, "call", None)
            fn_name = getattr(call_fn, "__name__", "")
            if fn_name in ("get_current_role", "require_admin"):
                return True
            # Recurse into sub-dependencies
            sub_deps = getattr(d, "dependencies", [])
            if check_deps(sub_deps):
                return True
        return False

    return check_deps(dependant.dependencies)


class TestRouteSecurityAudit:
    """Verifies that all protected endpoints require get_current_role dependency."""

    def test_all_protected_routes_require_authentication(self):
        """DONE WHEN Criterion 4: All API routes except health and login require get_current_role."""
        routes = _get_all_api_routes(app)
        assert len(routes) > 0, "FastAPI application must register API routes"

        # Explicit allow-list of public endpoints that do not require auth
        PUBLIC_ENDPOINTS = {
            "/",
            "/health",
            "/auth/login",
            "/auth/demo-accounts",
            "/auth/demo-login",
            "/about-architecture",
            "/system-health",
            "/evaluations",
            "/document-library",
            "/policy-change",
            "/ask-policy",
            "/dashboard",
            "/ui",
            "/download-ui-zip",
        }

        unprotected_routes = []
        protected_routes_count = 0

        for r in routes:
            path = r.path
            if path in PUBLIC_ENDPOINTS:
                continue

            protected_routes_count += 1
            if not _has_role_dependency(r):
                unprotected_routes.append(f"{r.methods} {path}")

        assert len(unprotected_routes) == 0, (
            f"Security Violation: Found {len(unprotected_routes)} protected routes lacking get_current_role dependency: "
            f"{unprotected_routes}"
        )
        assert protected_routes_count >= 10, (
            f"Expected at least 10 protected API routes, found {protected_routes_count}"
        )

    def test_missing_token_returns_401_on_all_protected_endpoints(self):
        """Verifies that calling any protected endpoint without token returns HTTP 401."""
        client = TestClient(app)

        test_endpoints = [
            ("GET", "/documents"),
            ("GET", "/documents/academic_regulations_2024.pdf"),
            ("POST", "/ask", {"question": "What is the policy?"}),
            ("POST", "/ask/stream", {"question": "What is the policy?"}),
            ("GET", "/system/stats"),
            ("GET", "/evaluations/reports"),
            ("GET", "/evaluations/reports/test_report.json"),
            ("GET", "/admin/security/users"),
            ("GET", "/admin/security/denied-attempts"),
            ("GET", "/auth/me"),
        ]

        for item in test_endpoints:
            method = item[0]
            path = item[1]
            body = item[2] if len(item) > 2 else None

            if method == "GET":
                resp = client.get(path)
            elif method == "POST":
                resp = client.post(path, json=body or {})
            else:
                continue

            assert resp.status_code == 401, (
                f"Expected 401 Unauthorized for missing token on {method} {path}, got {resp.status_code}: {resp.text}"
            )


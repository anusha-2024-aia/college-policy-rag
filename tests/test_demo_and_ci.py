"""Phase 9 Automated Tests: Interactive Showcase, CI/CD Pipeline & Docker Hardening."""

from pathlib import Path
import pytest
import yaml

from scripts.demo_walkthrough import (
    main as demo_main,
    run_scenario_1_version_conflict,
    run_scenario_2_partial_amendment,
    run_scenario_3_unchanged_clause_precision,
    run_scenario_4_rbac_adversarial_defense,
    run_scenario_5_authorized_admin_access,
    run_scenario_6_temporal_time_travel,
)
from app.core.database import get_test_session
from app.services.retrieval import HybridRetrievalService
from app.services.embedding import MockEmbeddingService
from app.services.reranker import MockRerankerService
from app.services.llm import MockLLMService
from app.services.qa import QAService


@pytest.fixture(scope="module")
def qa_service_fixture():
    db = get_test_session()
    embedding_svc = MockEmbeddingService(dimension=1536)
    reranker_svc = MockRerankerService()
    llm_svc = MockLLMService()
    retrieval_svc = HybridRetrievalService(
        db_session=db,
        embedding_service=embedding_svc,
        reranker_service=reranker_svc,
    )
    return QAService(retrieval_service=retrieval_svc, llm_service=llm_svc)


class TestInteractiveDemo:
    """Verifies all 6 live showcase scenarios in scripts/demo_walkthrough.py."""

    def test_demo_main_execution(self):
        """Verifies full demo_main() execution completes without unhandled errors."""
        demo_main()

    def test_scenario_1_version_conflict(self, qa_service_fixture):
        """Verifies attendance conflict generates ChangeCards."""
        run_scenario_1_version_conflict(qa_service_fixture)

    def test_scenario_2_partial_amendment(self, qa_service_fixture):
        """Verifies partial amendment cross-references base policy."""
        run_scenario_2_partial_amendment(qa_service_fixture)

    def test_scenario_3_unchanged_clause(self, qa_service_fixture):
        """Verifies unchanged clause emits zero false conflicts."""
        run_scenario_3_unchanged_clause_precision(qa_service_fixture)

    def test_scenario_4_rbac_adversarial_defense(self, qa_service_fixture):
        """Verifies 4-layer defense blocks adversarial prompt injection with zero leaks."""
        run_scenario_4_rbac_adversarial_defense(qa_service_fixture)

    def test_scenario_5_authorized_admin(self, qa_service_fixture):
        """Verifies admin role authorized to retrieve confidential salary policy."""
        run_scenario_5_authorized_admin_access(qa_service_fixture)

    def test_scenario_6_temporal_time_travel(self, qa_service_fixture):
        """Verifies temporal historical query activates valid_from/to time travel."""
        run_scenario_6_temporal_time_travel(qa_service_fixture)


class TestCIWorkflowConfiguration:
    """Verifies .github/workflows/ci.yml structure, jobs, and safety invariants."""

    def test_ci_file_exists_and_is_valid_yaml(self):
        ci_path = Path(".github/workflows/ci.yml")
        assert ci_path.exists(), "CI workflow file .github/workflows/ci.yml must exist"

        content = ci_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(content)
        assert isinstance(parsed, dict)

        # Trigger checks
        triggers = parsed.get("on", parsed.get(True))  # YAML interprets 'on' as boolean True if unquoted
        assert triggers is not None
        if isinstance(triggers, dict):
            assert "push" in triggers or "pull_request" in triggers

        # Required jobs
        jobs = parsed.get("jobs", {})
        assert "test" in jobs, "CI must contain a 'test' job"
        assert "security-audit" in jobs, "CI must contain a 'security-audit' job"
        assert "evaluation-benchmark" in jobs, "CI must contain an 'evaluation-benchmark' job"
        assert "docker-build" in jobs, "CI must contain a 'docker-build' job"

    def test_security_audit_job_runs_phase6(self):
        ci_path = Path(".github/workflows/ci.yml")
        content = ci_path.read_text(encoding="utf-8")
        assert "run_phase6_tests" in content
        assert "pytest tests/test_phase6_suite.py" in content


class TestProductionDockerPackaging:
    """Verifies Dockerfile.backend, Dockerfile.frontend, and docker-compose.yml configuration."""

    def test_backend_dockerfile_invariants(self):
        df_path = Path("Dockerfile.backend")
        assert df_path.exists()
        content = df_path.read_text(encoding="utf-8")

        assert "FROM python:3.11-slim" in content
        assert "COPY app /app/app" in content
        assert "COPY ui /app/ui" in content
        assert "COPY data /app/data" in content
        assert "COPY eval /app/eval" in content
        assert "EXPOSE 8000" in content
        assert "HEALTHCHECK" in content
        assert "uvicorn app.main:app" in content

    def test_frontend_dockerfile_invariants(self):
        df_path = Path("Dockerfile.frontend")
        assert df_path.exists()
        content = df_path.read_text(encoding="utf-8")

        assert "FROM python:3.11-slim" in content
        assert "COPY ui /app/ui" in content
        assert "EXPOSE 8501" in content
        assert "HEALTHCHECK" in content
        assert "streamlit run ui/app.py" in content

    def test_docker_compose_security_bindings(self):
        dc_path = Path("docker-compose.yml")
        assert dc_path.exists()
        content = dc_path.read_text(encoding="utf-8")
        compose = yaml.safe_load(content)

        services = compose.get("services", {})
        assert "pgvector" in services
        assert "backend" in services
        assert "frontend" in services

        # Security invariant: NO service may bind to 0.0.0.0 on the host
        for s_name, s_cfg in services.items():
            ports = s_cfg.get("ports", [])
            for p in ports:
                port_str = str(p)
                assert not port_str.startswith("0.0.0.0:"), f"Service {s_name} violates security by binding to 0.0.0.0"
                if ":" in port_str:
                    host_part = port_str.split(":")[0]
                    assert host_part in ("127.0.0.1", "localhost"), f"Port binding {port_str} must bind to 127.0.0.1"


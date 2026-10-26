"""Main API router combining all endpoint modules."""

from fastapi import APIRouter
from app.api.routes import health, ask, documents, evaluations, system, auth, admin_security

api_router = APIRouter()

# Include authentication routes
api_router.include_router(auth.router)

# Include admin security dashboard routes
api_router.include_router(admin_security.router)

# Include health routes at root
api_router.include_router(health.router)

# Include question answering routes
api_router.include_router(ask.router)

# Include document catalog and inspection routes
api_router.include_router(documents.router)

# Include evaluation benchmarks routes
api_router.include_router(evaluations.router)

# Include system statistics routes
api_router.include_router(system.router)

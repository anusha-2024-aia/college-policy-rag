"""Main API router combining all endpoint modules."""

from fastapi import APIRouter
from app.api.routes import health, ask

api_router = APIRouter()

# Include health routes at root
api_router.include_router(health.router)

# Include question answering routes
api_router.include_router(ask.router)

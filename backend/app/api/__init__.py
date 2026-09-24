"""INDRA API — router exports."""
from app.api.dashboard import router as dashboard_router
from app.api.events import router as events_router
from app.api.reports import router as reports_router
from app.api.feed import router as feed_router
from app.api.geo import router as geo_router
from app.api.auth import router as auth_router
from app.api.teams import router as teams_router
from app.api.profile import router as profile_router
from app.api.alerts import router as alerts_router
from app.api.audit import router as audit_router
from app.api.meta import router as meta_router
from app.api.stations import router as stations_router

__all__ = [
    "dashboard_router",
    "events_router",
    "reports_router",
    "feed_router",
    "geo_router",
    "auth_router",
    "teams_router",
    "profile_router",
    "alerts_router",
    "audit_router",
    "meta_router",
    "stations_router",
]


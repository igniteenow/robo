"""Cron dashboard routes (extracted verbatim from web_server.py).

Handler bodies are byte-identical.  The ``*_sync`` workers, profile resolution
and the threadpool wrapper (``_run_cron_dashboard_io``) still live in
web_server — reached via the late-binding seam in :mod:`robo_cli.web_deps`
so ``monkeypatch.setattr(web_server, ...)`` keeps working (several cron tests
rely on exactly that).
"""

import asyncio  # noqa: F401 — used by handlers
import functools  # noqa: F401
import logging
from typing import Optional  # noqa: F401

from fastapi import APIRouter, HTTPException, Request  # noqa: F401
from fastapi.responses import JSONResponse  # noqa: F401

from robo_cli.web_deps import late
from robo_cli.web_models import (
    CronJobCreate,
    CronJobUpdate,
    AutomationBlueprintInstantiate,
)

# Same logger the handlers used before extraction (identical logger object).
_log = logging.getLogger("robo_cli.web_server")

router = APIRouter()

# Late-bound web_server helpers (resolved at call time; cycle-safe,
# monkeypatch-transparent — includes config readers so existing
# ``monkeypatch.setattr(web_server, "load_config", ...)`` idioms behave
# identically for these routes).
_run_cron_dashboard_io = late("_run_cron_dashboard_io")
_list_cron_jobs_sync = late("_list_cron_jobs_sync")
_get_cron_job_sync = late("_get_cron_job_sync")
_list_cron_job_runs_sync = late("_list_cron_job_runs_sync")
_create_cron_job_sync = late("_create_cron_job_sync")
_update_cron_job_sync = late("_update_cron_job_sync")
_pause_cron_job_sync = late("_pause_cron_job_sync")
_resume_cron_job_sync = late("_resume_cron_job_sync")
_trigger_cron_job_sync = late("_trigger_cron_job_sync")
_delete_cron_job_sync = late("_delete_cron_job_sync")
_call_cron_for_profile = late("_call_cron_for_profile")
load_config = late("load_config")
cfg_get = late("cfg_get")


@router.get("/api/cron/jobs")
async def list_cron_jobs(profile: str = "all"):
    return await _run_cron_dashboard_io(_list_cron_jobs_sync, profile)


@router.get("/api/cron/jobs/{job_id}")
async def get_cron_job(job_id: str, profile: Optional[str] = None):
    return await _run_cron_dashboard_io(_get_cron_job_sync, job_id, profile)


@router.get("/api/cron/jobs/{job_id}/runs")
async def list_cron_job_runs(job_id: str, profile: Optional[str] = None, limit: int = 20):
    return await _run_cron_dashboard_io(_list_cron_job_runs_sync, job_id, profile, limit)


@router.post("/api/cron/jobs")
async def create_cron_job(body: CronJobCreate, profile: Optional[str] = None):
    return await _run_cron_dashboard_io(_create_cron_job_sync, body, profile)


@router.get("/api/cron/delivery-targets")
async def get_cron_delivery_targets():
    """Delivery targets the cron dropdown should offer.

    Always includes the implicit ``local`` option. Beyond that, the list is
    derived dynamically from the configured gateway platforms via
    ``cron.scheduler.cron_delivery_targets()`` — no hardcoded platform list. A
    configured platform that hasn't set its cron home channel is still returned
    with ``home_target_set: false`` so the UI can surface it as "configure a
    home channel first" rather than hiding it.
    """
    targets = [
        {
            "id": "local",
            "name": "Local (save only)",
            "home_target_set": True,
            "home_env_var": None,
        }
    ]
    try:
        from cron.scheduler import cron_delivery_targets

        targets.extend(cron_delivery_targets())
    except Exception:
        _log.exception("GET /api/cron/delivery-targets failed")
    return {"targets": targets}


@router.put("/api/cron/jobs/{job_id}")
async def update_cron_job(job_id: str, body: CronJobUpdate, profile: Optional[str] = None):
    return await _run_cron_dashboard_io(_update_cron_job_sync, job_id, body, profile)


@router.post("/api/cron/jobs/{job_id}/pause")
async def pause_cron_job(job_id: str, profile: Optional[str] = None):
    return await _run_cron_dashboard_io(_pause_cron_job_sync, job_id, profile)


@router.post("/api/cron/jobs/{job_id}/resume")
async def resume_cron_job(job_id: str, profile: Optional[str] = None):
    return await _run_cron_dashboard_io(_resume_cron_job_sync, job_id, profile)


@router.post("/api/cron/jobs/{job_id}/trigger")
async def trigger_cron_job(job_id: str, profile: Optional[str] = None):
    return await _run_cron_dashboard_io(_trigger_cron_job_sync, job_id, profile)


@router.delete("/api/cron/jobs/{job_id}")
async def delete_cron_job(job_id: str, profile: Optional[str] = None):
    return await _run_cron_dashboard_io(_delete_cron_job_sync, job_id, profile)


@router.get("/api/cron/blueprints")
async def list_cron_blueprints():
    """Return the blueprint catalog as form schemas for the dashboard gallery.

    The ``deliver`` slot's options are rewritten from the user's actually
    configured gateway platforms (plus the universal origin/local/all), so the
    form never offers a platform that isn't connected.
    """
    try:
        from cron.blueprint_catalog import CATALOG, blueprint_catalog_entry

        deliver_options = None
        try:
            from cron.scheduler import cron_delivery_targets

            platforms = [t["id"] for t in cron_delivery_targets() if t.get("id")]
            deliver_options = ["origin", "local", *platforms]
        except Exception:
            _log.debug("cron_delivery_targets unavailable; using static deliver options", exc_info=True)

        entries = []
        for r in CATALOG:
            entry = blueprint_catalog_entry(r)
            if deliver_options:
                for f in entry.get("fields", []):
                    if f.get("name") == "deliver":
                        f["options"] = deliver_options
            entries.append(entry)
        return {"blueprints": entries}
    except Exception as e:
        _log.exception("GET /api/cron/blueprints failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/cron/blueprints/instantiate")
async def instantiate_blueprint(body: AutomationBlueprintInstantiate, profile: str = "default"):
    """Fill a blueprint's slots and create the cron job (form-submit path)."""
    try:
        from cron.blueprint_catalog import fill_blueprint, get_blueprint, BlueprintFillError

        blueprint = get_blueprint(body.blueprint)
        if blueprint is None:
            raise HTTPException(status_code=404, detail=f"Unknown blueprint: {body.blueprint}")
        try:
            spec = fill_blueprint(blueprint, body.values)
        except BlueprintFillError as exc:
            # Field-level validation error — 422 so the form can show it inline.
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        # Blueprint-created jobs deliver to the dashboard's configured target by
        # default; the form's deliver slot overrides via spec["deliver"].
        spec.pop("origin", None)
        # create_job does per-profile file I/O — keep it off the event loop
        # like the sibling cron endpoints (partial avoids **spec keys ever
        # colliding with the wrapper's own parameters).
        _create = functools.partial(_call_cron_for_profile, profile, "create_job", **spec)
        return await _run_cron_dashboard_io(_create)
    except HTTPException:
        raise
    except Exception as e:
        _log.exception("POST /api/cron/blueprints/instantiate failed")
        raise HTTPException(status_code=400, detail=str(e))

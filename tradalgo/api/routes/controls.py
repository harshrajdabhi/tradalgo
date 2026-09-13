import glob

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import Engine

from tradalgo.api.deps import get_engine, settings_for_request
from tradalgo.api.models import KillSwitchRequest
from tradalgo.config import Settings
from tradalgo.dashboard import controls

router = APIRouter(prefix="/api", tags=["controls"])


def _settings(request: Request) -> Settings:
    return settings_for_request(request)


def _engine(settings: Settings = Depends(_settings)) -> Engine:
    return get_engine(settings)


def _config_path(request: Request) -> str:
    return request.app.state.config_path


@router.post("/alerts/{alert_id}/resend")
def resend_alert(alert_id: int, engine: Engine = Depends(_engine)):
    ok = controls.resend_alert(engine, alert_id)
    if not ok:
        raise HTTPException(status_code=409, detail="alert is not in 'failed' status")
    return {"ok": True}


@router.post("/kill-switch")
def set_kill_switch(body: KillSwitchRequest, settings: Settings = Depends(_settings)):
    controls.set_kill_switch(settings.paths.data_dir, body.on)
    return {"on": body.on}


@router.get("/settings")
def get_config(path: str = Depends(_config_path)):
    with open(path) as f:
        return yaml.safe_load(f)


@router.put("/settings")
def put_config(new_config: dict, path: str = Depends(_config_path)):
    try:
        controls.save_settings(path, new_config)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    backups = sorted(glob.glob(f"{path}.bak-*"))
    return {"ok": True, "backup": backups[-1] if backups else None}

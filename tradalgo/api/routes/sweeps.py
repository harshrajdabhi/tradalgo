import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from tradalgo.api.deps import settings_for_request
from tradalgo.config import Settings

router = APIRouter(prefix="/api/sweeps", tags=["sweeps"])

_NAME_RE = re.compile(r"^sweep-[0-9-]+$")


def _settings(request: Request) -> Settings:
    return settings_for_request(request)


def _reports_dir(settings: Settings) -> Path:
    return Path(settings.paths.data_dir) / "reports"


@router.get("")
def list_sweeps(settings: Settings = Depends(_settings)):
    out = []
    reports_dir = _reports_dir(settings)
    if reports_dir.exists():
        for path in sorted(reports_dir.glob("sweep-*.json")):
            try:
                payload = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            out.append({
                "name": path.stem, "generated_at": payload.get("generated_at"),
                "verdict": payload.get("verdict"), "total_combinations": payload.get("total_combinations"),
            })
    return out


@router.get("/{name}")
def get_sweep(name: str, settings: Settings = Depends(_settings)):
    if not _NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="invalid sweep name")
    reports_dir = _reports_dir(settings)
    path = (reports_dir / f"{name}.json").resolve()
    if reports_dir.resolve() not in path.parents or not path.exists():
        raise HTTPException(status_code=404, detail=f"sweep {name!r} not found")
    payload = json.loads(path.read_text())
    recommended_path = reports_dir / f"{name}-recommended.yaml"
    if recommended_path.exists():
        payload["recommended_yaml"] = recommended_path.read_text()
    return payload

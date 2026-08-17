"""FastAPI application for the compliance modeling web."""
from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Optional

import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import orchestrator as orch

ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT / "frontend"
UPLOAD_DIR = orch.UPLOAD_DIR
JOBS_DIR = orch.JOBS_DIR
MODEL_OUTPUT_DIR = orch.MODEL_OUTPUT_DIR

app = FastAPI(title="合规建模智能网页", version="1.0.0")

app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")
app.mount("/artifacts", StaticFiles(directory=str(MODEL_OUTPUT_DIR)), name="artifacts")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def access_password_middleware(request: Request, call_next):
    password = os.environ.get("ACCESS_PASSWORD", "")
    if password and request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith("/api"):
        supplied = request.headers.get("x-access-password", "")
        if supplied != password:
            return JSONResponse(status_code=401, content={"detail": "访问密码错误或缺失"})
    return await call_next(request)


class FeedbackBody(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = ""
    rebuild: bool = False


class QueryBody(BaseModel):
    query: str


class LearnBody(BaseModel):
    name: str
    goal: str = ""


class InstallBody(BaseModel):
    name: str
    approved: bool = False
    client_id: str = ""


class DeleteBody(BaseModel):
    skill_id: str
    approved: bool = False
    client_id: str = ""


class ApproveBody(BaseModel):
    client_id: str


class ApplyDeleteBody(BaseModel):
    skill_ids: list[str]
    approved: bool = False


def _save_upload(file: UploadFile, upload_id: str) -> Path:
    original = orch.sanitize_filename(file.filename or "input.csv")
    suffix = Path(original).suffix.lower()
    if suffix not in {".csv", ".xlsx", ".xls", ".json"}:
        raise HTTPException(status_code=400, detail="仅支持 CSV、Excel 或 JSON 文件")
    upload_dir = UPLOAD_DIR / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    input_path = upload_dir / f"input{suffix}"
    content = file.file.read() if hasattr(file, "file") else None
    if content is None:
        content = b""
    # Limit to 50 MB as a pragmatic local-app safeguard.
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件过大，最大支持 50MB")
    input_path.write_bytes(content)
    orch.save_json(upload_dir / "meta.json", {
        "upload_id": upload_id,
        "original_filename": original,
        "created_at": orch.now_iso(),
    })
    return input_path


@app.get("/")
def index():
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        return {"message": "frontend/index.html 尚未创建"}
    return FileResponse(str(index_file))


@app.get("/api/health")
def health():
    return {"ok": True, "time": orch.now_local()}


@app.post("/api/data/preview")
async def preview(file: UploadFile = File(...)):
    upload_id = uuid.uuid4().hex[:16]
    input_path = _save_upload(file, upload_id)
    try:
        preview = orch.preview_data(input_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"无法解析文件: {exc}") from exc
    return {"upload_id": upload_id, "input_path": str(input_path), **preview}


@app.post("/api/jobs")
async def create_job(
    file: Optional[UploadFile] = File(None),
    upload_id: Optional[str] = Form(None),
    target: str = Form(...),
    models: str = Form(""),
    cardinality_threshold: int = Form(20),
    skip_tuning: bool = Form(False),
    epochs: int = Form(100),
    stability_runs: int = Form(50),
    goal: str = Form(""),
):
    if file is not None:
        upload_id = uuid.uuid4().hex[:16]
        input_path = _save_upload(file, upload_id)
    elif upload_id:
        candidate = UPLOAD_DIR / upload_id
        matches = list(candidate.glob("input.*")) if candidate.exists() else []
        if not matches:
            raise HTTPException(status_code=404, detail="upload_id 不存在")
        input_path = matches[0]
    else:
        raise HTTPException(status_code=400, detail="必须上传文件或提供 upload_id")

    try:
        info = orch.preview_data(input_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"无法解析文件: {exc}") from exc
    if target not in info["columns"]:
        raise HTTPException(status_code=400, detail=f"目标列不存在: {target}")
    if not (1 <= epochs <= 5000):
        raise HTTPException(status_code=400, detail="epochs 必须在 1 到 5000 之间")
    if stability_runs not in {30, 50, 100}:
        raise HTTPException(status_code=400, detail="稳定性重复次数只能选择 30、50 或 100")

    job_id = uuid.uuid4().hex[:12]
    model_list = [m.strip() for m in models.split(",") if m.strip()] or orch.DEFAULT_MODELS[:]
    params = {
        "cardinality_threshold": cardinality_threshold,
        "models": model_list,
        "skip_tuning": skip_tuning,
        "epochs": epochs,
        "stability_runs": stability_runs,
    }
    job = orch.write_job(
        job_id,
        status="pending",
        upload_id=upload_id,
        input_path=str(input_path),
        target=target,
        goal=goal,
        params=params,
        iteration_count=0,
        logs=[],
        feedback=[],
        skills_used=[],
        created_at=orch.now_iso(),
    )
    orch.start_job(job_id)
    return {"job_id": job_id, "status": "pending", "preview": info}


@app.get("/api/jobs/latest")
def jobs_latest():
    job = orch.latest_job()
    if not job:
        return {"job": None}
    return {"job": job}


@app.get("/api/jobs")
def jobs():
    items = []
    for job in orch.list_jobs():
        items.append({
            "job_id": job.get("job_id"),
            "status": job.get("status"),
            "target": job.get("target"),
            "iteration_count": job.get("iteration_count"),
            "created_at": job.get("created_at"),
            "finished_at": job.get("finished_at"),
            "best_model": (job.get("result") or {}).get("metrics", {}).get("best_model", {}).get("name") if job.get("result") else None,
        })
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return {"jobs": items}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = orch.read_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    result = orch.delete_job(job_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "删除失败"))
    return result


@app.post("/api/jobs/{job_id}/feedback")
def feedback(job_id: str, body: FeedbackBody):
    job = orch.read_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    feedback_list = job.setdefault("feedback", [])
    feedback_list.append({
        "rating": body.rating,
        "comment": body.comment,
        "rebuild": body.rebuild,
        "timestamp": orch.now_iso(),
    })
    orch.write_job(job_id, feedback=feedback_list)
    rebuild_job_id = None
    terminal = job.get("status") in {"pass", "accepted", "blocked"}
    if terminal and (body.rating <= 3 or body.rebuild):
        new_job_id = uuid.uuid4().hex[:12]
        orch.write_job(
            new_job_id,
            status="pending",
            upload_id=job.get("upload_id"),
            input_path=job.get("input_path"),
            target=job.get("target"),
            goal=job.get("goal") or f"基于任务 {job_id} 的反馈重建",
            params=job.get("params") or {},
            iteration_count=0,
            logs=[],
            feedback=[],
            skills_used=[],
            parent_job_id=job_id,
            created_at=orch.now_iso(),
        )
        orch.start_job(new_job_id)
        rebuild_job_id = new_job_id
    return {"ok": True, "feedback": feedback_list[-1], "rebuild_job_id": rebuild_job_id}


@app.get("/api/skills")
def skills():
    return {"skills": orch.list_skills()}


@app.get("/api/skills/recommendations")
def skills_recommendations(refresh: bool = False):
    return orch.get_skill_recommendations(refresh=refresh)


@app.post("/api/skills/recommendations/{rec_id}/approve")
def skills_recommendation_approve(rec_id: str, body: ApproveBody):
    return orch.approve_skill_recommendation(rec_id, body.client_id)


@app.post("/api/skills/find")
def skills_find(body: QueryBody):
    return orch.find_skills(body.query)


@app.post("/api/skills/learn")
def skills_learn(body: LearnBody):
    try:
        return orch.create_skill_draft(body.name, body.goal)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/skills/install")
def skills_install(body: InstallBody):
    return orch.install_skill(body.name, body.approved)


@app.post("/api/skills/delete")
def skills_delete(body: DeleteBody):
    return orch.delete_skill(body.skill_id, body.approved)


@app.get("/api/reviews/latest")
def reviews_latest():
    return orch.latest_review()


@app.post("/api/reviews/run")
def reviews_run():
    return orch.run_skill_review(dry_run=True)


@app.post("/api/reviews/apply-delete")
def reviews_apply_delete(body: ApplyDeleteBody):
    return orch.apply_skill_review_delete(body.skill_ids, body.approved)


@app.get("/api/compliance/latest")
def compliance_latest():
    return orch.latest_compliance()


@app.get("/api/compliance/status")
def compliance_status():
    return orch.get_compliance_status()


@app.post("/api/compliance/run")
def compliance_run():
    return orch.run_compliance_with_risk()


@app.get("/api/patterns/recommend")
def patterns_recommend(goal: str = "", target_variable: str = "", dataset: str = "", sample_size: int = 0):
    import os
    import sys
    env = os.environ.copy()
    env["MODEL_PATTERN_DATA_DIR"] = str(orch.PATTERN_DIR)
    args = [sys.executable, str(orch.PATTERN_RECOMMEND)]
    if goal:
        args += ["--goal", goal]
    if target_variable:
        args += ["--target-variable", target_variable]
    if dataset:
        args += ["--dataset", dataset]
    if sample_size:
        args += ["--sample-size", str(sample_size)]
    res = orch.run_command(args, timeout=180, env=env)
    try:
        payload = json.loads(res["stdout"]) if res["returncode"] == 0 else {}
    except Exception:
        payload = {"stdout": res["stdout"], "stderr": res["stderr"]}
    return {"returncode": res["returncode"], "payload": payload, "stderr": res["stderr"]}


scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def scheduled_review():
    orch.run_compliance_with_risk()
    orch.run_skill_review(dry_run=True)


@app.on_event("startup")
def startup_event():
    # Ensure all runtime directories exist.
    for d in (UPLOAD_DIR, JOBS_DIR, MODEL_OUTPUT_DIR, orch.PATTERN_DIR, orch.SKILL_DRAFT_DIR, orch.SKILL_CANDIDATE_DIR, orch.SKILL_REVIEW_DIR, orch.COMPLIANCE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    if not scheduler.running:
        scheduler.add_job(scheduled_review, CronTrigger(hour=21, minute=0, timezone="Asia/Shanghai"), id="daily_skill_review", replace_existing=True)
        scheduler.add_job(scheduled_review, IntervalTrigger(minutes=5, timezone="Asia/Shanghai"), id="compliance_5min", replace_existing=True)
        scheduler.start()


if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)

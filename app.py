"""
app.py — FastAPI wrapper cho tuyen_sinh_AI.py
Hỗ trợ text + ảnh đính kèm (base64), serve index.html từ static/
"""

import os
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from tuyen_sinh_AI import TuVanTuyenSinh

# ── Session store ─────────────────────────────────────────────────────────────
sessions: dict[str, TuVanTuyenSinh] = {}

def lay_bot(session_id: str) -> TuVanTuyenSinh:
    if session_id not in sessions:
        sessions[session_id] = TuVanTuyenSinh()
    return sessions[session_id]

@asynccontextmanager
async def lifespan(app: FastAPI):
    lay_bot("default")
    yield

app = FastAPI(title="AI Tư Vấn Tuyển Sinh", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Schemas ───────────────────────────────────────────────────────────────────

class CauHoiRequest(BaseModel):
    session_id: str = "default"
    cau_hoi: str = ""
    image_base64: Optional[str] = None   # base64 ảnh (không có data: prefix)
    image_type: Optional[str] = "image/jpeg"

class TraLoiResponse(BaseModel):
    session_id: str
    tra_loi: str

class ResetRequest(BaseModel):
    session_id: str = "default"

# ── Serve frontend ────────────────────────────────────────────────────────────
_BASE = os.path.dirname(os.path.abspath(__file__))

# Serve file tĩnh (ảnh, JS, CSS...) nếu có thư mục static/
_static_dir = os.path.join(_BASE, "static")
if os.path.exists(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

@app.api_route("/", methods=["GET", "HEAD"])
def serve_frontend():
    """Trả về index.html — ưu tiên static/index.html, fallback index.html cùng thư mục."""
    for path in [
        os.path.join(_BASE, "static", "index.html"),
        os.path.join(_BASE, "index.html"),
    ]:
        if os.path.exists(path):
            return FileResponse(path, media_type="text/html")
    return {"status": "ok", "message": "AI Tư Vấn Tuyển Sinh 🎓 — đặt index.html vào thư mục static/"}

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.api_route("/health", methods=["GET", "HEAD"])
def health_check():
    return {"status": "ok"}

@app.post("/hoi", response_model=TraLoiResponse)
def hoi(body: CauHoiRequest):
    """Nhận câu hỏi (+ ảnh tuỳ chọn) và trả về câu trả lời."""
    if not body.cau_hoi.strip() and not body.image_base64:
        raise HTTPException(status_code=400, detail="Câu hỏi không được để trống.")
    try:
        bot = lay_bot(body.session_id)
        if body.image_base64:
            tra_loi = bot.hoi_voi_anh(
                cau_hoi=body.cau_hoi or "(Xem ảnh đính kèm)",
                image_base64=body.image_base64,
                image_type=body.image_type or "image/jpeg",
            )
        else:
            tra_loi = bot.hoi(body.cau_hoi)
        return TraLoiResponse(session_id=body.session_id, tra_loi=tra_loi)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/reset")
def reset(body: ResetRequest):
    if body.session_id in sessions:
        sessions[body.session_id].reset_lich_su()
    return {"status": "ok", "message": f"Đã reset session '{body.session_id}'"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)

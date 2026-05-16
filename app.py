"""
app.py — FastAPI + Supabase auth + tuyen_sinh_AI
"""

import os
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from tuyen_sinh_AI import TuVanTuyenSinh

try:
    from supabase import create_client, Client as SupabaseClient
    _SUPABASE_URL  = os.getenv("SUPABASE_URL", "")
    _SUPABASE_ANON = os.getenv("SUPABASE_ANON_KEY", "")
    sb: SupabaseClient = create_client(_SUPABASE_URL, _SUPABASE_ANON) if _SUPABASE_URL else None
except ImportError:
    sb = None

sessions: dict[str, TuVanTuyenSinh] = {}

def lay_bot(session_id: str) -> TuVanTuyenSinh:
    if session_id not in sessions:
        sessions[session_id] = TuVanTuyenSinh()
    return sessions[session_id]

@asynccontextmanager
async def lifespan(app: FastAPI):
    lay_bot("default")
    yield

app = FastAPI(title="Magerok AI", version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_user_id(authorization: Optional[str] = Header(default=None)) -> str:
    if not sb or not _SUPABASE_URL:
        return "anonymous"
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Chưa đăng nhập.")
    token = authorization.split(" ", 1)[1]
    try:
        user = sb.auth.get_user(token)
        return user.user.id
    except Exception:
        raise HTTPException(status_code=401, detail="Token không hợp lệ hoặc đã hết hạn.")

class CauHoiRequest(BaseModel):
    cau_hoi: str = ""
    image_base64: Optional[str] = None
    image_type: Optional[str] = "image/jpeg"

class TraLoiResponse(BaseModel):
    tra_loi: str
    user_id: str

_BASE   = os.path.dirname(os.path.abspath(__file__))
_static = os.path.join(_BASE, "static")
if os.path.exists(_static):
    app.mount("/static", StaticFiles(directory=_static), name="static")

# ── Routes HTML — tất cả serve từ domain root (không /static/) ───────────────

@app.api_route("/", methods=["GET", "HEAD"])
def root():
    """Trang login — Supabase redirect về đây sau OAuth."""
    return FileResponse(os.path.join(_static, "login.html"), media_type="text/html")

@app.api_route("/login", methods=["GET", "HEAD"])
def login_page():
    return FileResponse(os.path.join(_static, "login.html"), media_type="text/html")

@app.api_route("/chat", methods=["GET", "HEAD"])
def chat_page():
    """Trang chat chính — Supabase redirect về đây sau đăng nhập thành công."""
    return FileResponse(os.path.join(_static, "index.html"), media_type="text/html")

@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return {"status": "ok"}

# ── Chat endpoints ────────────────────────────────────────────────────────────

@app.post("/hoi", response_model=TraLoiResponse)
def hoi(body: CauHoiRequest, user_id: str = Depends(get_user_id)):
    if not body.cau_hoi.strip() and not body.image_base64:
        raise HTTPException(status_code=400, detail="Câu hỏi không được để trống.")
    try:
        bot = lay_bot(user_id)
        if body.image_base64:
            tra_loi = bot.hoi_voi_anh(
                cau_hoi=body.cau_hoi or "(Xem ảnh đính kèm)",
                image_base64=body.image_base64,
                image_type=body.image_type or "image/jpeg",
            )
        else:
            tra_loi = bot.hoi(body.cau_hoi)
        return TraLoiResponse(tra_loi=tra_loi, user_id=user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/reset")
def reset(user_id: str = Depends(get_user_id)):
    if user_id in sessions:
        sessions[user_id].reset_lich_su()
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)

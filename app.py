"""
app.py — FastAPI wrapper cho tuyen_sinh_AI.py
Render chạy file này để khởi động web server.

Endpoints:
  GET  /          → kiểm tra server còn sống
  POST /hoi       → gửi câu hỏi, nhận câu trả lời
  POST /reset     → xóa lịch sử hội thoại của session
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from tuyen_sinh_AI import TuVanTuyenSinh

# ── Session store — mỗi user có bot riêng ────────────────────────────────────
sessions: dict[str, TuVanTuyenSinh] = {}

def lay_bot(session_id: str) -> TuVanTuyenSinh:
    if session_id not in sessions:
        sessions[session_id] = TuVanTuyenSinh()
    return sessions[session_id]


# ── Khởi động app ─────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Khởi tạo 1 bot mặc định lúc startup để load model embedding sẵn
    lay_bot("default")
    yield

app = FastAPI(
    title="AI Tư Vấn Tuyển Sinh",
    description="Hỏi về điểm chuẩn, ngành học, định hướng nghề nghiệp",
    version="1.0.0",
    lifespan=lifespan,
)

# Cho phép frontend gọi API (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # production nên đổi thành domain cụ thể
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Schemas ───────────────────────────────────────────────────────────────────

class CauHoiRequest(BaseModel):
    session_id: str = "default"
    cau_hoi: str

class TraLoiResponse(BaseModel):
    session_id: str
    tra_loi: str

class ResetRequest(BaseModel):
    session_id: str = "default"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/")
def health_check():
    """Render dùng endpoint này để kiểm tra service còn sống."""
    return {"status": "ok", "message": "AI Tư Vấn Tuyển Sinh đang chạy 🎓"}


@app.post("/hoi", response_model=TraLoiResponse)
def hoi(body: CauHoiRequest):
    """
    Gửi câu hỏi và nhận câu trả lời.

    Body JSON:
        session_id : string — dùng để phân biệt người dùng (mặc định "default")
        cau_hoi   : string — câu hỏi của học sinh
    """
    if not body.cau_hoi.strip():
        raise HTTPException(status_code=400, detail="Câu hỏi không được để trống.")
    try:
        bot = lay_bot(body.session_id)
        tra_loi = bot.hoi(body.cau_hoi)
        return TraLoiResponse(session_id=body.session_id, tra_loi=tra_loi)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/reset")
def reset(body: ResetRequest):
    """Xóa lịch sử hội thoại — gọi khi người dùng bấm 'Cuộc trò chuyện mới'."""
    if body.session_id in sessions:
        sessions[body.session_id].reset_lich_su()
    return {"status": "ok", "message": f"Đã reset session '{body.session_id}'"}


# ── Chạy trực tiếp (dev) ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)

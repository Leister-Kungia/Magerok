"""
app.py — FastAPI wrapper cho tuyen_sinh_AI.py
Hỗ trợ: text thuần + ảnh đính kèm (base64)
"""

import os
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from tuyen_sinh_AI import TuVanTuyenSinh

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
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class CauHoiRequest(BaseModel):
    session_id: str = "default"
    cau_hoi: str
    image_base64: Optional[str] = None
    image_type: Optional[str] = None

class TraLoiResponse(BaseModel):
    session_id: str
    tra_loi: str

class ResetRequest(BaseModel):
    session_id: str = "default"

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", include_in_schema=False)
def index():
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return {"status": "ok", "message": "AI Tư Vấn Tuyển Sinh đang chạy 🎓"}

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.post("/hoi", response_model=TraLoiResponse)
def hoi(body: CauHoiRequest):
    if not body.cau_hoi.strip() and not body.image_base64:
        raise HTTPException(status_code=400, detail="Câu hỏi không được để trống.")
    try:
        bot = lay_bot(body.session_id)
        if body.image_base64 and body.image_type:
            tra_loi = bot.hoi_voi_anh(
                cau_hoi=body.cau_hoi,
                image_base64=body.image_base64,
                image_type=body.image_type,
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
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)

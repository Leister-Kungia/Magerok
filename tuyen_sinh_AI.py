"""
╔══════════════════════════════════════════════════════════════════════════════╗
║              AI TƯ VẤN TUYỂN SINH ĐẠI HỌC — FILE TỔNG HỢP                 ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Cấu trúc file này (đọc theo thứ tự):                                       ║
║    PHẦN 0 — CÀI ĐẶT & HƯỚNG DẪN NHANH                                      ║
║    PHẦN 1 — CẤU HÌNH (chỉnh ở đây nếu muốn thay đổi gì)                   ║
║    PHẦN 2 — PROMPTS (kịch bản cho từng AI agent)                            ║
║    PHẦN 3 — INGEST (nạp dữ liệu Excel/PDF/Web → ChromaDB)                  ║
║    PHẦN 4 — QUERY (nhận câu hỏi → tìm dữ liệu → gọi AI → trả lời)         ║
║    PHẦN 5 — MAIN (chạy thử trên terminal hoặc khởi động server web)         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  AGENTS CÓ SẴN:                                                              ║
║    diem_chuan   — tư vấn điểm chuẩn, cơ hội trúng tuyển                    ║
║    truong       — thông tin trường, học phí, cơ sở vật chất                 ║
║    nganh        — ngành học, môn học, nghề nghiệp sau ra trường              ║
║    to_hop       — tổ hợp xét tuyển A00/B00/D01...                           ║
║    huong_nghiep — định hướng chọn ngành theo đam mê & tố chất               ║
║    hoc_tap      — lộ trình học tập, kỹ năng cần có sau khi chọn ngành       ║
║    kien_thuc    — dạy kiến thức (lập trình, toán, khoa học...)              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  CÁCH DÙNG NHANH:                                                            ║
║    1. pip install -r requirements.txt                                        ║
║    2. Đặt GROQ_API_KEY vào biến môi trường hoặc file .env                   ║
║    3. python tuyen_sinh_AI.py ingest   ← nạp dữ liệu (làm 1 lần)           ║
║    4. python tuyen_sinh_AI.py chat     ← test thử trên terminal             ║
║    5. python tuyen_sinh_AI.py server   ← khởi động server cho nhóm web      ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ══════════════════════════════════════════════════════════════════════════════
# PHẦN 1 — CẤU HÌNH TRUNG TÂM
# Chỉnh sửa ở đây khi cần thay đổi model, đường dẫn, hoặc thêm website crawl
# ══════════════════════════════════════════════════════════════════════════════

import os
import re
import sys
import uuid
import json
import time
import base64
import io
import logging
from datetime import datetime

# Thư viện bên ngoài — cài bằng: pip install -r requirements.txt
import chromadb
from groq import Groq
import pandas as pd
import pdfplumber
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from dotenv import load_dotenv

# Thư viện vẽ hình — cài thêm: pip install matplotlib networkx
try:
    import matplotlib
    matplotlib.use("Agg")  # không cần GUI, render sang file
    import matplotlib.pyplot as plt
    import matplotlib.patches mpatches
    import numpy as np
    import networkx as nx
    _CAN_DRAW = True
except ImportError:
    _CAN_DRAW = False

load_dotenv()  # Đọc API key từ file .env nếu có

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# GROQ KEY dự phòng lấy từ môi trường
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# ── HỆ THỐNG MODEL DỰ PHÒNG 4 LỚP (BẤT TỬ RATE LIMIT) ───────────────────────
MODEL_TEXT_1 = "llama-3.3-70b-versatile"    # Lớp 1: Brain mạnh nhất, thông minh nhất
MODEL_TEXT_2 = "gemma2-9b-it"               # Lớp 2: Backup ổn định, tiếng Việt tốt
MODEL_TEXT_3 = "llama-3.1-8b-instant"       # Lớp 3: Siêu nhanh, hạn mức gói free rất rộng
MODEL_TEXT_4 = "mixtral-8x7b-instruct"      # Lớp 4: Phương án cuối cùng bảo vệ hệ thống

MODEL_VISION_1 = "llama-3.2-11b-vision-preview" # Vision lớp 1: Đọc ảnh nhanh, nhẹ
MODEL_VISION_2 = "llama-3.2-90b-vision-preview" # Vision lớp 2: Đọc ảnh chi tiết, sâu rộng

# ── ChromaDB ─────────────────────────────────────────────────────────────────
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CHROMA_DB_PATH  = os.path.join(_BASE_DIR, "chroma_db")
COLLECTION_NAME = "tuyen_sinh_2024"

# ── Chunking ─────────────────────────────────────────────────────────────────
CHUNK_SIZE    = 500   # số ký tự mỗi đoạn văn
CHUNK_OVERLAP = 50    # số ký tự chồng lấp giữa 2 đoạn liên tiếp

# ── RAG ──────────────────────────────────────────────────────────────────────
TOP_K_RESULTS = 5     # lấy 5 đoạn văn liên quan nhất khi tìm kiếm

# ── Thư mục dữ liệu ──────────────────────────────────────────────────────────
EXCEL_DIR = os.path.join(_BASE_DIR, "data", "excel")
PDF_DIR   = os.path.join(_BASE_DIR, "data", "pdf")

# ── Website cần crawl ────────────────────────────────────────────────────────
WEBSITES_TO_CRAWL = [
    {
        "url": "https://tuyensinh.hust.edu.vn",
        "truong": "DHBK_HN",
        "ten_truong": "ĐH Bách Khoa Hà Nội",
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# PHẦN 1B — TỔ HỢP MÔN CHUẨN (bảng cứng, không để AI tự đoán)
# ══════════════════════════════════════════════════════════════════════════════

TO_HOP_TABLE = {
    # Khối A
    "A00": ["Toán", "Vật lý", "Hóa học"],
    "A01": ["Toán", "Vật lý", "Tiếng Anh"],
    "A02": ["Toán", "Vật lý", "Sinh học"],
    "A05": ["Toán", "Hóa học", "Tiếng Anh"],
    "A06": ["Toán", "Vật lý", "Địa lý"],
    "A07": ["Toán", "Lịch sử", "Địa lý"],
    "A08": ["Toán", "Hóa học", "Sinh học"],
    "A09": ["Toán", "Địa lý", "Tiếng Anh"],
    "A10": ["Toán", "Vật lý", "Tin học"],
    "A14": ["Toán", "Tiếng Anh", "Tin học"],
    "A16": ["Toán", "Vật lý", "GDCD"],
    # Khối B
    "B00": ["Toán", "Hóa học", "Sinh học"],
    "B01": ["Toán", "Sinh học", "Tiếng Anh"],
    "B03": ["Toán", "Sinh học", "Lịch sử"],
    "B04": ["Toán", "Sinh học", "Địa lý"],
    "B08": ["Toán", "Sinh học", "GDCD"],
    # Khối C
    "C00": ["Ngữ văn", "Lịch sử", "Địa lý"],
    "C01": ["Ngữ văn", "Toán", "Vật lý"],
    "C02": ["Ngữ văn", "Toán", "Hóa học"],
    "C03": ["Ngữ văn", "Toán", "Lịch sử"],
    "C04": ["Ngữ văn", "Toán", "Địa lý"],
    "C05": ["Ngữ văn", "Vật lý", "Hóa học"],
    "C06": ["Ngữ văn", "Vật lý", "Sinh học"],
    "C07": ["Ngữ văn", "Hóa học", "Sinh học"],
    "C08": ["Ngữ văn", "Lịch sử", "GDCD"],
    "C14": ["Toán", "Ngữ văn", "GDCD"],
    "C19": ["Ngữ văn", "Lịch sử", "Tiếng Anh"],
    "C20": ["Ngữ văn", "Địa lý", "GDCD"],
    # Khối D
    "D01": ["Ngữ văn", "Toán", "Tiếng Anh"],
    "D02": ["Ngữ văn", "Toán", "Tiếng Nga"],
    "D03": ["Ngữ văn", "Toán", "Tiếng Pháp"],
    "D04": ["Ngữ văn", "Toán", "Tiếng Trung"],
    "D07": ["Toán", "Hóa học", "Tiếng Anh"],
    "D08": ["Toán", "Sinh học", "Tiếng Anh"],
    "D09": ["Toán", "Lịch sử", "Tiếng Anh"],
    "D10": ["Toán", "Địa lý", "Tiếng Anh"],
    "D14": ["Ngữ văn", "Lịch sử", "Tiếng Anh"],
    "D15": ["Ngữ văn", "Địa lý", "Tiếng Anh"],
}

_MON_ALIAS = {
    "toan": "Toán", "vat ly": "Vật lý", "ly": "Vật lý", "vật lý": "Vật lý",
    "hoa hoc": "Hóa học", "hoa": "Hóa học", "hóa": "Hóa học", "hóa học": "Hóa học",
    "sinh hoc": "Sinh học", "sinh": "Sinh học", "sinh học": "Sinh học",
    "ngu van": "Ngữ văn", "van": "Ngữ văn", "ngữ văn": "Ngữ văn",
    "lich su": "Lịch sử", "su": "Lịch sử", "lịch sử": "Lịch sử",
    "dia ly": "Địa lý", "dia": "Địa lý", "địa lý": "Địa lý",
    "tieng anh": "Tiếng Anh", "anh": "Tiếng Anh", "tiếng anh": "Tiếng Anh",
    "tin hoc": "Tin học", "tin": "Tin học", "tin học": "Tin học",
    "gdcd": "GDCD", "cong dan": "GDCD", "công dân": "GDCD",
}

def tra_to_hop(ma_to_hop):
    ma = ma_to_hop.strip().upper()
    if ma in TO_HOP_TABLE:
        return f"{ma}: {', '.join(TO_HOP_TABLE[ma])}"
    return None

def to_hop_context():
    lines = ["BẢNG TỔ HỢP MÔN XÉT TUYỂN ĐẠI HỌC (CHUẨN BỘ GD&ĐT):"]
    for ma, mon in TO_HOP_TABLE.items():
        lines.append(f"  {ma}: {', '.join(mon)}")
    return "
".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# PHẦN 1C — WEB SEARCH
# ══════════════════════════════════════════════════════════════════════════════

_WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
}

def tim_kiem_web(query, n_trang=2):
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# PHẦN 1D — ENGINE VẼ HÌNH (Matplotlib / NetworkX)
# ══════════════════════════════════════════════════════════════════════════════

_IMAGE_TAG_RE = re.compile(r'\[GENERATE_IMAGE:\s*(.+?)\]', re.IGNORECASE | re.DOTALL)

def ve_hinh(mo_ta):
    if not _CAN_DRAW: return None
    try:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.plot([0, 1, 2], [0, 1, 4], label="Demo Line")
        ax.legend()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        buf.seek(0)
        plt.close(fig)
        return base64.b64encode(buf.read()).decode("utf-8")
    except:
        return None

def xu_ly_anh_trong_tra_loi(text):
    matches = _IMAGE_TAG_RE.findall(text)
    anh_list = []
    for mo_ta in matches:
        b64 = ve_hinh(mo_ta)
        if b64: anh_list.append(b64)
    sach_text = _IMAGE_TAG_RE.sub("", text).strip()
    return sach_text, anh_list


# ══════════════════════════════════════════════════════════════════════════════
# PHẦN 2 — KỊCH BẢN CHUYÊN GIA (PROMPTS)
# ══════════════════════════════════════════════════════════════════════════════

ROUTER_SYSTEM = "Bạn là bộ định tuyến câu hỏi. Luôn luôn trả về định dạng JSON chứa key 'agents'."
DIEM_CHUAN_SYSTEM = "Bạn là chuyên gia tư vấn điểm chuẩn đại học Việt Nam."
TRUONG_SYSTEM = "Bạn là chuyên gia thông tin các trường đại học."
NGANH_SYSTEM = "Bạn là chuyên gia định hướng ngành học."
TO_HOP_SYSTEM = "Bạn là chuyên gia quy chế khối thi."
HUONG_NGHIEP_SYSTEM = "Bạn là chuyên gia trắc nghiệm hướng nghiệp."
HOC_TAP_SYSTEM = "Bạn là thủ khoa chia sẻ bí kíp học tập."
KIEN_THUC_SYSTEM = "Bạn là gia sư giảng giải kiến thức khoa học, lập trình."
AGGREGATOR_SYSTEM = "Bạn là chuyên gia tổng hợp thông tin thân thiện."

def build_diem_chuan_prompt(du_lieu, cau_hoi, lich_su=""): return f"Data:
{du_lieu}
Q: {cau_hoi}"
def build_truong_prompt(du_lieu, cau_hoi, lich_su=""): return f"Data:
{du_lieu}
Q: {cau_hoi}"
def build_nganh_prompt(du_lieu, cau_hoi, lich_su=""): return f"Q: {cau_hoi}"
def build_to_hop_prompt(du_lieu, cau_hoi, lich_su=""): return f"Context:
{to_hop_context()}
Q: {cau_hoi}"
def build_huong_nghiep_prompt(du_lieu, cau_hoi, lich_su=""): return f"Q: {cau_hoi}"
def build_hoc_tap_prompt(du_lieu, cau_hoi, lich_su=""): return f"Q: {cau_hoi}"
def build_kien_thuc_prompt(du_lieu, cau_hoi, lich_su=""): return f"Q: {cau_hoi}"
def build_aggregator_prompt(cau_hoi_goc, cac_ket_qua):
    res = f"Câu hỏi: {cau_hoi_goc}
"
    for k, v in cac_ket_qua.items(): res += f"[{k}]: {v}
"
    return res


# ══════════════════════════════════════════════════════════════════════════════
# PHẦN 3 — INGEST DỮ LIỆU
# ══════════════════════════════════════════════════════════════════════════════

def _tao_groq_client():
    if not GROQ_API_KEY:
        raise ValueError("Chưa cấu hình GROQ_API_KEY trong file .env")
    return Groq(api_key=GROQ_API_KEY)


# ══════════════════════════════════════════════════════════════════════════════
# PHẦN 4 — QUERY & MULTI-LAYER FALLBACK ENGINE (BẤT TỬ)
# ══════════════════════════════════════════════════════════════════════════════

class TuVanTuyenSinh:
    def __init__(self):
        chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        self.collection = chroma_client.get_or_create_collection(COLLECTION_NAME)
        self.groq = _tao_groq_client()
        self.lich_su = []

    def _safe_groq_call(self, messages, max_tokens=1200, response_format=None):
        models_pool = [MODEL_TEXT_1, MODEL_TEXT_2, MODEL_TEXT_3, MODEL_TEXT_4]
        for idx, model in enumerate(models_pool):
            try:
                kwargs = {"model": model, "messages": messages, "max_tokens": max_tokens}
                if response_format: kwargs["response_format"] = response_format
                resp = self.groq.chat.completions.create(**kwargs)
                return resp.choices[0].message.content.strip()
            except Exception as e:
                error_msg = str(e).lower()
                is_rate_limit = any(k in error_msg for k in ["rate_limit", "429", "quota", "exhausted", "token", "limit"])
                if is_rate_limit:
                    log.warning(f"Model {model} lỗi nghẽn hoặc giới hạn. Chuyển tầng tiếp theo...")
                    continue
                else:
                    continue
        return "Xin lỗi, tất cả các tài nguyên AI dự phòng đang bận, vui lòng thử lại sau."

    def _phan_tich_cau_hoi(self, cau_hoi):
        messages = [
            {"role": "system", "content": ROUTER_SYSTEM},
            {"role": "user", "content": f"Phân tích: {cau_hoi}"}
        ]
        text = self._safe_groq_call(messages, max_tokens=200, response_format={"type": "json_object"})
        try:
            data = json.loads(text)
            return data.get("agents", ["nganh"]), ""
        except:
            return ["nganh"], ""

    def _tim_du_lieu(self, cau_hoi, loai_filter=None):
        try:
            results = self.collection.query(query_texts=[cau_hoi], n_results=TOP_K_RESULTS)
            docs = results.get("documents", [[]])[0]
            return "
---
".join(docs) if docs else ""
        except:
            return ""

    def hoi(self, cau_hoi):
        agents, _ = self._phan_tich_cau_hoi(cau_hoi)
        agent_map = {
            "diem_chuan": (DIEM_CHUAN_SYSTEM, build_diem_chuan_prompt, "diem_chuan"),
            "truong": (TRUONG_SYSTEM, build_truong_prompt, "truong"),
            "nganh": (NGANH_SYSTEM, build_nganh_prompt, "nganh"),
            "to_hop": (TO_HOP_SYSTEM, build_to_hop_prompt, "to_hop"),
            "huong_nghiep": (HUONG_NGHIEP_SYSTEM, build_huong_nghiep_prompt, None),
            "hoc_tap": (HOC_TAP_SYSTEM, build_hoc_tap_prompt, None),
            "kien_thuc": (KIEN_THUC_SYSTEM, build_kien_thuc_prompt, None),
        }
        cac_ket_qua = {}
        for agent_name in agents:
            if agent_name in agent_map:
                sys_p, b_fn, f_type = agent_map[agent_name]
                data_context = self._tim_du_lieu(cau_hoi, f_type)
                messages = [
                    {"role": "system", "content": sys_p},
                    {"role": "user", "content": b_fn(data_context, cau_hoi)}
                ]
                cac_ket_qua[agent_name] = self._safe_groq_call(messages)
        if not cac_ket_qua:
            messages = [{"role": "system", "content": NGANH_SYSTEM}, {"role": "user", "content": cau_hoi}]
            cac_ket_qua["nganh"] = self._safe_groq_call(messages)
        tra_loi_raw = self._safe_groq_call([
            {"role": "system", "content": AGGREGATOR_SYSTEM},
            {"role": "user", "content": build_aggregator_prompt(cau_hoi, cac_ket_qua)}
        ])
        tra_loi, anh_list = xu_ly_anh_trong_tra_loi(tra_loi_raw)
        return {"tra_loi": tra_loi, "anh": anh_list}

    def hoi_voi_anh(self, cau_hoi, image_base64, image_type="image/jpeg"):
        vision_pool = [MODEL_VISION_1, MODEL_VISION_2]
        messages = [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{image_type};base64,{image_base64}"}},
                {"type": "text", "text": f"Đọc và dịch ảnh để lời giải: {cau_hoi}"}
            ]
        }]
        for model in vision_pool:
            try:
                resp = self.groq.chat.completions.create(model=model, max_tokens=1000, messages=messages)
                context_anh = resp.choices[0].message.content.strip()
                return self.hoi(f"{cau_hoi}

[Dữ liệu từ ảnh]:
{context_anh}")
            except:
                continue
        return self.hoi(cau_hoi)

    def reset_lich_su(self):
        self.lich_su = []


# ══════════════════════════════════════════════════════════════════════════════
# PHẦN 5 — ĐIỂM VÀO HỆ THỐNG
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Magerok AI Engine Ready.")

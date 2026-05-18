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
    import matplotlib.patches as mpatches
    import numpy as np
    import networkx as nx
    _CAN_DRAW = True
except ImportError:
    _CAN_DRAW = False
    _DRAW_WARN = "matplotlib/networkx chưa cài — tính năng vẽ hình bị tắt."

load_dotenv()  # Đọc API key từ file .env nếu có

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

if not _CAN_DRAW:
    log.warning("matplotlib/networkx chưa cài — tính năng vẽ hình bị tắt. Chạy: pip install matplotlib networkx numpy")

# ── API & Model ───────────────────────────────────────────────────────────────
GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")   # lấy tại console.groq.com
LLM_MODEL       = "llama-3.3-70b-versatile"        # miễn phí, mạnh, tiếng Việt tốt
FALLBACK_MODEL  = "gemma2-9b-it"                   # Model dự phòng khi hết Quota/Rate Limit

# EMBEDDING_MODEL không dùng — embedding chạy local qua ChromaDB DefaultEmbeddingFunction (ONNX)

# ── ChromaDB ─────────────────────────────────────────────────────────────────
# Đường dẫn tính từ vị trí file .py, không phụ thuộc thư mục đang chạy lệnh
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
# THÊM TRƯỜNG MỚI: copy một block { } và điền vào
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

TO_HOP_TABLE: dict[str, list[str]] = {
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
    # Năng khiếu / Thể thao
    "H00": ["Ngữ văn", "Năng khiếu 1", "Năng khiếu 2"],
    "T00": ["Toán", "Thể dục", "Năng khiếu"],
}

_MON_ALIAS: dict[str, str] = {
    "toan": "Toán", "vat ly": "Vật lý", "ly": "Vật lý", "vật lý": "Vật lý",
    "hoa hoc": "Hóa học", "hoa": "Hóa học", "hóa": "Hóa học", "hóa học": "Hóa học",
    "sinh hoc": "Sinh học", "sinh": "Sinh học", "sinh học": "Sinh học",
    "ngu van": "Ngữ văn", "van": "Ngữ văn", "ngữ văn": "Ngữ văn",
    "lich su": "Lịch sử", "su": "Lịch sử", "lịch sử": "Lịch sử",
    "dia ly": "Địa lý", "dia": "Địa lý", "địa lý": "Địa lý",
    "tieng anh": "Tiếng Anh", "anh": "Tiếng Anh", "tiếng anh": "Tiếng Anh",
    "tin hoc": "Tin học", "tin": "Tin học", "tin học": "Tin học",
    "gdcd": "GDCD", "cong dan": "GDCD", "công dân": "GDCD",
    "tieng trung": "Tiếng Trung", "trung": "Tiếng Trung",
    "tieng phap": "Tiếng Pháp", "phap": "Tiếng Pháp",
    "tieng nga": "Tiếng Nga", "nga": "Tiếng Nga",
}

def tra_to_hop(ma_to_hop: str) -> str | None:
    ma = ma_to_hop.strip().upper()
    if ma in TO_HOP_TABLE:
        mon = ", ".join(TO_HOP_TABLE[ma])
        return f"{ma}: {mon}"
    return None

def tim_ma_to_hop(cac_mon: list[str]) -> list[str]:
    chuan = []
    for m in cac_mon:
        m_lower = m.strip().lower()
        chuan.append(_MON_ALIAS.get(m_lower, m.strip()))
    chuan_set = set(chuan)
    ket_qua = []
    for ma, mon_list in TO_HOP_TABLE.items():
        if set(mon_list) == chuan_set:
            ket_qua.append(f"{ma}: {', '.join(mon_list)}")
    return ket_qua

def to_hop_context() -> str:
    lines = ["BẢNG TỔ HỢP MÔN XÉT TUYỂN ĐẠI HỌC (CHUẨN BỘ GD&ĐT):"]
    for ma, mon in TO_HOP_TABLE.items():
        lines.append(f"  {ma}: {', '.join(mon)}")
    lines.append("")
    lines.append("LƯU Ý QUAN TRỌNG — CÁC NHẦM LẪN PHỔ BIẾN:")
    lines.append("  - A01 = Toán, Vật lý, Tiếng ANH (KHÔNG phải Tin học)")
    lines.append("  - A10 = Toán, Vật lý, Tin học (KHÔNG phải Tiếng Anh)")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# PHẦN 1C — WEB SEARCH
# ══════════════════════════════════════════════════════════════════════════════

_WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MagerokBot/1.0; +https://magerok.com)",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
}

_TUYEN_SINH_SITES = ["tuyensinh247.com", "diemthi.24h.com.vn", "tuyensinh.vn"]

def _google_search_urls(query: str, num: int = 5) -> list[str]:
    site_filter = " OR ".join(f"site:{s}" for s in _TUYEN_SINH_SITES)
    full_query  = f"{query} ({site_filter})"
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": full_query, "kl": "vn-vi"},
            headers=_WEB_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        urls = []
        for a in soup.select("a.result__url"):
            href = a.get("href", "")
            if href.startswith("http") and len(urls) < num:
                urls.append(href)
        if not urls:
            for a in soup.select(".result__title a"):
                href = a.get("href", "")
                if "duckduckgo.com" not in href and href.startswith("http"):
                    urls.append(href)
                if len(urls) >= num:
                    break
        return urls
    except Exception as e:
        log.warning(f"[WebSearch] DuckDuckGo lỗi: {e}")
        return []

def _fetch_page_text(url: str, max_chars: int = 3000) -> str:
    try:
        resp = requests.get(url, headers=_WEB_HEADERS, timeout=10)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "iframe", "ads"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return "\n".join(lines)[:max_chars]
    except Exception as e:
        log.warning(f"[WebFetch] {url} → {e}")
        return ""

def tim_kiem_web(query: str, n_trang: int = 3) -> str:
    log.info(f"[WebSearch] Truy vấn: {query}")
    urls = _google_search_urls(query, num=n_trang + 2)
    if not urls:
        return ""
    doan_van = []
    for url in urls[:n_trang]:
        text = _fetch_page_text(url)
        if text and len(text) > 200:
            doan_van.append(f"[Nguồn: {url}]\n{text}")
        if len(doan_van) >= n_trang:
            break
    if not doan_van:
        return ""
    return "\n\n===\n\n".join(doan_van)


# ══════════════════════════════════════════════════════════════════════════════
# PHẦN 1D — ENGINE VẼ HÌNH (Matplotlib / NetworkX)
# ══════════════════════════════════════════════════════════════════════════════

_IMG_DIR = os.path.join(_BASE_DIR, "static", "generated")
os.makedirs(_IMG_DIR, exist_ok=True)
_IMAGE_TAG_RE = re.compile(r'\[GENERATE_IMAGE:\s*(.+?)\]', re.IGNORECASE | re.DOTALL)

def _fig_to_base64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)
    return base64.b64encode(buf.read()).decode("utf-8")

def _parse_image_desc(desc: str) -> dict:
    d = desc.lower()
    if any(k in d for k in ["concept map", "concept_map", "mind map", "sơ đồ", "diagram"]):
        return {"loai": "concept_map"}
    if any(k in d for k in ["unit circle", "vòng tròn đơn vị", "circle sin cos"]):
        return {"loai": "unit_circle"}
    if any(k in d for k in ["triangle", "tam giác", "rectangle", "hình chữ nhật", "geometry", "hình học"]):
        return {"loai": "geometry"}
    return {"loai": "plot"}

def _ve_plot(desc: str):
    fig, ax = plt.subplots(figsize=(7, 5), facecolor="#f8fbff")
    ax.set_facecolor("#ffffff")
    ax.grid(True, linestyle="--", alpha=0.5, color="#ccddee")
    x = np.linspace(-10, 10, 800)
    colors = ["#1F3A5F", "#2EC4B6", "#E05A2B"]
    funcs = re.findall(r'y\s*=\s*([^,\[\]]+?)(?:,|\band\b|$)', desc, re.IGNORECASE)
    if not funcs: funcs = ["x**2"]
    
    plotted = 0
    for i, expr in enumerate(funcs[:3]):
        expr_py = (expr.strip().replace("^", "**").replace("sqrt", "np.sqrt").replace("sin", "np.sin").replace("cos", "np.cos"))
        try:
            y = eval(expr_py, {"x": x, "np": np, "__builtins__": {}})
            ax.plot(x, y, color=colors[i % len(colors)], linewidth=2.2, label=f"y = {expr.strip()}")
            plotted += 1
        except: continue
    ax.axhline(0, color="#333", linewidth=0.8)
    ax.axvline(0, color="#333", linewidth=0.8)
    if plotted > 0: ax.legend()
    ax.set_ylim(-20, 20)
    return fig

def _ve_hinh_hoc(desc: str):
    fig, ax = plt.subplots(figsize=(6, 6), facecolor="#f8fbff")
    ax.set_facecolor("#ffffff")
    ax.set_aspect("equal")
    rect = plt.Rectangle((0.5, 0.5), 4, 2.5, fill=True, facecolor="#EEF4FB", edgecolor="#1F3A5F", linewidth=2)
    ax.add_patch(rect)
    ax.set_xlim(0, 5.5); ax.set_ylim(-0.5, 3.5)
    return fig

def _ve_vong_tron_don_vi():
    fig, ax = plt.subplots(figsize=(6, 6), facecolor="#f8fbff")
    theta = np.linspace(0, 2*np.pi, 400)
    ax.plot(np.cos(theta), np.sin(theta), color="#1F3A5F", linewidth=2)
    ax.axhline(0, color="#555", linewidth=0.8)
    ax.axvline(0, color="#555", linewidth=0.8)
    ax.set_xlim(-1.5, 1.5); ax.set_ylim(-1.5, 1.5)
    return fig

def ve_hinh(mo_ta: str) -> str | None:
    if not _CAN_DRAW: return None
    try:
        cfg = _parse_image_desc(mo_ta)
        loai = cfg["loai"]
        if loai == "unit_circle": fig = _ve_vong_tron_don_vi()
        elif loai == "geometry": fig = _ve_hinh_hoc(mo_ta)
        else: fig = _ve_plot(mo_ta)
        return _fig_to_base64(fig)
    except Exception as e:
        log.error(f"Lỗi vẽ hình: {e}")
        return None

def xu_ly_anh_trong_tra_loi(text: str) -> tuple[str, list[str]]:
    matches = _IMAGE_TAG_RE.findall(text)
    anh_list = []
    for mo_ta in matches:
        b64 = ve_hinh(mo_ta)
        if b64: anh_list.append(b64)
    sạch_text = _IMAGE_TAG_RE.sub("", text).strip()
    return sạch_text, anh_list


# ══════════════════════════════════════════════════════════════════════════════
# PHẦN 2 — KỊCH BẢN CHUYÊN GIA (PROMPTS)
# ══════════════════════════════════════════════════════════════════════════════

def _ngay_hom_nay() -> str:
    return datetime.now().strftime("%d/%m/%Y")

ROUTER_SYSTEM = """
Bạn là bộ định tuyến phân tích câu hỏi tuyển sinh đại học Việt Nam.
Hãy phân tích câu hỏi và trả về JSON có cấu trúc sau:
{
  "agents": ["tên_agent_1", "tên_agent_2"],
  "can_hoi_them": "câu hỏi ngắn nếu thiếu thông tin quan trọng"
}
"""

DIEM_CHUAN_SYSTEM = "Bạn là chuyên gia tư vấn điểm chuẩn đại học Việt Nam. Hãy dựa vào dữ liệu để tư vấn chính xác."
TRUONG_SYSTEM = "Bạn là chuyên gia thông tin các trường đại học. Cung cấp thông tin khách quan về học phí, cơ sở vật chất."
NGANH_SYSTEM = "Bạn là người đi trước chia sẻ sâu sắc về ngành học, cơ hội việc làm và môn học thực tế."
TO_HOP_SYSTEM = "Bạn là chuyên gia quy chế tuyển sinh Bộ Giáo dục."
HUONG_NGHIEP_SYSTEM = "Bạn là chuyên gia trắc nghiệm hướng nghiệp."
HOC_TAP_SYSTEM = "Bạn là thủ khoa chia sẻ bí kíp học tập đại học."
KIEN_THUC_SYSTEM = "Bạn là gia sư giảng giải kiến thức khoa học, lập trình dễ hiểu."
AGGREGATOR_SYSTEM = "Bạn là chuyên gia tổng hợp thông tin thân thiện, đưa ra câu trả lời cuối cùng mạch lạc cho học sinh."

def build_diem_chuan_prompt(du_lieu, cau_hoi, lich_su=""):
    return f"Dữ liệu:\n{du_lieu}\n\nCâu hỏi: {cau_hoi}"
def build_truong_prompt(du_lieu, cau_hoi, lich_su=""):
    return f"Dữ liệu trường:\n{du_lieu}\n\nCâu hỏi: {cau_hoi}"
def build_nganh_prompt(du_lieu, cau_hoi, lich_su=""):
    return f"Câu hỏi về ngành: {cau_hoi}"
def build_to_hop_prompt(du_lieu, cau_hoi, lich_su=""):
    return f"{to_hop_context()}\n\nCâu hỏi: {cau_hoi}"
def build_huong_nghiep_prompt(du_lieu, cau_hoi, lich_su=""):
    return f"Hướng nghiệp câu hỏi: {cau_hoi}"
def build_hoc_tap_prompt(du_lieu, cau_hoi, lich_su=""):
    return f"Lộ trình học: {cau_hoi}"
def build_kien_thuc_prompt(du_lieu, cau_hoi, lich_su=""):
    return f"Giải thích kiến thức: {cau_hoi}"
def build_aggregator_prompt(cau_hoi_goc, cac_ket_qua):
    res = f"Câu hỏi: {cau_hoi_goc}\n"
    for k, v in cac_ket_qua.items(): res += f"[{k}]: {v}\n"
    return res


# ══════════════════════════════════════════════════════════════════════════════
# PHẦN 3 — INGEST DỮ LIỆU
# ══════════════════════════════════════════════════════════════════════════════

def _tao_groq_client():
    if not GROQ_API_KEY:
        raise ValueError("Chưa cấu hình GROQ_API_KEY trong file .env")
    return Groq(api_key=GROQ_API_KEY)

def _khoi_tao_chroma(reset=False):
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    if reset:
        try: client.delete_collection(COLLECTION_NAME)
        except: pass
    return client.get_or_create_collection(COLLECTION_NAME)

def _embed(texts: list[str]) -> list[list[float]]:
    # ChromaDB tự động chạy Embedding local thông qua ONNX dưới nền nếu không truyền.
    # Để tránh lỗi đồng bộ API, ta trả về mảng rỗng để ChromaDB tự sinh embedding lúc add.
    return []


# ══════════════════════════════════════════════════════════════════════════════
# PHẦN 4 — QUERY & FALLBACK LOGIC
# ══════════════════════════════════════════════════════════════════════════════

class TuVanTuyenSinh:
    def __init__(self):
        log.info("Đang khởi động hệ thống tư vấn tuyển sinh với cơ chế Fallback...")
        chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        self.collection = chroma_client.get_or_create_collection(COLLECTION_NAME)
        self.groq = _tao_groq_client()
        self.lich_su = []

    def _safe_groq_call(self, messages: list, model_main: str = LLM_MODEL, model_fallback: str = FALLBACK_MODEL, max_tokens: int = 1200, response_format: dict = None) -> str:
        """
        Hàm bọc an toàn: Tự động phát hiện lỗi Rate Limit / Out of Quota 
        của model chính để lập tức chuyển sang model dự phòng gemma2-9b-it.
        """
        try:
            # Thử gọi model chính trước (Llama-3.3-70b)
            kwargs = {"model": model_main, "messages": messages, "max_tokens": max_tokens}
            if response_format:
                kwargs["response_format"] = response_format
                
            resp = self.groq.chat.completions.create(**kwargs)
            return resp.choices[0].message.content.strip()
            
        except Exception as e:
            error_msg = str(e).lower()
            # Nếu dính lỗi Rate Limit, Quota, Too Many Requests (429) hoặc cạn kiệt token
            if any(k in error_msg for k in ["rate_limit", "rate limit", "429", "quota", "exhausted", "token"]):
                log.warning(f"\n⚠️ HẾT QUOTA MODEL CHÍNH ({model_main})! Đang tự động kích hoạt model dự phòng ({model_fallback})...")
                try:
                    kwargs_fallback = {"model": model_fallback, "messages": messages, "max_tokens": max_tokens}
                    if response_format:
                        kwargs_fallback["response_format"] = response_format
                        
                    resp = self.groq.chat.completions.create(**kwargs_fallback)
                    return resp.choices[0].message.content.strip()
                except Exception as fallback_error:
                    log.error(f"Sập hầm cả model dự phòng: {fallback_error}")
                    return f"Hệ thống đang quá tải ở cả 2 kênh dữ liệu. Vui lòng thử lại sau vài phút! Chi tiết lỗi: {str(fallback_error)}"
            else:
                # Trả về lỗi gốc nếu là loại lỗi khác không phải cạn tài nguyên
                raise e

    def _phan_tich_cau_hoi(self, cau_hoi: str) -> tuple[list[str], str]:
        messages = [
            {"role": "system", "content": ROUTER_SYSTEM},
            {"role": "user", "content": f"Hãy phân loại câu hỏi sau sang dạng JSON:\n\"{cau_hoi}\""}
        ]
        text = self._safe_groq_call(messages, max_tokens=300, response_format={"type": "json_object"})
        try:
            data = json.loads(text)
            agents = data.get("agents", ["nganh"])
            can_hoi_them = data.get("can_hoi_them", "").strip()
            return agents, can_hoi_them
        except:
            return ["nganh"], ""

    def _tim_du_lieu(self, cau_hoi: str, loai_filter: str = None) -> str:
        try:
            # Tìm kiếm văn bản thuần thông qua ChromaDB query cơ bản
            results = self.collection.query(query_texts=[cau_hoi], n_results=TOP_K_RESULTS)
            docs = results.get("documents", [[]])[0]
            return "\n---\n".join(docs) if docs else ""
        except:
            return ""

    def _tim_du_lieu_voi_web(self, ten_agent: str, cau_hoi: str, loai_filter: str | None) -> str:
        du_lieu_local = self._tim_du_lieu(cau_hoi, loai_filter)
        if not du_lieu_local and ten_agent in {"diem_chuan", "truong", "nganh"}:
            return tim_kiem_web(cau_hoi, n_trang=2)
        return du_lieu_local

    def _goi_chuyen_gia(self, ten_agent: str, system_prompt: str, build_fn, du_lieu: str, cau_hoi: str) -> str:
        system_final = system_prompt.replace("{ngay_hom_nay}", _ngay_hom_nay())
        messages = [
            {"role": "system", "content": system_final},
            {"role": "user", "content": build_fn(du_lieu, cau_hoi, "")}
        ]
        return self._safe_groq_call(messages, max_tokens=1000)

    def _tong_hop(self, cau_hoi_goc: str, cac_ket_qua: dict) -> str:
        aggregator_final = AGGREGATOR_SYSTEM.replace("{ngay_hom_nay}", _ngay_hom_nay())
        messages = [
            {"role": "system", "content": aggregator_final},
            {"role": "user", "content": build_aggregator_prompt(cau_hoi_goc, cac_ket_qua)}
        ]
        return self._safe_groq_call(messages, max_tokens=1200)

    def hoi(self, cau_hoi: str) -> dict:
        log.info(f"\n[User Request]: {cau_hoi}")
        agents, can_hoi_them = self._phan_tich_cau_hoi(cau_hoi)
        
        if can_hoi_them and len(self.lich_su) == 0:
            return {"tra_loi": can_hoi_them, "anh": []}

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
                data_context = self._tim_du_lieu_voi_web(agent_name, cau_hoi, f_type)
                cac_ket_qua[agent_name] = self._goi_chuyen_gia(agent_name, sys_p, b_fn, data_context, cau_hoi)

        if not cac_ket_qua:
            cac_ket_qua["nganh"] = self._goi_chuyen_gia("nganh", NGANH_SYSTEM, build_nganh_prompt, "", cau_hoi)

        tra_loi_raw = self._tong_hop(cau_hoi, cac_ket_qua)
        tra_loi, anh_list = xu_ly_anh_trong_tra_loi(tra_loi_raw)
        
        self.lich_su.append({"role": "user", "content": cau_hoi})
        self.lich_su.append({"role": "assistant", "content": tra_loi})
        self.lich_su = self.lich_su[-20:]
        
        return {"tra_loi": tra_loi, "anh": anh_list}

    def hoi_voi_anh(self, cau_hoi: str, image_base64: str, image_type: str = "image/jpeg") -> dict:
        log.info("[Vision] Đang phân tích hình ảnh đính kèm...")
        try:
            # Model Vision xử lý ảnh
            resp = self.groq.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                max_tokens=1500,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:{image_type};base64,{image_base64}"}},
                            {"type": "text", "text": f"Hãy đọc và trích xuất thông tin chữ/số từ bức ảnh tuyển sinh này để bổ trợ cho câu hỏi: {cau_hoi}"}
                        ]
                    }
                ]
            )
            context_anh = resp.choices[0].message.content.strip()
            return self.hoi(f"{cau_hoi}\n\n[Thông tin bổ sung trích xuất tự động từ ảnh của học sinh]:\n{context_anh}")
        except Exception as e:
            log.error(f"Lỗi Vision: {e}. Chuyển sang chạy tin nhắn thuần.")
            return self.hoi(cau_hoi)

    def reset_lich_su(self):
        self.lich_su = []


# ══════════════════════════════════════════════════════════════════════════════
# PHẦN 5 — ĐIỂM VÀO HỆ THỐNG (CHẠY THỬ / SERVER)
# ══════════════════════════════════════════════════════════════════════════════

def chay_chat():
    bot = TuVanTuyenSinh()
    print("\n=== HỆ THỐNG TỰ ĐỘNG CHUYỂN MODEL ĐÃ SẴN SÀNG ===")
    print("Gõ 'exit' hoặc 'quit' để thoát.\n")
    while True:
        try:
            q = input("Học sinh hỏi: ").strip()
            if not q or q.lower() in ["exit", "quit"]: break
            res = bot.hoi(q)
            print(f"\nMagerok AI trả lời:\n{res['tra_loi']}\n")
            if res['anh']: print(f"==> [Hệ thống đã sinh kèm {len(res['anh'])} ảnh minh họa thành công] <==")
            print("-" * 50)
        except KeyboardInterrupt: break

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "chat":
        chay_chat()
    else:
        print("Chạy lệnh: 'python tuyen_sinh_AI.py chat' để bắt đầu test thử terminal.")
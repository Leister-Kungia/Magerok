# -*- coding: utf-8 -*-
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
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import re
import sys
import json
import base64
import io
import logging
from datetime import datetime

import chromadb
from groq import Groq
import pandas as pd
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    _CAN_DRAW = True
except ImportError:
    _CAN_DRAW = False

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# CONFIG MODEL HỆ THỐNG DỰ PHÒNG CHỐNG SẬP 4 TẦNG
MODEL_TEXT_1 = "llama-3.3-70b-versatile"
MODEL_TEXT_2 = "gemma2-9b-it"
MODEL_TEXT_3 = "llama-3.1-8b-instant"
MODEL_TEXT_4 = "mixtral-8x7b-instruct"

MODEL_VISION_1 = "llama-3.2-11b-vision-preview"
MODEL_VISION_2 = "llama-3.2-90b-vision-preview"

CHROMA_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chroma_db")
COLLECTION_NAME = "tuyen_sinh_2024"
TOP_K_RESULTS = 5

ROUTER_SYSTEM = "Bạn là bộ định tuyến câu hỏi tuyển sinh đại học Việt Nam. Hãy phân tích câu hỏi và trả về duy nhất chuỗi cấu trúc định dạng JSON có dạng: {\"agents\": [\"nganh\"], \"can_hoi_them\": \"\"}"
DIEM_CHUAN_SYSTEM = "Bạn là chuyên gia điểm chuẩn đại học Việt Nam."
TRUONG_SYSTEM = "Bạn là chuyên gia thông tin về các trường đại học."
NGANH_SYSTEM = "Bạn là chuyên gia tư vấn hướng nghiệp và cơ hội việc làm các ngành."
TO_HOP_SYSTEM = "Bạn là chuyên gia quy chế khối thi."
AGGREGATOR_SYSTEM = "Bạn là tổng hợp viên thân thiện giúp học sinh hiểu rõ thông tin tuyển sinh."

class TuVanTuyenSinh:
    def __init__(self):
        log.info("Khởi tạo hệ thống tư vấn tuyển sinh với chuỗi Fallback 4 tầng bất tử...")
        chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        self.collection = chroma_client.get_or_create_collection(COLLECTION_NAME)
        self.groq = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
        self.lich_su = []

    def _safe_groq_call(self, messages: list, max_tokens: int = 1200, response_format: dict = None) -> str:
        models_pool = [MODEL_TEXT_1, MODEL_TEXT_2, MODEL_TEXT_3, MODEL_TEXT_4]
        for idx, model in enumerate(models_pool):
            try:
                log.info(f"[Groq Engine] Thử gọi Model Tầng {idx+1}: {model}")
                kwargs = {"model": model, "messages": messages, "max_tokens": max_tokens}
                if response_format:
                    kwargs["response_format"] = response_format
                resp = self.groq.chat.completions.create(**kwargs)
                return resp.choices[0].message.content.strip()
            except Exception as e:
                err_str = str(e).lower()
                is_rate_limit = any(k in err_str for k in ["rate_limit", "429", "quota", "exhausted", "token", "limit"])
                if is_rate_limit:
                    log.warning(f"⚠️ [TẦNG {idx+1} CẠN KIỆT] Model {model} quá tải, chuyển sang tầng kế tiếp.")
                    continue
                log.error(f"Lỗi tại model {model}: {e}")
                continue
        return "Tất cả các model thuộc hệ thống dự phòng đều tạm thời không phản hồi do giới hạn băng thông."

    def _phan_tich_cau_hoi(self, cau_hoi: str) -> tuple[list[str], str]:
        messages = [
            {"role": "system", "content": ROUTER_SYSTEM},
            {"role": "user", "content": f"Phân loại câu hỏi sau: {cau_hoi}"}
        ]
        text = self._safe_groq_call(messages, max_tokens=300, response_format={"type": "json_object"})
        try:
            data = json.loads(text)
            return data.get("agents", ["nganh"]), data.get("can_hoi_them", "")
        except:
            return ["nganh"], ""

    def hoi(self, cau_hoi: str) -> dict:
        agents, can_hoi_them = self._phan_tich_cau_hoi(cau_hoi)
        cac_ket_qua = {}
        for agent in agents:
            messages = [
                {"role": "system", "content": NGANH_SYSTEM},
                {"role": "user", "content": cau_hoi}
            ]
            cac_ket_qua[agent] = self._safe_groq_call(messages, max_tokens=800)
            
        messages_agg = [
            {"role": "system", "content": AGGREGATOR_SYSTEM},
            {"role": "user", "content": f"Tổng hợp thông tin sau cho học sinh: {json.dumps(cac_ket_qua)}"}
        ]
        tra_loi = self._safe_groq_call(messages_agg, max_tokens=1000)
        return {"tra_loi": tra_loi, "anh": []}

    def hoi_voi_anh(self, cau_hoi: str, image_base64: str, image_type: str = "image/jpeg") -> dict:
        log.info("[Vision Engine] Nhận diện và trích xuất dữ liệu ảnh...")
        vision_pool = [MODEL_VISION_1, MODEL_VISION_2]
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{image_type};base64,{image_base64}"}},
                    {"type": "text", "text": f"Đọc kỹ dữ liệu chữ/số có trong ảnh tuyển sinh này để bổ trợ câu hỏi: {cau_hoi}"}
                ]
            }
        ]
        for idx, model in enumerate(vision_pool):
            try:
                resp = self.groq.chat.completions.create(model=model, max_tokens=1200, messages=messages)
                txt = resp.choices[0].message.content.strip()
                return self.hoi(f"{cau_hoi}\n\n[Dữ liệu ảnh]:\n{txt}")
            except Exception as e:
                log.warning(f"Lỗi Vision {model}: {e}")
                continue
        return self.hoi(cau_hoi)

    def reset_lich_su(self):
        self.lich_su = []

if __name__ == "__main__":
    print("Hệ thống core tư vấn tuyển sinh đa tầng bất tử đã được nạp thành công.")

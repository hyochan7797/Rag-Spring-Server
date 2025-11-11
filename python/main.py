import uvicorn
from fastapi import FastAPI, Response
from pydantic import BaseModel
import google.generativeai as genai
import os
import json
from typing import List, Dict, Optional
import re
from typing import List, Dict, Optional, Union
# 1. RAG 파이프라인 (GPT Rerank 모듈) 임포트
from rag_pipeline import search_similar_docs 
from fastapi.middleware.cors import CORSMiddleware

# =========================================
# [중요] FastAPI 앱 초기화
# =========================================
app = FastAPI()
chat_histories = {}

# --- [개선된] 자동 필터링 엔진 (정규표현식 기반) ---
BANK_PATTERNS = {
    r"우리\s*은행": "우리은행",
    r"신한\s*은행": "신한은행",
    r"국민\s*은행": "국민은행",
    r"kb\s*은행": "국민은행",
    r"하나\s*은행": "하나은행",
    r"기업\s*은행": "기업은행",
}

TYPE_PATTERNS = {
    r"신용\s*대출": "sinyoung",
    r"마이너스\s*통장": "sinyoung",
    r"마통": "sinyoung",
    r"담보\s*대출": "dambo",
    r"주택\s*담보": "dambo",
    r"주담대": "dambo",
    r"아파트\s*담보": "dambo",
    r"전세\s*자금": "dambo",
    r"전세\s*대출": "dambo"
}

def extract_filters_from_query(query: str):
    """
    [개선] 문맥을 고려하여 더 스마트하게 필터를 추출합니다.
    """
    extracted_banks = []
    extracted_types = []

    # 1. 은행 키워드 검색
    for pattern, bank_name in BANK_PATTERNS.items():
        if re.search(pattern, query, re.IGNORECASE):
            if bank_name not in extracted_banks:
                extracted_banks.append(bank_name)
    
    # 2. 대출 종류 키워드 검색
    for pattern, loan_type in TYPE_PATTERNS.items():
        if re.search(pattern, query, re.IGNORECASE):
            if loan_type not in extracted_types:
                extracted_types.append(loan_type)

    # 3. '직장인' 키워드 문맥 처리 (담보가 없을 때만 신용대출로 간주)
    if re.search(r"직장인", query, re.IGNORECASE):
        if "dambo" not in extracted_types:
             if "sinyoung" not in extracted_types:
                 extracted_types.append("sinyoung")

    return extracted_banks if extracted_banks else None, \
           extracted_types if extracted_types else None


# 2. Gemini Client 초기화
try:
    google_api_key = os.getenv("GOOGLE_API_KEY")
    if not google_api_key:
        # 로컬 개발을 위한 .env 로드 시도
        from dotenv import load_dotenv
        load_dotenv("/app/.env")
        google_api_key = os.getenv("GOOGLE_API_KEY")
        
    if google_api_key:
        genai.configure(api_key=google_api_key)
        generation_model = genai.GenerativeModel('gemini-2.5-flash')
        print("✅ [main.py] Gemini(답변 생성용) 설정 완료.")
    else:
         print("⚠️ [main.py] GOOGLE_API_KEY 없음.")
         generation_model = None
except Exception as e:
    print(f"⚠️ [main.py] Gemini 초기화 오류: {e}")
    generation_model = None

class ChatRequest(BaseModel):
    user_id: Union[str, int]
    question: str
    allowed_banks: Optional[List[str]] = None
    allowed_loan_types: Optional[List[str]] = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_header(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.post("/chat")
def ask_chat(query: ChatRequest):
    user_id = str(query.user_id)
    question = query.question

    # --- 자동 필터링 적용 ---
    final_banks = query.allowed_banks
    final_types = query.allowed_loan_types

    if final_banks is None and final_types is None:
         auto_banks, auto_types = extract_filters_from_query(question)
         if final_banks is None: final_banks = auto_banks
         if final_types is None: final_types = auto_types
         
         if auto_banks or auto_types:
             print(f"🤖 자동 필터 적용: 은행={final_banks}, 종류={final_types}")

    # --- 대화 히스토리 관리 ---
    if user_id not in chat_histories:
        chat_histories[user_id] = []
    history = chat_histories[user_id]
    history.append({"role": "user", "content": question})

    # --- Step 1: RAG 파이프라인 호출 (검색 + 1차 평가) ---
    top_docs, top_scores = search_similar_docs(
        history_list=history,
        query=question,
        allowed_banks=final_banks,
        allowed_types=final_types
    )

    if not top_docs:
        return {"answer": "죄송합니다. 해당 조건에 맞는 대출 상품 정보를 찾을 수 없습니다."}

    # --- Step 2: Gemini 호출 (교차 검증 + 최종 답변 생성) ---
    context_str = ""
    for i, (doc, gpt_score) in enumerate(zip(top_docs, top_scores)):
        context_str += f"\n[청크 {i}] (GPT점수: {gpt_score}점)\n{doc}\n"

    system_prompt = f"""
당신은 유능한 은행원입니다. 고객의 질문에 친절하게 답변해주세요.
반드시 아래 [제공된 청크]만을 기반으로 답변해야 합니다.
[제공된 청크]에 없는 내용은 절대로 지어내지 말고, "죄송하지만 제가 가진 정보로는 확인이 어렵습니다"라고 솔직하게 말해주세요.

---
[중요] 답변 작성 규칙 (2-Step Verification):
1. 당신도 이 청크들이 질문과 얼마나 관련이 있는지 1~10점으로 평가하세요 (Gemini 점수).
2. [GPT점수]와 당신의 [Gemini 점수]의 평균을 계산하세요.
3. 평균 점수가 3점 미만인 청크는 '근거 없는 정보'로 간주하고 답변에서 완전히 배제하세요.
4. 답변의 맨 마지막에 반드시 [AI 신뢰도 코멘트]를 한 줄 추가해주세요:
   - 평균 9~10점 청크 사용 시: "✨ AI 신뢰도: 매우 높음 (확실한 문서 기반)"
   - 평균 7~8점 청크 사용 시: "✅ AI 신뢰도: 높음 (관련 문서 기반)"
   - 평균 3~6점 청크 사용 시: "⚠️ AI 신뢰도: 보통 (일부 관련성 낮은 정보 포함 가능)"
   - 모든 청크가 3점 미만일 시: "❌ AI 신뢰도: 낮음 (관련 정보 없음)" 이라고만 답변하고 내용은 출력하지 마세요.

[제공된 청크]:
{context_str}
"""

    messages = [
        {"role": "user", "parts": [system_prompt + "\n\n고객 질문: " + question]}
    ]

    try:
        response = generation_model.generate_content(messages)
        final_answer = response.text
        
        history.append({"role": "model", "content": final_answer})
        return {"answer": final_answer}

    except Exception as e:
        print(f"⚠️ Gemini 답변 생성 중 오류: {e}")
        return {"answer": "죄송합니다. 답변을 생성하는 도중 오류가 발생했습니다."}
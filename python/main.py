import uvicorn
from fastapi import FastAPI, Response
from pydantic import BaseModel
import google.generativeai as genai
import os
import json
from typing import List, Dict, Optional, Union
import re
from fastapi.middleware.cors import CORSMiddleware
import asyncio  
# [중요] 아까 수정한 로컬 리랭커 포함된 검색 모듈 임포트
# rag_pipeline.py 파일이 같은 폴더에 있어야 합니다.
from rag_pipeline import search_similar_docs 

# =========================================
# FastAPI 앱 초기화
# =========================================
app = FastAPI()
chat_histories = {}

# --- 자동 필터링 엔진 (정규표현식 기반) ---
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
    사용자 질문에서 은행명과 대출 종류를 자동으로 추출합니다.
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

    # 3. '직장인' 키워드 문맥 처리 (담보 관련 말이 없으면 신용대출로 간주)
    if re.search(r"직장인", query, re.IGNORECASE):
        if "dambo" not in extracted_types and "sinyoung" not in extracted_types:
             extracted_types.append("sinyoung")

    return extracted_banks if extracted_banks else None, \
           extracted_types if extracted_types else None


# Gemini Client 초기화
try:
    google_api_key = os.getenv("GOOGLE_API_KEY")
    if not google_api_key:
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
async def ask_chat(query: ChatRequest):
    user_id = str(query.user_id)
    question = query.question

    # --- 1. 자동 필터링 적용 ---
    final_banks = query.allowed_banks
    final_types = query.allowed_loan_types

    if final_banks is None and final_types is None:
         auto_banks, auto_types = extract_filters_from_query(question)
         if final_banks is None: final_banks = auto_banks
         if final_types is None: final_types = auto_types
         
         if auto_banks or auto_types:
             print(f"🤖 자동 필터 적용: 은행={final_banks}, 종류={final_types}")

    # --- 2. 대화 히스토리 관리 ---
    if user_id not in chat_histories:
        chat_histories[user_id] = []
    history = chat_histories[user_id]
    history.append({"role": "user", "content": question})

    # --- 3. RAG 파이프라인 호출 (검색 + 리랭킹) ---
    # 여기서 돌아오는 top_docs는 이미 BGE-Reranker가 검증을 끝낸 상위 3개 문서입니다.
    # top_scores는 리랭커가 매긴 점수입니다 (예: 2.5, -1.2 등)
    top_docs, top_scores = await search_similar_docs(
        history_list=history,
        query=question,
        allowed_banks=final_banks,
        allowed_types=final_types
    )

    if not top_docs:
        return {"answer": "죄송합니다. 해당 조건에 맞는 대출 상품 정보를 찾을 수 없습니다."}

    # [안전장치] 리랭커 점수가 너무 낮으면(관련성 없음) 답변 거부
    # BGE-Reranker 점수 기준: 보통 0점 이하면 관련성이 매우 떨어지는 것임 (상황에 따라 조절 가능)
    if top_scores[0] < -2.0: 
        print(f"⚠️ 최고 점수가 너무 낮음({top_scores[0]}). 답변 거부.")
        return {"answer": "죄송합니다. 질문하신 내용과 관련된 정보를 문서에서 찾을 수 없습니다."}


    # --- 4. Gemini 프롬프트 구성 (단순화됨) ---
    context_str = ""
    for i, doc in enumerate(top_docs):
        # 점수는 Gemini에게 보여주지 않아도 됩니다. (이미 검증됨)
        context_str += f"\n[참고 문서 {i+1}]:\n{doc}\n"

    system_prompt = f"""
당신은 금융 상품 전문 상담 AI입니다. 고객의 질문에 대해 아래 [참고 문서]를 바탕으로 정확하고 친절하게 답변해주세요.

[답변 작성 원칙]
1. **사실 기반:** 반드시 아래 제공된 [참고 문서]에 있는 내용만 포함하세요. 문서에 없는 내용은 "확인되지 않습니다"라고 답하세요.
2. **구조적 답변:** 읽기 편하게 불렛 포인트 등을 활용해 정리해주세요.
3. **거짓 정보 방지:** 사용자가 묻지 않은 내용을 굳이 지어내지 마세요.
4. **출처 명시 불필요:** [참고 문서 1]과 같이 언급할 필요는 없습니다. 자연스럽게 말하세요.

[참고 문서]:
{context_str}
"""

    messages = [
        {"role": "user", "parts": [system_prompt + "\n\n고객 질문: " + question]}
    ]

    try:
        # Gemini 호출
        response = generation_model.generate_content(messages)
        final_answer = response.text
        
        # --- 5. 신뢰도 꼬리표 붙이기 (자동) ---
        # 리랭커 점수가 높으면 신뢰도 높음 표시
        reliability_msg = ""
        best_score = top_scores[0]
        
        if best_score > 0.5:
            reliability_msg = "\n\n✨ AI 신뢰도: 매우 높음 (정확한 관련 문서 발견)"
        elif best_score > -1.0:
            reliability_msg = "\n\n✅ AI 신뢰도: 높음 (관련 문서 참고함)"
        else:
            reliability_msg = "\n\n⚠️ AI 신뢰도: 보통 (문서 내용이 충분하지 않을 수 있음)"
            
        final_response = final_answer + reliability_msg

        history.append({"role": "model", "content": final_response})
        return {"answer": final_response}

    except Exception as e:
        print(f"⚠️ Gemini 답변 생성 중 오류: {e}")
        return {"answer": "죄송합니다. 답변을 생성하는 도중 오류가 발생했습니다."}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
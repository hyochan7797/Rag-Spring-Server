import uvicorn
from fastapi import FastAPI, Response, Header, HTTPException
from pydantic import BaseModel
import google.generativeai as genai
import os
import json
from typing import List, Dict, Optional, Union, Any
import re
from fastapi.middleware.cors import CORSMiddleware
import asyncio  
# [중요] 아까 수정한 로컬 리랭커 포함된 검색 모듈 임포트
# rag_pipeline.py 파일이 같은 폴더에 있어야 합니다.
from rag_pipeline import search_similar_docs, refresh_vectorstore
from fss_crawler import crawl_all

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


async def rewrite_query(question: str, history: list) -> str:
    """
    모호한 사용자 질문을 검색에 최적화된 쿼리로 변환.
    - 대화 맥락(이전 user 메시지)을 반영하여 생략된 정보를 보완
    - 검색에만 사용; 답변 생성은 원본 question을 유지
    """
    if generation_model is None:
        return question

    # 현재 질문 제외, 이전 user 메시지 최대 3개 추출
    prev_user_msgs = [m["content"] for m in history if m["role"] == "user"]
    context_str = " / ".join(prev_user_msgs[-4:-1]) if len(prev_user_msgs) > 1 else ""

    prompt = f"""금융 대출 상품 검색 시스템의 검색 쿼리 최적화 전문가입니다.
아래 [이전 대화]와 [현재 질문]을 분석하여, 벡터 DB와 BM25 키워드 검색에 최적화된 단일 검색 쿼리를 생성하세요.

[변환 규칙]
1. 모호한 표현을 구체적인 금융 용어로 변환 (예: "싼 곳" → "최저금리 대출", "빌리다" → "대출 신청")
2. 이전 대화에서 언급된 은행명·대출종류·조건을 현재 질문에 자연스럽게 통합
3. 검색 쿼리는 핵심 키워드 중심의 1~2문장
4. 원래 질문의 의도를 반드시 유지할 것
5. 한국어로만 출력

[이전 대화]: {context_str if context_str else "없음"}
[현재 질문]: {question}

검색 쿼리만 출력 (설명·부연 없이):"""

    try:
        resp = await asyncio.to_thread(generation_model.generate_content, prompt)
        rewritten = resp.text.strip().strip('"').strip("'")
        if rewritten and rewritten != question:
            print(f"🔄 쿼리 재작성: '{question}' → '{rewritten}'")
            return rewritten
    except Exception as e:
        print(f"⚠️ 쿼리 재작성 실패, 원본 사용: {e}")
    return question


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
    history: Optional[List[Dict[str, str]]] = None  # Spring이 MySQL에서 꺼내 전달

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

    # --- 2. 대화 히스토리 ---
    # Spring이 MySQL 히스토리를 실어 보내면 그걸 사용 (재시작해도 유지)
    # 없으면 인메모리 fallback (로컬 단독 실행 시)
    if query.history is not None:
        history = list(query.history) + [{"role": "user", "content": question}]
    else:
        if user_id not in chat_histories:
            chat_histories[user_id] = []
        history = chat_histories[user_id]
        history.append({"role": "user", "content": question})

    # --- 3. 쿼리 재작성 (검색 품질 향상) ---
    # 재작성된 쿼리는 검색에만 사용; 답변 생성은 원본 question 유지
    rewritten = await rewrite_query(question, history)

    # --- 4. RAG 파이프라인 호출 (검색 + 리랭킹) ---
    top_docs, top_scores = await search_similar_docs(
        history_list=history,
        query=question,
        allowed_banks=final_banks,
        allowed_types=final_types,
        rewritten_query=rewritten,
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

        # 인메모리 fallback 사용 중일 때만 응답 저장 (Spring 경유 시 MySQL에 저장됨)
        if query.history is None:
            history.append({"role": "model", "content": final_response})
        return {"answer": final_response}

    except Exception as e:
        print(f"⚠️ Gemini 답변 생성 중 오류: {e}")
        return {"answer": "죄송합니다. 답변을 생성하는 도중 오류가 발생했습니다."}

@app.post("/admin/refresh")
async def refresh_vectors(x_admin_key: str = Header(...)):
    """FSS API에서 최신 대출 데이터를 수집해 Qdrant 벡터 갱신 (Spring Batch가 호출)"""
    admin_key = os.getenv("ADMIN_API_KEY")
    if not admin_key or x_admin_key != admin_key:
        raise HTTPException(status_code=403, detail="인증 실패")

    print("🚀 [admin/refresh] FSS 크롤링 시작...")
    try:
        new_docs, new_metas = await crawl_all()
        if not new_docs:
            return {"status": "error", "message": "수집된 데이터 없음"}

        success = await refresh_vectorstore(new_docs, new_metas)
        if success:
            return {"status": "ok", "chunks": len(new_docs)}
        else:
            return {"status": "error", "message": "벡터 갱신 실패 — 로그 확인"}
    except Exception as e:
        print(f"⚠️ [admin/refresh] 오류: {e}")
        return {"status": "error", "message": str(e)}


@app.on_event("startup")
async def startup_event():
    import rag_pipeline
    if rag_pipeline.vectorstore is None:
        print("🚀 [startup] Qdrant 데이터 없음 — FSS API 초기 적재 시작...")
        try:
            docs, metas = await crawl_all()
            if docs:
                await refresh_vectorstore(docs, metas)
                print(f"✅ [startup] 초기 적재 완료 ({len(docs)}개 청크)")
            else:
                print("⚠️ [startup] FSS API에서 데이터를 가져오지 못했습니다.")
        except Exception as e:
            print(f"⚠️ [startup] 초기 적재 실패: {e}")
    else:
        print("✅ [startup] 기존 Qdrant 데이터 재사용 — 크롤링 생략")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
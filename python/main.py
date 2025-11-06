import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
import google.generativeai as genai
import os
import json # [신규] Gemini의 JSON 응답 파싱
from typing import List # [신규] 타입 힌트

# 1. RAG 파이프라인 (GPT Rerank 모듈) 임포트
from rag_pipeline import search_similar_docs 
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
chat_histories = {}

# 2. Gemini Client 초기화 (Judge + Generate 용)
try:
    if os.getenv("GOOGLE_API_KEY"):
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
        print("✅ (main.py) Gemini Judge+Generate 모델 설정 완료.")
    else:
        print("⚠️ (main.py) GOOGLE_API_KEY가 없습니다.")
except Exception as e:
    print(f"⚠️ (main.py) Gemini 설정 실패: {e}")

# 3. [신규] Gemini Judge+Generate 모델 정의
try:
    # Gemini가 JSON 응답을 반환하도록 설정
    gemini_json_config = genai.GenerationConfig(response_mime_type="application/json")
    generation_model = genai.GenerativeModel(
        'gemini-2.5-flash', # 형님이 찾아내신 2.5 flash 모델
        generation_config=gemini_json_config
    )
    print("✅ (main.py) Gemini 'gemini-2.5-flash' (JSON 모드) 초기화 완료.")
except Exception as e:
    print(f"⚠️ (main.py) Gemini 'gemini-2.5-flash' 모델 초기화 실패: {e}")
    generation_model = None

# 4. [수정됨] FastAPI 요청/응답 모델
class ChatRequest(BaseModel):
    user_id: int
    question: str
    allowed_types: List[str] = [] # (예: ["신용대출"])
    allowed_banks: List[str] = [] # (예: ["우리은행"])

class ChatResponse(BaseModel):
    answer: str

# 5. [신규] Gemini 프롬프트 헬퍼 (Step 2)
def build_gemini_judge_prompt(query: str, documents: List[str], gpt_scores: List[dict]) -> str:
    """
    [Step 2] Gemini에게 (A)교차 검증, (B)답변 생성, (C)점수 코멘트 생성을
    한 번에 JSON으로 요청하는 프롬프트를 생성합니다.
    """
    
    # GPT 점수 리스트를 [문서 N]에 매핑
    doc_with_gpt_score_str = ""
    for i, doc in enumerate(documents):
        # gpt_scores 리스트에서 현재 인덱스(i)에 해당하는 점수 찾기
        gpt_score_item = next((item for item in gpt_scores if item.get("index") == i), None)
        gpt_score = gpt_score_item.get("relevance_score") if gpt_score_item else "N/A"
        
        doc_with_gpt_score_str += f"\n\n[문서 {i} (GPT 점수: {gpt_score})]:\n{doc}"

    system_prompt = f"""
당신은 '금융 상품 전문가'이자 'RAG 파이프라인 평가자'입니다.
당신의 임무는 (A)GPT의 평가를 교차 검증하고, (B)3점 미만 문서를 제거하고, (C)최종 답변을 생성하고, (D)점수 코멘트를 JSON으로 반환하는 것입니다.

[지시사항]
1.  아래 [후보 문서 목록]을 [사용자 질문]과 비교하여 **당신(Gemini)의 'gemini_score' (1~10점)를 매기세요.**
2.  당신의 'gemini_score'와 [문서]에 적힌 'GPT 점수'의 **평균('average_score')을 계산하세요.** (GPT 점수가 N/A이면 gemini_score를 평균으로 사용)
3.  'average_score'가 **3점 미만인 문서는 '근거 없는 주장'으로 간주하여 필터링**합니다.
4.  **필터링(3점 이상)을 통과한 문서들**만을 기반으로 [사용자 질문]에 대한 [final_answer]를 생성하세요.
5.  필터링(3점 이상)을 통과한 문서들의 'average_score' 중 **가장 높은 점수**를 기준으로 [score_comment]를 생성하세요.
    - 9~10점: "이 답변은 제공된 문서와 정확도 높게 일치합니다."
    - 7~8점: "이 답변은 대부분 문서의 내용을 기반으로 합니다."
    - 3~6점: "이 답변은 일부 문서의 내용을 기반으로 하나, 일부는 근거가 부족할 수 있습니다."
    - (3점 미만 문서는 이미 필터링되어 답변에 사용되지 않음)
    - (필터링 통과한 문서가 없으면, '참고할 만한 문서를 찾지 못했습니다.' 코멘트)

[반환 형식]
반드시 다음 구조의 JSON 객체 하나만 반환하세요:
{{
  "final_answer": "사용자 질문에 대한 최종 답변입니다. (3점 이상 문서 기반)",
  "score_comment": "가장 높은 평균 점수에 대한 코멘트입니다."
}}

---
[사용자 질문]:
{query}

[후보 문서 목록 (GPT 평가 포함)]:
{doc_with_gpt_score_str}
"""
    return system_prompt

# 6. [수정됨] Chat 엔드포인트 (2-Step RAG)
@app.post("/chat", response_model=ChatResponse)
async def ask_chat(request: ChatRequest):
    user_id = request.user_id
    question = request.question

    if not generation_model:
        return ChatResponse(answer="죄송합니다. 답변 생성기 모델이 초기화되지 않았습니다.")

    # 사용자별 대화 히스토리 관리
    if user_id not in chat_histories:
        chat_histories[user_id] = []
    history = chat_histories[user_id]
    history.append({"role": "user", "content": question})

    # --- [Step 1] GPT Rerank (LLM 호출 1) ---
    try:
        # (문서 리스트, GPT 점수 리스트)를 반환받음
        candidate_docs, gpt_scores = search_similar_docs(
            history,
            question,
            top_k=3, # Gemini에게 전달할 최대 문서 개수
            allowed_types=request.allowed_types,
            allowed_banks=request.allowed_banks
        )
    except Exception as e:
        print(f"🔥 /chat 엔드포인트에서 search_similar_docs 호출 중 치명적 오류: {e}")
        return ChatResponse(answer="죄송합니다. 문서를 검색하는 중 오류가 발생했습니다.")

    if not candidate_docs:
        # RAG 파이프라인이 1차 검색(Qdrant)에서 문서를 찾지 못한 경우
        print("ℹ️ (main.py) RAG 1차 검색 결과 0개.")
        answer = "죄송합니다. 관련 상품 정보를 찾을 수 없습니다. (필터 조건 확인)"
        history.append({"role": "assistant", "content": answer})
        return ChatResponse(answer=answer)

    # --- [Step 2] Gemini (Judge + Generate) (LLM 호출 2) ---
    try:
        # Gemini에게 (후보 문서 + GPT 점수)를 전달하여 '2차 평가 + 답변 생성' 요청
        final_prompt = build_gemini_judge_prompt(question, candidate_docs, gpt_scores)
        
        response = generation_model.generate_content(final_prompt)
        
        # Gemini가 반환한 JSON 파싱
        response_json = json.loads(response.text)
        
        final_answer = response_json.get("final_answer", "답변을 생성하지 못했습니다.")
        score_comment = response_json.get("score_comment", "점수 코멘트를 생성하지 못했습니다.")
        
        # 최종 답변에 점수 코멘트 덧붙이기
        answer_with_comment = f"{final_answer}\n\n[신뢰도: {score_comment}]"
        
        print(f"💬 (main.py) Step 2 (Gemini Judge+Generate) 완료.")

    except Exception as e:
        print(f"⚠️ (main.py) Step 2 (Gemini Judge+Generate) 중 오류: {e}")
        # Step 2 실패 시, Step 1의 결과라도 활용 (Fallback)
        context_str = "\n\n---\n\n".join(candidate_docs)
        answer_with_comment = f"""
죄송합니다. 답변을 생성하는 중 오류가 발생했습니다.
참고로, GPT-3.5가 1차로 평가한 관련 문서는 다음과 같습니다:
{context_str}
"""

    # 대화 저장
    history.append({"role": "assistant", "content": answer_with_comment})
    return ChatResponse(answer=answer_with_comment)

# CORS 설정 (이전과 동일)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    print("🚀 FastAPI 서버(2-Step RAG)를 http://127.0.0.1:8000 에서 시작합니다.")
    # (실행 시: uvicorn main:app --host 0.0.0.0 --port 8000)
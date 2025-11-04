import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
import google.generativeai as genai
import os

# 1. RAG 파이프라인 (문서 검색기) 임포트
# (rag_pipeline.py 파일이 같은 디렉토리에 있다고 가정)
from rag_pipeline import search_similar_docs 
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
chat_histories = {}

# 2. Gemini Client 초기화 (답변 생성용)
try:
    # .env 파일은 rag_pipeline.py가 시작 시점에 이미 로드함
    google_api_key = os.getenv("GOOGLE_API_KEY")
    if google_api_key:
        genai.configure(api_key=google_api_key)
        # 형님이 찾아내신 gemini-2.5-flash 모델을 답변 생성용으로 설정
        generation_model = genai.GenerativeModel('gemini-2.5-flash') 
        print("✅ (main.py) Gemini 답변 생성기 모델 (gemini-2.5-flash) 설정 완료.")
    else:
        print("⚠️ (main.py) GOOGLE_API_KEY가 없습니다.")
        generation_model = None
except Exception as e:
    print(f"⚠️ (main.py) Gemini 설정 실패: {e}")
    generation_model = None

# 3. 요청 모델 (기존 코드 유지)
class ChatRequest(BaseModel):
    user_id: int
    question: str

# 4. CORS 설정 (기존 코드 유지)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 로컬 테스트용. 실제 배포 시엔 도메인으로 제한
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 5. [신규] 점수 코멘트 생성 헬퍼 함수
def get_score_comment(score: float) -> str:
    """형님이 요청한 점수대별 코멘트를 반환합니다."""
    score = round(score, 1) # 소수점 첫째 자리까지 반올림
    
    if score >= 9:
        return f"평균 {score}점 (높은 정확도)"
    elif score >= 7: # 7.0 ~ 8.9
        return f"평균 {score}점 (대부분 문서 기반)"
    elif score >= 3: # 3.0 ~ 6.9
        return f"평균 {score}점 (일부 근거 없는 주장 포함)"
    else: # 3.0 미만
        return f"평균 {score}점 (근거 없는 주장)"


# 6. [수정됨] Chat 엔드포인트 (코멘트 추가)
@app.post("/chat")
def ask_chat(query: ChatRequest):
    user_id = query.user_id
    question = query.question

    # 사용자별 대화 히스토리 관리 (기존 코드 유지)
    if user_id not in chat_histories:
        chat_histories[user_id] = []
    history = chat_histories[user_id]
    history.append({"role": "user", "content": question})

    # --- [1단계] RAG 파이프라인 호출 (문서 + '점수' 검색) ---
    # [수정] 이제 (context_docs, doc_scores) 두 개의 값을 반환받음
    context_docs, doc_scores = search_similar_docs(history, question, top_k=3)
    context = "\n\n".join(context_docs)
    
    comment = "" # 코멘트 초기화
    
    if not context_docs:
        # [수정] 3점 이상 문서가 없는 경우
        print("ℹ️ (main.py) RAG 결과 0개 (3점 이상 문서 없음). LLM이 자체 지식으로 답변합니다.")
        context = "참고할 만한 관련 문서를 찾지 못했습니다."
        comment = "(답변 근거: 참고 문서 없음)"
    else:
        # [신규] RAG 문서가 있는 경우, 점수 코멘트 생성
        # doc_scores 리스트의 평균 'average_score'를 계산
        avg_score = sum(item['average_score'] for item in doc_scores) / len(doc_scores)
        comment = f"(답변 근거: {get_score_comment(avg_score)})"
        print(f"ℹ️ (main.py) {comment} 생성됨.")


    if not generation_model:
        return {"answer": "죄송합니다. 답변 생성기 모델(Gemini)이 초기화되지 않았습니다."}
        
    # --- [2단계] Gemini 질의 프롬프트 구성 (동일) ---
    system_prompt = "너는 금융 대출 상담 챗봇이야. 주어진 참고정보를 바탕으로 문맥을 정확히 분석해서 답변해. 참고정보에 내용이 없으면 '정보를 찾을 수 없습니다'라고 답변해."
    
    history_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history[-4:]])
    
    full_prompt = f"""
[최근 대화 내용]
{history_str}

[참고정보]
{context}

[사용자 질문]
{question}

[지시사항]
위 정보를 바탕으로 'assistant'로서 답변을 생성해줘.
"""
    
    # --- [3단계] Gemini 모델 호출 (최종 답변 생성) ---
    try:
        response = generation_model.generate_content(full_prompt)
        answer = response.text.strip()
        
        # [신규] 생성된 답변에 준비된 코멘트를 덧붙임
        final_answer = f"{answer}\n\n{comment}"

    except Exception as e:
        print(f"⚠️ (main.py) Gemini 답변 생성 중 오류: {e}")
        return {"answer": "죄송합니다. 답변을 생성하는 중 오류가 발생했습니다."}

    # 대화 저장 (기존 코드 유지)
    history.append({"role": "assistant", "content": final_answer}) # 코멘트가 포함된 답변 저장
    return {"answer": final_answer}


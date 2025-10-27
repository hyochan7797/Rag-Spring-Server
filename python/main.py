from fastapi import FastAPI
from pydantic import BaseModel
from rag_pipeline import get_embedding, search_similar_docs, documents, client
from fastapi.middleware.cors import CORSMiddleware
app = FastAPI()
chat_histories = {}

class ChatRequest(BaseModel):
    user_id: int
    question: str
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 로컬 테스트용. 운영 시 도메인 지정
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
@app.post("/chat")
def ask_chat(query: ChatRequest):
    user_id = query.user_id
    question = query.question

    if user_id not in chat_histories:
        chat_histories[user_id] = []
    history = chat_histories[user_id]
    history.append({"role": "user", "content": question})

    context_docs = search_similar_docs(history, question)
    context = "\n\n".join(context_docs)
    if not context.strip():
        return {"answer": "죄송합니다. 현재 제공 가능한 대출 상품 정보가 없습니다."}

    messages = [
        {"role": "system", "content": "너는 금융 대출 상담 챗봇이야. 문맥을 정확히 분석해서 답변해."},
        *history[-4:],
        {"role": "user", "content": f"참고정보:\n{context}\n\n질문: {question}"}
    ]

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=messages
    )
    answer = response.choices[0].message.content.strip()
    history.append({"role": "assistant", "content": answer})
    return {"answer": answer}

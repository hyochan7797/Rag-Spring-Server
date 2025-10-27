import pandas as pd
import numpy as np
import faiss
from openai import OpenAI
import os
import chardet
from tqdm import tqdm

# ===== CSV 경로 =====
credit_csv = "/app/data/sinyoung.csv"
dambo_csv = "/app/data/dambo.csv"

# ===== FAISS 인덱스 경로 =====
DATA_DIR = "/data"
os.makedirs(DATA_DIR, exist_ok=True)
index_file_path = os.path.join(DATA_DIR, "faiss_index.index")

# ===== OpenAI 클라이언트 =====
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY 환경변수가 설정되어 있지 않습니다.")
client = OpenAI(api_key=api_key)

# ===== CSV 로드 =====
def detect_encoding(file_path):
    with open(file_path, "rb") as f:
        raw = f.read(10000)
    return chardet.detect(raw)["encoding"]

df_credit = pd.read_csv(credit_csv, encoding=detect_encoding(credit_csv))
df_dambo = pd.read_csv(dambo_csv, encoding=detect_encoding(dambo_csv))
df_all = pd.concat([df_credit, df_dambo], ignore_index=True).fillna("")

# ===== 문서 구성 =====
def build_documents(df):
    docs = []
    for _, row in df.iterrows():
        doc = f"""
[loan_type] {row.get('loan_type', '')}
[상품명] {row.get('상품명', '')}
[담보] {row.get('담보', '')}
[상품특징] {row.get('상품특징', '')}
[대출신청자격] {row.get('대출신청자격', '')}
[대출금액] {row.get('대출금액', '')}
[대출기간 및 상환 방법] {row.get('대출기간 및 상환 방법', '')}
[대출금리] {row.get('대출금리', '')}
[중도상환 수수료] {row.get('중도상환 수수료', '')}
[금리인하요구권 대상 여부] {row.get('금리인하요구권 대상 여부', '')}
[연체이자] {row.get('연체이자(지연배상금) 관련 사항', '')}
[고객 유의사항] {row.get('고객께서 알아두셔야 할 사항', '')}
""".strip()
        docs.append({"text": doc, "metadata": {"상품명": row.get("상품명", ""), "loan_type": row.get("loan_type", "")}})
    return docs

documents = build_documents(df_all)

# ===== 임베딩 함수 =====
def get_embedding(text):
    response = client.embeddings.create(model="text-embedding-ada-002", input=text)
    return response.data[0].embedding

# ===== FAISS 인덱스 로드/생성 =====
if os.path.exists(index_file_path):
    print("기존 FAISS 인덱스 로드 중...")
    index = faiss.read_index(index_file_path)
else:
    print("FAISS 인덱스 생성 중...")
    embeddings = [get_embedding(doc["text"]) for doc in tqdm(documents)]
    dimension = len(embeddings[0])
    index = faiss.IndexFlatL2(dimension)
    index.add(np.array(embeddings).astype("float32"))
    faiss.write_index(index, index_file_path)
    print(f"FAISS 인덱스 저장 완료: {index_file_path}")

# ===== 문서 검색 =====
def search_similar_docs(history_list, query, top_k=2, max_chars=1500):
    recent_context = " ".join([msg["content"] for msg in history_list[-4:] if msg["role"] == "user"])
    full_query = (recent_context + " " + query).strip()
    if not full_query:
        return []
    query_embedding = get_embedding(full_query)
    D, I = index.search(np.array([query_embedding]).astype("float32"), top_k)
    return [documents[i]["text"][:max_chars] for i in I[0]]
import pandas as pd
import numpy as np
import chardet
from tqdm import tqdm
from dotenv import load_dotenv
import os
from openai import OpenAI
from qdrant_client import QdrantClient
from collections import Counter
from qdrant_client.http.models import FieldCondition, Filter, MatchValue, MatchAny
from langchain_qdrant import Qdrant
from langchain_openai import OpenAIEmbeddings
import json
import google.generativeai as genai 
from typing import List, Tuple, Dict, Optional

# =KST======================
# 1️⃣ 환경 설정 로드
# =======================
dotenv_path = "/app/.env"
print(f"🔍 Loading .env from: {dotenv_path}")

if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path, override=True)
else:
    print("⚠️ .env 파일을 찾을 수 없습니다. OS 환경 변수를 사용합니다.")

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
api_key = os.getenv("OPENAI_API_KEY")
qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
collection_name = os.getenv("COLLECTION_NAME", "loan_docs")
google_api_key = os.getenv("GOOGLE_API_KEY")

if google_api_key:
    try:
        genai.configure(api_key=google_api_key)
        print("✅ Google Gemini API 설정 완료.")
    except Exception as e:
        print(f"⚠️ Google Gemini API 설정 실패: {e}")
        google_api_key = None 
else:
    print("ℹ️ GOOGLE_API_KEY가 설정되지 않았습니다.")

if not api_key:
    raise ValueError("OPENAI_API_KEY 환경변수가 설정되어 있지 않습니다.")

# =======================
# 2️⃣ CSV 로드
# =======================
LOAN_DATA_MAP = {
    "sinyoung": "/app/data/sinyoung.csv",
    "dambo": "/app/data/dambo.csv",
}

def detect_encoding(file_path):
    try:
        with open(file_path, "rb") as f:
            raw = f.read(10000)
        return chardet.detect(raw)["encoding"]
    except FileNotFoundError:
        return None
    except Exception:
        return "utf-8" 

def load_manual_loan_data(data_map: Dict[str, str]) -> pd.DataFrame:
    all_dfs = []
    for default_loan_type, file_path in data_map.items():
        if not os.path.exists(file_path):
            print(f"⚠️ [경고] 파일을 찾을 수 없습니다: {file_path}. 건너뜁니다.")
            continue
        encoding = detect_encoding(file_path)
        if not encoding: continue
        try:
            df = pd.read_csv(file_path, encoding=encoding)
            if 'loan_type' not in df.columns:
                df['loan_type'] = default_loan_type
            all_dfs.append(df)
            print(f"  ✅ '{os.path.basename(file_path)}' 로드 완료 ({len(df)}개)")
        except Exception as e:
            print(f"  ⚠️ '{os.path.basename(file_path)}' 로드 실패: {e}")

    if not all_dfs:
        raise FileNotFoundError("로드할 수 있는 CSV 파일이 없습니다.")
    return pd.concat(all_dfs, ignore_index=True).fillna("")

df_all = load_manual_loan_data(LOAN_DATA_MAP)
print(f"📊 총 {len(df_all)}개의 데이터 로드 완료.")

# =======================
# 3️⃣ 문서 및 메타데이터 구성 (시맨틱 청킹)
# =======================
def build_documents_with_semantic_chunking(df):
    docs = []
    metadatas = []
    
    if 'loan_type' not in df.columns: df['loan_type'] = df.get('상품명', '기타')
    if 'bank_name' not in df.columns: df['bank_name'] = '알수없음'

    def aggressive_normalize_type(val):
        val_str = str(val).strip()
        if "신용" in val_str: return "sinyoung"
        if "담보" in val_str: return "dambo"
        return val_str

    df['loan_type'] = df['loan_type'].apply(aggressive_normalize_type)
    print(f"🔍 [디버깅] 최종 변환된 loan_type: {df['loan_type'].unique().tolist()}")

    bank_counter = Counter()
    type_counter = Counter()

    for _, row in tqdm(df.iterrows(), total=df.shape[0], desc="시맨틱 청킹 중"):
        bank_name = str(row.get('bank_name') or '알수없음').strip()
        loan_type = str(row.get('loan_type') or '기타').strip()
        product_name = str(row.get('상품명') or '알수없음').strip()

        bank_counter[bank_name] += 1
        type_counter[loan_type] += 1

        common_header = f"[bank_name] {bank_name}\n[loan_type] {loan_type}\n[상품명] {product_name}"
        common_metadata = {"loan_type": loan_type, "product_name": product_name, "bank_name": bank_name}

        docs.append(f"{common_header}\n[상품특징] {row.get('상품특징') or '내용 없음'}\n[담보] {row.get('담보') or '내용 없음'}".strip())
        metadatas.append({**common_metadata, "chunk_type": "특징"})
        docs.append(f"{common_header}\n[대출신청자격] {row.get('대출신청자격') or '내용 없음'}".strip())
        metadatas.append({**common_metadata, "chunk_type": "자격"})
        docs.append(f"{common_header}\n[대출금액] {row.get('대출금액') or '내용 없음'}\n[대출기간 및 상환 방법] {row.get('대출기간 및 상환 방법') or '내용 없음'}".strip())
        metadatas.append({**common_metadata, "chunk_type": "한도/기간"})
        docs.append(f"{common_header}\n[대출금리] {row.get('대출금리') or '내용 없음'}\n[중도상환 수수료] {row.get('중도상환 수수료') or '내용 없음'}".strip())
        metadatas.append({**common_metadata, "chunk_type": "금리/비용"})
        docs.append(f"{common_header}\n[고객 유의사항] {row.get('고객께서 알아두셔야 할 사항') or '내용 없음'}\n[연체이자] {row.get('연체이자(지연배상금) 관련 사항') or '내용 없음'}".strip())
        metadatas.append({**common_metadata, "chunk_type": "유의사항"})
        
    print("\n📊 [최종 데이터 적재 통계]")
    print(f"   🏦 은행: {dict(bank_counter)}")
    print(f"   📑 종류: {dict(type_counter)}")
    print("-" * 50)

    return docs, metadatas

documents, metadatas = build_documents_with_semantic_chunking(df_all)
print(f"📄 시맨틱 청킹 완료: 총 {len(documents)}개 청크 생성됨.")

# =======================
# 4️⃣ Qdrant 연결 및 벡터 저장
# =======================
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
client = QdrantClient(url=qdrant_url)
vectorstore = None

try:
    collections = [c.name for c in client.get_collections().collections]
    print(f"🆕 Qdrant 컬렉션 데이터 적재 (덮어쓰기): {collection_name}")
    vectorstore = Qdrant.from_texts(
        texts=documents,
        embedding=embeddings,
        metadatas=metadatas,
        url=qdrant_url,
        collection_name=collection_name,
        force_recreate=True, 
    )
    print("✅ 컬렉션 생성 및 데이터 저장 완료.")
except Exception as e:
    print(f"⚠️ Qdrant 초기화 오류: {e}")
    vectorstore = None

# =======================
# 5️⃣ Rerank 함수 (GPT-3.5)
# =======================
def _rerank_with_gpt(query: str, documents: List[str]) -> List[Dict]:
    if not documents: return []
    documents_str = ""
    for i, doc in enumerate(documents): documents_str += f"\n\n[문서 {i}]:\n{doc}" 
    
    system_prompt = """
당신은 '관련성 평가 전문가'입니다.
주어진 '사용자 쿼리'에 대해 '문서 목록'이 얼마나 적절한지 평가하세요.
반드시 "rankings"라는 단일 키를 가진 JSON 객체를 반환해야 합니다.
"rankings" 값은 다음 객체들의 리스트입니다:
{"index": 문서인덱스(int), "relevance_score": 관련성점수(1~10, int)}
"""
    user_prompt = f"[쿼리]: {query}\n[문서 목록]:{documents_str}\nJSON을 반환하세요."

    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo-1106", 
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        data = json.loads(response.choices[0].message.content)
        rankings = data.get("rankings", [])
        return sorted(rankings, key=lambda x: x["relevance_score"], reverse=True)
    except Exception as e:
        print(f"⚠️ GPT Rerank 오류: {e}")
        return [{"index": i, "relevance_score": 5} for i in range(len(documents))]

# =======================
# 7️⃣ 검색 함수 (필터 키 수정됨!)
# =======================
def search_similar_docs(
    history_list, query, allowed_banks: Optional[List[str]] = None, allowed_types: Optional[List[str]] = None
) -> Tuple[List[str], List[float]]:
    
    if vectorstore is None:
        print("⚠️ Qdrant 연결 실패 상태입니다.")
        return [], []

    recent_context = " ".join([msg["content"] for msg in history_list[-2:] if msg["role"] == "user"])
    full_query = (recent_context + " " + query).strip()

    filters = []
    # [핵심 수정] 'metadata.' 접두사 추가!
    if allowed_banks:
        print(f"🔎 [필터 ON] 은행: {allowed_banks}")
        filters.append(FieldCondition(key="metadata.bank_name", match=MatchAny(any=allowed_banks)))
    else:
        print("⚪ [필터 SKIP] 은행 필터 없음")

    if allowed_types:
        print(f"🔎 [필터 ON] 종류: {allowed_types}")
        filters.append(FieldCondition(key="metadata.loan_type", match=MatchAny(any=allowed_types)))
    else:
        print("⚪ [필터 SKIP] 종류 필터 없음")
    
    qdrant_filter = Filter(must=filters) if filters else None
    
    try:
        search_results = vectorstore.similarity_search_with_score(
            full_query, k=15, filter=qdrant_filter
        )
        print(f"🚚 1차 검색 결과: {len(search_results)}개 문서 발견")
    except Exception as e:
        print(f"⚠️ Qdrant 검색 중 오류 발생: {e}")
        return [], []

    if not search_results and qdrant_filter:
        print("\n🚨 [긴급 디버깅] 필터 때문에 결과가 0개입니다! 필터 끄고 DB 실태조사 합니다...")
        try:
            debug_results = vectorstore.similarity_search_with_score(full_query, k=3)
            if not debug_results:
                print("💀 [충격] 필터를 껐는데도 데이터가 없습니다. DB가 비어있습니다!")
            else:
                print("🧐 [DB 실태조사 결과] (이 메타데이터가 필터와 왜 안 맞는지 확인하세요!)")
                for i, (doc, score) in enumerate(debug_results):
                    meta = getattr(doc, 'metadata', '메타데이터 없음')
                    print(f"   📄 [문서 {i}] 메타데이터: {meta}")
                print("-" * 50)
        except Exception as e:
             print(f"⚠️ 디버깅 검색 중 오류: {e}")
        return [], []

    if not search_results:
        return [], []

    candidate_docs = [doc.page_content for doc, _ in search_results]
    gpt_rankings = _rerank_with_gpt(full_query, candidate_docs)
    
    final_docs = []
    final_scores = []
    for rank in gpt_rankings:
        idx = rank["index"]
        if idx < len(candidate_docs):
            final_docs.append(candidate_docs[idx])
            final_scores.append(rank["relevance_score"])
            
    return final_docs, final_scores
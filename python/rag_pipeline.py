import pandas as pd
import numpy as np
import chardet
from tqdm import tqdm
from dotenv import load_dotenv
import os
from qdrant_client import QdrantClient
from collections import Counter
from qdrant_client.http.models import FieldCondition, Filter, MatchValue, MatchAny
from langchain_qdrant import Qdrant
from langchain_openai import OpenAIEmbeddings
import json
import google.generativeai as genai 
from typing import List, Tuple, Dict, Optional
# [NEW] 로컬 AI 모델 준비
import torch
import asyncio
from sentence_transformers import CrossEncoder

print("🚀 로컬 리랭커(BGE-Reranker) 모델 로딩 중...")
device = "cuda" if torch.cuda.is_available() else "cpu"
# 금융 문서는 기니까 max_length=1024로 설정
reranker_model = CrossEncoder('BAAI/bge-reranker-v2-m3', max_length=1024, device=device)
# =KST======================
# 1️⃣ 환경 설정 로드
# =======================
dotenv_path = "/app/.env"
print(f"🔍 Loading .env from: {dotenv_path}")

if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path, override=True)
else:
    print("⚠️ .env 파일을 찾을 수 없습니다. OS 환경 변수를 사용합니다.")

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
# [변경 후 함수]
def _rerank_local(query: str, documents: List[str], top_k: int = 3) -> Tuple[List[str], List[float]]:
    if not documents: return [], []
    
    # AI가 읽기 편하게 [질문, 답변] 쌍으로 만듦
    model_inputs = [[query, doc] for doc in documents]
    
    # 0.1초 만에 점수 계산 (인터넷 연결 X)
    scores = reranker_model.predict(model_inputs)
    
    # 점수 높은 순서대로 정렬해서 상위 3개만 리턴
    results = sorted(zip(scores, documents), key=lambda x: x[0], reverse=True)
    return [doc for _, doc in results[:top_k]], [score for score, _ in results[:top_k]]
# =======================
# 7️⃣ 검색 함수 (필터 키 수정됨!)
# =======================
async def search_similar_docs(
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
            full_query, k=30, filter=qdrant_filter
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

    
    print("⚡ 리랭킹 수행 중 (Local BGE Model)...")
    
    # asyncio.to_thread를 사용하여 무거운 계산 작업을 메인 루프 밖으로 뺍니다.
    final_docs, final_scores = await asyncio.to_thread(
        _rerank_local, full_query, candidate_docs, top_k=3
    )
    
    return final_docs, final_scores


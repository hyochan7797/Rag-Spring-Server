import pandas as pd
import numpy as np
import chardet
from tqdm import tqdm
from dotenv import load_dotenv
import os
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http.models import FieldCondition, Filter, MatchValue, MatchAny
from langchain_qdrant import Qdrant
from langchain_openai import OpenAIEmbeddings
import json
import google.generativeai as genai 
from typing import List, Tuple, Dict 

# =KST======================
# 1️⃣ 환경 설정 로드
# =======================
dotenv_path = "/app/.env" # [수정] .env 파일 경로 (원래대로 복구)
print(f"🔍 Loading .env from: {dotenv_path}")

if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path, override=True)
else:
    print("⚠️ .env 파일을 찾을 수 없습니다. OS 환경 변수를 사용합니다.")

# --- OpenAI 설정 ---
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
api_key = os.getenv("OPENAI_API_KEY")

# --- Qdrant 설정 ---
qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
collection_name = os.getenv("COLLECTION_NAME", "loan_docs")

# --- Google Gemini 설정 ---
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


print(f"🔑 OPENAI_API_KEY 확인: {api_key[:10] + '...' if api_key else '없음'}")
print(f"🗃️ Qdrant URL: {qdrant_url} / Collection: {collection_name}")

if not api_key:
    raise ValueError("OPENAI_API_KEY 환경변수가 설정되어 있지 않습니다.")

# =======================
# 2️⃣ [수정됨] CSV 로드 (V1: 수동 파일 리스트 방식 + 절대 경로)
# =======================

# [수정] docker-compose.yml이 보장하는 '절대 경로'를 하드코딩합니다.
# (동적 경로 os.path.join 제거 -> `FileNotFoundError` 해결)
LOAN_DATA_MAP = {
    "sinyoung": "/app/data/sinyoung.csv",
    "dambo": "/app/data/dambo.csv",
    # "car": "/app/data/car_loan.csv" # 나중에 이 한 줄만 추가하시면 됩니다.
}

def detect_encoding(file_path):
    """파일 인코딩을 감지합니다."""
    try:
        with open(file_path, "rb") as f:
            raw = f.read(10000)
        return chardet.detect(raw)["encoding"]
    except FileNotFoundError:
        # [수정] 오류 대신 경고만 출력하고 None 반환
        print(f"  ⚠️ [경고] 파일을 찾을 수 없습니다: {file_path}. 건너뜁니다.")
        return None
    except Exception as e:
        print(f"  ⚠️ [경고] 인코딩 감지 중 오류 ({file_path}): {e}")
        return "utf-8" # 기본값으로 대체

def load_manual_loan_data(data_map: Dict[str, str]) -> pd.DataFrame:
    """
    [신규] LOAN_DATA_MAP에 정의된 파일들을 수동으로 로드하고 병합합니다.
    """
    all_dfs = []
    print(f"📂 수동 파일 리스트({len(data_map)}개) 스캔 중...")
    
    for loan_type, file_path in data_map.items():
        encoding = detect_encoding(file_path)
        if not encoding:
            continue # 파일이 없으면 다음 파일로
            
        try:
            df = pd.read_csv(file_path, encoding=encoding)
            
            # 1. loan_type 컬럼 추가 (파일 이름 기준)
            if 'loan_type' not in df.columns:
                df['loan_type'] = loan_type
                
            # 2. bank_name 컬럼 확인 (필수)
            if 'bank_name' not in df.columns:
                print(f"  ⚠️ [경고] '{file_path}'에 'bank_name' 컬럼이 없습니다. 'bank_name' 필터가 작동하지 않습니다.")
                df['bank_name'] = '알수없음' # Fallback
                
            all_dfs.append(df)
            print(f"  ✅ '{file_path}' 로드 완료 (타입: {loan_type}, {len(df)}개 항목)")
        except Exception as e:
            print(f"  ⚠️ '{file_path}' 로드 실패: {e}")

    if not all_dfs:
        # [수정] raise 대신 빈 DataFrame 반환
        print("⚠️ [오류] 로드할 수 있는 CSV 파일이 없습니다.")
        return pd.DataFrame()
        
    df_all = pd.concat(all_dfs, ignore_index=True).fillna("")
    return df_all

df_all = load_manual_loan_data(LOAN_DATA_MAP)

# [수정] FastAPI가 멈추지 않도록, df_all이 비어있으면 raise
if df_all.empty:
    raise FileNotFoundError("데이터 디렉토리에서 로드할 수 있는 데이터가 없습니다.")
print(f"📊 총 {len(df_all)}개의 데이터 로드 완료.")


# =======================
# 3️⃣ [수정됨] "시맨틱 청킹(Semantic Chunking)" 적용
# =======================
def build_documents_with_metadata(df):
    """
    [수정] "시맨틱 청킹"을 적용하여, CSV 1줄(상품)을 
    의미 단위(예: 자격, 금리)로 쪼개어 여러 개의 문서(청크)로 만듭니다.
    """
    docs = []
    metadatas = []
    
    # 필수 컬럼 확인
    required_cols = ['loan_type', 'bank_name', '상품명']
    for col in required_cols:
        if col not in df.columns:
            print(f"⚠️ [경고] '{col}' 컬럼이 CSV에 없습니다. '{col}' 필터가 작동하지 않을 수 있습니다.")
            df[col] = '알수없음' # Fallback

    print(f"🔄 '시맨틱 청킹' 시작... (상품 {len(df)}개)")

    for _, row in tqdm(df.iterrows(), total=df.shape[0], desc="시맨틱 청킹 중"):
        
        # --- 모든 청크에 공통으로 포함될 핵심 정보 ---
        # (검색 시 어떤 상품의 일부인지 식별하기 위함)
        common_header = f"""
[bank_name] {row.get('bank_name', '')}
[loan_type] {row.get('loan_type', '')}
[상품명] {row.get('상품명', '')}
"""
        # --- 공통 메타데이터 ---
        common_metadata = {
            "loan_type": row.get('loan_type', '기타'),
            "product_name": row.get('상품명', '알수없음'),
            "bank_name": row.get('bank_name', '기타')
        }

        # --- 청크 1: 상품 특징 ---
        # (상품의 전반적인 개요)
        chunk_1_text = f"""
{common_header.strip()}
[상품특징] {row.get('상품특징', '내용 없음')}
[담보] {row.get('담보', '내용 없음')}
""".strip()
        docs.append(chunk_1_text)
        metadatas.append({**common_metadata, "chunk_type": "특징"})

        # --- 청크 2: 대출 자격 ---
        # (형님이 찾으시던 "법조인" 같은 특정 자격 요건 검색용)
        chunk_2_text = f"""
{common_header.strip()}
[대출신청자격] {row.get('대출신청자격', '내용 없음')}
""".strip()
        docs.append(chunk_2_text)
        metadatas.append({**common_metadata, "chunk_type": "자격"})

        # --- 청크 3: 금액 및 기간 ---
        # ("최대 5억", "10년 상환" 등 검색용)
        chunk_3_text = f"""
{common_header.strip()}
[대출금액] {row.get('대출금액', '내용 없음')}
[대출기간 및 상환 방법] {row.get('대출기간 및 상환 방법', '내용 없음')}
""".strip()
        docs.append(chunk_3_text)
        metadatas.append({**common_metadata, "chunk_type": "한도/기간"})

        # --- 청크 4: 금리 및 수수료 ---
        # ("고정금리 5%", "중도상환수수료" 등 검색용)
        chunk_4_text = f"""
{common_header.strip()}
[대출금리] {row.get('대출금리', '내용 없음')}
[중도상환 수수료] {row.get('중도상환 수수료', '내용 없음')}
[연체이자] {row.get('연체이자(지연배상금) 관련 사항', '내용 없음')}
""".strip()
        docs.append(chunk_4_text)
        metadatas.append({**common_metadata, "chunk_type": "금리/수수료"})

        # --- 청크 5: 기타 사항 ---
        chunk_5_text = f"""
{common_header.strip()}
[금리인하요구권 대상 여부] {row.get('금리인하요구권 대상 여부', '내용 없음')}
[고객 유의사항] {row.get('고객께서 알아두셔야 할 사항', '내용 없음')}
""".strip()
        docs.append(chunk_5_text)
        metadatas.append({**common_metadata, "chunk_type": "기타"})

    print(f"✅ '시맨틱 청킹' 완료. (상품 {len(df)}개 -> 총 {len(docs)}개 청크 생성)")
    return docs, metadatas


documents, metadatas = build_documents_with_metadata(df_all)
print(f"📄 총 문서(청크) 개수: {len(documents)}, 메타데이터 개수: {len(metadatas)}")

# =======================
# 4️⃣ Qdrant 연결 및 벡터 저장
# =======================
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
client = QdrantClient(url=qdrant_url)
vectorstore = None

try:
    collections_response = client.get_collections()
    collections = [c.name for c in collections_response.collections]
    
    # [주의] 시맨틱 청킹을 적용했으므로, DB를 새로 만들어야 합니다.
    # (force_recreate=True가 이 역할을 하지만, 
    #  docker volume을 삭제하는 것이 가장 확실합니다.)
    
    if collection_name not in collections:
        print(f"🆕 Qdrant 컬렉션 생성: {collection_name}")
        vectorstore = Qdrant.from_texts(
            texts=documents,
            embedding=embeddings,
            metadatas=metadatas,
            url=qdrant_url,
            collection_name=collection_name,
            force_recreate=True,
        )
        print("✅ 컬렉션 생성 및 (청킹된) 데이터 저장 완료.")
    else:
        # [수정] 만약 컬렉션이 이미 있다면, (청킹되지 않은)
        # 이전 데이터일 수 있으므로, 강제로 재생성합니다.
        print(f"⚠️ [경고] 기존 컬렉션 '{collection_name}'을(를) 삭제하고 (청킹된) 데이터로 재생성합니다.")
        client.recreate_collection(
            collection_name=collection_name,
            vectors_config=embeddings.model_name # (이 부분은 모델에 따라 다를 수 있으나, Langchain Qdrant가 보통 알아서 처리)
            # Qdrant.from_texts가 내부적으로 사용하는 벡터 설정에 맞춰야 함
            # 가장 간단한 방법은 그냥 collection을 삭제(down)하고 다시 올리는 것
        )
        vectorstore = Qdrant.from_texts(
            texts=documents,
            embedding=embeddings,
            metadatas=metadatas,
            url=qdrant_url,
            collection_name=collection_name,
            force_recreate=False, # 위에서 이미 삭제했으므로
        )
        print("✅ 기존 컬렉션 재생성 및 (청킹된) 데이터 저장 완료.")

        # (원래 로직: 기존 컬렉션 사용)
        # print(f"✅ 기존 컬렉션 사용: {collection_name}")
        # vectorstore = Qdrant(
        #     client=client,
        #     collection_name=collection_name,
        #     embeddings=embeddings
        # )
        # count_result = client.count(collection_name=collection_name, exact=True)
        # print(f"✅ 기존 컬렉션 로드 완료. (문서 수: {count_result.count})")


except Exception as e:
    print(f"⚠️ Qdrant 초기화 오류: {e}")
    print(f"    Qdrant 서버가 실행 중인지, {qdrant_url} 주소가 올바른지 확인하세요.")
    vectorstore = None

# ==================================
# 5️⃣ LLM as Judge (GPT-3.5)
# ==================================
def _rerank_with_gpt(query: str, documents: list[str]) -> List[Dict]:
    """
    [GPT-3.5]를 Judge(평가자)로 사용하여 문서 목록을 재정렬합니다.
    점수 정보가 포함된 전체 랭킹 리스트(dict)를 반환합니다.
    """
    if not documents:
        return []

    system_prompt = """
당신은 지능이 매우 높은 '관련성 평가 전문가'입니다.
당신의 임무는 주어진 '사용자 쿼리'에 대해 '문서 목록(청크)'이 얼마나 적절하게 답변하는지 평가하는 것입니다.
반드시 "rankings"라는 단일 키를 가진 JSON 객체를 반환해야 합니다.
"rankings"의 값은 객체들의 리스트이며, 각 객체는 다음을 포함해야 합니다:
1. "index": 문서의 원본 인덱스 (0부터 시작).
2. "relevance_score": 관련성 점수 (1점 = 완전히 무관함, 10점 = 완벽하게 관련됨).
이 리스트를 "relevance_score" 기준으로 내림차순(가장 관련성 높은 항목이 맨 위) 정렬해주세요.
"""

    documents_str = ""
    for i, doc in enumerate(documents):
        # [수정] 청크가 작아졌으므로 2000자 제한 제거 (전체 텍스트 표시)
        documents_str += f"\n\n[문서 {i}]:\n{doc}" 

    user_prompt = f"""
[사용자 쿼리]:
{query}

[평가할 문서 목록(청크)]:
{documents_str}

지시사항에 설명된 대로 JSON 출력을 제공해주세요.
"""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo-1106", 
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        
        response_json_str = response.choices[0].message.content
        data = json.loads(response_json_str)
        rankings = data.get("rankings", [])
        
        if not rankings or not all("index" in item and "relevance_score" in item for item in rankings):
             raise ValueError("GPT LLM이 반환한 JSON 형식이 올바르지 않습니다.")

        sorted_rankings = sorted(rankings, key=lambda x: x["relevance_score"], reverse=True)
        
        print(f"🤖 GPT-3.5 Rerank 결과 (전체): {sorted_rankings}")
        
        if not all(item["index"] < len(documents) for item in sorted_rankings):
             raise ValueError("GPT LLM이 반환한 인덱스가 유효하지 않습니다.")
             
        return sorted_rankings

    except Exception as e:
        print(f"⚠️ _rerank_with_gpt 중 오류: {e}")
        raise e # 이 오류는 Step 1의 핵심이므로 main.py로 전파

# ==================================
# 6️⃣ LLM as Judge (Gemini) - [삭제됨]
# ==================================
# (이 작업은 이제 main.py (Step 2)에서 수행됩니다)


# ========================================
# 7️⃣ [수정됨] 검색 함수 (Step 1: GPT Rerank)
# ========================================
def search_similar_docs(
    history_list: List[Dict],
    query: str,
    top_k: int = 3,
    rerank_candidates_count: int = 6, # 1차 검색 후보 수
    max_chars: int = 1500, # (이 매개변수는 이제 main.py에서만 의미 있음)
    allowed_types: List[str] = None, # 예: ["sinyoung", "dambo"]
    allowed_banks: List[str] = None  # 예: ["우리은행", "신한은행"]
) -> Tuple[List[str], List[Dict]]:
    """
    [수정됨] 2-Step RAG의 1단계(Step 1)
    1. Qdrant 1차 검색 (필터 적용)
    2. GPT-3.5 Rerank (LLM 호출 1)
    3. (후보 문서(청크) 리스트, GPT 랭킹 리스트)를 반환
    """
    if vectorstore is None:
        print("⚠️ Qdrant 벡터스토어가 초기화되지 않았습니다.")
        return [], []

    # 1. 쿼리 구성
    recent_context = " ".join(
        [msg["content"] for msg in history_list[-4:] if msg["role"] == "user"]
    )
    full_query = (recent_context + " " + query).strip()
    if not full_query:
        return [], []
    print(f"🔍 전체 검색 쿼리: {full_query[:100]}...")

    # 2. 1차 검색 (Qdrant)
    
    # 2-1. Qdrant 필터 생성
    qdrant_filter_conditions = []
    if allowed_types:
        print(f"ℹ️ 필터 적용 (대출 종류): {allowed_types}")
        qdrant_filter_conditions.append(
            FieldCondition(key="loan_type", match=MatchAny(any=allowed_types))
        )
    if allowed_banks:
        print(f"ℹ️ 필터 적용 (은행): {allowed_banks}")
        qdrant_filter_conditions.append(
            FieldCondition(key="bank_name", match=MatchAny(any=allowed_banks))
        )
        
    qdrant_filter = Filter(must=qdrant_filter_conditions) if qdrant_filter_conditions else None

    # 2-2. Qdrant 검색
    try:
        search_results = vectorstore.similarity_search_with_score(
            full_query,
            k=rerank_candidates_count, # Rerank 후보(6개)만큼 가져옴
            filter=qdrant_filter 
        )
        print(f"🚚 1차 검색 (필터 적용됨: {bool(qdrant_filter)}), {len(search_results)}개 결과 수신")
    except Exception as e:
        print(f"⚠️ Qdrant 1차 검색 오류: {e}")
        return [], []

    if not search_results:
        print("⚠️ 1차 검색 결과 0개.")
        return [], []

    # 3. [Step 1] GPT-3.5 Rerank (LLM 호출 1)
    
    # Rerank 후보 문서(청크) 리스트 (전체 텍스트)
    candidate_docs = [doc.page_content for doc, score in search_results]

    try:
        print(f"🤖 (Step 1) GPT-3.5 as Judge/Reranker 시작... (후보: {len(candidate_docs)}개)")
        gpt_rankings = _rerank_with_gpt(full_query, candidate_docs)
        
        if not gpt_rankings:
            print("⚠️ (Step 1) GPT Rerank 결과 0개.")
            return [], []
        
        # [수정] 필터링/정렬은 Step 2 (main.py)에서 수행
        #       여기서는 (후보 문서 리스트, GPT 랭킹 리스트)를 그대로 반환
        
        print(f"✅ (Step 1) GPT Rerank 완료. (후보 문서 {len(candidate_docs)}개, GPT 랭킹 {len(gpt_rankings)}개)를 main.py로 전달.")

        # [수정] 반환 값 변경
        # (후보 문서(청크) 리스트, GPT 랭킹 리스트)
        return candidate_docs, gpt_rankings

    except Exception as e:
        # GPT Rerank 실패 시 (Fallback)
        # (main.py가 Fallback 처리할 수 있도록, 1차 검색 결과와 빈 랭킹을 반환)
        print(f"⚠️ (Step 1) GPT Rerank 실패: {e}")
        print("    (Fallback) 1차 검색(Qdrant) 결과와 빈 랭킹을 main.py로 전달합니다.")
        
        # 1차 검색(Qdrant) 순서대로 랭킹을 가짜로 만들어줌
        fallback_rankings = [
            {"index": i, "relevance_score": 10 - i} # 임시 점수
            for i in range(len(candidate_docs))
        ]
        
        # (후보 문서 리스트, 1차 검색 랭킹)
        return candidate_docs, fallback_rankings
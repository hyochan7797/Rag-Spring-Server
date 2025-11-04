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

# ... (1~6번 섹션은 이전과 동일) ...
# =KST======================
# 1️⃣ 환경 설정 로드
# =======================
dotenv_path = "/app/.env"
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
        google_api_key = None # 키가 유효하지 않으면 None으로 설정
else:
    print("ℹ️ GOOGLE_API_KEY가 설정되지 않았습니다. 교차 검증을 건너뜁니다.")


print(f"🔑 OPENAI_API_KEY 확인: {api_key[:10] + '...' if api_key else '없음'}")
print(f"🗃️ Qdrant URL: {qdrant_url} / Collection: {collection_name}")

if not api_key:
    raise ValueError("OPENAI_API_KEY 환경변수가 설정되어 있지 않습니다.")

# =======================
# 2️⃣ CSV 로드 (이전과 동일)
# =======================
credit_csv = "/app/data/sinyoung.csv"
dambo_csv = "/app/data/dambo.csv"

def detect_encoding(file_path):
    """파일 인코딩을 감지합니다."""
    try:
        with open(file_path, "rb") as f:
            raw = f.read(10000)
        return chardet.detect(raw)["encoding"]
    except FileNotFoundError:
        print(f"⚠️ 파일을 찾을 수 없습니다: {file_path}")
        return None
    except Exception as e:
        print(f"⚠️ 인코딩 감지 중 오류 발생: {e}")
        return "utf-8" # 기본값으로 대체

encoding_credit = detect_encoding(credit_csv)
encoding_dambo = detect_encoding(dambo_csv)

df_credit = pd.read_csv(credit_csv, encoding=encoding_credit) if encoding_credit else pd.DataFrame()
df_dambo = pd.read_csv(dambo_csv, encoding=encoding_dambo) if encoding_dambo else pd.DataFrame()

if df_credit.empty and df_dambo.empty:
    raise FileNotFoundError("두 CSV 파일 모두 로드에 실패했습니다.")

df_all = pd.concat([df_credit, df_dambo], ignore_index=True).fillna("")
print(f"📊 총 {len(df_all)}개의 데이터 로드 완료.")

# =======================
# 3️⃣ 문서 및 메타데이터 구성 (이전과 동일)
# =======================
def build_documents_with_metadata(df):
    docs = []
    metadatas = []
    
    if 'loan_type' not in df.columns:
        print("⚠️ 'loan_type' 컬럼을 찾을 수 없습니다. '상품명'으로 대체합니다.")
        df['loan_type'] = df['상품명'] # 대체 필드

    for _, row in tqdm(df.iterrows(), total=df.shape[0], desc="문서 구성 중"):
        doc_text = f"""
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
        
        doc_metadata = {
            "loan_type": row.get('loan_type', '기타'),
            "product_name": row.get('상품명', '알수없음')
        }
        
        docs.append(doc_text)
        metadatas.append(doc_metadata)
        
    return docs, metadatas

documents, metadatas = build_documents_with_metadata(df_all)
print(f"📄 문서 개수: {len(documents)}, 메타데이터 개수: {len(metadatas)}")

# =======================
# 4️⃣ Qdrant 연결 및 벡터 저장 (이전과 동일)
# =======================
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
client = QdrantClient(url=qdrant_url)
vectorstore = None

try:
    collections_response = client.get_collections()
    collections = [c.name for c in collections_response.collections]
    
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
        print("✅ 컬렉션 생성 및 데이터 저장 완료.")
    else:
        print(f"✅ 기존 컬렉션 사용: {collection_name}")
        vectorstore = Qdrant(
            client=client,
            collection_name=collection_name,
            embeddings=embeddings
        )
        count_result = client.count(collection_name=collection_name, exact=True)
        print(f"✅ 기존 컬렉션 로드 완료. (문서 수: {count_result.count})")

except Exception as e:
    print(f"⚠️ Qdrant 초기화 오류: {e}")
    print(f"    Qdrant 서버가 실행 중인지, {qdrant_url} 주소가 올른지 확인하세요.")

# ==================================
# 5️⃣ LLM as Judge (GPT-3.5) (이전과 동일)
# ==================================
def _rerank_with_gpt(query: str, documents: list[str]) -> list[dict]:
    """
    [GPT-3.5]를 Judge(평가자)로 사용하여 문서 목록을 재정렬합니다.
    점수 정보가 포함된 전체 랭킹 리스트(dict)를 반환합니다.
    """
    if not documents:
        return []

    system_prompt = """
당신은 지능이 매우 높은 '관련성 평가 전문가'입니다.
당신의 임무는 주어진 '사용자 쿼리'에 대해 '문서 목록'이 얼마나 적절하게 답변하는지 평가하는 것입니다.
반드시 "rankings"라는 단일 키를 가진 JSON 객체를 반환해야 합니다.
"rankings"의 값은 객체들의 리스트이며, 각 객체는 다음을 포함해야 합니다:
1. "index": 문서의 원본 인덱스 (0부터 시작).
2. "relevance_score": 관련성 점수 (1점 = 완전히 무관함, 10점 = 완벽하게 관련됨).
이 리스트를 "relevance_score" 기준으로 내림차순(가장 관련성 높은 항목이 맨 위) 정렬해주세요.
"""

    documents_str = ""
    for i, doc in enumerate(documents):
        documents_str += f"\n\n[문서 {i}]:\n{doc[:2000]}" 

    user_prompt = f"""
[사용자 쿼리]:
{query}

[평가할 문서 목록]:
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
        raise e # 오류를 상위로 전파

# ==================================
# 6️⃣ LLM as Judge (Gemini) (이전과 동일)
# ==================================
def _cross_validate_with_gemini(query: str, documents: list[str]) -> list[dict]:
    """
    [Gemini]를 Judge(평가자)로 사용하여 교차 검증을 위한 재정렬을 수행합니다.
    점수 정보가 포함된 전체 랭킹 리스트(dict)를 반환합니다.
    """
    if not documents or not google_api_key:
        if not google_api_key:
            print("ℹ️ Gemini 교차 검증 건너뜀 (API 키 없음)")
        return []

    # --- 'gemini-2.5-flash' 모델 사용 ---
    try:
        config = genai.GenerationConfig(response_mime_type="application/json")
        gemini_model = genai.GenerativeModel(
            'gemini-2.5-flash', # 형님이 찾으신 모델
            generation_config=config   # JSON 모드 설정 적용
        )
    except Exception as e:
        # 모델 초기화 실패 시 (예: API 키 오류 또는 지원되지 않는 설정)
        print(f"⚠️ Gemini 모델/설정 초기화 오류: {e}")
        print("    교차 검증을 건너뜁니다.")
        return []
    
    # --- Gemini용 프롬프트 (GPT와 동일한 지시사항) ---
    gemini_prompt = """
당신은 지능이 매우 높은 '관련성 평가 전문가'입니다.
당신의 임무는 주어진 '사용자 쿼리'에 대해 '문서 목록'이 얼마나 적절하게 답변하는지 평가하는 것입니다.
반드시 "rankings"라는 단일 키를 가진 JSON 객체를 반환해야 합니다.
"rankings"의 값은 객체들의 리스트이며, 각 객체는 다음을 포함해야 합니다:
1. "index": 문서의 원본 인덱스 (0부터 시작).
2. "relevance_score": 관련성 점수 (1점 = 완전히 무관함, 10점 = 완벽하게 관련됨).
이 리스트를 "relevance_score" 기준으로 내림차순(가장 관련성 높은 항목이 맨 위) 정렬해주세요.

---

[사용자 쿼리]:
{query}

[평가할 문서 목록]:
"""
    documents_str = ""
    for i, doc in enumerate(documents):
        documents_str += f"\n\n[문서 {i}]:\n{doc[:2000]}"

    final_prompt = gemini_prompt.format(query=query) + documents_str

    try:
        response = gemini_model.generate_content(final_prompt)
        
        # JSON 응답에서 마크다운(```) 제거
        response_json_str = response.text.strip().replace("```json", "").replace("```", "").strip()
        
        data = json.loads(response_json_str)
        rankings = data.get("rankings", [])
        
        if not rankings or not all("index" in item and "relevance_score" in item for item in rankings):
             raise ValueError("Gemini LLM이 반환한 JSON 형식이 올바르지 않습니다.")

        sorted_rankings = sorted(rankings, key=lambda x: x["relevance_score"], reverse=True)
        
        print(f"🔄 Gemini 교차 검증 결과 (전체): {sorted_rankings}")
        
        if not all(item["index"] < len(documents) for item in sorted_rankings):
             raise ValueError("Gemini LLM이 반환한 인덱스가 유효하지 않습니다.")
             
        return sorted_rankings

    except Exception as e:
        print(f"⚠️ _cross_validate_with_gemini 중 오류: {e}")
        raise e # 오류를 상위로 전파


# ========================================
# 7️⃣ [수정됨] 검색 함수 (필터 기준 변경 및 점수 반환)
# ========================================
def search_similar_docs(
    history_list: list[dict],
    query: str,
    top_k: int = 3,
    max_chars: int = 1500,
    allowed_types: list[str] = None, 
    filter_field: str = "loan_type",
    rerank_candidates_count: int = 6 
):
    """
    [수정]
    1. Qdrant 1차 검색 (6개)
    2. GPT-3.5 Rerank (점수)
    3. Gemini Rerank (점수)
    4. 두 점수의 평균 계산
    5. [변경] 평균 3점 이상인 문서만 필터링 ("근거 없는 주장" 제외)
    6. 3점 이상인 문서를 'Gemini 점수' 기준으로 정렬
    7. 상위 top_k(3개) 반환 + [변경] (문서 리스트, 점수 리스트)를 반환
    """
    if vectorstore is None:
        print("⚠️ Qdrant 벡터스토어 초기화 실패")
        return [], [] # [수정] 빈 리스트 2개 반환

    # 1. 쿼리 구성 (동일)
    recent_context = " ".join(
        [msg["content"] for msg in history_list[-4:] if msg["role"] == "user"]
    )
    full_query = (recent_context + " " + query).strip()
    if not full_query:
        return [], [] # [수정] 빈 리스트 2개 반환
    print(f"🔍 전체 검색 쿼리: {full_query[:100]}...")


    # 2. 1차 검색 (Qdrant) (동일)
    qdrant_filter = None
    if allowed_types:
        qdrant_filter = Filter(
            should=[
                FieldCondition(
                    key=filter_field,
                    match=MatchValue(value=loan_type)
                ) for loan_type in allowed_types
            ]
        )
    
    try:
        search_results = vectorstore.similarity_search_with_score(
            full_query,
            k=rerank_candidates_count, 
            filter=qdrant_filter
        )
        print(f"🚚 1차 검색 (필터 적용됨: {bool(allowed_types)}), {len(search_results)}개 결과 수신")
    except Exception as e:
        print(f"⚠️ Qdrant 검색 오류: {e}")
        return [], [] # [수정] 빈 리스트 2개 반환

    if not search_results:
        print("⚠️ 1차 검색 결과 없음.")
        return [], [] # [수정] 빈 리스트 2개 반환

    candidate_docs = [doc.page_content for doc, score in search_results]
    top_docs = []
    top_scores = [] # [신규] 반환할 점수 리스트

    # 3. GPT-3.5 Rerank (동일)
    print(f"🤖 GPT-3.5 as Judge/Reranker 시작... (후보: {len(candidate_docs)}개)")
    try:
        gpt_rankings = _rerank_with_gpt(full_query, candidate_docs)
    except Exception as e:
        print(f"⚠️ GPT-3.5 Rerank 실패: {e}")
        gpt_rankings = [] 

    # 4. Gemini Rerank (동일)
    print("🔄 Gemini as Judge/Reranker 시작...")
    try:
        gemini_rankings = _cross_validate_with_gemini(full_query, candidate_docs)
    except Exception as e:
        print(f"⚠️ Gemini Rerank 실패: {e}")
        gemini_rankings = [] 
    
    # 5. [수정됨] Rerank 결과 취합, 필터링, 정렬
    if not gpt_rankings and not gemini_rankings:
        print("⚠️ GPT와 Gemini Rerank 모두 실패! (Fallback)")
        print("    (대체 로직: Qdrant 벡터 유사도 순으로 반환합니다.)")
        top_docs = [doc.page_content for doc, score in search_results[:top_k]]
        # Fallback의 경우 점수 정보가 없으므로 빈 리스트 반환
        top_scores = [] 
    
    else:
        gpt_scores = {item.get('index'): item.get('relevance_score', 0) for item in gpt_rankings}
        gemini_scores = {item.get('index'): item.get('relevance_score', 0) for item in gemini_rankings}

        combined_scores = []
        for i in range(len(candidate_docs)):
            gpt_score = gpt_scores.get(i, 0)
            gemini_score = gemini_scores.get(i, 0)
            
            if gpt_score > 0 or gemini_score > 0:
                if gpt_score > 0 and gemini_score > 0:
                    average_score = (gpt_score + gemini_score) / 2
                else:
                    average_score = max(gpt_score, gemini_score) 
                    
                combined_scores.append({
                    "index": i,
                    "average_score": average_score,
                    "gpt_score": gpt_score,
                    "gemini_score": gemini_score
                })
        
        print(f"📊 점수 취합 결과 (전체): {combined_scores}")

        # 5-3. [수정] '근거 없는 주장' 제외 필터
        min_average_score = 3 # [수정] 8점에서 3점으로 변경
        filtered_list = [
            item for item in combined_scores 
            if item["average_score"] >= min_average_score
        ]
        print(f"ℹ️ 평균 점수 필터링 적용 (기준: {min_average_score}점 이상)")
        print(f"📊 필터링 결과: {len(filtered_list)}개 문서 통과")

        # 5-4. Gemini 점수 기준으로 최종 정렬 (동일)
        sorted_list = sorted(filtered_list, key=lambda x: x["gemini_score"], reverse=True)
        
        # 5-5. 상위 top_k(3개) 만큼만 최종 선택
        final_selection = sorted_list[:top_k]
        final_indices = [item["index"] for item in final_selection]
        
        top_docs = [candidate_docs[i] for i in final_indices]
        top_scores = final_selection # [신규] 점수 리스트를 할당

        if top_docs:
            print(f"✅ 교차 검증 및 필터링 완료. (Gemini 점수 기준 정렬)")
            for item in final_selection:
                print(f"    - [문서 {item['index']}] Avg: {item['average_score']}, Gemini: {item['gemini_score']}, GPT: {item['gpt_score']}")
        else:
            print("✅ 교차 검증 및 필터링 완료. (3점 이상 문서 없음)")


    # 6. [수정됨] 최종 결과 반환
    limited_docs = [doc[:max_chars] for doc in top_docs]
    print(f"✅ 최종 문서 {len(limited_docs)}개 반환 (각 {max_chars}자 제한)")
    
    # [수정] 문서 리스트와 점수 리스트를 튜플로 반환
    return limited_docs, top_scores

# RAG 시스템 이해 가이드

이 문서는 프로젝트의 RAG 구조를 처음 보는 사람이 빠르게 이해하고 수정할 수 있도록 정리한 문서다.

## 전체 구조

이 프로젝트는 Spring과 FastAPI를 함께 사용한다.

```text
사용자
  -> Spring
      로그인/세션 관리
      MySQL 대화 이력 저장
      FastAPI로 질문과 히스토리 전달
  -> FastAPI
      질문 분석
      검색 필터 추출
      쿼리 확장
      Qdrant 검색
      BM25 검색
      RRF 통합
      BGE Reranker 정렬
      Gemini 답변 생성
```

RAG 검색과 관련된 핵심 책임은 FastAPI 쪽에 있다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| `python/main.py` | FastAPI `/chat`, `/admin/refresh` 엔드포인트 |
| `python/fss_crawler.py` | 금융감독원 API 수집 및 청크 생성 |
| `python/rag_pipeline.py` | Qdrant, BM25, RRF, BGE Reranker 검색 파이프라인 |
| `python/filter_extraction.py` | 질문에서 은행명/상품군 자동 필터 추출 |
| `python/query_expansion.py` | 마통, 주담대 등 도메인 줄임말 쿼리 확장 |
| `python/document_aliases.py` | 문서 적재 시 검색 별칭 생성 |
| `python/eval_retrieval.py` | 검색 품질 평가 스크립트 |
| `python/eval_golden_set.json` | hard-only 평가 질문 세트 |
| `docs/04_evaluation.md` | 평가 프레임워크 설명 |
| `docs/07_fss_api_expansion.md` | FSS API 확장 설명 |
| `docs/08_filter_ownership.md` | Spring/FastAPI 필터 책임 분리 설명 |

## 데이터 수집 흐름

금융상품 데이터는 `python/fss_crawler.py`에서 수집한다.

수집 대상:

| product_type | FSS endpoint | 설명 |
|---|---|---|
| `sinyoung` | `creditLoanProductsSearch` | 개인신용대출 |
| `dambo_mortgage` | `mortgageLoanProductsSearch` | 주택담보대출 |
| `dambo_jeonse` | `rentHouseLoanProductsSearch` | 전세자금대출 |
| `deposit` | `depositProductsSearch` | 정기예금 |
| `saving` | `savingProductsSearch` | 적금 |
| `annuity_saving` | `annuitySavingProductsSearch` | 연금저축 |
| `company` | `companySearch` | 금융회사 |

현재 Qdrant 적재 기준:

```text
total            730
annuity_saving   343
company          173
saving            59
sinyoung          43
dambo_jeonse      41
deposit           37
dambo_mortgage    34
```

## FSS 권역코드

일부 API는 `topFinGrpNo` 권역코드가 필요하다.

대출, 예금, 적금은 은행권 중심으로 수집한다.

```text
020000
```

연금저축과 금융회사는 여러 권역을 순회한다.

```text
020000
030200
030300
050000
060000
```

연금저축펀드는 주로 `060000` 금융투자 권역에서 나온다.

## 청크 구조

각 상품은 하나의 풍부한 청크로 만든다.

청크에는 다음 정보가 들어간다.

```text
[금융회사명]
[상품명]
[상품종류]
[가입방법]
[가입대상]
[우대조건]
[만기 후 이자율]
[옵션 정보]
[검색 별칭]
[공시기간]
```

예금/적금 옵션 예시:

```text
save_trm=12개월
intr_rate_type=S
intr_rate_type_nm=단리
intr_rate=2.50%
intr_rate2=3.00%
```

연금저축 옵션 예시:

```text
pnsn_recp_trm_nm=10년 확정
pnsn_entr_age_nm=30세
mon_paym_atm_nm=100,000원
paym_prd_nm=10년
pnsn_strt_age_nm=60세
pnsn_recp_amt=201304
```

## Metadata 구조

Qdrant payload의 metadata에는 검색 필터용 값이 저장된다.

```json
{
  "bank_name": "국민은행",
  "loan_type": "deposit",
  "product_type": "deposit",
  "product_name": "KB Star 정기예금",
  "product_code": "010300100335",
  "dcls_month": "202605",
  "aliases": ["정기예금", "예금"]
}
```

주의:

`loan_type`이라는 이름을 사용하지만 실제로는 대출뿐 아니라 예금, 적금, 연금저축, 금융회사 타입까지 포함한다.

## 검색 파이프라인

검색은 `python/rag_pipeline.py`에서 처리한다.

단계:

```text
1. 질문 또는 재작성 질문 준비
2. metadata 필터 구성
3. Dense 검색
4. BM25 검색
5. RRF로 후보 통합
6. BGE Reranker로 최종 정렬
7. 상위 문서를 Gemini 답변 생성에 전달
```

## Dense 검색

Dense 검색은 OpenAI embedding과 Qdrant를 사용한다.

```text
model: text-embedding-3-small
vector DB: Qdrant
```

임베딩 배치 관련 환경변수:

```text
EMBEDDING_CHUNK_SIZE=8
QDRANT_BATCH_SIZE=8
EMBEDDING_MAX_RETRIES=20
```

데이터가 늘어나면 OpenAI embedding API의 요청 토큰 제한 또는 TPM 제한에 걸릴 수 있다. 이 경우 위 값을 더 낮추거나 재시도 횟수를 늘린다.

## BM25 검색

BM25는 `rank_bm25`를 사용한다.

역할:

```text
상품명, 은행명, 금리 유형, 옵션 필드처럼 정확한 키워드 매칭
마통, 주담대 같은 별칭이 문서에 들어가 있을 때 빠르게 매칭
```

앱 시작 시 기존 Qdrant 데이터를 scroll해서 BM25 인덱스를 재구축한다.

## RRF

Dense와 BM25 결과는 Reciprocal Rank Fusion으로 합친다.

이유:

```text
Dense는 의미 검색에 강함
BM25는 정확한 키워드 검색에 강함
둘 중 하나만 쓰면 누락되는 케이스가 생김
```

## BGE Reranker

최종 후보는 `BAAI/bge-reranker-v2-m3`로 재정렬한다.

역할:

```text
Dense/BM25/RRF가 넓게 후보를 가져옴
BGE Reranker가 질문-문서 쌍을 보고 최종 순위를 결정
```

현재 CPU로 로딩된다.

```text
device=cpu
```

## 자동 필터 추출

필터 추출은 `python/filter_extraction.py`가 담당한다.

예:

```text
국민은행 마통 금리 알려줘
-> allowed_banks = ["국민은행"]
-> allowed_types = ["sinyoung"]
```

```text
KB 연금저축 중 가치주 주식형 펀드 찾아줘
-> allowed_banks = ["국민은행", "KB자산운용"]
-> allowed_types = ["annuity_saving"]
```

Spring에서는 자동 필터 추출을 하지 않는다.  
FastAPI가 RAG 검색용 필터를 단일 책임으로 관리한다.

## 쿼리 확장

`python/query_expansion.py`는 확실한 줄임말만 확장한다.

예:

| 입력 | 확장 |
|---|---|
| 마통 | 마이너스통장, 마이너스한도대출 |
| 주담대 | 주택담보대출 |
| 아담대 | 아파트담보대출 |
| 전세대출 | 전세자금대출 |
| 앱, 모바일 | 스마트폰 |
| 청년 | 만19세, 만34세, 청년적금 |
| 월복리 | 월복리, 월복리적금 |

모든 동의어를 쿼리 확장으로 처리하지 않는다.  
대부분의 별칭은 문서 적재 시 `document_aliases.py`에서 문서 본문에 넣는다.

## 문서 별칭

`python/document_aliases.py`는 상품명과 상품군을 보고 검색 별칭을 만든다.

예:

```text
마이너스한도대출
-> 마통, 마이너스통장, 마이너스한도대출, 한도대출
```

```text
NH1934월복리적금
-> 청년, 청년적금, 만19세, 만34세, 월복리, 월복리적금
```

문서 별칭을 변경하면 Qdrant 재적재가 필요하다.

```powershell
curl.exe -X POST "http://localhost:8000/admin/refresh" -H "X-Admin-Key: admin"
```

## 데이터 갱신

FastAPI의 `/admin/refresh`가 전체 수집과 벡터 재생성을 담당한다.

```powershell
curl.exe -X POST "http://localhost:8000/admin/refresh" -H "X-Admin-Key: admin"
```

동작:

```text
1. FSS API 전체 수집
2. 새 Qdrant backing collection 생성
3. 문서 임베딩
4. 벡터 적재
5. alias 전환
6. 기존 collection 삭제
7. BM25 인덱스 갱신
```

현재는 blue/green 방식으로 새 컬렉션을 만든 뒤 alias를 바꾼다.

예:

```text
loan_docs_v1
loan_docs_v2
alias: loan_docs
```

## 데이터 확인 명령

상품군별 Qdrant 개수 확인:

```powershell
docker compose exec fastapi python -c "from collections import Counter; from rag_pipeline import client,_get_alias_backing; c=_get_alias_backing(); pts,_=client.scroll(collection_name=c, limit=3000, with_payload=True, with_vectors=False); print(Counter(p.payload.get('metadata',{}).get('loan_type') for p in pts)); print('total', len(pts)); print('collection', c)"
```

FSS 수집만 확인:

```powershell
docker compose exec fastapi python -c "import asyncio; from fss_crawler import crawl_all; docs,metas=asyncio.run(crawl_all()); from collections import Counter; print(len(docs)); print(Counter(m['loan_type'] for m in metas))"
```

연금저축 060000 권역 확인:

```powershell
docker compose exec fastapi python -c "import asyncio; from fss_crawler import _fetch_all_pages; base,opt=asyncio.run(_fetch_all_pages('annuitySavingProductsSearch', '060000')); print('base', len(base)); print('option', len(opt)); print(base[:1]); print(opt[:1])"
```

## 평가

평가는 `python/eval_retrieval.py`로 실행한다.

현재 평가셋은 hard-only 24개다.

```powershell
docker compose exec fastapi python eval_retrieval.py --difficulty hard --output-json eval_hard_only_final.json
```

현재 최종 결과:

```text
cases      : 24
Recall@1   : 1.000
Recall@10  : 1.000
MRR        : 1.000
NDCG@10    : 1.000
```

주의:

평가셋을 변경하면 FastAPI 이미지를 다시 빌드해야 한다.  
현재 `python` 폴더 전체가 컨테이너에 bind mount되어 있지 않기 때문이다.

```powershell
docker compose up -d --build fastapi
```

## 수정 시 주의사항

### 상품군을 추가할 때

수정 위치:

```text
python/fss_crawler.py
python/filter_extraction.py
python/document_aliases.py
python/eval_golden_set.json
docs/RAG_SYSTEM_GUIDE.md
```

필요하면 `query_expansion.py`도 수정한다.

### 별칭을 추가할 때

문서 별칭:

```text
python/document_aliases.py
```

질문 별칭:

```text
python/query_expansion.py
```

문서 별칭을 바꾸면 `/admin/refresh`가 필요하다.  
질문 별칭만 바꾸면 FastAPI 재빌드만 하면 된다.

### 필터 추출을 수정할 때

수정 위치:

```text
python/filter_extraction.py
```

평가와 실제 앱이 같은 모듈을 사용하므로, 수정 후 hard-only 평가를 다시 돌린다.

## 자주 발생한 문제

### 연금저축이 0건으로 나옴

원인:

```text
은행권 코드 020000만 조회
```

해결:

```text
연금저축은 060000 금융투자 권역 포함
```

### 임베딩 중 token limit 에러

원인:

```text
한 번에 너무 많은 긴 문서를 임베딩
```

해결:

```text
EMBEDDING_CHUNK_SIZE 낮추기
QDRANT_BATCH_SIZE 낮추기
EMBEDDING_MAX_RETRIES 늘리기
```

### 검색 결과가 필터 때문에 사라짐

예:

```text
KB 연금저축 중 가치주 주식형 펀드 찾아줘
```

원인:

```text
KB를 국민은행으로만 해석하면 KB자산운용 문서가 제외됨
```

해결:

```text
KB + 연금저축/펀드 문맥에서는 KB자산운용도 필터 후보에 포함
```

## 현재 상태 요약

RAG 핵심 파이프라인은 안정화된 상태다.

```text
수집: 완료
청크 구성: 완료
옵션 필드 포함: 완료
Qdrant 적재: 완료
BM25 + Dense + RRF: 완료
BGE Reranker: 완료
도메인 별칭: 완료
자동 필터: FastAPI로 단일화
hard-only 평가: 1.000
```

앞으로 RAG를 변경할 때는 먼저 `eval_golden_set.json`에 실패 질문을 추가하고, 수치가 개선되는지 확인한 뒤 반영하는 방식으로 관리한다.

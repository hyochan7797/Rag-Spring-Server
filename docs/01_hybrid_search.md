# RAG 검색 품질 개선: Dense → Hybrid Search (BM25 + Dense + BGE Reranker)

## 개요

금융 대출 상품 RAG 챗봇의 검색 정확도를 높이기 위해 **순수 Dense 검색**에서 **BM25 + Dense 하이브리드 검색**으로 파이프라인을 개선했다.
BGE-Reranker는 최종 정렬 단계에서 그대로 유지했다.

---

## 배경 — 왜 Dense 단독 검색이 부족한가

| 검색 방식 | 강점 | 약점 |
|-----------|------|------|
| **Dense (임베딩)** | 의미적으로 유사한 문서 탐색 우수 | 정확한 키워드(금리 숫자, 은행명, 상품코드)에 약함 |
| **BM25 (키워드)** | 정확한 단어 매칭 우수 | 동의어·문맥 이해 불가 |

예시:
- `"3% 이하 신용대출"` → Dense는 낮은 금리 상품을 잘 찾지만, 정확한 숫자 매칭은 BM25가 더 정확
- `"국민은행 KB스타대출"` → 상품명 일치는 BM25가 우선

두 방식을 결합하면 각각의 단점을 보완할 수 있다.

---

## 변경 전 파이프라인 (Before)

```
사용자 질문
    │
    ▼
[Dense 검색] text-embedding-3-small → Qdrant
    │  top-30 문서
    ▼
[BGE-Reranker] bge-reranker-v2-m3
    │  top-3 문서
    ▼
[Gemini] 답변 생성
```

**한계:**
- 정확한 금리 수치, 상품명, 은행명 키워드 검색 정확도 낮음
- Dense 벡터가 의미 공간에서 유사하지만 실제 관련도 낮은 문서를 포함하는 경우 존재

---

## 변경 후 파이프라인 (After)

```
사용자 질문
    │
    ├──────────────────────┐
    ▼                      ▼
[Dense 검색]          [BM25 검색]
text-embedding-3-small   rank_bm25 (in-memory)
top-30 문서              top-30 문서
    │                      │
    └──────────┬───────────┘
               ▼
         [RRF 통합]
   Reciprocal Rank Fusion (k=60)
         top-30 후보
               │
               ▼
       [BGE-Reranker]
       bge-reranker-v2-m3
         top-3 문서
               │
               ▼
        [Gemini 답변 생성]
```

---

## 핵심 기술 설명

### 1. BM25 (Best Match 25)

전통적인 확률 기반 키워드 검색 알고리즘. 단어 빈도(TF)와 역문서 빈도(IDF)를 조합해 점수를 계산한다.

```
score(D, Q) = Σ IDF(qi) * (f(qi, D) * (k1 + 1)) / (f(qi, D) + k1 * (1 - b + b * |D| / avgdl))
```

- `f(qi, D)`: 문서 D에서 단어 qi의 출현 빈도
- `|D|`: 문서 길이, `avgdl`: 평균 문서 길이
- `k1=1.5`, `b=0.75` (BM25 기본값)

### 2. Reciprocal Rank Fusion (RRF)

두 검색 결과의 순위(rank)를 기반으로 점수를 통합하는 방법.
실제 점수 값(dense score, BM25 score)을 사용하지 않아 스케일 차이 문제가 없다.

```python
rrf_score(doc) = Σ 1 / (k + rank_i)   # k=60 (상수)
```

Dense top-5에 있고 BM25 top-10에도 있는 문서는 두 기여도가 합산되어 상위로 올라온다.

### 3. BM25 인덱스 관리 전략

BM25는 전체 코퍼스를 메모리에 올려야 한다. 두 가지 상황을 처리했다:

| 상황 | 처리 |
|------|------|
| FSS 크롤링 후 벡터 갱신 | `refresh_vectorstore()` 내에서 `_build_bm25_index()` 호출 |
| 앱 재시작 (Qdrant에 기존 데이터 있음) | `_rebuild_bm25_from_qdrant()` — Qdrant scroll API로 전체 문서 복원 |

---

## 구현 상세

### 추가된 주요 함수

**`_build_bm25_index(docs, metas)`**
```python
def _build_bm25_index(docs, metas=None):
    tokenized  = [doc.lower().split() for doc in docs]
    bm25_index = BM25Okapi(tokenized)
    # 필터링을 위해 메타데이터도 병렬 저장
```

**`_bm25_search(query, k, allowed_banks, allowed_types)`**
```python
def _bm25_search(query, k=30, allowed_banks=None, allowed_types=None):
    scores  = bm25_index.get_scores(query.lower().split())
    # 메타데이터 기반 필터 적용 (Dense와 동일 조건)
    # 점수 0 이하 문서 제외 (완전 무관 문서 차단)
```

**`_rrf_merge(dense_results, bm25_results, k=60)`**
```python
def _rrf_merge(dense_results, bm25_results, k=60):
    for rank, (doc, _) in enumerate(dense_results):
        rrf_scores[doc] += 1.0 / (k + rank + 1)
    for rank, (doc, _) in enumerate(bm25_results):
        rrf_scores[doc] += 1.0 / (k + rank + 1)
```

### 수정된 파일

| 파일 | 변경 내용 |
|------|----------|
| `python/rag_pipeline.py` | BM25 인덱스 전역 추가, 하이브리드 검색 구현 |
| `python/requirements.txt` | `rank-bm25==0.2.2` 추가 |

---

## 트러블슈팅

### 문제 1: 앱 재시작 시 BM25 인덱스 유실

**증상:** 서버 재시작 후 BM25 인덱스가 None 상태 → Dense only로 폴백  
**원인:** BM25 인덱스는 메모리 상태라 재시작 시 사라짐  
**해결:** `init_vectorstore_from_existing()`에 `_rebuild_bm25_from_qdrant()` 추가
- Qdrant scroll API로 전체 문서 재수집 후 BM25 재구축
- 595개 문서 기준 약 1~2초 소요 (무시 가능)

### 문제 2: BM25 필터와 Dense 필터 불일치

**증상:** Dense 검색은 `bank_name`, `loan_type` 필터를 Qdrant 레벨에서 적용하지만 BM25는 필터 없이 전체 검색  
**원인:** BM25 인덱스는 Qdrant 밖에 있어 Qdrant 필터를 사용할 수 없음  
**해결:** `bm25_metas` 리스트를 병렬 유지하여 Python 레벨에서 필터링
```python
indexed = [
    (i, s) for i, s in indexed
    if (not allowed_banks or bm25_metas[i].get("bank_name") in allowed_banks)
    and (not allowed_types or bm25_metas[i].get("loan_type") in allowed_types)
]
```

### 문제 3: PYTHONUNBUFFERED 미설정으로 로그 미출력

**증상:** Docker 컨테이너에서 print 출력이 `docker logs`에 나타나지 않음  
**원인:** Python 기본 stdout 버퍼링 — 비-TTY 환경(Docker)에서는 블록 버퍼링 적용  
**해결:** `python/Dockerfile`에 `ENV PYTHONUNBUFFERED=1` 추가

### 문제 4: load_dotenv override=True로 Docker 환경변수 덮어쓰기

**증상:** `docker-compose`에서 `QDRANT_URL=http://qdrant:6333`을 주입해도 실제 연결은 `localhost:6333`으로 시도 → Connection refused  
**원인:** `python/.env`의 `QDRANT_URL=http://localhost:6333`이 `override=True` 옵션으로 docker 환경변수를 덮어씀  
**해결:** `load_dotenv(override=False)` 로 변경 — 이미 주입된 환경변수를 .env가 덮어쓰지 않도록

---

## 기대 효과

| 쿼리 유형 | Before | After |
|-----------|--------|-------|
| `"신한은행 신용대출"` (은행명 명시) | Dense가 의미적 유사 문서 우선 | BM25가 "신한은행" 정확 매칭 + RRF 통합 |
| `"금리 3% 이하"` (수치 검색) | 임베딩 공간에서 수치 구분 어려움 | BM25 키워드 매칭으로 관련 문서 상위 |
| `"변동금리 주택담보대출 비교"` (의미 검색) | Dense가 강점 | Dense 결과 그대로 유지 |

RRF 통합 후 BGE-Reranker가 최종 정렬을 담당하므로, 두 방식 중 하나가 좋은 후보를 가져오기만 해도 최종 top-3 품질이 향상된다.

---

## 의존성

```
rank-bm25==0.2.2   # BM25 구현체 (numpy 기반)
```

기존 의존성 변경 없음. BM25 인덱스는 in-memory라 별도 인프라 불필요.

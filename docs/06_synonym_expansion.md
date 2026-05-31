# RAG 검색 별칭과 동의어 확장

## 개요

HyDE hard set 평가에서 `국민은행 마통 금리 알려줘` 케이스가 2위에 머물렀다.

```text
Baseline hard set Recall@1 = 0.833
HyDE hard set Recall@1     = 0.833
```

원인은 HyDE보다 `마통` 같은 금융권 줄임말이 원문 상품명인 `마이너스한도대출`과 직접 매칭되지 않는 문제였다.

동의어를 모두 쿼리 확장 규칙으로 관리하면 유지보수가 어려워진다. 그래서 다음 방향으로 나눴다.

```text
확실한 줄임말 몇 개만 쿼리에서 확장
대부분의 별칭은 문서 적재 시 상품 문서 안에 저장
```

## 적용 방식

### 1. 문서 적재 시 별칭 추가

상품명과 상품종류를 보고 검색 별칭을 만든 뒤 청크 본문과 metadata에 함께 저장한다.

예시:

```text
[상품명] 마이너스한도대출
[검색 별칭]
마통 마이너스통장 마이너스한도대출 한도대출
```

이렇게 하면 사용자가 `마통`으로 검색해도 BM25가 문서 쪽 별칭에 직접 매칭될 수 있다.

### 2. 쿼리에서는 확실한 줄임말만 확장

쿼리 확장은 자주 쓰이고 의미가 명확한 표현만 처리한다.

| 입력 표현 | 쿼리 확장 |
|---|---|
| 마통, 마이너스 통장 | 마이너스통장, 마이너스한도대출 |
| 주담대 | 주택담보대출 |
| 아담대 | 아파트담보대출 |
| 전세대출 | 전세자금대출 |
| 정기예금 | 예금, 정기예금 |
| 연금저축 | 연금저축 |

## 변경 파일

| 파일 | 변경 내용 |
|---|---|
| `python/document_aliases.py` | 상품명과 상품종류 기반 문서 별칭 생성 |
| `python/query_expansion.py` | 쿼리 확장을 확실한 금융 줄임말 중심으로 축소 |
| `python/fss_crawler.py` | 청크 본문과 metadata에 `aliases` 저장 |
| `python/main.py` | `/chat` 검색 전에 `expand_domain_synonyms()` 적용 |
| `python/eval_retrieval.py` | 평가 검색에도 동일한 쿼리 확장 적용 |

## 평가 방법

문서 별칭은 Qdrant에 새로 적재해야 반영된다.

```powershell
docker compose up -d --build fastapi
docker compose exec fastapi python eval_retrieval.py --difficulty hard --output-json eval_before_alias_refresh.json
```

그 다음 `/admin/refresh` 또는 startup 적재를 통해 벡터를 다시 만들고 평가한다.

```powershell
docker compose exec fastapi python eval_retrieval.py --difficulty hard --output-json eval_after_alias_refresh.json
```

확인 케이스:

```text
hard_kb_minus_colloquial
질문: 국민은행 마통 금리 알려줘
기대: 마이너스한도대출 rank 1
```

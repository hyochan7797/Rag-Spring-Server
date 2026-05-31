# RAG 검색 최적화: HyDE

## 개요

HyDE(Hypothetical Document Embeddings)는 사용자 질문을 그대로 임베딩하지 않고, 질문에 답하는 형태의 짧은 가상 문서를 LLM으로 만든 뒤 그 문서를 Dense 검색에 사용하는 방식이다.

금융 상품 문서는 상품명, 금리, 한도, 가입조건 같은 설명형 문장으로 되어 있으므로, 짧은 질문보다 답변형 문장이 벡터 공간에서 실제 문서와 더 가까울 수 있다.

## 적용 방식

현재 구현은 HyDE를 옵션으로만 켠다.

```text
사용자 질문
  -> Query Rewriting
  -> HyDE 가상 문서 생성
  -> Dense 검색: HyDE 문서 사용
  -> BM25 검색: 기존 검색 쿼리 사용
  -> RRF 통합
  -> BGE-Reranker 최종 정렬
```

BM25에는 HyDE 문서를 쓰지 않는다. HyDE가 틀린 방향으로 확장될 수 있기 때문에, 키워드 검색은 기존 쿼리로 유지해서 보정 역할을 하게 한다.

## 변경 파일

| 파일 | 변경 내용 |
|---|---|
| `python/rag_pipeline.py` | `hyde_query` 파라미터 추가, Dense 검색에만 HyDE 쿼리 적용 |
| `python/main.py` | `/chat` 요청의 `use_hyde` 옵션과 `generate_hyde_query()` 추가 |
| `python/eval_retrieval.py` | `--use-hyde` 옵션 추가 |
| `python/eval_golden_set.json` | easy/hard 평가 케이스 추가 |
| `docs/04_evaluation.md` | HyDE 전후 평가 방법과 측정 결과 정리 |

## 실행 방법

기본 검색 평가:

```powershell
docker compose exec fastapi python eval_retrieval.py --output-json eval_baseline.json
```

HyDE 검색 평가:

```powershell
docker compose exec fastapi python eval_retrieval.py --use-hyde --output-json eval_hyde.json
```

Gemini free tier에서 429 quota 오류가 나면 hard set만 나누어 실행하거나 `--hyde-delay`를 늘린다.

```powershell
docker compose exec fastapi python eval_retrieval.py --difficulty hard --use-hyde --hyde-delay 15 --output-json eval_hyde_hard.json
```

서비스 호출에서 HyDE를 켜려면 FastAPI `/chat` 요청에 `use_hyde`를 추가한다.

```json
{
  "user_id": "test_user",
  "question": "국민은행 마통 금리 알려줘",
  "use_hyde": true
}
```

기본값은 `false`라서 기존 Spring 호출 흐름에는 영향이 없다.

## 2026-05-31 현재 결과

Easy set 기준으로는 baseline과 HyDE가 모두 만점이다.

```text
Baseline Recall@1 = 1.000
HyDE     Recall@1 = 1.000
```

이 결과는 HyDE가 불필요하다는 뜻이 아니라, 현재 easy set이 너무 명확하다는 뜻이다. 그래서 줄임말, 상품명 생략, 넓은 질의가 포함된 hard set을 추가했다.

## 주의사항

HyDE는 Gemini 호출이 한 번 더 들어가므로 지연 시간과 API 비용이 늘어난다. 또한 가상 문서가 질문 의도를 과하게 확장하면 Dense 검색 품질이 떨어질 수 있다.

그래서 적용 여부는 `eval_retrieval.py`로 baseline과 HyDE 결과를 비교한 뒤 결정한다.

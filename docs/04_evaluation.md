# RAG 검색 품질 평가 프레임워크

검색 파이프라인 변경 전후 품질을 수치로 비교하기 위한 평가 도구다.

## 구성

| 파일 | 역할 |
|---|---|
| `python/eval_golden_set.json` | 어려운 질문과 정답 문자열을 가진 골든셋 |
| `python/eval_retrieval.py` | 검색 결과를 평가하고 Recall, MRR, NDCG 출력 |

## 골든셋 구성

현재 골든셋은 hard-only 24개 케이스다. easy set은 제거했다.

의도적으로 다음 유형을 포함한다.

```text
상품명 생략
은행명 또는 회사명 표기 흔들림
마통, 주담대 같은 줄임말
예금/적금/대출 교차 질문
연금저축 옵션 조건 질문
금융회사 지역/연락처 질문
```

상품군은 대출, 예금, 적금, 연금저축, 금융회사를 모두 포함한다.

```text
sinyoung
dambo_mortgage / dambo_jeonse
deposit
saving
annuity_saving
company
```

각 케이스는 다음 형식이다.

```json
{
  "id": "hard_credit_colloquial_minus",
  "difficulty": "hard",
  "question": "국민은행 마통 금리랑 조건 알려줘",
  "expected_any": ["마이너스한도대출"]
}
```

`expected_any` 중 하나라도 검색 결과 문서에 포함되면 정답으로 본다.

## 실행 방법

`python` 폴더는 컨테이너에 bind mount되지 않는다. 골든셋을 바꾼 뒤에는 먼저 FastAPI 이미지를 다시 빌드한다.

```powershell
docker compose up -d --build fastapi
```

전체 평가:

```powershell
docker compose exec fastapi python eval_retrieval.py --output-json eval_hard_only_730.json
```

hard만 명시해서 실행:

```powershell
docker compose exec fastapi python eval_retrieval.py --difficulty hard --output-json eval_hard_only_730.json
```

HyDE 옵션과 비교:

```powershell
docker compose exec fastapi python eval_retrieval.py --difficulty hard --output-json eval_baseline_hard_only_730.json
docker compose exec fastapi python eval_retrieval.py --difficulty hard --use-hyde --hyde-delay 15 --output-json eval_hyde_hard_only_730.json
```

## 지표

| 지표 | 의미 |
|---|---|
| Recall@1 | 첫 번째 결과가 정답인지 |
| Recall@k | 상위 k개 안에 정답이 포함되는지 |
| MRR | 첫 정답 순위의 역수 평균 |
| NDCG@k | 정답이 상위에 있을수록 높게 주는 순위 가중 점수 |

## 현재 데이터 상태

2026-05-31 기준 Qdrant 적재 상태:

```text
collection       loan_docs_v1
total            730
annuity_saving   343
company          173
saving            59
sinyoung          43
dambo_jeonse      41
deposit           37
dambo_mortgage    34
```

## 해석 기준

hard-only 골든셋에서 실패가 나오면 다음 순서로 본다.

```text
1. 필터 추출이 잘못 걸렸는지
2. 문서 별칭이 부족한지
3. 쿼리 별칭이 부족한지
4. BM25가 못 잡는 표현인지
5. Dense 후보에는 있는데 reranker가 밀어냈는지
6. 멀티쿼리 검색이 필요한지
```

HyDE는 비용과 지연이 있으므로 기본값은 OFF다. hard-only 기준으로 수치 개선이 확인될 때만 적용한다.

## 2026-05-31 hard-only 1차 결과

24개 hard-only 케이스 기준 1차 결과:

```text
Recall@1   0.875
Recall@10  0.958
MRR        0.903
NDCG@10    0.916
```

실패 또는 순위 밀림 케이스:

```text
hard_deposit_mobile_no_product_name  rank=2
hard_saving_woori_mobile             rank=6
hard_no_bank_product_discovery       rank=-
```

개선 반영:

```text
평가 스크립트도 실제 /chat과 동일하게 자동 필터 추출 사용
청년/월복리/앱/모바일/스마트폰 별칭 추가
예금/적금 문서에 모바일 가입 관련 검색 별칭 추가
KB + 연금저축/펀드 문맥에서는 KB자산운용도 은행 필터 후보에 포함
`우리은행 앱으로 드는 자유적금`은 WON적금뿐 아니라 우리SUPER주거래적금도 조건에 맞으므로 정답 후보에 포함
```

문서 별칭 변경은 Qdrant 재적재 후 반영된다.

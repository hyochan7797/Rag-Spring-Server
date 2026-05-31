# Spring/FastAPI 필터 책임 분리

## 결정

질문에서 은행명과 상품군을 자동 추론하는 로직은 FastAPI 한 곳에서 관리한다.

Spring은 필터를 추론하지 않는다.

## 이유

자동 필터는 Qdrant metadata 구조와 직접 연결된다.

```text
metadata.bank_name
metadata.loan_type
```

현재 상품군:

```text
sinyoung
dambo_mortgage
dambo_jeonse
deposit
saving
annuity_saving
company
```

이 타입들은 RAG 인덱스의 분류 체계이므로 FastAPI가 소유하는 것이 자연스럽다.

Spring과 FastAPI 양쪽에서 같은 분류를 관리하면 다음 문제가 생긴다.

```text
상품군 추가 시 두 군데 수정
정규식/별칭 불일치
평가 스크립트와 실제 앱 동작 불일치
멀티쿼리/HyDE/필터 누적 적용 위치 혼란
```

## 현재 요청 흐름

```text
Browser
  -> Spring /api/ask
      question만 전달
  -> FastAPI /chat
      user_id
      question
      history
  -> FastAPI 내부
      자동 필터 추출
      쿼리 확장
      Qdrant 검색
      rerank
      답변 생성
```

## 변경 내용

| 파일 | 변경 |
|---|---|
| `java/src/main/resources/templates/chat.html` | `allowed_banks`, `allowed_loan_types` 전송 제거 |
| `python/main.py` | `/chat` 요청 스키마에서 `allowed_*` 제거, FastAPI 내부 자동 필터만 사용 |
| `python/filter_extraction.py` | 앱과 평가가 공유하는 필터 추출 단일 모듈 |
| `python/eval_retrieval.py` | 실제 앱과 같은 필터 추출 경로로 평가 |

## 예외

나중에 사용자가 UI에서 직접 필터를 선택하는 기능을 만든다면, 그것은 자동 추론이 아니라 명시적 사용자 선택이다.

그 경우에는 별도 API 필드로 다시 설계한다.

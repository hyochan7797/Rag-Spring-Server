# RAG 검색 품질 개선: 쿼리 재작성 (Query Rewriting)

## 개요

사용자의 자연어 질문은 검색 시스템이 처리하기에 최적화된 형태가 아닌 경우가 많다.
"금리 싼 곳 알려줘", "저번에 말한 거 비교해줘" 같은 표현은 사람끼리는 통하지만,
벡터 임베딩과 BM25 키워드 매칭 모두에서 검색 품질이 크게 떨어진다.

이를 해결하기 위해 **LLM(Gemini)을 활용한 쿼리 재작성 단계**를 검색 파이프라인 앞에 추가했다.

---

## 문제 정의

### Before — 원본 질문을 그대로 검색

사용자가 입력하는 질문에는 두 가지 유형의 노이즈가 있다.

**① 모호한 표현**

| 사용자 입력 | 실제 의도 |
|---|---|
| "금리 싼 곳 어디야?" | 최저금리 신용대출 상품 조회 |
| "빌릴 수 있는 데 알려줘" | 대출 가능 상품 목록 |
| "직장인인데 얼마나 받을 수 있어?" | 직장인 신용대출 한도 조회 |

→ Dense 검색은 의미 유사도로 어느 정도 커버하지만, BM25는 "금리", "신용대출" 같은 정확한 키워드가 없으면 결과가 없다.

**② 다중 턴 대화에서 맥락 생략**

```
턴 1: "우리은행 신용대출 금리 알려줘"       ← 은행·종류 명시
턴 2: "그럼 거기 한도는 어떻게 돼?"        ← "거기"가 우리은행 신용대출을 가리키지만
                                           검색 쿼리엔 "우리은행", "신용대출" 없음
```

→ 턴 2 질문으로 검색하면 "우리은행" 필터도 없고, BM25 키워드도 없어 전혀 다른 상품이 검색됨.

---

## 해결책 — LLM 기반 쿼리 재작성

검색 전에 Gemini에게 질문을 검색 최적화 형태로 변환시킨다.

```
원본: "그럼 거기 한도는?"
재작성: "우리은행 신용대출 대출 한도 및 최대 대출 가능 금액"
```

**핵심 설계 원칙:**
- 재작성된 쿼리는 **검색(BM25 + Dense)에만** 사용
- **답변 생성(Gemini)은 원본 질문** 그대로 사용 → 사용자 표현 보존, 의도 왜곡 방지

---

## 변경 전/후 파이프라인

### Before

```
사용자 질문 (원본)
    │
    ├──────────────────────┐
    ▼                      ▼
[Dense 검색]          [BM25 검색]         ← 모호한 원본 쿼리로 검색
    │                      │
    └──────────┬───────────┘
               ▼
         [RRF 통합]
               ▼
       [BGE-Reranker]
               ▼
       [Gemini 답변 생성]
```

### After

```
사용자 질문 (원본)
    │
    ▼
[쿼리 재작성] Gemini          ← 대화 맥락 + 모호한 표현 → 검색 최적화 쿼리
    │                             실패 시 원본으로 자동 fallback
    │ (재작성 쿼리)               (원본 질문 보존)
    ├──────────────────────┐           │
    ▼                      ▼           │
[Dense 검색]          [BM25 검색]      │
    │                      │           │
    └──────────┬───────────┘           │
               ▼                       │
         [RRF 통합]                    │
               ▼                       │
       [BGE-Reranker]                  │
               ▼                       │
       [Gemini 답변 생성] ◄────────────┘
       (원본 질문 기반)
```

---

## 구현 상세

### 추가된 함수: `rewrite_query()`  (`python/main.py`)

```python
async def rewrite_query(question: str, history: list) -> str:
    if generation_model is None:
        return question  # Gemini 없으면 그냥 원본 반환

    # 현재 질문 제외, 이전 user 메시지 최대 3개
    prev_user_msgs = [m["content"] for m in history if m["role"] == "user"]
    context_str = " / ".join(prev_user_msgs[-4:-1]) if len(prev_user_msgs) > 1 else ""

    prompt = f"""...[변환 규칙 포함 프롬프트]...
[이전 대화]: {context_str}
[현재 질문]: {question}
검색 쿼리만 출력:"""

    try:
        resp = await asyncio.to_thread(generation_model.generate_content, prompt)
        rewritten = resp.text.strip()
        if rewritten and rewritten != question:
            print(f"🔄 쿼리 재작성: '{question}' → '{rewritten}'")
            return rewritten
    except Exception as e:
        print(f"⚠️ 쿼리 재작성 실패, 원본 사용: {e}")
    return question
```

### 변경된 `/chat` 엔드포인트 (`python/main.py`)

```python
# --- 3. 쿼리 재작성 (검색 품질 향상) ---
rewritten = await rewrite_query(question, history)

# --- 4. RAG 파이프라인 호출 ---
top_docs, top_scores = await search_similar_docs(
    history_list=history,
    query=question,           # 원본 (보존)
    allowed_banks=final_banks,
    allowed_types=final_types,
    rewritten_query=rewritten, # 재작성 쿼리 (검색용)
)

# 답변 생성은 원본 question 사용 (변경 없음)
messages = [{"role": "user", "parts": [system_prompt + "\n\n고객 질문: " + question]}]
```

### 변경된 `search_similar_docs()` (`python/rag_pipeline.py`)

```python
async def search_similar_docs(
    history_list, query,
    allowed_banks=None, allowed_types=None,
    rewritten_query: Optional[str] = None,   # 신규 파라미터
):
    if rewritten_query:
        full_query = rewritten_query  # 이미 맥락 반영됨
    else:
        recent_context = " ".join(...)
        full_query = (recent_context + " " + query).strip()
    # 이후 Dense → BM25 → RRF → Reranker 동일
```

---

## 트러블슈팅

### 문제 1: 재작성 쿼리가 원본 의도를 벗어남

**증상:** "국민은행 금리 비교해줘" → "국민은행 KB스타대출 변동금리 고정금리 비교 분석" 처럼 과도하게 확장  
**원인:** LLM이 프롬프트 없이 자유롭게 생성하면 hallucination 포함 가능  
**해결:** 프롬프트에 명시적 제약 추가
```
4. 원래 질문의 의도를 반드시 유지할 것
```
그리고 Gemini가 생성한 쿼리가 원본 질문과 동일하면 재작성 생략 처리.

---

### 문제 2: 재작성 쿼리 + 히스토리 이중 컨텍스트 문제

**증상:** `search_similar_docs` 내부에서 `recent_context + rewritten_query`가 합산되어 검색 쿼리가 비대해짐  
**원인:** 기존 `search_similar_docs`는 히스토리 최근 2개 user 메시지를 쿼리에 항상 붙였는데, 재작성 쿼리는 이미 맥락을 반영한 상태  
**해결:** `rewritten_query` 파라미터가 있을 때는 히스토리 컨텍스트 확장을 스킵

```python
if rewritten_query:
    full_query = rewritten_query  # 이중 확장 방지
else:
    recent_context = " ".join(...)
    full_query = (recent_context + " " + query).strip()
```

---

### 문제 3: 쿼리 재작성 Gemini API 호출 지연

**증상:** 재작성 단계에서 추가 LLM 호출 → 응답 지연 발생 우려  
**원인:** Gemini API는 동기 호출이며 FastAPI의 이벤트 루프를 블로킹  
**해결:** `asyncio.to_thread()`로 비동기 처리
```python
resp = await asyncio.to_thread(generation_model.generate_content, prompt)
```
또한 재작성 실패(API 오류, 타임아웃) 시 원본 쿼리를 자동으로 사용하는 fallback 적용.

---

### 문제 4: 답변 생성에 재작성 쿼리 사용 시 표현 변형

**증상 (설계 단계):** 재작성 쿼리를 Gemini 답변 생성에도 사용하면, 사용자가 "거기 한도는?" 이라고 물었을 때 답변이 재작성된 쿼리 기준으로 생성되어 부자연스러운 답변 출력  
**해결:** 검색(rewritten_query)과 답변 생성(원본 question)을 철저히 분리

```python
# 검색: 재작성 쿼리
top_docs, top_scores = await search_similar_docs(..., rewritten_query=rewritten)

# 답변 생성: 원본 질문
messages = [{"role": "user", "parts": [system_prompt + "\n\n고객 질문: " + question]}]
```

---

## 개선 효과

| 질문 유형 | Before | After |
|---|---|---|
| 모호한 구어체 ("싼 곳", "빌리다") | BM25 키워드 미스 → Dense only 폴백 | 재작성 후 "최저금리 대출" → BM25·Dense 모두 히트 |
| 다중 턴 맥락 생략 ("거기", "그거") | 이전 은행명·종류 누락 → 엉뚱한 상품 검색 | 재작성에서 이전 맥락 보완 → 정확한 필터 매칭 |
| 명확한 질문 ("우리은행 신용대출 금리") | 정상 동작 | 재작성 결과 = 원본 → 추가 비용 없음 |
| Gemini API 실패 | - | 원본 쿼리로 자동 fallback → 서비스 무중단 |

---

## 수정된 파일

| 파일 | 변경 내용 |
|---|---|
| `python/main.py` | `rewrite_query()` 함수 추가, `/chat` 엔드포인트에 재작성 단계 삽입 |
| `python/rag_pipeline.py` | `search_similar_docs()`에 `rewritten_query` 파라미터 추가, 이중 컨텍스트 방지 로직 |

---

## 의존성

신규 라이브러리 없음. 이미 사용 중인 Gemini(`google-generativeai`) 재활용.

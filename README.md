# Rag-Spring-Server

금융상품 RAG 챗봇의 Spring Boot 백엔드 서버입니다.  
사용자 인증/세션 관리, 대화 이력 저장, FastAPI RAG 서버 연동을 담당합니다.

## 아키텍처

```
사용자
  → Spring (이 레포)
      로그인/세션 관리
      MySQL 대화 이력 저장
      FastAPI로 질문과 히스토리 전달
  → FastAPI (별도 레포)
      질문 분석 / 필터 추출 / 쿼리 확장
      Qdrant Dense 검색 + BM25 + RRF + BGE Reranker
      Gemini 답변 생성
```

FastAPI RAG 서버는 별도 레포에서 관리합니다.

## 기술 스택

| 구성 요소 | 내용 |
|---|---|
| Spring Boot | Java 17, Gradle |
| DB | MySQL 8 |
| 컨테이너 | Docker / Docker Compose |
| CI/CD | GitHub Actions → GHCR → EC2 |

## 로컬 실행

### 1. 환경변수 설정

```bash
cp .env.example .env
```

`.env`에서 다음 값을 수정합니다.

```
MYSQL_ROOT_PASSWORD=...
MYSQL_DATABASE=finance_db
MYSQL_USER=app_user
MYSQL_PASSWORD=...
ADMIN_API_KEY=...
```

FastAPI가 로컬에서 실행 중이라면 기본값(`http://host.docker.internal:8000`)이 자동으로 사용됩니다.

### 2. 실행

```bash
docker compose up -d
```

Spring은 `localhost:8080`, MySQL은 `localhost:3308`으로 노출됩니다.

### 3. 헬스체크

```bash
curl http://localhost:8080/actuator/health
```

## EC2 배포 (Spring + MySQL만 AWS, FastAPI는 로컬)

FastAPI가 EC2에 올리기 무거운 경우 이 방식을 사용합니다.  
자세한 내용은 [docs/SPRING_AWS_LOCAL_FASTAPI.md](docs/SPRING_AWS_LOCAL_FASTAPI.md)를 참고하세요.

### 개요

```
Browser
  → EC2:8080 (Spring + MySQL)
  → ngrok/Cloudflare Tunnel
  → 로컬 FastAPI
  → 로컬 Qdrant / 로컬 모델
```

### EC2 초기 설정

EC2의 `~/Rag-Spring-Server/.env`에 아래 값을 설정합니다.

```
MYSQL_ROOT_PASSWORD=...
MYSQL_DATABASE=finance_db
MYSQL_USER=app_user
MYSQL_PASSWORD=...
ADMIN_API_KEY=...

FASTAPI_URL=https://example.ngrok-free.app/chat
FASTAPI_ADMIN_URL=https://example.ngrok-free.app/admin/refresh

LOAN_REFRESH_CRON=-
```

### EC2 배포 명령

```bash
cd ~/Rag-Spring-Server
docker compose -f docker-compose.spring-aws.yml pull
docker compose -f docker-compose.spring-aws.yml up -d
docker compose -f docker-compose.spring-aws.yml ps
curl http://localhost:8080/actuator/health
```

### 로컬 FastAPI 터널 노출 (ngrok)

```bash
ngrok http 8000
```

ngrok URL이 바뀌면 EC2 `.env`의 `FASTAPI_URL`, `FASTAPI_ADMIN_URL`을 수정하고 Spring 컨테이너를 재시작합니다.

```bash
docker compose -f docker-compose.spring-aws.yml up -d --force-recreate spring
```

## CI/CD

`main` 브랜치에 push하면 GitHub Actions가 자동 실행됩니다.

1. Gradle 테스트
2. Docker 이미지 빌드 → GHCR(`ghcr.io/hyochan7797/rag-spring`) push
3. EC2에 `docker-compose.spring-aws.yml` 복사
4. EC2에서 `docker compose pull && up -d`

필요한 GitHub Secrets:

| Secret | 설명 |
|---|---|
| `EC2_HOST` | EC2 퍼블릭 IP 또는 도메인 |
| `EC2_USER` | EC2 SSH 사용자명 |
| `EC2_SSH_KEY` | EC2 SSH 개인키 |
| `EC2_PORT` | SSH 포트 (기본 22) |
| `GHCR_READ_TOKEN` | EC2에서 GHCR 이미지 pull용 토큰 |

## 데이터 갱신 (수동 refresh)

Spring을 통해 FastAPI의 `/admin/refresh`를 호출합니다.

```bash
curl -X POST http://localhost:8080/admin/batch/refresh \
  -H "X-Admin-Key: <ADMIN_API_KEY>"
```

이 요청은 FSS API 전체 수집 → Qdrant 재적재 → BM25 인덱스 갱신을 수행합니다.  
소요 시간이 길 수 있습니다 (기본 read-timeout 10분).

## 환경변수 목록

| 변수 | 기본값 | 설명 |
|---|---|---|
| `MYSQL_ROOT_PASSWORD` | (필수) | MySQL root 비밀번호 |
| `MYSQL_DATABASE` | `finance_db` | DB 이름 |
| `MYSQL_USER` | `app_user` | DB 사용자 |
| `MYSQL_PASSWORD` | (필수) | DB 비밀번호 |
| `ADMIN_API_KEY` | (필수) | admin 엔드포인트 인증키 |
| `FASTAPI_URL` | `http://host.docker.internal:8000/chat` | FastAPI chat 엔드포인트 |
| `FASTAPI_ADMIN_URL` | `http://host.docker.internal:8000/admin/refresh` | FastAPI admin 엔드포인트 |
| `LOAN_REFRESH_CRON` | `-` (비활성) | 자동 갱신 크론 표현식 |

## 관련 문서

- [RAG 시스템 전체 구조](docs/RAG_SYSTEM_GUIDE.md)
- [Spring on AWS + FastAPI 로컬 연동](docs/SPRING_AWS_LOCAL_FASTAPI.md)
- [Hybrid Search](docs/01_hybrid_search.md)
- [Data Enrichment](docs/02_data_enrichment.md)
- [Query Rewriting](docs/03_query_rewriting.md)
- [Evaluation](docs/04_evaluation.md)
- [HyDE](docs/05_hyde.md)
- [Synonym Expansion](docs/06_synonym_expansion.md)
- [FSS API Expansion](docs/07_fss_api_expansion.md)
- [Filter Ownership](docs/08_filter_ownership.md)

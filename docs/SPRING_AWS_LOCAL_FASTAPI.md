# Spring on AWS and FastAPI on local

This setup runs only Spring and MySQL on EC2. FastAPI runs on your local PC and is exposed to EC2 through a temporary public tunnel such as ngrok or Cloudflare Tunnel.

Use this for development and demos when the FastAPI RAG stack is too heavy for a small EC2 instance.

## Architecture

```text
Browser
  -> EC2:8080
  -> Spring container
  -> public tunnel URL
  -> local FastAPI
  -> local Qdrant / local model runtime
```

EC2 does not run FastAPI or Qdrant in this mode.

## EC2 compose file

Use:

```bash
docker compose -f docker-compose.spring-aws.yml up -d
```

`docker-compose.aws.yml` is also Spring/MySQL only now, but `docker-compose.spring-aws.yml` is the clearer file name for this mode.

## Local FastAPI

In the separate FastAPI repository on your local PC:

```bash
cd /c/Users/gyskf/IdeaProjects/ai-server/python
docker compose up -d qdrant
uvicorn main:app --host 0.0.0.0 --port 8000
```

FastAPI must have its local environment variables set, including:

```text
OPENAI_API_KEY=...
GOOGLE_API_KEY=...
FSS_API_KEY=...
ADMIN_API_KEY=...
QDRANT_URL=http://localhost:6333
COLLECTION_NAME=loan_docs
```

If local Qdrant is not running, start it locally before using RAG search.

Check FastAPI:

```bash
curl http://localhost:8000/health
```

## Expose local FastAPI with ngrok

On your local PC:

```bash
ngrok http 8000
```

ngrok will print a public HTTPS URL such as:

```text
https://example.ngrok-free.app
```

Use that URL for Spring:

```text
FASTAPI_URL=https://example.ngrok-free.app/chat
FASTAPI_ADMIN_URL=https://example.ngrok-free.app/admin/refresh
```

Both values are required on EC2. The Spring compose file intentionally fails fast when these are missing so the container does not accidentally call its own `localhost`.

## EC2 `.env`

In `~/rag/.env` on EC2, keep only Spring/MySQL values plus the remote FastAPI URLs:

```text
MYSQL_ROOT_PASSWORD=...
MYSQL_DATABASE=finance_db
MYSQL_USER=app_user
MYSQL_PASSWORD=...

ADMIN_API_KEY=...

FASTAPI_URL=https://example.ngrok-free.app/chat
FASTAPI_ADMIN_URL=https://example.ngrok-free.app/admin/refresh

LOAN_REFRESH_CRON=-
```

`LOAN_REFRESH_CRON=-` disables automatic refresh. Keep it disabled in this mode because the tunnel URL can change.

## EC2 deployment commands

```bash
cd ~/rag
docker compose -f docker-compose.spring-aws.yml pull
docker compose -f docker-compose.spring-aws.yml up -d
docker compose -f docker-compose.spring-aws.yml ps
curl http://localhost:8080/actuator/health
```

## Updating the FastAPI tunnel URL

When ngrok gives a new URL:

```bash
cd ~/rag
nano .env
docker compose -f docker-compose.spring-aws.yml up -d --force-recreate spring
```

Then check:

```bash
docker compose -f docker-compose.spring-aws.yml logs --tail=80 spring
```

## Manual refresh

Spring can call local FastAPI through the tunnel:

```bash
curl -X POST http://localhost:8080/admin/batch/refresh \
  -H "X-Admin-Key: $(grep ADMIN_API_KEY .env | cut -d= -f2)"
```

This request runs on EC2, reaches Spring, then Spring calls the local FastAPI tunnel URL.

## Notes

- Your local PC must stay on while Spring uses FastAPI.
- Free ngrok URLs can change when restarted.
- Keep `ADMIN_API_KEY` long and secret because `/admin/refresh` is reachable through the tunnel.
- This is a development/demo setup, not a production architecture.

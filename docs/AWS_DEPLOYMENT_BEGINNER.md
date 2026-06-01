# AWS beginner deployment guide

This project is prepared for the lowest-complexity AWS path:

1. Run one EC2 instance.
2. Install Docker and Docker Compose.
3. Run Spring, FastAPI, MySQL, and Qdrant with `docker-compose.aws.yml`.

This avoids paid managed services such as RDS at the beginning. It is simpler and usually cheaper for a small learning deployment, but the database lives on the EC2 disk, so backups matter.

## Cost safety first

Before creating servers:

1. Create an AWS Budget.
2. Add a billing alarm.
3. Use one small EC2 instance only.
4. Stop or terminate the EC2 instance when you are done practicing.
5. Do not create RDS, NAT Gateway, or Load Balancer yet.

## Local files used for AWS

- `docker-compose.aws.yml`: production-style Compose file for one EC2.
- `.env`: real secret values. Do not commit this file.
- `.env.example`: template for required environment variables.
- `java/src/main/resources/application-prod.yml`: Spring production profile.

## EC2 inbound ports

For the first test, open only:

- SSH: `22`, from your IP only.
- Spring app: `8080`, from your IP first. Later, open to public if needed.

MySQL, Qdrant, and FastAPI are not exposed to the internet in `docker-compose.aws.yml`.

## First EC2 commands

After connecting to the EC2 instance:

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin git
sudo usermod -aG docker ubuntu
exit
```

Reconnect, then:

```bash
git clone <your-repository-url>
cd rag
cp .env.example .env
nano .env
docker compose -f docker-compose.aws.yml up -d --build
docker compose -f docker-compose.aws.yml logs -f spring
```

Health check:

```bash
curl http://localhost:8080/actuator/health
```

From your PC browser:

```text
http://<EC2_PUBLIC_IP>:8080
```

## Batch controls

Manual refresh:

```bash
curl -X POST http://localhost:8080/admin/batch/refresh \
  -H "X-Admin-Key: <ADMIN_API_KEY>"
```

Batch status:

```bash
curl http://localhost:8080/admin/batch/status \
  -H "X-Admin-Key: <ADMIN_API_KEY>"
```

To disable the automatic daily schedule and run only manual refreshes, set this in `.env`:

```text
LOAN_REFRESH_CRON=-
```

## Later improvements

After the first successful deployment:

1. Add a domain.
2. Add HTTPS with Nginx and Let's Encrypt.
3. Move MySQL to RDS only if you accept the cost.
4. Add automated backups for MySQL and Qdrant volumes.

# Jenkins CI/CD beginner guide

This project can use Jenkins for a simple CI/CD flow:

```text
Git push -> Jenkins pipeline -> Spring tests -> Docker Compose build -> EC2 deploy
```

## Recommended learning order

1. Deploy manually to EC2 once.
2. Confirm the app works at `http://<EC2_PUBLIC_IP>:8080`.
3. Install Jenkins on the same EC2 instance for practice.
4. Connect Jenkins to your Git repository.
5. Add the production `.env` file as a Jenkins credential.
6. Run the pipeline from `Jenkinsfile`.

Manual deployment first is important because it proves AWS, Docker, environment variables, and security group settings work before Jenkins is added.

## Cost and server warning

Jenkins, MySQL, Qdrant, FastAPI, and Spring on one small EC2 instance can be heavy. This is okay for learning, but not ideal for real production.

For the cheapest beginner setup:

- Use one EC2 instance.
- Stop the EC2 instance when you are not practicing.
- Do not add RDS, Load Balancer, NAT Gateway, or ECR yet.

## Jenkins credential needed

The `Jenkinsfile` expects one file credential:

```text
Credential ID: rag-prod-env
Type: Secret file
Content: your production .env file
```

The secret file should contain values like:

```text
MYSQL_ROOT_PASSWORD=...
MYSQL_DATABASE=finance_db
MYSQL_USER=app_user
MYSQL_PASSWORD=...
COLLECTION_NAME=loan_docs
ADMIN_API_KEY=...
OPENAI_API_KEY=...
GOOGLE_API_KEY=...
FSS_API_KEY=...
LOAN_REFRESH_CRON=0 0 2 * * *
```

Do not commit the real `.env` file to Git.

## Jenkins pipeline behavior

The pipeline:

1. Validates `docker-compose.aws.yml`.
2. Runs Spring tests.
3. Builds the Spring jar.
4. Deploys with Docker Compose only on the `main` branch.
5. Prints the latest Spring logs after each run.

## First Jenkins job

Create a Jenkins job:

1. New Item.
2. Choose `Pipeline`.
3. Pipeline definition: `Pipeline script from SCM`.
4. SCM: Git.
5. Repository URL: your Git repository URL.
6. Branch: `*/main`.
7. Script Path: `Jenkinsfile`.
8. Save.
9. Click `Build Now`.

## Common failure points

- `docker: permission denied`: Jenkins user cannot access Docker.
- `rag-prod-env not found`: the Jenkins secret file credential is missing.
- Spring test fails: Java/JDK or database test profile issue.
- App does not open in browser: EC2 security group does not allow inbound `8080`.

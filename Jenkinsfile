pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
    }

    environment {
        COMPOSE_FILE = 'docker-compose.aws.yml'
    }

    stages {
        stage('Validate') {
            steps {
                sh 'docker compose -f "$COMPOSE_FILE" config >/dev/null'
            }
        }

        stage('Test Spring') {
            steps {
                dir('java') {
                    sh 'chmod +x gradlew'
                    sh './gradlew test'
                }
            }
        }

        stage('Build Spring Jar') {
            steps {
                dir('java') {
                    sh './gradlew bootJar'
                }
            }
        }

        stage('Deploy To EC2') {
            when {
                branch 'main'
            }
            steps {
                withCredentials([file(credentialsId: 'rag-prod-env', variable: 'ENV_FILE')]) {
                    sh 'cp "$ENV_FILE" .env'
                    sh 'docker compose -f "$COMPOSE_FILE" up -d --build'
                    sh 'docker compose -f "$COMPOSE_FILE" ps'
                }
            }
        }
    }

    post {
        always {
            sh 'docker compose -f "$COMPOSE_FILE" logs --tail=80 spring || true'
        }
    }
}

# 1️⃣ Java 17 기반 이미지 (빌드용)
FROM eclipse-temurin:17-jdk AS build

# 2️⃣ 작업 디렉터리 설정
WORKDIR /app

# 3️⃣ Gradle Wrapper 및 설정 파일 복사
COPY gradlew .
COPY gradle gradle
COPY build.gradle .
COPY settings.gradle .

# 4️⃣ 소스 복사 및 빌드
COPY src src
RUN chmod +x gradlew && ./gradlew clean bootJar -x test

# 5️⃣ 실제 실행용 스테이지 (Slim)
FROM eclipse-temurin:17-jdk AS spring_build
WORKDIR /app

# 6️⃣ build/libs의 jar 복사
COPY --from=build /app/build/libs/*.jar app.jar

# 7️⃣ 포트 개방
EXPOSE 8080

# 8️⃣ 실행 명령
ENTRYPOINT ["java", "-jar", "app.jar"]

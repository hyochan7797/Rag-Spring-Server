FROM eclipse-temurin:17-jdk AS build

WORKDIR /app

COPY gradlew .
COPY gradle gradle
COPY build.gradle .
COPY settings.gradle .

RUN apt-get update \
    && apt-get install -y --no-install-recommends dos2unix \
    && dos2unix gradlew \
    && rm -rf /var/lib/apt/lists/*

COPY src src
RUN chmod +x gradlew && ./gradlew clean bootJar -x test

FROM eclipse-temurin:17-jre

WORKDIR /app
COPY --from=build /app/build/libs/*.jar app.jar

EXPOSE 8080

ENTRYPOINT ["java", "-jar", "app.jar"]

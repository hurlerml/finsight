FROM maven:3.9.9-eclipse-temurin-17 AS build

WORKDIR /build
COPY pom.xml ./
RUN mvn --batch-mode --strict-checksums dependency:go-offline
COPY src ./src
RUN mvn --batch-mode --strict-checksums package

FROM eclipse-temurin:17-jre

RUN groupadd --system finsight && useradd --system --gid finsight finsight
WORKDIR /app
COPY --from=build /build/target/fints-gateway.jar /app/fints-gateway.jar

USER finsight
EXPOSE 8082
ENTRYPOINT ["java", "-jar", "/app/fints-gateway.jar"]

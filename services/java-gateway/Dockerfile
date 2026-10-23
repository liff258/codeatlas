# ---------- 构建阶段 ----------
FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /build

# 先只拷 pom 拉依赖，利用层缓存：改业务代码不会重新下载整个依赖树
COPY pom.xml .
RUN mvn -B -q dependency:go-offline

COPY src ./src
RUN mvn -B -q -DskipTests package

# ---------- 运行阶段 ----------
FROM eclipse-temurin:17-jre-alpine
WORKDIR /app

# 时区与字符集：中文日志和 OffsetDateTime 都依赖它
ENV TZ=Asia/Shanghai \
    JAVA_TOOL_OPTIONS="-Dfile.encoding=UTF-8 -Duser.timezone=Asia/Shanghai"

COPY --from=build /build/target/*.jar app.jar

RUN addgroup -S app && adduser -S app -G app && chown app:app app.jar
USER app

EXPOSE 8080

ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-XX:+UseG1GC", "-jar", "app.jar"]

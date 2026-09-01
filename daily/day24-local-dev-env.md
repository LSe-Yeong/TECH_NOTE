# 팀 로컬 개발 환경 표준화하기

> 이 문서가 답할 질문: **팀원마다 갈라진 로컬 환경은 실제로 무엇을 깨뜨리고, 어디까지 코드로 고정해야 하는가?**
>
> 기준: Spring Boot 4.1 / Docker Compose v2 / Gradle 9 / Testcontainers for Java. 사내 배포 파이프라인, IDE 설정 동기화, 모노레포 빌드 캐시는 다루지 않습니다. "새로 온 사람이 저장소를 클론한 뒤 앱이 뜨기까지"에만 집중합니다.

## 1. 핵심 개념 — 표준화의 대상은 절차가 아니라 상태입니다

신입이 들어옵니다. README를 봅니다.

```
1. JDK 17을 설치합니다
2. 로컬에 PostgreSQL을 설치하고 사용자 dev/dev를 만듭니다
3. Redis를 설치하고 6379로 띄웁니다
4. application-local.yml을 팀에 요청하세요
```

이 문서대로 하면 이틀이 걸립니다. 그리고 이틀 뒤에도 안 됩니다. JDK는 21이 깔려 있고, 회사 노트북엔 다른 프로젝트가 쓰는 PostgreSQL 15가 이미 5432를 잡고 있고, `application-local.yml`을 준 사람의 것은 3개월 전 스키마 기준입니다.

여기서 팀은 보통 README를 더 자세히 씁니다. 단계가 4개에서 12개로 늘어납니다. 그래도 안 됩니다.

이유는 단순합니다. **문서는 틀려도 아무 일도 일어나지 않습니다.** PostgreSQL을 15에서 16으로 올린 사람은 자기 컴퓨터에서 잘 돌아가므로 README를 고칠 이유가 없습니다. 반면 저장소에 들어 있는 `compose.yaml`이 틀리면 그 사람 것부터 안 뜹니다.

> 로컬 환경 표준화는 "모두가 같은 절차를 따르게 만드는 일"이 아니라, **"틀어지면 즉시 깨지는 자리로 설정을 옮기는 일"** 입니다. 실행되지 않는 것은 표준이 될 수 없습니다.

이게 없으면 벌어지는 일은 온보딩 지연이 아닙니다. 진짜 비용은 그 뒤에 옵니다. 로컬에서만 재현되는 버그, 로컬에서만 재현 안 되는 버그, "제 컴퓨터에서는 되는데요"로 끝나는 리뷰. 환경이 변수로 남아 있으면 모든 디버깅에 "혹시 환경 문제인가"라는 분기가 하나씩 더 붙습니다.

## 2. 갈라지는 세 개의 층

로컬 환경이라는 뭉뚱그린 말을 쪼개면 세 층입니다. 층마다 어긋났을 때의 증상이 다르고, 고정하는 수단도 다릅니다.

| 층 | 무엇이 다른가 | 어긋나면 나오는 증상 | 고정 수단 |
|---|---|---|---|
| **툴체인** | JDK, 빌드 도구, 언어 런타임 버전 | 컴파일 에러, `UnsupportedClassVersionError`, CI에서만 실패 | Gradle 툴체인, Wrapper, mise/asdf |
| **백킹 서비스** | DB·Redis·큐의 버전, 스키마, 시드 데이터 | 특정 쿼리만 실패, 마이그레이션 충돌, 나만 나는 제약 위반 | Compose 파일, Testcontainers |
| **설정·시크릿** | 접속 정보, 기능 플래그, 외부 API 키 | 앱이 아예 안 뜨거나, 엉뚱한 환경을 바라봄 | `.env.example`, 환경변수 |

세 층은 독립적입니다. 그래서 하나만 잡고 다 됐다고 생각하는 순간이 위험합니다. Compose로 DB를 띄웠지만 JDK가 제각각인 팀, 툴체인은 고정했지만 각자 로컬 PostgreSQL을 쓰는 팀 모두 흔합니다.

### 2-1. 방향은 하나입니다 — 사람이 맞추던 것을 파일로 내립니다

세 층 모두 해법의 형태는 같습니다. **사람의 기억에 있던 값을 저장소 안의 파일로 내리고, 그 파일을 도구가 읽게 만듭니다.** 그러면 값이 틀렸을 때 사람이 아니라 도구가 먼저 알아챕니다.

## 3. 층별로 고정하기

### 3-1. 툴체인 — 빌드가 JDK를 고르게 합니다

"JDK 17을 설치하세요"는 표준화가 아닙니다. 빌드 스크립트가 JDK를 직접 고르게 하는 게 표준화입니다. Gradle의 Java 툴체인이 이걸 합니다.

```kotlin
// build.gradle.kts
java {
    toolchain {
        languageVersion = JavaLanguageVersion.of(21)
    }
}
```

이렇게 선언하면 Gradle이 컴파일·테스트·javadoc 태스크에 쓸 JDK를 로컬에서 찾습니다. 없으면 내려받습니다. 단, 자동 다운로드는 그냥 되지 않고 **툴체인 리졸버 플러그인을 붙여야 동작합니다**([Gradle Toolchains](https://docs.gradle.org/current/userguide/toolchains.html)).

```kotlin
// settings.gradle.kts
plugins {
    id("org.gradle.toolchains.foojay-resolver-convention") version "1.0.0"
}
```

여기서 핵심은 편의가 아닙니다. **개발자가 어떤 JDK로 Gradle을 실행하든 결과물이 같아진다**는 점입니다. Gradle을 띄우는 JVM과 코드를 컴파일하는 JVM이 분리되므로, "내 JAVA_HOME이 뭐였더라"가 빌드 결과에서 빠집니다.

Java 밖의 도구(Node, Terraform, AWS CLI 등)까지 버전을 맞춰야 한다면 `mise` 같은 버전 관리자를 저장소 설정 파일과 함께 씁니다. mise는 asdf의 `.tool-versions` 파일을 그대로 읽습니다([mise 문서](https://mise.jdx.dev/dev-tools/comparison-to-asdf.html)).

그리고 Gradle Wrapper는 반드시 커밋합니다. `gradlew`는 빌드 도구 자체의 버전을 고정하는 장치입니다. 이걸 빼고 각자 설치한 Gradle을 쓰면 툴체인을 아무리 잘 잡아도 소용없습니다.

### 3-2. 백킹 서비스 — 로컬에 설치하지 않습니다

DB를 로컬에 직접 설치하는 순간 그 DB는 사람마다 다른 상태를 갖습니다. 버전도, 스키마도, 남아 있는 데이터도 다릅니다. 컨테이너로 내리면 이 셋이 전부 파일에 적힙니다.

```yaml
# compose.yaml
services:
  postgres:
    image: postgres:16.4          # 태그를 고정합니다
    environment:
      POSTGRES_DB: orders
      POSTGRES_USER: orders
      POSTGRES_PASSWORD: local-only-password
    ports:
      - "15432:5432"              # 호스트 포트를 비틀어 충돌을 피합니다
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U orders -d orders"]
      interval: 5s
      timeout: 3s
      retries: 10

  redis:
    image: redis:7.4-alpine
    ports:
      - "16379:6379"
```

Spring Boot 3.1부터는 이 파일을 애플리케이션이 직접 다룹니다. `spring-boot-docker-compose`를 개발 전용 의존성으로 넣으면 앱을 실행할 때 `docker compose up`을 호출하고, 종료할 때 `docker compose stop`을 호출합니다. 컨테이너 접속 정보로 서비스 커넥션 빈까지 만들어 줍니다([Development-time Services](https://docs.spring.io/spring-boot/reference/features/dev-services.html)).

```kotlin
dependencies {
    developmentOnly("org.springframework.boot:spring-boot-docker-compose")
}
```

이 의존성의 값어치는 `docker compose up`을 대신 쳐주는 게 아닙니다. **`application-local.yml`에 적던 접속 URL·계정이 사라진다**는 점입니다. 사람이 옮겨 적는 값이 없어지면 그 값이 틀릴 일도 없습니다.

알아둘 속성 몇 개입니다.

| 속성 | 의미 |
|---|---|
| `spring.docker.compose.file` | compose 파일 경로를 명시 |
| `spring.docker.compose.lifecycle-management` | `none` / `start-only` / `start-and-stop` |
| `spring.docker.compose.skip.in-tests` | 테스트에서 건너뛸지 (기본값 `true`) |
| `spring.docker.compose.readiness.timeout` | 컨테이너 준비 대기 한도 |

스키마와 시드 데이터는 컨테이너에 맡기지 말고 마이그레이션 도구(Flyway, Liquibase)에 맡기는 편이 안전합니다. 이유는 함정 섹션에서 설명합니다.

### 3-3. 설정 — 저장소에는 구조를, 로컬에는 값을

세 번째 층은 이미 다룬 원칙을 그대로 씁니다. 저장소에는 "어떤 키가 필요한지"만 두고, 값은 각자의 환경변수로 넣습니다. 자세한 내용은 `day06-env-variable.md`를 참고합니다.

로컬 표준화 관점에서 하나만 덧붙입니다. **`.env.example`을 두되, 필수 키에 기본값을 주지 않습니다.** 기본값이 있으면 키를 빠뜨린 사람의 앱이 조용히 뜨고, 엉뚱한 곳을 바라보다가 나중에 터집니다. 없으면 그 자리에서 안 뜹니다. 안 뜨는 편이 훨씬 낫습니다.

## 4. 어디까지 갈 것인가

표준화에는 단계가 있고, 위로 갈수록 재현성은 올라가지만 대가도 커집니다. 전부 최상단으로 갈 필요는 없습니다.

| 단계 | 방식 | 얻는 것 | 내는 값 |
|---|---|---|---|
| 1 | README 절차 | 비용 0 | 드리프트를 막지 못함 |
| 2 | 저장소 파일로 고정 (Wrapper, 툴체인, compose.yaml, .env.example) | 툴체인·서비스·설정 3층 고정 | OS별 차이는 남음 |
| 3 | 개발 환경 전체를 컨테이너 안으로 (Dev Container) | OS·시스템 라이브러리까지 동일 | 빌드 시간, 파일 I/O 성능, 디버깅 난도 |

대부분의 백엔드 팀에게 **적정선은 2단계**입니다. JDK와 백킹 서비스와 설정 키가 고정되면 "제 컴퓨터에서는" 문제의 대부분이 사라집니다.

3단계를 고려할 만한 경우는 따로 있습니다. 네이티브 라이브러리를 링크해야 하거나(이미지 처리, 암호화 모듈), OS 패키지에 의존하거나, 팀에 Windows·macOS·Linux가 섞여 있고 그 차이가 실제로 문제를 만들어 온 경우입니다. 이때 [Dev Containers 스펙](https://containers.dev/)의 `devcontainer.json`을 쓰면 이미지·기능·포트 포워딩·생성 후 스크립트를 한 파일로 기술할 수 있습니다.

```jsonc
// .devcontainer/devcontainer.json
{
  "name": "order-service",
  "image": "mcr.microsoft.com/devcontainers/java:21",
  "forwardPorts": [8080],
  "postCreateCommand": "./gradlew build -x test"
}
```

생명주기 스크립트는 실행 시점이 다릅니다. `onCreateCommand`(컨테이너 최초 생성) → `updateContentCommand` → `postCreateCommand`(사용자에게 할당된 뒤) 순으로 생성 시 한 번, `postStartCommand`는 시작할 때마다, `postAttachCommand`는 도구가 붙을 때마다 실행됩니다. 앞 단계가 실패하면 뒤 단계는 실행되지 않습니다([devcontainer.json 레퍼런스](https://containers.dev/implementors/json_reference/)).

3단계의 대가는 명확합니다. 컨테이너 안에서 IDE 인덱싱과 빌드가 돌아가므로 느려지고, 볼륨 마운트 방식에 따라 파일 I/O가 눈에 띄게 떨어집니다. **"환경 차이로 잃은 시간"이 "컨테이너 때문에 느려진 시간"보다 클 때만 3단계로 갑니다.** 그 계산을 안 하고 올라가면 개발자들이 조용히 로컬 실행으로 돌아갑니다.

## 5. 예제

### 5-1. 재현되지 않는 compose 파일 ❌

```yaml
services:
  postgres:
    image: postgres:latest
    environment:
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    ports:
      - "5432:5432"
    volumes:
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

문제가 넷입니다.

1. `latest` — 오늘 클론한 사람과 반년 전 클론한 사람의 메이저 버전이 다릅니다.
2. `5432` 직접 노출 — 로컬에 깔린 다른 PostgreSQL과 충돌합니다.
3. `init.sql` + 영속 볼륨 — 스크립트는 데이터 디렉터리가 비어 있을 때만 실행됩니다. 볼륨이 남아 있으면 새로 추가한 테이블이 반영되지 않습니다([postgres 공식 이미지](https://hub.docker.com/_/postgres)).
4. `${DB_PASSWORD}` — 로컬 전용 컨테이너의 비밀번호를 개인 환경변수로 넘기면, 값이 없는 사람은 원인을 알기 어려운 실패를 만납니다.

### 5-2. 고정한 compose 파일 ✔️

```yaml
services:
  postgres:
    image: postgres:16.4
    environment:
      POSTGRES_DB: orders
      POSTGRES_USER: orders
      POSTGRES_PASSWORD: local-only-password
    ports:
      - "15432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U orders -d orders"]
      interval: 5s
      retries: 10
```

바뀐 점입니다.

- 태그를 패치 버전까지 고정합니다. 올릴 때는 커밋으로 올립니다. 그러면 "언제 누가 왜 올렸는지"가 남습니다.
- 호스트 포트를 비틀어 기존 설치와 공존시킵니다.
- 볼륨을 빼서 컨테이너를 **버려도 되는 것**으로 만듭니다. 상태가 남지 않으면 "내 로컬 DB만 이상한" 상황 자체가 생기지 않습니다. 데이터 유지가 필요하면 볼륨을 두되, 스키마는 반드시 마이그레이션 도구가 관리하게 합니다.
- 로컬 전용 비밀번호는 그냥 적습니다. 이 값은 시크릿이 아니라 로컬 컨테이너의 고정 상수입니다. 진짜 시크릿은 애초에 로컬 컨테이너에 들어가면 안 됩니다.
- 헬스체크를 넣습니다. 이게 없으면 앱이 DB보다 먼저 떠서 첫 실행만 실패하는, 원인 찾기 나쁜 증상이 생깁니다.

## 6. 개발용 DB와 테스트용 DB는 다른 문제입니다

Compose와 Testcontainers를 놓고 "둘 중 뭘 쓰냐"를 고민하는 경우가 많은데, 대체재가 아닙니다. 푸는 문제가 다릅니다.

| | Docker Compose | Testcontainers |
|---|---|---|
| 수명 | 개발자가 끌 때까지 | 테스트 실행 단위 |
| 데이터 | 계속 쌓임 (원하면 유지) | 매번 깨끗함 |
| 주 용도 | 앱 실행하며 손으로 확인 | 자동화된 테스트 |
| CI | 보통 필요 없음 | CI에서 그대로 동작 |

실무 구성은 대개 이렇습니다. **개발 실행은 Compose, 테스트는 Testcontainers.** Spring Boot의 `spring.docker.compose.skip.in-tests` 기본값이 `true`인 것도 이 조합을 전제로 합니다. 테스트가 Compose 컨테이너를 건드리지 않게 막아 두는 겁니다.

테스트 컨테이너 구성을 개발 실행에도 재사용하고 싶다면 Spring Boot가 별도 진입점을 제공합니다.

```java
// src/test/java/com/example/orders/TestOrderApplication.java
public class TestOrderApplication {
    public static void main(String[] args) {
        SpringApplication.from(OrderApplication::main)
                .with(ContainersConfiguration.class)
                .run(args);
    }
}
```

```java
@TestConfiguration(proxyBeanMethods = false)
class ContainersConfiguration {

    @Bean
    @ServiceConnection
    PostgreSQLContainer<?> postgresContainer() {
        return new PostgreSQLContainer<>("postgres:16.4");
    }
}
```

`./gradlew bootTestRun`으로 실행합니다. `@ServiceConnection`이 접속 정보를 자동으로 연결하므로 여기서도 URL을 손으로 적지 않습니다.

## 7. 함정

**볼륨에 남은 옛 스키마**

- **증상**: 동료가 추가한 컬럼이 내 로컬에만 없습니다. `init.sql`에는 분명히 들어 있습니다.
- **원인**: `/docker-entrypoint-initdb.d`의 스크립트는 데이터 디렉터리가 비어 있을 때만 실행됩니다. 이미 초기화된 볼륨이 붙어 있으면 통째로 건너뜁니다.
- **해법**: 스키마를 초기화 스크립트로 관리하지 않습니다. Flyway·Liquibase가 매 실행마다 차이를 적용하게 맡깁니다. 이미 꼬였다면 `docker compose down -v`로 볼륨째 지우고 다시 만듭니다.

**Testcontainers 재사용을 CI에 켜기**

- **증상**: 로컬 테스트는 빠른데 CI에서 간헐적으로 실패하거나 컨테이너가 계속 쌓입니다.
- **원인**: 재사용 기능은 테스트가 끝나도 컨테이너를 종료하지 않습니다. 공식 문서가 **CI 사용에 적합하지 않다**고 명시한 실험적 기능입니다([Testcontainers Reuse](https://java.testcontainers.org/features/reuse/)).
- **해법**: 켜는 스위치를 `~/.testcontainers.properties`나 `TESTCONTAINERS_REUSE_ENABLE` 환경변수에만 둡니다. 이 설정은 클래스패스 프로퍼티 파일로는 켜지지 않는데, 저장소에 커밋되어 CI까지 따라가는 걸 막는 구조입니다.

**로컬 compose 파일로 배포까지 하기**

- **증상**: 로컬 편의를 위해 넣은 포트 노출이나 디버그 옵션이 상위 환경에 그대로 나갑니다.
- **원인**: 파일 하나를 여러 환경이 공유하면 가장 관대한 설정으로 수렴합니다.
- **해법**: 로컬용 compose 파일은 로컬 전용으로 못 박습니다. 배포 매니페스트와 파일을 공유하지 않습니다.

**호스트 포트 고정 충돌**

- **증상**: 다른 프로젝트를 켜 두면 `bind: address already in use`가 납니다.
- **원인**: 여러 저장소가 관례적으로 같은 표준 포트를 호스트에 노출합니다.
- **해법**: 프로젝트마다 호스트 포트를 다르게 비틉니다(`15432`, `25432`). 컨테이너 내부 포트는 표준 그대로 두면 되므로 앱 설정은 건드릴 게 없습니다.

**arm64에 이미지가 없는 경우**

- **증상**: Apple Silicon 사용자만 컨테이너가 안 뜨거나 극단적으로 느립니다.
- **원인**: 멀티 아키텍처 이미지가 없어 에뮬레이션으로 돌아가거나 실행이 실패합니다.
- **해법**: 해당 서비스만 `platform: linux/amd64`를 명시해 동작을 예측 가능하게 만들고, 느려지는 걸 감수할지 대체 이미지를 쓸지 팀에서 정합니다. 조용히 각자 알아서 우회하는 상태가 가장 나쁩니다.

**표준화 파일이 CI에서 검증되지 않음**

- **증상**: 반년 뒤 새로 온 사람의 `compose.yaml`이 안 뜹니다.
- **원인**: 아무도 깨끗한 상태에서 시작해 본 적이 없습니다. 기존 팀원은 이미 만들어진 볼륨과 이미지를 쓰고 있습니다.
- **해법**: 클론 → 실행 → 헬스체크 통과까지를 CI 잡 하나로 만듭니다. 온보딩 절차를 파이프라인이 매일 대신 밟게 하는 겁니다.

## 8. 참고자료

- [Spring Boot — Development-time Services](https://docs.spring.io/spring-boot/reference/features/dev-services.html)
- [Gradle — Toolchains for JVM projects](https://docs.gradle.org/current/userguide/toolchains.html)
- [Development Containers Specification](https://containers.dev/implementors/json_reference/)
- [Testcontainers for Java — Reusable Containers](https://java.testcontainers.org/features/reuse/)
- [Docker — Compose Watch](https://docs.docker.com/compose/how-tos/file-watch/)
- [postgres 공식 이미지 — 초기화 스크립트](https://hub.docker.com/_/postgres)
- 관련 문서: `day06-env-variable.md`, `day18-graceful-shutdown.md`

<!-- TODO: Compose Watch(develop.watch)의 최소 요구 Compose 버전은 공식 문서에서 확인하지 못해 본문에 쓰지 않았습니다. 로컬 핫 리로드 절을 추가한다면 먼저 확인이 필요합니다. -->

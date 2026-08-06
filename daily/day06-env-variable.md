# 환경변수로 설정을 관리하는 법

> 이 문서가 답할 질문: **배포마다 달라지는 값을 왜 하필 환경변수로 빼고, 환경변수는 어디까지 감당할 수 있는가?**
>
> 기준: Spring Boot 4.1 / Docker Compose / Kubernetes.

## 1. 핵심 개념 — 설정은 코드가 아니라 배포에 속한다

여기서 말하는 **설정(config)** 은 "배포 환경마다 달라지는 값"입니다. DB 접속 정보, 외부 API 키, 연동 서버 호스트명 같은 것들입니다. 반대로 어떤 요청을 어떤 컨트롤러가 받을지 같은 규칙은 배포와 무관하니 설정이 아니라 코드입니다.

Twelve-Factor App이 제시하는 판별 기준은 한 문장입니다. **"지금 이 코드베이스를 그대로 오픈소스로 공개해도 유출되는 게 없는가?"** 없다면 설정이 제대로 분리된 겁니다 ([The Twelve-Factor App — Config](https://12factor.net/config)).

> `application.yml`에 개발 DB 주소를 적어두고 `application-prod.yml`에 운영 DB 주소를 적었습니다. 잘 돌아갑니다. 그런데 이 방식은 두 가지를 동시에 깨뜨립니다. 첫째, 운영 DB 비밀번호가 Git 히스토리에 영구히 남습니다. 지우고 다시 커밋해도 히스토리에는 그대로 있습니다. 둘째, staging이 생기고 QA 환경이 생기고 성능테스트 환경이 생깁니다. 파일이 환경 수만큼 늘어나고, 새 환경을 만들 때마다 코드를 고쳐서 배포해야 합니다. **설정이 코드에 묶여 있으면 환경을 늘리는 비용이 배포 비용이 됩니다.**

12-Factor가 환경변수를 고른 이유도 여기 있습니다. 언어·OS와 무관하게 존재하고, 실수로 커밋될 파일이 아니며, **환경 이름으로 묶이지 않고 값 하나하나가 독립적**이라 환경이 늘어도 조합 폭발이 없습니다.

## 2. 구조 — 우선순위 사다리

환경변수를 "설정 파일 대신 쓰는 것"으로 이해하면 반쪽입니다. 정확하게는 **여러 설정 소스가 쌓인 사다리에서 특정 층을 차지하는 것**입니다. 위층이 아래층을 덮어씁니다.

Spring Boot 4.1의 `PropertySource` 순서는 15단계인데, 실무에서 마주치는 층만 아래에서 위로 추리면 이렇습니다 ([Externalized Configuration](https://docs.spring.io/spring-boot/reference/features/external-config.html)).

| 층 | 소스 | 누가 정하나 |
|---:|---|---|
| 낮음 | `SpringApplication.setDefaultProperties` | 개발자 (코드) |
| ↓ | `@PropertySource` | 개발자 (코드) |
| ↓ | `application.yml` / `application-{profile}.yml` | 개발자 (저장소) |
| ↓ | **OS 환경변수** | **배포 시스템** |
| ↓ | Java 시스템 프로퍼티 (`-Dkey=value`) | 실행 스크립트 |
| ↓ | `SPRING_APPLICATION_JSON` | 배포 시스템 |
| 높음 | 커맨드라인 인자 (`--key=value`) | 실행 명령 |

이 표에서 읽어야 할 건 **환경변수가 `application.yml`보다 위에 있다**는 사실입니다. 여기서 실무 전략이 나옵니다.

```
application.yml  →  "합리적인 기본값" + "환경마다 달라지는 값의 자리(placeholder)"
환경변수         →  배포할 때 실제로 꽂히는 값
```

저장소에는 **구조**만 두고, **값**은 배포 시점에 주입합니다. 파일을 지우고 환경변수만 쓰는 게 아닙니다. 파일은 "이 애플리케이션이 어떤 설정을 필요로 하는가"를 문서처럼 남기는 역할을 계속합니다.

## 3. 흐름

### 3-1. 코드로 보는 구성

```yaml
# src/main/resources/application.yml
spring:
  datasource:
    url: ${DB_URL}                    # 기본값 없음 — 안 주면 기동 실패
    username: ${DB_USERNAME}
    password: ${DB_PASSWORD}
  jpa:
    hibernate:
      ddl-auto: validate              # 환경 무관 — 환경변수로 뺄 이유 없음

payment:
  base-url: ${PAYMENT_BASE_URL}
  timeout-ms: ${PAYMENT_TIMEOUT_MS:3000}   # 콜론 뒤가 기본값
```

`${DB_URL}`처럼 기본값을 두지 않으면, 환경변수가 없을 때 플레이스홀더를 해석하지 못해 **기동 중에 예외로 죽습니다.** 이게 의도한 동작입니다. 없는 채로 뜨는 것보다 못 뜨는 게 낫습니다 (5절).

값을 받는 쪽은 타입 안전하게 묶습니다.

```java
@ConfigurationProperties(prefix = "payment")
public record PaymentProperties(String baseUrl, int timeoutMs) {
}
```

```java
@Configuration
@EnableConfigurationProperties(PaymentProperties.class)
class PaymentConfig {

    @Bean
    RestClient paymentRestClient(PaymentProperties properties) {
        return RestClient.builder()
                .baseUrl(properties.baseUrl())
                .build();
    }
}
```

`@Value("${payment.base-url}")`를 여기저기 뿌리는 것보다 이쪽이 낫습니다. **어떤 설정이 필요한지가 클래스 하나에 모여서, 새 환경을 만들 때 무엇을 채워야 하는지 코드가 알려줍니다.**

### 3-2. 이름 변환 규칙

환경변수 이름에는 점(`.`)이나 하이픈(`-`)을 쓸 수 없는 OS가 대부분입니다. Spring Boot는 **완화된 바인딩(relaxed binding)** 으로 이 간극을 메웁니다. 규칙은 세 줄입니다.

```
1. 점(.)을 언더스코어(_)로 바꾼다
2. 하이픈(-)은 제거한다        ← 언더스코어로 바꾸는 게 아니라 지웁니다
3. 대문자로 바꾼다
```

| 프로퍼티 | 환경변수 |
|---|---|
| `spring.datasource.url` | `SPRING_DATASOURCE_URL` |
| `payment.base-url` | `PAYMENT_BASEURL` |
| `spring.main.log-startup-info` | `SPRING_MAIN_LOGSTARTUPINFO` |
| `my.service[0].other` | `MY_SERVICE_0_OTHER` |

2번이 가장 많이 틀리는 지점입니다. `payment.base-url`을 `PAYMENT_BASE_URL`로 쓰면 `payment.base.url`로 해석됩니다. 리스트 바인딩은 **인덱스를 언더스코어로 감싸는** 형태라는 것도 기억할 만합니다 ([Binding From Environment Variables](https://docs.spring.io/spring-boot/reference/features/external-config.html)).

### 3-3. 주입 지점 — 값은 어디서 오나

애플리케이션 입장에서는 다 같은 환경변수지만, 채워 넣는 주체는 계층마다 다릅니다.

```
로컬       .env 파일 / IDE 실행 구성
컨테이너   docker run -e  /  compose의 environment·env_file
오케스트라 Kubernetes ConfigMap(일반 설정) · Secret(민감값)
CI/CD      파이프라인 시크릿 → 배포 매니페스트로 전달
```

```yaml
# compose.yaml
services:
  order-api:
    image: order-api:1.4.0
    environment:
      DB_URL: jdbc:mysql://mysql:3306/orders
      DB_USERNAME: ${DB_USERNAME}       # 셸이나 .env에서 보간
      DB_PASSWORD: ${DB_PASSWORD}
    env_file:
      - ./config/common.env
```

Docker Compose에도 우선순위가 있습니다. 높은 쪽부터 `docker compose run -e` → 셸/`.env`로 보간된 값 → `environment` 속성 → `env_file` 속성 → Dockerfile의 `ENV`입니다 ([Environment variables precedence](https://docs.docker.com/compose/how-tos/environment-variables/envvars-precedence/)). Dockerfile `ENV`가 가장 낮다는 게 중요합니다. **이미지에 박아둔 값은 언제든 덮이므로 "이미지에 넣어놨으니 안전"하지 않고, 동시에 `docker history`로 그대로 노출됩니다.**

Kubernetes에서는 이렇게 갈립니다.

```yaml
env:
  - name: DB_PASSWORD
    valueFrom:
      secretKeyRef:
        name: order-api-secret
        key: db-password
envFrom:
  - configMapRef:
      name: order-api-config       # ConfigMap의 모든 키를 한 번에
```

## 4. 특징

### 4-1. 환경변수가 잘 맞는 값

- 배포마다 **반드시** 달라지는 값 (DB 호스트, 외부 API 엔드포인트)
- 개수가 적고, 한 줄짜리 문자열이며, 구조가 없는 값
- 기동 시점에 정해지면 되고, 도중에 바뀔 일이 없는 값

### 4-2. 환경변수가 잘 안 맞는 값

- **구조가 깊은 설정.** 중첩 3단계짜리 라우팅 규칙을 `A_B_C_D_0_E`로 표현하는 순간 아무도 못 읽습니다. 이건 파일로 마운트합니다.
- **개행이 들어간 값.** 인증서, PEM 키, 긴 JSON. 셸 이스케이프에서 반드시 사고가 납니다.
- **런타임에 바뀌어야 하는 값.** 환경변수는 프로세스 시작 시점에 복사됩니다. 뒤에서 바꿔도 안 바뀝니다 (7절 함정 3).
- **환경마다 달라지지 않는 값.** `ddl-auto: validate`를 환경변수로 빼면 설정 목록만 길어지고 얻는 게 없습니다.

### 4-3. 트레이드오프 — 공짜가 아닌 지점

**타입이 없습니다.** 전부 문자열입니다. `RETRY_COUNT=three`를 넣으면 컴파일도 통과하고 배포도 성공하고 기동할 때 터집니다. `@ConfigurationProperties` + Bean Validation으로 기동 시점에 잡는 게 그나마 최선입니다.

**추적이 어렵습니다.** 설정 파일은 Git에 diff가 남지만 환경변수는 안 남습니다. "어제까지 되던 게 왜 안 되지"를 추적할 히스토리가 없습니다. 그래서 값 자체는 저장소 밖에 두더라도, **어떤 키가 필요한지는 반드시 저장소에 문서로 남깁니다** (`.env.example` 같은 형태).

**노출 경로가 많습니다.** 6절에서 따로 다룹니다.

## 5. 예제 — 조용히 잘못된 값으로 뜨는 애플리케이션

### 5-1. 클린하지 않은 코드 ❌

```yaml
spring:
  datasource:
    url: ${DB_URL:jdbc:mysql://localhost:3306/orders}
    username: ${DB_USERNAME:root}
    password: ${DB_PASSWORD:}          # 기본값이 빈 문자열
```

```java
@Value("${payment.api-key:test-key}")   // 없으면 테스트 키로 동작
private String apiKey;
```

로컬에서 편하게 돌리려고 기본값을 넣었습니다. 문제는 **운영 배포에서 환경변수 이름을 하나 오타 냈을 때** 드러납니다. 애플리케이션은 정상 기동하고, 헬스체크도 통과하고, 로컬 DB에 붙으려다 실패하거나 — 더 나쁘게는 결제 요청이 테스트 키로 나갑니다. **에러가 아니라 잘못된 성공이라 아무도 모릅니다.**

`${DB_PASSWORD:}`는 특히 위험합니다. 콜론 뒤가 비어 있으면 "기본값 없음"이 아니라 "기본값이 빈 문자열"입니다.

### 5-2. 개선한 코드 ✔️

```yaml
spring:
  datasource:
    url: ${DB_URL}                     # 기본값 없음 = 없으면 기동 실패
    username: ${DB_USERNAME}
    password: ${DB_PASSWORD}

payment:
  api-key: ${PAYMENT_API_KEY}
  timeout-ms: ${PAYMENT_TIMEOUT_MS:3000}   # 안전한 기본값은 남겨도 됨
```

```java
@Validated
@ConfigurationProperties(prefix = "payment")
public record PaymentProperties(
        @NotBlank String apiKey,
        @Positive @Max(10_000) int timeoutMs) {
}
```

로컬 편의는 저장소에 커밋하지 않는 `.env`나 IDE 실행 구성으로 해결합니다. 기준은 이렇습니다.

**"이 값이 틀리면 조용히 잘못 동작하는가?" → 기본값을 주지 않습니다. "틀려도 티가 나거나 영향이 작은가?" → 기본값을 줍니다.** 타임아웃 3초는 후자, API 키는 전자입니다.

## 6. 시크릿은 환경변수의 한계 지점

여기가 12-Factor를 그대로 따르면 안 되는 부분입니다. 환경변수는 하드코딩보다 낫지만, **프로세스 전체에 평문으로 공유되는 전역 블록**이라는 성질이 남습니다.

OWASP는 이렇게 정리합니다. "환경변수는 일반적으로 모든 프로세스에서 접근 가능하며 로그나 시스템 덤프에 포함될 수 있다." 그리고 **"다른 방법이 불가능한 경우가 아니라면 환경변수 사용은 권장하지 않는다"** 고 명시합니다 ([OWASP Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)).

실제로 새는 경로는 이렇습니다.

1. **`docker inspect`** — 컨테이너의 `Config.Env`가 그대로 찍힙니다.
2. **자식 프로세스 상속** — 애플리케이션이 띄운 셸, 사이드카, 서드파티 에이전트가 전부 물려받습니다.
3. **`/proc/<pid>/environ`** — 같은 UID로 실행되는 프로세스나 root면 읽습니다.
4. **크래시 덤프·에러 리포팅** — 프로세스 상태를 통째로 수집하는 도구가 환경변수까지 실어 보냅니다.
5. **Actuator `/env`** — 값이 API로 나갑니다.

5번은 Spring Boot가 방어해둔 편입니다. `management.endpoint.env.show-values`와 `management.endpoint.configprops.show-values`의 기본값이 `never`라 값이 마스킹되고, `management.endpoints.web.exposure.include`의 기본값은 `health` 하나뿐입니다 ([Application Properties](https://docs.spring.io/spring-boot/appendix/application-properties/index.html)). **문제는 "편하니까" `include: "*"` 로 열어두는 순간 마스킹만 남고 노출 범위는 활짝 열린다는 겁니다.**

그래서 실무 기준은 이렇게 나눕니다.

| 값의 종류 | 전달 방식 |
|---|---|
| 일반 설정 (호스트, 타임아웃, 기능 플래그) | 환경변수 |
| 시크릿 (DB 비밀번호, API 키) | 파일 마운트 (Secret 볼륨) 또는 시크릿 매니저 |
| 인증서·긴 구조체 | 파일 마운트 |

파일 마운트가 나은 이유는 세 가지입니다. 자식 프로세스에 자동으로 상속되지 않고, 읽는 시점을 코드가 제어할 수 있으며, **값이 갱신될 때 반영됩니다.**

## 7. 함정

**함정 1 — 하이픈을 언더스코어로 바꿔서 값이 안 들어간다**

- **증상**: `PAYMENT_BASE_URL`을 분명히 설정했는데 `payment.base-url`이 비어 있거나 기본값으로 뜹니다. 에러 로그도 없습니다.
- **원인**: 변환 규칙은 "하이픈을 언더스코어로"가 아니라 **"하이픈 제거"** 입니다. `PAYMENT_BASE_URL`은 `payment.base.url`로 해석되어, 아무도 안 읽는 새 프로퍼티가 하나 생긴 겁니다.
- **해법**: `payment.base-url` → `PAYMENT_BASEURL`. 헷갈릴 소지를 없애려면 **프로퍼티 이름 자체에 하이픈을 쓰지 않는 것**도 방법입니다. 확인은 `@ConfigurationProperties`에 `@NotBlank`를 붙여 기동 시점에 터뜨리는 게 가장 빠릅니다.

**함정 2 — 오타 난 환경변수가 에러 없이 무시된다**

- **증상**: 배포 후 외부 연동이 개발 서버로 나갑니다. 로그에는 아무 이상이 없습니다.
- **원인**: 환경변수는 스키마가 없습니다. `PAYMEMT_BASEURL`처럼 오타를 내면 그 변수는 그냥 아무도 안 쓰는 값으로 남고, 애플리케이션은 `application.yml`의 기본값으로 조용히 뜹니다.
- **해법**: 필수 설정에 기본값을 주지 않아 **기동 실패로 만듭니다**(5-2절). 추가로 `.env.example`에 필요한 키 목록을 유지하고, 배포 파이프라인에서 매니페스트의 키 목록과 대조하는 검사를 넣습니다.

**함정 3 — ConfigMap을 고쳤는데 반영이 안 된다**

- **증상**: Kubernetes에서 ConfigMap 값을 수정하고 `kubectl apply`까지 했는데 애플리케이션 동작이 그대로입니다. Secret을 회전시켰는데 옛날 비밀번호로 계속 붙습니다.
- **원인**: 공식 문서가 못을 박고 있습니다. **"환경변수로 소비되는 ConfigMap은 자동으로 갱신되지 않으며 파드 재시작이 필요하다"** ([ConfigMap](https://kubernetes.io/docs/concepts/configuration/configmap/)). Secret도 같습니다. "컨테이너가 이미 Secret을 환경변수로 소비 중이라면, 재시작하지 않는 한 Secret 갱신을 인식하지 못한다" ([Distribute Credentials Securely](https://kubernetes.io/docs/tasks/inject-data-application/distribute-credentials-secure/)). 프로세스 환경 블록은 `exec` 시점에 복사되는 스냅샷이기 때문입니다.
- **해법**: 갱신이 필요한 값은 **볼륨으로 마운트**합니다. 볼륨은 자동 갱신되지만 즉시는 아닙니다. kubelet 동기화 주기 + 캐시 전파 지연만큼 늦습니다. 재시작 방식을 유지한다면, ConfigMap 내용의 해시를 파드 템플릿 애노테이션에 넣어 **내용이 바뀌면 롤링 재시작이 자동으로 걸리게** 만듭니다.

**함정 4 — 시크릿이 로그와 이미지에 남는다**

- **증상**: 보안 점검에서 로그 수집기나 이미지 레이어에 DB 비밀번호가 발견됩니다. 코드에는 하드코딩이 없습니다.
- **원인**: 세 가지가 흔합니다. (1) Dockerfile `ENV`로 넣은 값이 `docker history`에 남습니다. (2) 디버깅용으로 넣은 `printenv`·기동 스크립트의 `set -x`가 전체 환경을 찍습니다. (3) 예외 리포팅 도구가 프로세스 환경을 수집합니다.
- **해법**: 이미지에는 시크릿을 넣지 않습니다(어차피 Compose에서 가장 낮은 우선순위라 값으로서의 가치도 없습니다). 기동 스크립트에서 `set -x`를 쓰지 않거나 시크릿 주입 구간만 끕니다. Actuator는 필요한 엔드포인트만 노출하고 `show-values` 기본값을 건드리지 않습니다.

**함정 5 — 로컬에서만 쓰는 `.env`가 커밋된다**

- **증상**: 저장소에 `.env`가 올라가 있고 안에 실제 키가 들어 있습니다.
- **원인**: `.gitignore`에 `.env`를 넣어두고 `.env.local`, `.env.prod` 같은 변형 파일을 만들면 패턴에 안 걸립니다.
- **해법**: `.env*`를 무시하고 `!.env.example`만 예외로 둡니다. 그리고 사람이 지키는 규칙 대신 **커밋 전 시크릿 스캐너**를 CI에 넣습니다. 이미 커밋됐다면 파일을 지우는 걸로 끝나지 않습니다. 히스토리에 남아 있으므로 **해당 키를 폐기하고 재발급하는 게 유일한 해결**입니다.

## 8. 정리

- 배포마다 달라지는 값만 밖으로 뺍니다. 안 달라지는 값까지 빼면 목록만 길어집니다.
- 저장소에는 구조와 안전한 기본값을, 배포 시스템에는 실제 값을 둡니다.
- **필수 설정에 기본값을 주지 않는 것이 가장 값싼 방어입니다.** 못 뜨는 게 잘못 뜨는 것보다 낫습니다.
- 시크릿은 환경변수의 경계 밖입니다. 파일 마운트나 시크릿 매니저로 넘깁니다.
- 환경변수는 기동 시점의 스냅샷입니다. 바뀌어야 하는 값이면 애초에 다른 방법을 씁니다.

## 9. 참고자료

- [The Twelve-Factor App — Config](https://12factor.net/config)
- [Spring Boot — Externalized Configuration](https://docs.spring.io/spring-boot/reference/features/external-config.html)
- [Spring Boot — Common Application Properties](https://docs.spring.io/spring-boot/appendix/application-properties/index.html)
- [Kubernetes — ConfigMaps](https://kubernetes.io/docs/concepts/configuration/configmap/)
- [Kubernetes — Distribute Credentials Securely Using Secrets](https://kubernetes.io/docs/tasks/inject-data-application/distribute-credentials-secure/)
- [Docker Compose — Environment variables precedence](https://docs.docker.com/compose/how-tos/environment-variables/envvars-precedence/)
- [OWASP — Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
- 설정을 읽어 빈을 만드는 과정의 앞단(클래스 로딩·시스템 프로퍼티)은 `daily/day01-jvm-why.md`에서 다룹니다.

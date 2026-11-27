# 내가 넣은 값이 왜 안 먹는가 — 설정 우선순위는 무엇이 결정하는가

> 이 문서가 답할 질문: **같은 키를 여러 곳에 적었을 때 어느 값이 이기는가 — 그리고 "분명히 고쳤는데 안 바뀌는" 설정은 어디서 덮이고 있는가?**

기준 버전: **Spring Boot 4.2.0** (2026년 11월 19일 Maven Central 배포). 본문의 규칙은 설정 로딩이 `ConfigData` 모델로 재작성된 **2.4**부터 동일하게 적용되므로 3.x에서도 그대로 읽을 수 있습니다. 유형은 문제해결형입니다 — "값이 안 먹는다"는 증상에서 출발해 어디서 덮였는지 특정하는 순서로 내려갑니다.

## 1. 핵심 개념 — 설정은 파일이 아니라 쌓인 레이어입니다

`application.yml`은 설정이 아닙니다. **설정 레이어 중 하나**입니다. 애플리케이션이 뜰 때 Spring은 15종류의 소스를 정해진 순서로 쌓고, 조회는 가장 위에서 아래로 내려가다 처음 만난 값에서 멈춥니다.

> 운영 DB 커넥션 풀을 20으로 늘려야 합니다. `application-prod.yml`에서 `spring.datasource.hikari.maximum-pool-size: 20`으로 고치고 배포합니다. 재배포 후에도 풀은 10입니다. 설정이 안 읽혔다고 생각해 프로필을 확인하는데 시작 로그에는 `The following 1 profile is active: "prod"`가 멀쩡히 찍혀 있습니다. 파일도 맞고 프로필도 맞습니다.
>
> 원인은 반년 전 누군가 Deployment에 넣어둔 `SPRING_DATASOURCE_HIKARI_MAXIMUMPOOLSIZE=10` 환경변수였습니다. **환경변수는 설정 파일보다 위 레이어입니다.** 파일을 어떻게 고쳐도 조회가 거기까지 내려가지 않습니다. 에러도 경고도 없습니다. 이 구조를 모르면 디버깅은 파일을 고치고 재배포하는 루프를 무한히 돕니다.

그래서 이 주제의 실무 질문은 "어디에 적어야 하는가"가 아닙니다. **"지금 그 값은 어디서 오고 있는가"** 입니다.

---

## 2. 헷갈림의 정체 — 축이 두 개입니다

설정 우선순위가 어려운 이유는 규칙이 복잡해서가 아니고, **독립된 두 질문을 하나로 보기 때문**입니다.

| 축 | 질문 | 결정하는 것 |
|---|---|---|
| **A. 소스 우선순위** | 같은 키가 여러 소스에 있을 때 누가 이기는가 | `PropertySource` 순서 |
| **B. 프로필 활성화** | `application-prod.yml`이 아예 로딩되는가 | `spring.profiles.*` |

"prod 프로필이니까 `application-prod.yml`이 이긴다"는 문장은 축 B를 축 A로 착각한 것입니다. 프로필은 **어떤 문서를 쌓을지** 고르고, 쌓인 뒤의 승부는 축 A가 정합니다. 프로필 전용 파일은 설정 파일 레이어 **안에서만** 우대받습니다. 그 레이어 바깥(환경변수, 커맨드라인)에는 아무 영향이 없습니다.

---

## 3. 축 A — 15단 사다리

공식 문서는 소스를 오름차순(나중이 이김)으로 나열합니다. 아래 표는 **높은 쪽부터** 뒤집은 것입니다([Externalized Configuration](https://docs.spring.io/spring-boot/reference/features/external-config.html)).

| 순위 | 소스 | 실무에서 |
|---:|---|---|
| 1 | Devtools 전역 설정 (`$HOME/.config/spring-boot`) | 로컬 한정 |
| 2 | `@TestPropertySource` | 테스트 |
| 3 | `@DynamicPropertySource` | 테스트 |
| 4 | `@SpringBootTest(properties = ...)` | 테스트 |
| 5 | **커맨드라인 인자** (`--key=value`) | 가장 센 운영 수단 |
| 6 | `SPRING_APPLICATION_JSON` | 이름 제약 우회용 |
| 7~9 | `ServletConfig` / `ServletContext` / JNDI | WAS 배포 |
| 10 | **Java 시스템 프로퍼티** (`-Dkey=value`) | JVM 옵션 |
| 11 | **OS 환경변수** | 컨테이너의 기본 수단 |
| 12 | `random.*` | |
| 13 | **Config data** (`application.*` 파일 전부) | 저장소에 커밋되는 것 |
| 14 | `@PropertySource` | 레거시 |
| 15 | `SpringApplication.setDefaultProperties` | 라이브러리 기본값 |

실무에서 외워야 할 건 세 칸입니다.

```text
커맨드라인  >  시스템 프로퍼티  >  환경변수  >  application.* 파일 전부
```

여기서 두 가지가 바로 따라옵니다.

- **환경변수 하나가 모든 yml을 무력화합니다.** 컨테이너 환경에서 "파일을 고쳤는데 안 바뀐다"의 1순위 원인입니다.
- **테스트는 최상위입니다** (2~4위). `@SpringBootTest(properties = "spring.jpa.hibernate.ddl-auto=create")`로 초록불을 만들어도 운영 동작은 아무것도 검증되지 않았습니다.

그리고 13위에 달린 주석이 중요합니다. `@PropertySource`는 **애플리케이션 컨텍스트 refresh 시점에야** `Environment`에 들어갑니다. `logging.*`과 `spring.main.*`은 그보다 먼저 읽히므로, `@PropertySource`로 로그 레벨을 바꾸려는 시도는 조용히 무시됩니다.

### 3-1. Config data 내부의 4단 — 직관이 깨지는 지점

13위 "Config data" 한 칸은 다시 네 단으로 쪼개집니다. 역시 나중이 이깁니다.

1. jar **내부**의 `application.*`
2. jar **내부**의 `application-{profile}.*`
3. jar **외부**의 `application.*`
4. jar **외부**의 `application-{profile}.*`

순서를 그대로 읽으면 이런 결론이 나옵니다 — **jar 옆 `./config/application.properties`(3번)가 jar 안의 `application-prod.yml`(2번)을 이깁니다.** 프로필 전용 파일인데 프로필 없는 파일에 집니다. "프로필 전용이 항상 우대된다"는 기대와 정반대입니다.

모순은 아닙니다. 기본 탐색 위치가 두 개의 **위치 그룹**으로 묶여 있기 때문입니다.

<!-- TODO: 확인 필요 — "외부 기본 파일이 jar 내부 프로필 파일을 이긴다"는 결론은 공식 문서의 Config data 4단 순서와 기본 탐색 위치의 그룹 구조에서 추론한 것입니다. 문서에 그 문장이 직접 적혀 있지는 않고, "프로필 전용이 기본 파일을 항상 덮는다"는 다른 문장과 겹쳐 읽으면 반대로 보입니다. 실제 애플리케이션으로 재현 검증하지 않았습니다. -->

```text
그룹 1 (classpath)  classpath:/  ;  classpath:/config/
그룹 2 (file)       file:./  ;  file:./config/  ;  file:./config/*/
```

"프로필 전용이 기본 파일을 덮는다"는 규칙은 **같은 그룹 안에서만** 성립합니다. 그룹끼리는 file 그룹이 classpath 그룹을 통째로 덮습니다. 쿠버네티스에서 ConfigMap을 `/config`에 마운트하는 구성이 바로 이 경로입니다.

### 3-2. `.properties`가 YAML을 이깁니다

같은 위치에 `application.properties`와 `application.yaml`이 둘 다 있으면 **`.properties`가 이깁니다.** 문서는 "애플리케이션 전체에서 한 가지 형식만 쓰라"고 권고합니다. 프로젝트 생성 시 만들어진 빈 `application.properties`를 지우지 않고 yml로 옮겨 쓰기 시작하면, 겹치는 키만 조용히 옛 값으로 돌아갑니다.

### 3-3. 위치를 직접 지정할 때

| 속성 | 동작 |
|---|---|
| `spring.config.location` | 기본 위치를 **대체**합니다 (classpath:/ 포함 전부 사라짐) |
| `spring.config.additional-location` | 기본 위치에 **추가**하고, 추가분이 기본을 덮습니다 |
| `spring.config.import` | 선언한 문서 **바로 아래**에 끼워넣고, 가져온 쪽이 이깁니다 |

`spring.config.name`·`location`·`additional-location` 세 개는 "어떤 파일을 읽을지" 결정하는 데 쓰이므로 **파일 안에 적을 수 없습니다.** 환경변수·시스템 프로퍼티·커맨드라인으로만 줍니다.

구분자도 의미가 있습니다. `,`는 위치 그룹을 나누고 `;`는 같은 그룹으로 묶습니다. 공식 문서의 예시가 이걸 명확히 보여줍니다 — 활성 프로필이 `prod,live`일 때

```text
spring.config.location=classpath:/cfg/,classpath:/ext/   → /cfg 전부 먼저, 그 다음 /ext 전부
spring.config.location=classpath:/cfg/;classpath:/ext/   → 두 위치를 같은 레벨로 보고 프로필 순서대로
```

---

## 4. 축 B — 프로필은 값이 아니라 스위치입니다

### 4-1. 켜는 방법이 네 가지입니다

| 속성 | 의미 |
|---|---|
| `spring.profiles.active` | 활성 프로필 목록. **덮어쓰기**입니다 |
| `spring.profiles.include` | active에 **더합니다**. 빼지는 못합니다 |
| `spring.profiles.group.<name>` | 이름 하나로 여러 개를 함께 켭니다 |
| `spring.profiles.default` | 활성 프로필이 없을 때 쓸 이름 (기본 `default`) |

`active`는 축 A를 그대로 따릅니다. `application.yml`에 `dev`를 적어두고 `--spring.profiles.active=prod`를 주면 **병합이 아니라 교체**입니다. `dev`는 사라집니다.

`include`는 다릅니다. 문서는 "`spring.profiles.include`는 각 property source마다 처리되므로 리스트의 일반적인 병합 규칙이 적용되지 않는다"고 못을 박습니다. 즉 **모든 소스의 include가 누적**됩니다. 커맨드라인에서 include를 다시 선언해도 yml에 적힌 include는 꺼지지 않습니다. 끄는 수단이 없습니다.

활성 프로필이 여러 개면 **마지막이 이깁니다.** `prod,live`라면 `application-live.properties`가 `application-prod.properties`를 덮습니다. 쓰는 순서가 설정값을 바꿉니다.

활성 프로필이 하나도 없으면 `default` 프로필이 켜지고 **`application-default.*`가 로딩됩니다.** 로컬에서만 쓸 설정을 여기 넣어두면 프로필 지정 없이 뜰 때만 적용됩니다.

### 4-2. 프로필 전용 문서에서는 프로필을 켤 수 없습니다

이게 2.4 이후 가장 자주 밟는 실패입니다. 원인은 로딩이 **2단계**로 돌기 때문입니다. `ConfigDataEnvironment.processAndApply()`의 호출 순서가 그대로 설명해 줍니다 ([4.2.0 소스](https://github.com/spring-projects/spring-boot/blob/v4.2.0/core/spring-boot/src/main/java/org/springframework/boot/context/config/ConfigDataEnvironment.java)).

```text
processInitial            ← 프로필을 모르는 상태로 기본 파일만 읽음
  → withProfiles          ← 여기서 활성 프로필을 확정
    → processWithProfiles ← 확정된 프로필로 전용 문서를 읽음
```

프로필은 1단계가 끝난 시점에 **이미 확정**됩니다. 그러니 3단계에 들어오는 문서가 프로필을 바꾸겠다고 하면 모순입니다. Spring Boot는 이를 추측하지 않고 기동을 실패시킵니다.

```text
Property 'spring.profiles.active' imported from location
  'class path resource [application-prod.yml]' is invalid in a profile specific resource
```

예외 클래스가 검사하는 금지 키는 `active`, `include`, `default`(및 `[0]` 인덱스 형태)이고, 문서는 `spring.profiles.group`에도 같은 제약이 적용된다고 명시합니다. 2.3까지 쓰던 `spring.profiles` 키도 이제 에러이고, 메시지가 `spring.config.activate.on-profile`로 바꾸라고 알려줍니다.

같은 2단계 구조에서 나오는 덜 알려진 실패가 하나 더 있습니다. 1단계에서 이미 읽혀야 하는 값을 프로필 전용 문서에만 정의하면 이렇게 떨어집니다.

<!-- TODO: 확인 필요 — `InactiveConfigDataAccessException`의 존재와 메시지 형식은 4.2.0 소스에서 확인했지만, 어떤 키 조합에서 실제로 터지는지는 소스의 `DENY_INACTIVE_BINDING` 사용 지점을 보고 추론했습니다. 대표적인 재현 케이스를 공식 문서에서 찾지 못했습니다. -->

```text
Inactive property source '...' cannot contain property '...'
```

### 4-3. 파일을 나누지 않고 한 파일 안에서 분기하기

`---`(YAML) 또는 `#---`(properties)로 문서를 쪼개고 활성 조건을 붙입니다. 구분자는 **앞에 공백이 없어야 하고 하이픈이 정확히 세 개**여야 합니다.

```yaml
spring:
  application:
    name: "order-api"
  datasource:
    hikari:
      maximum-pool-size: 5
---
spring:
  config:
    activate:
      on-profile: "prod | staging"
  datasource:
    hikari:
      maximum-pool-size: 20
```

문서는 위에서 아래로 처리되고 나중 문서가 앞 문서를 덮습니다.

`on-profile`은 단순 이름 대신 프로필 표현식을 받습니다. `Profiles.of(...)` javadoc이 연산자를 `!`(NOT), `&`(AND), `|`(OR) 셋으로 정의하고, **`&`와 `|`는 괄호 없이 섞을 수 없다**고 명시합니다 — `"a & b | c"`는 유효하지 않고 `"(a & b) | c"`로 써야 합니다. 쿠버네티스에서만 켜고 싶으면 `on-cloud-platform: "kubernetes"`를 씁니다.

---

## 5. 추측하지 않고 확인하는 두 가지

### 5-1. 시작 로그 — 프로필은 로그에 찍힙니다

`SpringApplication.logStartupProfileInfo()`가 내는 문구는 둘 중 하나입니다 ([4.2.0 소스](https://github.com/spring-projects/spring-boot/blob/v4.2.0/core/spring-boot/src/main/java/org/springframework/boot/SpringApplication.java)).

```text
The following 2 profiles are active: "prod", "metrics"
No active profile set, falling back to 1 default profile: "default"
```

두 번째 줄이 보이면 프로필 주입이 안 된 것입니다. 파일을 더 보지 말고 주입 경로부터 봅니다.

### 5-2. `/actuator/env/{키}` — 값의 출처를 직접 묻습니다

축 A를 추측 없이 확인하는 가장 빠른 수단입니다. 응답의 `property`가 **실제로 이긴 값**이고, `propertySources` 배열은 우선순위 순서로 나오며 그 키를 가진 소스마다 값과 `origin`(파일명·줄 번호)이 붙습니다.

```bash
curl -s localhost:8080/actuator/env/spring.datasource.hikari.maximum-pool-size
```

단, 민감값 보호 때문에 **기본적으로 값이 `******`로 가려집니다.** `show-values` 기본값이 `never`입니다. 운영에서 열 거라면 `always`가 아니라 인증 기반으로 엽니다.

```yaml
management:
  endpoint:
    env:
      show-values: when-authorized
      roles: "ops"
```

---

## 6. 예제 — 안 먹는 설정과 고친 설정

### 6-1. 안 먹는 설정 ❌

```yaml
# application-prod.yml  — 세 군데가 동시에 잘못됐습니다
spring:
  profiles:
    active: "prod"        # ❌ 프로필 전용 파일에서 프로필 활성화 → 기동 실패
  datasource:
    url: ${DB_URL}        # ❌ 환경변수가 이미 SPRING_DATASOURCE_URL을 쥐고 있으면 무의미
  jpa:
    hibernate:
      ddl-auto: "validate"
logging:
  level:
    root: "WARN"
```

```yaml
# k8s Deployment — 반년 전 누가 넣고 잊은 줄
env:
  - name: SPRING_DATASOURCE_URL
    value: "jdbc:mysql://10.0.3.14:3306/orders"   # 파일을 이깁니다
```

### 6-2. 고친 설정 ✔️

```yaml
# application.yml — 프로필 활성화는 프로필 없는 문서에서만
spring:
  application:
    name: "order-api"
  profiles:
    group:
      prod: ["metrics"]    # prod를 켜면 metrics도 함께 켜집니다
  datasource:
    hikari:
      maximum-pool-size: 5
---
spring:
  config:
    activate:
      on-profile: "prod"
  datasource:
    hikari:
      maximum-pool-size: 20
```

```yaml
# k8s Deployment — 환경변수는 "환경마다 다른 값"만 담습니다
env:
  - name: SPRING_PROFILES_ACTIVE
    value: "prod"
  - name: SPRING_DATASOURCE_PASSWORD
    valueFrom:
      secretKeyRef: { name: order-api-db, key: password }
```

규칙은 한 줄입니다. **파일에는 환경마다 달라지는 구조를, 환경변수에는 환경마다 달라지는 값만.** 같은 키가 양쪽에 다 있으면 파일 쪽은 죽은 코드입니다. 값을 밖으로 빼는 기준은 `day06-env-variable.md`, 환경 경계를 어디에 그을지는 `day52-env-separation.md`에서 다룹니다.

---

## 7. 함정

**프로필 전용 파일에서 프로필을 켠다**
- **증상**: 기동 즉시 실패. `is invalid in a profile specific resource`
- **원인**: 프로필은 전용 문서를 읽기 전에 확정됩니다. 문서가 자기를 켤 수 없습니다
- **해법**: `active`·`include`·`default`는 프로필 없는 문서에만 둡니다. 조건부 적용은 `spring.config.activate.on-profile`로 표현합니다

**잊힌 환경변수가 파일을 덮는다**
- **증상**: yml을 고치고 재배포해도 값이 그대로. 로그에 프로필은 정상
- **원인**: 환경변수(11위)가 설정 파일(13위)보다 위
- **해법**: `/actuator/env/{키}`로 `property.source`를 확인합니다. 소스가 `systemEnvironment`면 파일이 아니라 배포 매니페스트를 고칩니다

**환경변수 이름을 유추해서 쓴다**
- **증상**: 환경변수를 넣었는데 적용되지 않음. 에러 없음
- **원인**: 변환 규칙은 "점을 `_`로, **하이픈은 제거**, 대문자화"입니다. `spring.main.log-startup-info`는 `SPRING_MAIN_LOGSTARTUPINFO`이지 `SPRING_MAIN_LOG_STARTUP_INFO`가 아닙니다
- **해법**: 규칙대로 변환하고 `/actuator/env`로 확인합니다. 이름 제약이 심하면 `SPRING_APPLICATION_JSON`으로 블록째 넘깁니다

**`@Value`에 camelCase를 쓴다**
- **증상**: `application.yml`의 값은 읽히는데 환경변수로 덮으면 안 먹음. 또는 그 반대
- **원인**: 완화 바인딩(relaxed binding)은 `@ConfigurationProperties`의 기능이고 `@Value`는 제한적입니다. `@Value("${order.itemPrice}")`는 `order.itemPrice`와 `ORDER_ITEMPRICE`를 보지만 `order.item-price`는 못 봅니다
- **해법**: `@Value`를 쓸 때도 키는 kebab-case 정규형으로 적습니다. 키가 여러 개면 `@ConfigurationProperties`로 묶습니다

**리스트가 병합될 거라 기대한다**
- **증상**: `application.yml`에 origin 3개, `application-prod.yml`에 1개를 적었는데 prod에서 1개만 보임
- **원인**: 리스트는 병합이 아니라 **교체**입니다. 여러 프로필에 정의되면 가장 높은 우선순위의 것 하나만 쓰입니다
- **해법**: 전체 목록을 한 곳에만 둡니다. 환경마다 더하려면 키를 나눕니다 (`cors.base-origins` + `cors.extra-origins`)

**`.properties`와 `.yml`을 같이 둔다**
- **증상**: yml에 적은 값이 겹치는 키에서만 옛 값으로 돌아감
- **원인**: 같은 위치에서는 `.properties`가 이깁니다
- **해법**: 한 형식만 남깁니다. 프로젝트 생성 시 만들어진 빈 `application.properties`를 지웁니다

**`spring.config.location`으로 기본 위치를 날린다**
- **증상**: 외부 설정 파일을 지정한 뒤 jar 안 `application.yml`의 값이 전부 사라짐
- **원인**: `location`은 추가가 아니라 **대체**입니다
- **해법**: 추가가 목적이면 `spring.config.additional-location`을 씁니다

**테스트에서만 통과한다**
- **증상**: CI 초록불, 운영 실패
- **원인**: `@TestPropertySource`·`@SpringBootTest(properties)`는 우선순위 2~4위로 운영 경로를 전부 가립니다
- **해법**: 운영과 같은 레이어를 검증해야 한다면 테스트 속성으로 덮지 않고 프로필 또는 외부 위치를 그대로 태웁니다

---

## 8. 정리

"설정이 안 먹는다"를 만났을 때 순서는 셋입니다.

1. **시작 로그에서 활성 프로필을 봅니다** — `No active profile set`이면 축 B 문제입니다
2. **`/actuator/env/{키}`로 이긴 소스를 봅니다** — `systemEnvironment`면 파일을 고치는 일을 멈춥니다
3. **고칠 레이어를 고릅니다** — 같은 키를 두 레이어에 두는 게 원인이면, 하나를 지우는 것이 값을 맞추는 것보다 낫습니다

우선순위 15단을 다 외울 필요는 없습니다. 기억할 건 하나입니다. **같은 키가 두 곳에 있으면 아래쪽은 읽히지 않는 코드이고, 읽히지 않는 설정은 다음 사람을 반드시 한 번 속입니다.** 중복을 없애는 것이 순서를 외우는 것보다 값싸게 끝납니다.

## 9. 참고자료

- [Spring Boot — Externalized Configuration](https://docs.spring.io/spring-boot/reference/features/external-config.html) — 15단 우선순위, Config data 4단, 위치 그룹, `spring.config.import`, 완화 바인딩
- [Spring Boot — Profiles](https://docs.spring.io/spring-boot/reference/features/profiles.html) — `active`·`include`·`group`·`default`, 프로필 전용 문서 제약
- [Spring Boot — Actuator Endpoints: Sanitize Sensitive Values](https://docs.spring.io/spring-boot/reference/actuator/endpoints.html) — `show-values` 세 가지 값
- [Actuator `/env` 엔드포인트 응답 구조](https://docs.spring.io/spring-boot/api/rest/actuator/env.html)
- [`ConfigDataEnvironment` 소스 (v4.2.0)](https://github.com/spring-projects/spring-boot/blob/v4.2.0/core/spring-boot/src/main/java/org/springframework/boot/context/config/ConfigDataEnvironment.java) — 2단계 처리
- [`Profiles.of(...)` 소스 — 프로필 표현식 연산자](https://github.com/spring-projects/spring-framework/blob/main/spring-core/src/main/java/org/springframework/core/env/Profiles.java)
- [`InvalidConfigDataPropertyException` 소스 (v4.2.0)](https://github.com/spring-projects/spring-boot/blob/v4.2.0/core/spring-boot/src/main/java/org/springframework/boot/context/config/InvalidConfigDataPropertyException.java) — 금지 키 목록과 에러 메시지
- 관련 챕터: day06-env-variable.md, day52-env-separation.md, day24-local-dev-env.md

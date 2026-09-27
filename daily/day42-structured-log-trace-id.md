# 요청 하나를 끝까지 따라가기 — 트레이스 ID와 구조화 로그

> 이 문서가 답할 질문: **여러 서비스와 여러 스레드에 흩어진 로그에서, 특정 요청 하나만 골라 시작부터 끝까지 이어 붙이려면 무엇이 필요한가?**
>
> 분류: 문제해결형(증상 → 원인 → 해법). "로그는 다 남는데 이 요청이 어디서 어떻게 실패했는지 못 잇는다"는 증상에서 출발했습니다.
>
> 기준: Spring Boot 4.1 · W3C Trace Context Level 1 (2026년 9월 확인). **무엇을 남길지**는 `day36-log-design.md`에서, 로깅 프레임워크를 왜 쓰는지는 `day25-logging-basics.md`에서 다뤘습니다. 이 문서는 그 위에서 **어떻게 이어 붙이는가**만 다룹니다. 트레이스 수집 백엔드 운영과 스팬 기반 병목 분석은 범위 밖입니다.

## 1. 핵심 개념 — 시간으로 잇는 것과 ID로 잇는 것

요청 하나를 추적하는 방법은 두 가지뿐입니다. **시각으로 추측해서 잇거나, 식별자로 확정해서 잇거나.**

앞의 방법은 인스턴스가 한 대이고 초당 요청이 한 건일 때만 동작합니다. 두 대로 늘리고 초당 수십 건이 들어오는 순간, 같은 밀리초에 찍힌 로그가 스무 줄이 되고 그중 내 요청이 무엇인지 알 방법이 사라집니다.

> CS에서 "14시 3분경 결제가 안 됐다"는 문의가 옵니다. 주문번호는 있습니다. 로그를 엽니다. 주문번호로 검색하니 결제 서비스에서 `payment.gateway_error` 한 줄이 나옵니다. 그런데 **이 요청이 어디서 출발했는지**, 그 앞의 쿠폰 서비스가 뭐라고 답했는지, 재시도가 몇 번 있었는지는 안 나옵니다. 주문번호는 결제 서비스 로그에만 있고, 쿠폰 서비스는 쿠폰 ID로 로그를 남기기 때문입니다. 세 서비스 로그를 시각으로 맞춰보려 하지만 각자 다른 요청을 초당 수십 건씩 처리하고 있어서, **어느 줄이 짝인지 판정할 근거가 없습니다.**

**트레이스 ID**는 이 문제를 푸는 최소 장치입니다. 요청이 시스템에 들어온 지점에서 ID 하나를 만들고, 그 요청이 거치는 모든 서비스·스레드·로그 줄에 같은 ID를 붙입니다. 그러면 "이 요청"이라는 말이 검색 가능한 값이 됩니다.

여기서 두 층을 구분해야 합니다.

| 층 | 목적 | 없으면 |
|---|---|---|
| 로그 상관관계(correlation) | 흩어진 **로그 줄**을 한 요청으로 묶는다 | 요청 하나를 재생할 수 없다 |
| 분산 트레이싱(tracing) | 구간별 **소요시간과 부모-자식 관계**를 본다 | 어디가 느린지 모른다 |

둘은 같은 ID를 공유하지만 필요한 시점이 다릅니다. 장애 대응에서 먼저 필요한 건 대개 앞쪽입니다. 그리고 앞쪽은 트레이스 수집 백엔드를 붙이지 않아도 **로그만으로** 성립합니다.

## 2. 구조 — ID는 어떻게 경계를 넘는가

### 2-1. traceparent — 표준이 정한 55자

서비스 A가 만든 ID를 서비스 B가 알아야 합니다. 방법은 HTTP 헤더이고, W3C Trace Context가 그 포맷을 정해뒀습니다.

```text
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
             ^^ ^                              ^ ^              ^ ^^
             |  트레이스 ID(32 hex)              스팬 ID(16 hex)   플래그
             버전(2 hex)
```

네 필드를 하이픈으로 이은 **최소 55자**입니다. 버전은 현재 `00`이고 `ff`는 금지입니다. 트레이스 ID와 스팬 ID는 **전부 0이면 무효**이고, 헤더가 무효일 때 수신 측은 traceparent를 새로 만들고 함께 온 `tracestate`는 버려야 합니다([W3C Trace Context](https://www.w3.org/TR/trace-context/)).

플래그의 **최하위 비트가 sampled**입니다. `01`이면 호출자가 이 트레이스를 기록했을 수 있다는 뜻인데, 스펙 자체가 이것을 "엄격한 규칙이 아니라 호출자의 권고"라고 못박습니다. 이 한 줄이 §6-1 함정의 원인입니다.

`tracestate`는 벤더별 정보를 키-값으로 덧붙이는 동반 헤더입니다. 여러 추적 시스템이 한 트랜잭션을 나눠 처리할 때 씁니다.

### 2-2. 트레이스 ID와 스팬 ID의 역할이 다릅니다

- **트레이스 ID** — 요청 전체에 하나. 서비스를 넘어도 안 바뀝니다. **검색 키**입니다.
- **스팬 ID** — 작업 구간마다 하나. 서비스를 넘으면 새로 생깁니다. 부모 스팬 ID와 함께 **트리 구조**를 만듭니다.

로그 상관관계에 쓰는 건 트레이스 ID입니다. 스팬 ID는 "같은 요청 안에서 이 줄이 어느 구간인지"를 구분할 때 씁니다.

### 2-3. 로그에는 MDC를 거쳐서 들어갑니다

추적 라이브러리가 현재 트레이스 ID·스팬 ID를 MDC에 넣고, 로깅 프레임워크가 그걸 출력에 박습니다. Spring Boot는 Micrometer Tracing이 있으면 이 상관관계 ID를 **기본으로** 로그에 넣습니다. 기본 형태는 MDC의 `traceId`와 `spanId`를 묶은 `[traceId-spanId]`입니다.

```text
[803B448A0489F84084905D3093480352-3425F23BB2432450]
```

형태를 바꿀 때만 `logging.pattern.correlation`을 씁니다([Spring Boot — Tracing](https://docs.spring.io/spring-boot/reference/actuator/tracing.html)).

```yaml
logging:
  pattern:
    correlation: "[${spring.application.name:},%X{traceId:-},%X{spanId:-}] "
```

여기서 중요한 건 이게 **텍스트 패턴**이라는 점입니다. 텍스트 로그에서 트레이스 ID는 문자열의 일부일 뿐이라 정규식 없이는 질의 대상이 못 됩니다. 그래서 구조화 출력이 필요합니다.

### 2-4. 구조화 로그 — ID를 문장이 아니라 필드로

Spring Boot는 JSON 기반 세 포맷을 내장합니다. Elastic Common Schema(`ecs`), GELF(`gelf`), Logstash(`logstash`)이고, **ECS와 Logstash는 MDC 내용을 JSON에 포함합니다**([Spring Boot — Logging](https://docs.spring.io/spring-boot/reference/features/logging.html)).

```yaml
logging:
  structured:
    format:
      console: ecs
    json:
      add:
        service.version: "${APP_VERSION:unknown}"
```

MDC에 들어간 `traceId`가 JSON 필드로 나가면 `traceId:"803b..."` 같은 필드 질의가 됩니다. OpenTelemetry 로그 데이터 모델도 로그 레코드에 `TraceId`·`SpanId`·`TraceFlags` 필드를 정의하고 있고, SpanId가 있으면 TraceId도 있어야 한다고 규정합니다([OTel — Logs Data Model](https://opentelemetry.io/docs/specs/otel/logs/data-model/)). 로그와 트레이스를 서로 링크해주는 관측 도구들이 기대하는 자리가 이 필드입니다.

### 2-5. 진입점에서 누가 ID를 만드나

앱이 최초 진입점이 아닐 수 있습니다. ALB는 요청을 받을 때 `X-Amzn-Trace-Id`를 추가하거나 갱신합니다. 포맷은 `Root=1-{8자리 16진수 epoch}-{24자리 16진수 ID}`이고, 헤더가 없으면 `Root`를 만들고, `Root`가 이미 있으면 `Self`를 끼워 넣습니다. 액세스 로그를 켜면 이 헤더 내용이 기록됩니다([AWS — ALB 요청 추적](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-request-tracing.html)).

문제는 이게 **traceparent와 다른 체계**라는 점입니다. 둘을 이어두지 않으면 ALB 액세스 로그와 앱 로그가 서로 연결되지 않습니다(§6-5).

## 3. 흐름

### 3-1. 설정으로 보는 구성

Spring Boot 4.1에서 OTLP로 내보내는 구성입니다.

```groovy
dependencies {
    implementation 'org.springframework.boot:spring-boot-starter-actuator'
    implementation 'org.springframework.boot:spring-boot-starter-opentelemetry'
}
```

```yaml
spring:
  application:
    name: order-service
management:
  tracing:
    sampling:
      probability: 1.0   # 기본값은 0.1
logging:
  structured:
    format:
      console: ecs
```

두 가지만 짚습니다.

1. **샘플링 기본값은 0.1입니다.** 즉 트레이스의 10%만 수집 대상이 됩니다([Spring Boot — Tracing](https://docs.spring.io/spring-boot/reference/actuator/tracing.html)). 트래픽이 적은 서비스에서 이 값을 그대로 두면 정작 찾고 싶은 요청이 백엔드에 없습니다.
2. **Zipkin 계열은 별도 스타터입니다.** `spring-boot-starter-zipkin`(Brave)이 따로 있고, OpenTelemetry로 Zipkin에 보내는 조합은 Spring Boot 4.1에서 deprecated, 4.2에서 제거 예정입니다.

트레이스 수집 백엔드를 아직 못 붙이는 상황이라도, 액추에이터와 Micrometer Tracing만 있으면 **로그의 상관관계 ID는 그대로 생깁니다.** 여기까지가 가장 값싼 구간입니다.

### 3-2. 요청 하나가 두 서비스를 지나는 동안

```text
1. 클라이언트 → 게이트웨이     traceparent 없음
2. 게이트웨이 → order-service  traceparent: 00-4bf9...4736-00f0...02b7-01  (새로 생성)
3. order-service               스팬 시작 → MDC{traceId=4bf9...4736, spanId=a1b2...}
                               로그 3줄에 같은 traceId 박힘
4. order-service → coupon-service
                               traceparent: 00-4bf9...4736-a1b2...-01
                               traceId 동일 · spanId 교체 (자식 스팬)
5. coupon-service              MDC{traceId=4bf9...4736, spanId=c3d4...}
6. 실패 응답 ← 4xx             양쪽 로그에 같은 traceId 남음
```

3번과 5번이 핵심입니다. **서비스가 달라도 traceId는 같고 spanId는 다릅니다.** 그래서 `traceId`로 질의하면 두 서비스 로그가 한 줄기로 모이고, `spanId`로 좁히면 한 구간만 봅니다.

4번의 헤더 전파는 자동으로 되지만 **조건이 있습니다.** Spring Boot는 `RestTemplateBuilder`, `RestClient.Builder`, `WebClient.Builder`로 만든 클라이언트에만 계측을 넣습니다. `new RestTemplate()`으로 직접 만들면 전파되지 않습니다(§6-3).

### 3-3. 장애 때 실제로 밟는 순서

```text
1. 진입점 찾기    도메인 식별자(orderId 등)로 로그 한 줄 확보
2. traceId 추출   그 줄의 traceId 필드 복사
3. 전 구간 재생   서비스 구분 없이 traceId로 질의 → 시각 순 정렬
4. 경계 확인      마지막으로 남은 경계 로그가 실패 지점
5. 트레이스 확인   시간 분포가 필요하면 같은 traceId로 트레이스 UI 조회
```

1번이 되려면 도메인 식별자가 로그에 있어야 하고(`day36-log-design.md`), 3번이 되려면 traceId가 **필드로** 있어야 합니다. 5번이 되려면 그 트레이스가 샘플링을 통과했어야 합니다. 셋 중 하나가 빠지면 그 단계에서 멈춥니다.

## 4. 대가

### 4-1. 얻는 것

- 서비스 수가 늘어도 조사 시간이 서비스 수에 비례해 늘지 않습니다. 질의는 언제나 한 번입니다.
- "이 요청이 우리 쪽에 도달했는가"를 상대와 **같은 ID로** 대화할 수 있습니다.
- 재시도를 구분할 수 있습니다. 같은 traceId로 묶인 여러 시도는 클라이언트 재시도이고, 다른 traceId면 사용자가 다시 누른 것입니다.

### 4-2. 지불하는 것

- **모든 서비스가 참여해야 의미가 있습니다.** 한 서비스가 헤더를 버리면 그 지점에서 사슬이 끊기고, 끊긴 뒤로는 아무 가치가 없습니다. 이게 트레이싱 도입이 기술 문제보다 합의 문제인 이유입니다.
- **컨텍스트 전파에는 비용이 있습니다.** 스레드를 넘길 때마다 컨텍스트를 복사해야 하고, Spring 문서도 `ContextPropagatingTaskDecorator`가 작업 실행에 오버헤드를 만들며 **아주 작은 작업을 대량으로 돌리는 애플리케이션에는 권하지 않는다**고 명시합니다([Spring Framework — Observability](https://docs.spring.io/spring-framework/reference/integration/observability.html)).
- **로그 용량이 줄당 55자 이상 늘어납니다.** 텍스트 로그에서는 무시할 수준이 아닙니다.
- 샘플링을 1.0으로 올리면 수집·저장 비용이 그대로 10배가 됩니다. 로그 상관관계만 필요하면 이 비용은 안 내도 됩니다.

## 5. 예제 — 직접 만든 요청 ID vs 표준 전파

### 5-1. 직접 만드는 코드 ❌

```java
@Component
public class RequestIdFilter extends OncePerRequestFilter {

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        MDC.put("requestId", UUID.randomUUID().toString());
        try {
            chain.doFilter(request, response);
        } finally {
            MDC.clear();
        }
    }
}
```

한 서비스 안에서는 동작합니다. 문제는 세 가지입니다.

1. **들어온 ID를 안 봅니다.** 게이트웨이가 이미 ID를 붙여 보냈어도 무시하고 새로 만들어서, 게이트웨이 로그와 연결이 끊깁니다.
2. **나갈 때 안 보냅니다.** 하위 서비스는 또 자기 ID를 만듭니다. 서비스가 세 개면 한 요청에 ID가 세 개입니다.
3. 포맷이 우리끼리만 아는 값이라, 관측 도구가 트레이스와 링크해주지 못합니다.

### 5-2. 표준을 쓰고, 도메인 정보만 얹는 코드 ✔️

전파는 라이브러리에 맡기고, 애플리케이션은 **라이브러리가 모르는 정보**만 얹습니다.

```java
@Component
public class OrderContextFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger("request.summary");

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        // traceId/spanId는 Micrometer Tracing이 이미 MDC에 넣었습니다
        String tenantId = request.getHeader("X-Tenant-Id");
        if (tenantId != null) {
            MDC.put("tenantId", tenantId);
        }
        long startedAt = System.nanoTime();
        try {
            chain.doFilter(request, response);
        } finally {
            log.atInfo()
               .addKeyValue("method", request.getMethod())
               .addKeyValue("path", request.getRequestURI())
               .addKeyValue("status", response.getStatus())
               .addKeyValue("durationMs", (System.nanoTime() - startedAt) / 1_000_000)
               .setMessage("request.completed")
               .log();
            MDC.remove("tenantId");
        }
    }
}
```

`MDC.clear()`가 아니라 `MDC.remove("tenantId")`인 게 의도적입니다. 이 필터는 자기가 넣은 것만 치워야 합니다. `clear()`는 추적 라이브러리가 관리하는 항목까지 지워서, 이후 로그에서 traceId가 사라집니다.

이 값을 하위 서비스까지 넘기고 싶으면 baggage를 씁니다.

```yaml
management:
  tracing:
    baggage:
      remote-fields: tenantId       # HTTP 헤더로 하위 서비스까지 전파
      correlation:
        fields: tenantId            # MDC에 넣어 로그에 노출
```

다만 baggage는 **하위 모든 요청의 헤더에 실려 나갑니다.** W3C Baggage는 구현이 최소 64개 멤버·8192바이트를 지원하도록 규정하면서, 헤더가 사용자 식별 정보를 담을 수 있으므로 **신뢰 경계를 넘는 요청에는 baggage가 없도록 보장하라**고 명시합니다([W3C Baggage](https://www.w3.org/TR/baggage/)). 넣기 전에 "이 값이 외부 벤더 API 호출에도 붙어도 되는가"를 물어야 합니다.

## 6. 함정

### 6-1. 로그의 traceId를 복사해 넣었는데 트레이스가 없습니다

- **증상**: 로그에는 traceId가 멀쩡히 있습니다. 그 값을 트레이스 UI에 넣으면 "결과 없음"이 나옵니다. 어떤 요청은 되고 어떤 요청은 안 됩니다.
- **원인**: 샘플링입니다. OpenTelemetry SDK는 **샘플링 결정과 무관하게 스팬 ID를 생성**하므로 ID는 항상 존재합니다. 하지만 Sampler가 DROP을 반환하면 그 스팬은 non-recording이 되고, 스팬 프로세서와 익스포터를 거치지 않습니다 — 즉 **백엔드에 아예 안 갑니다**([OTel — Trace SDK](https://opentelemetry.io/docs/specs/otel/trace/sdk/)). Spring Boot의 기본 샘플링 확률은 0.1입니다.
- **해법**: "로그에 ID가 있다 = 트레이스가 있다"는 가정을 버립니다. 그다음 둘 중 하나입니다. 트래픽이 작으면 `management.tracing.sampling.probability`를 1.0으로 올립니다. 크면 확률 기반 대신 **오류·지연 기반으로 남길 트레이스를 고르는 방식**을 수집기 단계에 둡니다. 그리고 상위 서비스가 sampled=0으로 보내면 하위도 보통 따라 내려가므로, 결정은 진입점에서 일관되게 내려야 합니다.

### 6-2. 비동기 작업 로그에서 traceId가 사라지거나, 남의 것이 붙습니다

- **증상**: `@Async` 메서드나 스레드풀 작업의 로그에서 traceId가 비어 있습니다(`%X{traceId:-}`라서 조용히 공백). 더 나쁜 경우 **직전에 그 스레드를 쓴 다른 요청의 ID**가 붙습니다.
- **원인**: MDC와 추적 컨텍스트가 스레드 로컬입니다. 새 스레드로 작업이 넘어가면 컨텍스트가 따라가지 않습니다. 스레드풀은 스레드를 재사용하므로 앞 작업의 잔여 값이 남을 수 있습니다.
- **해법**: `io.micrometer:context-propagation`을 클래스패스에 두고 `ContextPropagatingTaskDecorator`를 빈으로 등록합니다. Spring Boot 자동 구성이 `TaskDecorator` 빈을 찾아 `AsyncTaskExecutor`에 끼워 넣습니다. 직접 만든 `ExecutorService`에는 적용되지 않으니, 그쪽은 별도로 감싸야 합니다. 메시지 큐 경계는 자동 계측 여부를 직접 확인해야 합니다 — 프로듀서·컨슈머 양쪽 모두 계측되어야 traceId가 이어집니다.

```java
@Bean
TaskDecorator contextPropagatingTaskDecorator() {
    return new ContextPropagatingTaskDecorator();
}
```

### 6-3. 어떤 호출은 전파되고 어떤 호출은 안 됩니다

- **증상**: 같은 서비스가 A 서비스를 부를 때는 traceId가 이어지는데, B 서비스를 부를 때는 B에서 새 트레이스가 시작됩니다.
- **원인**: HTTP 클라이언트를 빌더로 안 만들었습니다. Spring Boot의 계측은 `RestTemplateBuilder`, `RestClient.Builder`, `WebClient.Builder`를 거친 인스턴스에만 적용됩니다. `new RestTemplate()`이나 순수 `HttpClient`는 헤더를 안 붙입니다.
- **해법**: 클라이언트는 전부 빌더를 주입받아 만듭니다. 라이브러리가 내부에서 자체 HTTP 클라이언트를 쓰는 경우(SDK 등)에는 인터셉터로 직접 traceparent를 넣는 것 외에 방법이 없습니다.

### 6-4. traceId가 메시지 문자열 안에만 있습니다

- **증상**: 로그를 봤을 때 사람 눈에는 traceId가 보입니다. 그런데 로그 도구에서 `traceId:"..."`로 질의하면 0건입니다. `grep` 같은 전문 검색으로만 걸립니다.
- **원인**: 텍스트 패턴으로만 출력하고 있습니다. ID는 한 줄 전체 문자열의 일부일 뿐이라 필드가 아닙니다. 또는 개발자가 `log.info("orderId=" + id + " trace=" + traceId)` 식으로 직접 이어붙였습니다.
- **해법**: 구조화 포맷(ECS·Logstash)으로 내보내면 MDC가 JSON 필드가 됩니다. 애플리케이션 코드에서는 traceId를 **직접 찍지 않습니다** — 이미 붙습니다. 추가 정보는 문자열 연결이 아니라 `addKeyValue`로 넘깁니다.

### 6-5. 프록시 로그와 앱 로그가 안 이어집니다

- **증상**: ALB 액세스 로그에서 5xx를 찾았는데, 그 요청에 해당하는 앱 로그를 못 찾습니다. 시각과 경로로 추측할 수밖에 없습니다.
- **원인**: ALB는 `X-Amzn-Trace-Id`를 쓰고 앱은 `traceparent`를 씁니다. 서로 다른 값이라 조인할 키가 없습니다. 게다가 ALB는 요청 헤더가 7KB를 넘으면 `X-Amzn-Trace-Id`를 `Root` 필드로 **덮어써 버립니다**([AWS — ALB 요청 추적](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-request-tracing.html)).
- **해법**: 앱이 `X-Amzn-Trace-Id`를 읽어 MDC에 별도 필드로 함께 남깁니다. 그러면 프록시 로그의 값으로 앱 로그를 찾을 수 있고, 거기서 traceId를 얻어 나머지를 재생할 수 있습니다. 반대 방향으로 앱의 traceId를 응답 헤더에 실어 CS 대응에 쓰는 팀도 있는데, 그건 외부에 내부 식별자를 노출하는 결정이라 별도로 판단할 문제입니다.

### 6-6. 외부에서 온 traceparent를 그대로 믿습니다

- **증상**: 트레이스 하나에 수만 개 스팬이 붙거나, 관계없는 요청들이 한 트레이스로 뭉쳐 보입니다.
- **원인**: 인터넷에서 직접 들어오는 요청의 traceparent를 그대로 이어받았습니다. 헤더는 클라이언트가 임의로 채울 수 있는 값입니다. 같은 traceId를 계속 보내면 트레이스 하나가 무한히 자라고, sampled=1을 고정해 보내면 샘플링을 우회해 수집 비용을 올릴 수 있습니다.
- **해법**: 신뢰 경계를 정합니다. **내부 서비스 간 호출에서는 이어받고, 외부에서 직접 들어오는 경로에서는 새로 만듭니다.** 보통 게이트웨이나 엣지에서 헤더를 제거하거나 교체하는 방식으로 처리합니다.

<!-- TODO: 확인 필요 — Spring Boot에는 수용/생성 포맷을 나누는 management.tracing.propagation.consume / produce 속성이 있고 produce는 W3C가 기본이라고 알려져 있으나, 4.1 공통 속성 부록에서 기본값을 직접 확인하지 못했습니다. 실제 적용 전 해당 버전 문서로 확인하세요. -->

## 7. 정리

요청 하나를 끝까지 따라가는 일은 로그를 더 많이 남겨서 해결되지 않습니다. **모든 줄에 같은 검색 키를 심는 문제**입니다.

- 진입점에서 ID를 만들고, 경계를 넘을 때 **표준 헤더로** 넘기는가
- 그 ID가 문장이 아니라 **필드로** 나가는가
- 스레드와 큐를 넘을 때도 컨텍스트가 따라가는가
- "ID가 있다"와 "트레이스가 수집됐다"를 구분하고 있는가

마지막 항목이 실제로 가장 많이 사람을 헷갈리게 합니다. 로그 상관관계는 거의 공짜에 가깝고 지금 켤 수 있지만, 트레이스 수집은 샘플링과 비용 결정이 따라오는 별개의 일입니다. 순서를 섞으면 "트레이싱 도입"이 크게 느껴져서 정작 값싼 쪽도 못 켭니다.

## 8. 참고자료

- [W3C — Trace Context](https://www.w3.org/TR/trace-context/)
- [W3C — Propagation format for distributed context: Baggage](https://www.w3.org/TR/baggage/)
- [OpenTelemetry — Logs Data Model](https://opentelemetry.io/docs/specs/otel/logs/data-model/)
- [OpenTelemetry — Tracing SDK (Sampling)](https://opentelemetry.io/docs/specs/otel/trace/sdk/)
- [Spring Boot Reference — Tracing](https://docs.spring.io/spring-boot/reference/actuator/tracing.html)
- [Spring Boot Reference — Logging](https://docs.spring.io/spring-boot/reference/features/logging.html)
- [Spring Framework Reference — Observability](https://docs.spring.io/spring-framework/reference/integration/observability.html)
- [AWS — Application Load Balancer 요청 추적](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-request-tracing.html)
- 관련 문서: `day36-log-design.md`, `day25-logging-basics.md`, `day03-api-error-format.md`

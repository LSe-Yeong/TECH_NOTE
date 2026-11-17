# 느린 요청에서 시간을 쓴 구간을 어떻게 특정하는가 — 분산 추적

> 이 문서가 답할 질문: **여러 서비스와 여러 호출을 거친 느린 요청 하나에서, 실제로 시간을 쓴 구간을 어떻게 특정하는가?**

기준 버전: **Spring Boot 4.1.2 / 3.5**, **W3C Trace Context Level 1 (2021-11-23 권고안)**, **OpenTelemetry Collector Contrib `tailsamplingprocessor`**

## 1. 핵심 개념 — 로그와 메트릭이 답하지 못하는 질문

분산 추적(Distributed Tracing)은 **요청 하나가 거쳐간 모든 구간을 부모-자식 관계가 있는 트리로 기록하는 방식**입니다. 구간 하나를 스팬(span), 한 요청에 속한 스팬 전체를 트레이스(trace)라고 부릅니다.

> 주문 API p99가 2초입니다. 주문·결제·재고 세 서비스의 응답시간 패널을 열면 전부 평균 수십 ms로 정상입니다. 트레이스 ID로 로그를 긁어모으면 "결제를 호출했고, 재고를 조회했고, 성공했다"는 사실은 나옵니다. 그런데 **1.8초를 누가 썼는지는 어디에도 없습니다.** 각 서비스는 자기 구간만 재고, 그 구간들을 더해도 2초가 안 됩니다. 남는 시간은 "서비스 사이"에 있는데, 서비스 사이를 재는 주체가 없습니다.

세 가지 데이터는 모양이 다릅니다. 이 차이가 "왜 또 하나를 깔아야 하는가"의 답입니다.

| | 기록 단위 | 답할 수 있는 질문 | 답할 수 없는 질문 |
|---|---|---|---|
| 로그 | 시각 하나(점) | 무슨 일이 있었는가 | 그 일이 몇 ms 걸렸는가 |
| 메트릭 | 시간창 단위 합산값 | 전체가 느려졌는가 | 이 요청 하나가 왜 느렸는가 |
| 트레이스 | 시작·종료·부모가 있는 구간 | 이 요청의 시간을 누가 썼는가 | 어제 전체 평균이 얼마였는가 |

`dayNN` 기준으로 보면 day42-structured-log-trace-id.md가 "요청 하나의 로그를 모으는 것"까지 해결하고, 분산 추적은 그 위에 **구간과 부모 관계**를 얹습니다. 로그에 소요 시간을 직접 찍어서 비슷하게 따라 할 수는 있지만, 부모 관계가 없으면 "A가 느린 게 A 자신 때문인지 A가 호출한 B 때문인지"를 구분할 수 없습니다. 그 구분이 분산 추적의 존재 이유 전체입니다.

---

## 2. 구조 — 스팬 하나가 들고 있는 것

### 2-1. 트리를 만드는 식별자 세 개

- `trace_id` — 요청 하나에 하나. 모든 스팬이 공유합니다
- `span_id` — 구간 하나에 하나
- `parent_span_id` — 부모 구간의 `span_id`. 루트 스팬만 비어 있습니다

이 셋만 있으면 흩어진 스팬을 트리로 복원할 수 있습니다. 나머지(이름, 시작·종료 시각, 속성, 상태)는 그 트리에 붙는 살입니다.

### 2-2. 프로세스 경계를 넘기는 방법 — `traceparent`

같은 요청인지 아닌지는 **호출하는 쪽이 헤더에 넣어 알려주는 방법밖에 없습니다.** 표준은 W3C Trace Context이고, 헤더 하나로 끝납니다.

```
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
             ^^ ^------------ 32 hex ----------^ ^--- 16 hex ---^ ^^
           version          trace-id              parent-id    trace-flags
```

- `trace-id`는 소문자 hex 32자(16바이트), `parent-id`는 16자(8바이트)입니다
- **둘 다 전부 0이면 무효**이고, 이 경우 수신 측은 헤더를 무시해야 합니다
- `trace-flags`는 8비트 비트필드입니다. 버전 `00`에서 정의된 비트는 최하위 1비트 `sampled` 하나뿐이라, 값을 숫자로 비교하지 말고 **마스킹해서 읽어야** 합니다

출처: [W3C Trace Context, Recommendation 2021-11-23](https://www.w3.org/TR/trace-context/)

여기서 실무에 영향을 주는 문장이 하나 있습니다. 명세는 `sampled` 비트를 **호출자의 권고(recommendation)** 로 규정합니다. 호출자를 신뢰할 수 없고, 호출자에 버그가 있을 수 있고, 양쪽의 부하 상황이 다르기 때문입니다. 즉 **상류가 켜서 보낸 플래그를 하류가 뒤집어도 규격 위반이 아닙니다.** "앞단에서는 샘플링됐는데 뒤쪽 서비스 스팬만 없다"는 현상이 설정 실수가 아닐 수도 있는 이유입니다.

벤더 전용 정보는 `tracestate` 헤더가 따로 운반하며, `traceparent` 파싱이 성공했을 때만 해석됩니다.

### 2-3. SpanKind — 부모-자식으로 묶을 수 없는 관계

OpenTelemetry는 스팬 종류를 다섯 개로 정의합니다.

| SpanKind | 의미 |
|---|---|
| `SERVER` | 들어온 원격 요청의 처리. 클라이언트가 응답을 기다리는 중 |
| `CLIENT` | 나가는 원격 요청. 호출자가 응답을 기다립니다 |
| `PRODUCER` | 나중에 실행될 작업의 등록·발행 |
| `CONSUMER` | 프로듀서가 시작시킨 작업의 처리 |
| `INTERNAL` | 기본값. 프로세스 안에서 끝나는 구간 |

`CLIENT`/`SERVER`는 요청-응답이라 **타이밍이 묶여 있습니다.** 그래서 `CLIENT` 스팬이 `SERVER` 스팬의 부모가 되고, 둘의 차이가 네트워크와 큐잉 시간입니다.

`PRODUCER`/`CONSUMER`는 다릅니다. 명세는 `PRODUCER` 스팬이 **대응하는 `CONSUMER` 스팬보다 먼저 끝나는 경우가 많다**고 적습니다. 컨슈머가 시작하기도 전에 끝날 수 있습니다. 그래서 둘을 부모-자식으로 묶으면 "부모가 끝난 뒤에 시작하는 자식"이라는 모양이 되고, 지연 분석이 무의미해집니다. 이 관계는 부모가 아니라 **스팬 링크(Span Link)** 로 표현합니다. 링크는 다른 트레이스의 `SpanContext`도 가리킬 수 있습니다.

주의할 점이 하나 있습니다. **생성 시점에 넣은 링크는 샘플러가 볼 수 있지만, 나중에 `AddLink`로 붙인 링크는 보지 못할 수 있습니다.** 헤드 샘플링 결정은 생성 시점 정보만 쓰기 때문입니다.

출처: [OpenTelemetry Tracing API 명세](https://opentelemetry.io/docs/specs/otel/trace/api/)

### 2-4. 속성은 어디까지 넣어도 되는가

day66-prometheus-basics.md에서 라벨 카디널리티가 메트릭을 터뜨린다고 썼습니다. 트레이스는 기준이 다릅니다. 스팬은 집계 대상이 아니라 개별 기록이므로 `userId`, 주문번호, 전체 URL 같은 고유값을 넣어도 됩니다. 오히려 넣어야 합니다.

Micrometer Observation API는 이 구분을 API 레벨로 분리해 둡니다.

> "Low cardinality tags will be added to metrics and traces, while high cardinality tags will only be added to traces."
> — [Spring Boot 4.1.2, Observability](https://docs.spring.io/spring-boot/reference/actuator/observability.html)

`lowCardinalityKeyValue`는 메트릭 태그와 스팬 속성 양쪽에, `highCardinalityKeyValue`는 스팬에만 들어갑니다. 관측 한 번으로 둘을 만들면서 메트릭만 보호하는 구조입니다.

---

## 3. 흐름

### 3-1. 코드로 보는 구성

Spring Boot 3.5에서 OpenTelemetry + OTLP 조합은 의존성 두 개입니다. `spring-boot-starter-actuator`가 전제입니다.

```gradle
// Spring Boot 3.5 기준
implementation 'org.springframework.boot:spring-boot-starter-actuator'
implementation 'io.micrometer:micrometer-tracing-bridge-otel'
implementation 'io.opentelemetry:opentelemetry-exporter-otlp'
```

Spring Boot 4.1에서는 스타터 하나로 정리됐습니다. 3.x 좌표를 그대로 올리면 안 됩니다.

```gradle
// Spring Boot 4.1 기준
implementation 'org.springframework.boot:spring-boot-starter-actuator'
implementation 'org.springframework.boot:spring-boot-starter-opentelemetry'
```

```yaml
# Spring Boot 4.1 기준. 3.5는 management.otlp.tracing.endpoint
management:
  tracing:
    sampling:
      probability: 1.0
  opentelemetry:
    tracing:
      export:
        otlp:
          endpoint: http://otel-collector.internal:4318/v1/traces
logging:
  pattern:
    correlation: "[${spring.application.name:},%X{traceId:-},%X{spanId:-}] "
  include-application-name: false
```

`logging.pattern.correlation` 기본 형식은 `[traceId-spanId]`입니다. 위 설정은 Sleuth 시절 형식으로 바꾼 것이고, 로그와 트레이스를 같은 ID로 잇는 지점이 여기입니다.

자동 계측이 덮지 않는 구간은 직접 스팬을 만듭니다.

```java
@Service
public class OrderPricingService {

    private final ObservationRegistry registry;

    public OrderPricingService(ObservationRegistry registry) {
        this.registry = registry;
    }

    public Money calculate(Order order) {
        Observation observation = Observation.createNotStarted("order.pricing", this.registry)
                .lowCardinalityKeyValue("channel", order.channel().name())  // 메트릭 + 스팬
                .highCardinalityKeyValue("orderId", order.id().toString()); // 스팬만

        return observation.observe(() -> applyPromotions(order));
    }
}
```

애너테이션(`@Observed`, `@NewSpan`)을 쓰려면 `management.observations.annotations.enabled=true`와 `org.aspectj:aspectjweaver`가 필요합니다. 기본값은 꺼져 있습니다.

### 3-2. 전파 결과 — 폭포 읽기

```
주문-api        SERVER   POST /api/orders ─────────────────────────── 1,980ms
  └ 주문-api    INTERNAL order.pricing ──── 12ms
  └ 주문-api    CLIENT   POST /payments ───────────── 1,840ms
      └ 결제-api SERVER  POST /payments ───────────── 1,835ms
          └ 결제-api CLIENT SELECT card_bin ── 4ms
          └ 결제-api CLIENT POST pg-gateway ────────── 1,800ms
  └ 주문-api    CLIENT   SELECT stock ──── 9ms   (결제와 병렬)
  └ 주문-api    CLIENT   INSERT orders ─── 7ms
```

이 그림에서 읽히는 것은 세 가지입니다. PG 게이트웨이 호출이 1,800ms, 결제 서비스 자체가 쓴 시간은 1,835 − 1,804 = 31ms, 그리고 주문-api의 `CLIENT`(1,840)와 결제-api의 `SERVER`(1,835) 차이 5ms가 네트워크와 큐잉입니다.

**각 서비스의 응답시간 대시보드로는 절대 보이지 않던 사실**이 하나 있습니다. 결제-api의 평균 응답시간은 PG 호출을 포함하므로 "결제가 느리다"로 보이는데, 결제 서비스가 고칠 수 있는 구간은 31ms뿐입니다.

---

## 4. 병목을 찾는 네 가지 읽기

### 4-1. 총 시간이 아니라 자기 시간

스팬의 **self time** = 자기 duration − 자식 스팬들이 덮은 시간입니다. 총 시간이 긴 스팬은 대부분 "기다린 스팬"이고, 고칠 대상은 self time이 긴 스팬입니다. 자식이 병렬로 겹치면 단순 차감이 음수가 될 수 있으니, 겹침을 합집합으로 계산하는 UI인지 확인해야 합니다.

### 4-2. 임계 경로

총 지연을 정하는 것은 **서로 의존하는 스팬들의 가장 긴 사슬**입니다. 루트에서 시작해 "가장 늦게 끝나는 자식"을 따라 내려가면 그 사슬이 나옵니다. 위 예시의 `SELECT stock`(9ms)을 0ms로 만들어도 응답은 1ms도 빨라지지 않습니다. 결제와 병렬이고 임계 경로 밖이기 때문입니다.

self time 순위만 보고 튜닝 대상을 고르면 이 함정에 빠집니다. **self time이 크고 임계 경로 위에 있는 스팬**만이 의미 있는 후보입니다.

### 4-3. 스팬 개수의 패턴

트레이스 하나에 거의 같은 모양의 DB 스팬이 수십 개 줄줄이 늘어서 있으면 N+1입니다. 개별 스팬은 2~3ms라 어떤 슬로우 쿼리 로그에도 걸리지 않고, 합계만 수백 ms가 됩니다. **지연 분석에서 스팬의 길이보다 개수가 먼저 보이는 유일한 케이스**이고, 트레이스 없이는 발견 경로가 거의 없습니다.

### 4-4. 스팬이 없는 빈 구간

폭포에서 부모 스팬은 열려 있는데 자식이 아무것도 없는 공백이 있다면, 그 구간은 "빠른 구간"이 아니라 **계측되지 않은 구간**입니다. 흔한 정체는 커넥션 풀 대기, 스레드 풀 큐 대기, GC 멈춤, 그리고 끊긴 전파입니다. 공백은 결론이 아니라 다음 계측 대상입니다.

---

## 5. 샘플링 — 느린 요청만 남기는 문제

### 5-1. 헤드 샘플링과 그 한계

Spring Boot는 **기본적으로 요청의 10%만 샘플링합니다**. 백엔드를 보호하기 위한 기본값입니다 ([Spring Boot 4.1.2, Tracing](https://docs.spring.io/spring-boot/reference/actuator/tracing.html)). `management.tracing.sampling.probability`로 바꿉니다.

반면 OpenTelemetry Java 에이전트를 붙이는 방식은 `OTEL_TRACES_SAMPLER` 기본값이 `parentbased_always_on`, 즉 **100%** 입니다 ([OTel SDK 설정](https://opentelemetry.io/docs/languages/sdk-configuration/general/)). 같은 "기본 설정"인데 수집량이 10배 차이 나므로, 두 방식을 섞어 쓰는 조직에서 비용과 유실이 동시에 설명되지 않는 일이 생깁니다.

헤드 샘플링의 결정은 보통 trace ID 해시로 내려집니다. 그래야 모든 서비스가 같은 판단을 내려 **트레이스가 중간에 잘리지 않습니다.** 대신 구조적 한계가 생깁니다.

> 결정 시점에는 트레이스의 나머지가 아직 존재하지 않습니다. 그래서 OpenTelemetry 문서는 헤드 샘플링만으로는 **"에러가 포함된 트레이스를 전부 남긴다"를 보장할 수 없다**고 못 박습니다 ([Sampling](https://opentelemetry.io/docs/concepts/sampling/)).

느린 요청도 같습니다. 2초 걸린 요청인지 20ms 걸린 요청인지는 끝나봐야 아는데, 결정은 시작할 때 내려집니다. **기본 10%에서는 장애 때 찾고 있는 그 요청이 90% 확률로 없습니다.**

### 5-2. 테일 샘플링과 그 비용

테일 샘플링은 트레이스의 스팬이 거의 다 모인 뒤에 결정합니다. OpenTelemetry Collector의 `tailsamplingprocessor`는 `trace_id`로 스팬을 묶고 정책을 적용합니다.

- `decision_wait` 기본값 **30초** — 이 시간만큼 기다린 뒤 판단합니다
- `num_traces` 기본값 **50,000** — 메모리에 보관하는 트레이스 수
- 정책: `latency`(트레이스의 최초 시작~최종 종료 간격), `status_code`(`OK`/`ERROR`/`UNSET`), `probabilistic`, `and`, `composite`

출처: [tailsamplingprocessor README](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/processor/tailsamplingprocessor/README.md)

공짜가 아닙니다. 대가는 세 가지입니다.

1. **상태를 가진 컴포넌트가 됩니다.** 30초치 트레이스를 메모리에 들고 있어야 하고, 그 양이 곧 Collector의 용량 계획입니다
2. **같은 트레이스의 모든 스팬이 같은 Collector 인스턴스에 도착해야 합니다.** 그래서 Collector를 늘릴 때 그냥 늘리면 안 되고, `loadbalancing` exporter로 trace ID 기준 라우팅을 하는 1계층과 테일 샘플링을 하는 2계층으로 나눠야 합니다
3. **정책이 시스템과 함께 썩습니다.** OpenTelemetry 문서 스스로 운영·구현 난이도와 벤더 종속 위험을 비용으로 명시합니다

출발점은 "헤드 100% + Collector에서 테일"입니다. 애플리케이션에서 줄인 양은 되돌릴 수 없고, Collector에서 줄이면 정책만 바꾸면 됩니다.

---

## 6. 예제 — 트레이스가 끊기는 두 지점

### 6-1. 끊긴 코드 ❌

```java
@Service
public class PaymentClient {

    // ❌ 직접 생성한 클라이언트는 traceparent를 넣지 않습니다
    private final RestClient restClient = RestClient.create();

    public PaymentResult pay(PaymentRequest request) {
        return restClient.post()
                .uri("https://payment.internal/payments")
                .body(request)
                .retrieve()
                .body(PaymentResult.class);
    }
}
```

```java
@Service
public class OrderNotifier {

    // ❌ 다른 스레드로 넘어가면서 관측 컨텍스트가 사라집니다
    @Async
    public void notifyShipping(Long orderId) {
        log.info("배송 알림 발송: {}", orderId);  // traceId 자리가 비어 있습니다
    }
}
```

결제-api에는 `traceparent`가 없으니 **새 트레이스가 시작됩니다.** 끊긴 자리가 화면에서는 "여기서 처리가 끝났다"처럼 보이고, 1.8초는 아무 트레이스에도 속하지 않습니다.

### 6-2. 이어지게 고친 코드 ✔️

```java
@Service
public class PaymentClient {

    private final RestClient restClient;

    // ✔️ 자동 구성된 빌더를 주입받으면 전파 인터셉터가 붙어 있습니다
    public PaymentClient(RestClient.Builder builder) {
        this.restClient = builder.baseUrl("https://payment.internal").build();
    }

    public PaymentResult pay(PaymentRequest request) {
        return restClient.post()
                .uri("/payments")
                .body(request)
                .retrieve()
                .body(PaymentResult.class);
    }
}
```

```java
@Configuration
public class AsyncConfig {

    // ✔️ TaskDecorator로 스냅샷을 떠서 작업 스레드에 복원합니다
    @Bean("applicationTaskExecutor")
    public ThreadPoolTaskExecutor applicationTaskExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(8);
        executor.setQueueCapacity(100);
        executor.setThreadNamePrefix("order-async-");
        executor.setTaskDecorator(new ContextPropagatingTaskDecorator());
        executor.initialize();
        return executor;
    }
}
```

`org.springframework.core.task.support.ContextPropagatingTaskDecorator`는 Spring Framework 6.1부터 있고, `io.micrometer:context-propagation`이 클래스패스에 있어야 동작합니다. Javadoc은 **오버헤드가 있으므로 아주 작은 작업을 대량으로 돌리는 애플리케이션에는 권하지 않는다**고 적어둡니다 ([Javadoc](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/core/task/support/ContextPropagatingTaskDecorator.html)).

---

## 7. 함정

**기본 샘플링 10%로 장애를 분석하려 합니다**
- **증상**: 트레이싱을 붙였는데, 막상 고객이 알려준 느린 요청의 트레이스 ID로 검색하면 결과가 없습니다
- **원인**: Spring Boot 기본값이 10%이고, 헤드 샘플링은 느린지 여부를 알기 전에 결정합니다
- **해법**: 애플리케이션은 `probability: 1.0`으로 두고 Collector의 테일 샘플링에서 `latency`·`status_code` 정책으로 줄입니다. 테일 샘플링을 운영할 여력이 없다면 확률을 올리고 보존 기간을 짧게 가져가는 쪽이 낫습니다

**`new RestTemplate()` / `RestClient.create()`**
- **증상**: 트레이스가 특정 서비스에서 끊기고, 하류 서비스의 스팬이 전부 별개의 루트 트레이스로 생깁니다
- **원인**: 전파 인터셉터는 자동 구성된 `RestClient.Builder`·`RestTemplateBuilder`·`WebClient.Builder`를 거칠 때만 붙습니다. 직접 `new`로 만든 인스턴스에는 아무것도 붙지 않습니다
- **해법**: 빌더를 주입받아 만듭니다. 끊긴 지점을 찾을 때는 `CLIENT` 스팬 없이 끝나는 `SERVER` 스팬을 먼저 의심합니다

**`@Async`·커스텀 스레드 풀에서 컨텍스트 유실**
- **증상**: 비동기 메서드의 로그에서 `traceId`가 비고, 그 안의 작업이 트레이스에 나타나지 않습니다
- **원인**: 관측 컨텍스트는 ThreadLocal로 전달되고, 스레드가 바뀌면 사라집니다. Spring Framework는 `@Async` 자체를 Observation으로 계측할 계획이 없다고 밝혀 왔습니다
- **해법**: Executor에 `ContextPropagatingTaskDecorator`를 붙입니다. 서드파티 라이브러리가 자체 스레드 풀을 쓰면 그 풀에도 따로 적용해야 합니다
- <!-- TODO: 확인 필요 — spring.task.execution.propagate-context 프로퍼티 자동 등록은 PR #48385가 declined로 닫히고 메인테이너가 별도 커밋으로 가져갔습니다. 4.1.2 참조 문서·Task Execution 문서에는 아직 언급이 없어, 어느 버전에서 프로퍼티로 제공되는지 확정하지 못했습니다. 현재는 TaskDecorator 수동 등록을 전제로 쓰십시오. -->

**자식 스팬이 부모보다 길어 보입니다**
- **증상**: 폭포에서 자식이 부모 범위를 벗어나거나, 호출보다 응답이 먼저 시작한 것처럼 보입니다
- **원인**: 스팬 시각은 각 호스트의 시계로 찍힙니다. 호스트 간 시계 오차가 그대로 그림에 나타납니다. 더 헷갈리는 쪽은 백엔드의 보정입니다. Jaeger는 쿼리 단계에서 부모와 겹치는 자식의 시작 시각을 **이동시켜** 그려줍니다
- **해법**: 먼저 NTP 동기화 상태를 확인합니다. 보정 때문에 원인이 가려진다면 Jaeger 쿼리 측에서 끕니다(v1 `--query.max-clock-skew-adjustment`, v2 `jaeger_query` 확장의 `max_clock_skew_adjust`를 0으로). 서비스 내부 구간 비교는 같은 호스트 안이라 영향을 받지 않으니, **서비스 경계를 넘는 수 ms 차이를 근거로 결론 내지 않는 것**이 실무 기준입니다
- <!-- TODO: 확인 필요 — Jaeger 릴리스별 보정 기본값(0s인지 1s인지)은 출처가 엇갈립니다. 쓰는 버전의 설정 레퍼런스를 확인하십시오. -->

**스팬 이름에 ID가 들어갑니다**
- **증상**: 스팬 이름이 `GET /api/orders/85213`처럼 요청마다 달라져, "이 엔드포인트의 p99" 같은 집계가 불가능해집니다
- **원인**: 이름을 실제 경로로 지었습니다. 이름은 집계의 축이므로 저카디널리티여야 합니다
- **해법**: 이름과 저카디널리티 태그는 템플릿(`/api/orders/{orderId}`)으로, 실제 값은 `highCardinalityKeyValue`로 넣습니다. 속성값 길이·개수 상한은 `management.opentelemetry.tracing.limits.*`(Spring Boot 4.1)로 방어합니다

**이미 계측된 곳에 `@Observed`를 덧붙입니다**
- **증상**: 같은 구간의 스팬과 메트릭이 두 벌 생기고, 호출 수가 두 배로 집계됩니다
- **원인**: Spring MVC 컨트롤러나 Spring Data 리포지토리는 이미 자동 계측 대상입니다
- **해법**: 자동 계측을 프로퍼티나 `ObservationPredicate`로 끄고 애너테이션만 쓰거나, 애너테이션을 지웁니다 ([Spring Boot 4.1.2, Observability](https://docs.spring.io/spring-boot/reference/actuator/observability.html))

---

## 8. 그래서 셋을 다 깔아야 하는가

분산 추적은 메트릭을 대체하지 않습니다. 샘플링된 트레이스로 전체 비율을 계산하면 틀립니다. 반대로 메트릭은 day54-golden-signals.md의 네 지표가 "이상하다"까지만 알려주고 "어디"는 모릅니다.

실무 순서는 **메트릭으로 감지 → 트레이스로 구간 특정 → 로그로 그 구간의 사실 확인**입니다. 이 순서가 성립하려면 세 데이터가 같은 ID로 이어져야 하고, 그 접착제가 `traceId`입니다. 도입 작업의 절반은 스팬을 만드는 일이고, 나머지 절반은 로그와 스팬에 같은 ID를 흐르게 만드는 일입니다.

---

## 9. 참고자료

- [W3C Trace Context (Recommendation, 2021-11-23)](https://www.w3.org/TR/trace-context/)
- [OpenTelemetry — Sampling](https://opentelemetry.io/docs/concepts/sampling/)
- [OpenTelemetry — Tracing API 명세 (SpanKind, Links)](https://opentelemetry.io/docs/specs/otel/trace/api/)
- [OpenTelemetry — SDK 환경변수 설정](https://opentelemetry.io/docs/languages/sdk-configuration/general/)
- [OpenTelemetry Collector Contrib — Tail Sampling Processor](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/processor/tailsamplingprocessor/README.md)
- [Spring Boot Reference — Tracing](https://docs.spring.io/spring-boot/reference/actuator/tracing.html)
- [Spring Boot Reference — Observability](https://docs.spring.io/spring-boot/reference/actuator/observability.html)
- [Spring Framework Javadoc — `ContextPropagatingTaskDecorator`](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/core/task/support/ContextPropagatingTaskDecorator.html)
- [Jaeger — Deployment Configuration](https://www.jaegertracing.io/docs/2.20/deployment/configuration/)
- 관련 챕터: day42-structured-log-trace-id.md, day54-golden-signals.md, day66-prometheus-basics.md, day72-dashboard-design.md

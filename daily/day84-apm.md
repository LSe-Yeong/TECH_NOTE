# APM은 언제 필요한가 — 메트릭·로그·추적을 다 갖춘 다음에 남는 질문

> 이 문서가 답할 질문: **골든 시그널·구조화 로그·분산 추적을 이미 갖춘 팀에게 APM은 무엇을 더 주고, 그래서 언제 도입하는가?**

기준 버전: **OpenTelemetry Java Instrumentation 2.32.0 (3.0 릴리스 후보)**, **Spring Boot 4.1 / 3.5**, **OpenTelemetry eBPF Instrumentation 1.0**. 요금은 2026-11-25 조회 기준입니다.

## 1. 핵심 개념 — APM이 파는 것은 데이터가 아니라 "안 쓴 계측 코드"

APM(Application Performance Monitoring)은 제품 카테고리 이름이고, 실체는 두 덩어리입니다.

1. **프로세스 안에 붙어 코드 수정 없이 계측하는 에이전트**
2. 메트릭·트레이스·로그·프로파일을 같은 요청 단위로 **엮어서 보여주는 백엔드**

여기서 중요한 건 1번입니다. 2번은 Prometheus·Loki·Tempo 조합으로 직접 만들 수 있고, 실제로 day66-prometheus-basics.md부터 day78-distributed-tracing.md까지가 그 과정이었습니다. 직접 만들 수 없는 쪽은 **"계측을 누가 넣느냐"** 입니다.

> 주문 API p99가 2초입니다. day78 방식대로 트레이스를 열어 self time이 큰 스팬을 찾았습니다. `OrderService.place` 구간이 1.6초를 썼고, 그 안에 자식 스팬이 하나도 없습니다. DB도 아니고 외부 호출도 아닙니다. 1.6초 동안 CPU 위에서 무슨 메서드가 돌았는지는 **어느 신호에도 없습니다.** 스팬은 내가 넣은 곳에만 있고, 나는 `place` 안쪽에 아무것도 넣지 않았으니까요. 그리고 이 상황은 예외가 아니라 기본값입니다. 서비스 12개에 들어가는 라이브러리 전부에 사람이 손으로 스팬을 넣는 팀은 없습니다.

세 신호와 APM의 관계를 수집 주체로 정리하면 이렇습니다.

| | 계측을 넣는 주체 | 코드 변경 | 답하는 질문 |
|---|---|---|---|
| 메트릭 (day54) | 사람 (또는 프레임워크 기본) | 필요 | 전체가 느려졌는가 |
| 트레이스 (day78) | 사람 + 라이브러리 계측 | 필요 | 이 요청의 어느 구간이 느렸는가 |
| APM 에이전트 | 에이전트가 바이트코드 수정 | **없음** | (위 둘을 공짜로) |
| 프로파일 | 런타임 샘플러 | 없음 | 그 구간 안에서 어느 메서드가 태웠는가 |

즉 APM 도입 판단은 "데이터를 더 모을까"가 아닙니다. **"계측 작업을 사람이 할지 에이전트가 할지"** 와 **"스팬보다 한 단계 아래로 자주 내려가는지"** 두 질문입니다.

---

## 2. 구조 — 에이전트는 무엇을 하는가

### 2-1. `-javaagent`가 끼어드는 지점

JVM은 `-javaagent`로 지정된 JAR의 `premain`을 `main`보다 먼저 실행합니다. 에이전트는 여기서 `ClassFileTransformer`를 등록하고, 그 뒤로 로드되는 모든 클래스의 바이트코드를 변환할 기회를 얻습니다.

```bash
java -javaagent:/opt/otel/opentelemetry-javaagent.jar \
     -Dotel.service.name=order-api \
     -Dotel.exporter.otlp.endpoint=http://otel-collector.internal:4317 \
     -Dotel.traces.sampler=parentbased_traceidratio \
     -Dotel.traces.sampler.arg=0.1 \
     -jar order-api.jar
```

애플리케이션 코드는 한 줄도 바뀌지 않습니다. 대신 `DispatcherServlet`, `HikariDataSource`, `JedisPool`, Kafka 컨슈머 같은 **라이브러리 쪽 클래스**가 스팬을 만드는 코드를 품은 상태로 로드됩니다.

그래서 APM 제품의 실력은 UI가 아니라 **"몇 개의 라이브러리를, 몇 개의 버전 범위까지 아는가"** 입니다. 모르는 라이브러리는 계측되지 않고, 아는 라이브러리라도 버전이 어긋나면 변환이 실패합니다. OpenTelemetry Java 에이전트는 이걸 muzzle이라는 장치로 방어합니다 — 계측이 참조하는 메서드 시그니처가 실제 클래스패스에 다 있는지 먼저 검사하고, 하나라도 없으면 그 계측만 조용히 비활성화합니다. 애플리케이션이 `NoSuchMethodError`로 죽는 대신 스팬이 안 생기는 쪽으로 실패합니다.

### 2-2. 수집 경로는 세 가지입니다

| | 코드 변경 | 재시작 | 얻는 깊이 | 주 제약 |
|---|---|---|---|---|
| 인프로세스 에이전트 | 없음 | 필요 (`-javaagent`) | 라이브러리 경계 + 프로파일 | 프로세스 안에서 돈다 |
| SDK 직접 계측 | 필요 | 필요 | 원하는 만큼 | 사람 손이 든다 |
| eBPF (OBI) | 없음 | **불필요** | 커널이 보는 소켓·프로토콜 | 애플리케이션 맥락이 약하다 |

세 번째가 최근에 생긴 선택지입니다. Grafana Beyla가 2025년 5월 OpenTelemetry에 기부되어 OpenTelemetry eBPF Instrumentation(OBI)이 되었고, 1.0에 도달했습니다. 커널 쪽에서 보기 때문에 JVM 옵션을 바꾸거나 프로세스를 재시작하지 않고도 HTTP·gRPC 스팬을 얻습니다.

단, 공짜는 아닙니다. 1.0 발표문이 나열한 프레임워크 route 탐지 지원 목록은 Django·FastAPI·Flask·Rails·.NET과 일부 PHP 프레임워크이고, **Java 프레임워크는 그 목록에 없습니다.** 발표문도 "OBI가 자동으로 관측할 수 없는 애플리케이션 고유 맥락이 필요하면 언어 에이전트와 수동 계측이 여전히 유효하다"고 적습니다. route를 못 뽑으면 2-3절과 5절에서 다루는 "엔드포인트가 뭉치는" 문제가 그대로 따라옵니다.

출처: [Introducing OpenTelemetry eBPF Instrumentation (Grafana, 2025-05)](https://grafana.com/blog/opentelemetry-ebpf-instrumentation-beyla-donation/), [OBI v1.0.0 릴리스](https://opentelemetry.io/blog/2026/obi-v1-release/)

<!-- TODO: OBI의 Java 지원 범위는 발표문 나열 목록으로만 판단했습니다. 공식 support matrix에서 Java route 탐지 가능 여부를 재확인해야 합니다. -->

### 2-3. 프로파일 — 트레이스와 다른 축

트레이스는 **내가 경계를 그은 구간**만 봅니다. 프로파일러는 반대로 일정 주기마다 모든 스레드의 스택을 찍습니다. 경계를 미리 그을 필요가 없으니, 1절의 "자식 스팬 없는 1.6초"에 답할 수 있는 유일한 신호입니다.

JVM에는 이미 JDK Flight Recorder(JFR)가 들어 있습니다. Oracle 문서는 상시 기록용 `default.jfc` 설정의 오버헤드를 **보통 1% 미만**, 더 자세한 프로파일링 기록을 **대부분의 애플리케이션에서 2% 미만**으로 적습니다. 상시로 켜둘 수 있다는 전제가 여기서 나옵니다. 다만 같은 문서가 "애플리케이션에 따라 다르다"고 덧붙입니다.

출처: [Flight Recorder Configurations (JDK 24)](https://docs.oracle.com/en/java/javase/24/jfapi/flight-recorder-configurations.html), [Troubleshoot Performance Issues Using Flight Recorder (JDK 17)](https://docs.oracle.com/en/java/javase/17/troubleshoot/troubleshoot-performance-issues-using-jfr.html)

표준화는 아직입니다. OpenTelemetry는 프로파일을 네 번째 신호로 추가하는 작업을 2026년 3월 public alpha로 공개했고, 공식 발표문이 **중요한 프로덕션 워크로드에 쓰지 말라**고 명시합니다. 프로덕션 수준 백엔드도 아직 나오지 않은 상태입니다. 즉 "상시 프로파일링"은 2026년 11월 현재 벤더 제품을 쓰거나 JFR을 직접 돌리는 쪽입니다.

출처: [OpenTelemetry Profiles Enters Public Alpha](https://opentelemetry.io/blog/2026/profiles-alpha)

---

## 3. 흐름 — 느린 API 하나를 좁혀 들어가는 순서

좁히는 단계가 정해져 있고, **몇 단계까지 자주 내려가는지가 APM 필요 여부를 결정합니다.**

```
1단계  골든 시그널      "주문 API p99가 2초다"            → day54
2단계  트레이스         "OrderService.place가 1.6초다"     → day78
3단계  프로파일         "place 안의 정규식 컴파일이 1.4초다"  → 여기부터 APM 영역
4단계  코드             Pattern을 static final로 올린다
```

1~2단계에서 끝나는 장애가 대부분이면 APM은 아직 필요 없습니다. **3단계를 분기마다 반복하고 있다면 그게 신호입니다.**

### 3-1. 에이전트가 붙은 뒤 생기는 것과 안 생기는 것

생깁니다 — HTTP 서버·클라이언트 스팬, JDBC 쿼리 스팬, Redis·Kafka 스팬, 커넥션 풀 메트릭, JVM 런타임 메트릭.

안 생깁니다 — **내 비즈니스 메서드의 경계와 도메인 속성.** 에이전트는 `OrderService`가 뭔지 모릅니다. 그 부분만 수동으로 얹습니다.

```java
// build.gradle: implementation 'io.opentelemetry.instrumentation:opentelemetry-instrumentation-annotations'
import io.opentelemetry.instrumentation.annotations.SpanAttribute;
import io.opentelemetry.instrumentation.annotations.WithSpan;

@Service
public class OrderService {

    @WithSpan("order.place")
    public OrderResult place(@SpanAttribute("order.user_id") Long userId,
                             @SpanAttribute("order.item_count") int itemCount) {
        // ... 생략
    }
}
```

`@WithSpan`은 애너테이션만 선언하고, 실제로 스팬을 만드는 주체는 에이전트입니다. 에이전트 없이 이 애너테이션만 붙이면 아무 일도 일어나지 않습니다. day74-bean-validation.md에서 본 구조와 같습니다 — 선언과 실행 주체가 분리되어 있고, 실행 주체가 없으면 선언은 주석입니다.

속성 카디널리티 기준은 day78에서 정리한 그대로입니다. 스팬은 집계 대상이 아니라 개별 기록이므로 `order.user_id` 같은 고유값을 넣어도 됩니다. 반면 다음 절에서 볼 **스팬 이름**은 정반대입니다.

---

## 4. 판단 — 언제 도입하고 언제 미루는가

### 4-1. 도입이 정당한 신호

- **코드를 고칠 수 없습니다.** 빌드가 안 되는 레거시 WAR, 소스가 없는 서드파티 애플리케이션. 이 경우 에이전트는 유일한 선택지입니다.
- **서비스 수 × 라이브러리 수가 사람 손을 넘었습니다.** 서비스 12개에 수동 계측을 넣고 유지하는 비용이 에이전트 요금보다 큽니다.
- **3단계를 반복합니다.** 메서드 단위까지 내려가는 조사가 분기마다 있습니다.
- **신호 간 이동이 수작업입니다.** 에러 하나를 보고 트레이스를 찾고 로그를 긁고 호스트 메트릭을 열기까지 사람이 네 번 복사·붙여넣기 합니다.

### 4-2. 도입을 미뤄야 하는 신호

- **아직 아무 질문도 하고 있지 않습니다.** 알림이 없거나 전부 무시되는 상태(day60-alert-fatigue.md)에서 APM을 붙이면 무시할 화면이 하나 늘어납니다.
- **서비스가 하나입니다.** 모놀리식 한 대에서 트레이스는 거의 자기 자신이고, 2단계의 가치가 작습니다. JFR을 직접 돌리는 쪽이 싸고 깊습니다.
- **샘플링·보존 정책을 정할 사람이 없습니다.** 이건 비용 문제가 아니라 통제 문제입니다. 다음 절이 그 이유입니다.

### 4-3. 대가 — 성능, 비용 구조, 종속

**성능.** Elastic이 공개한 자사 샘플 애플리케이션 벤치마크입니다. 합성 부하이고, Elastic 자신도 "지표일 뿐이며 다른 애플리케이션에 외삽하지 말라"고 명시합니다.

| 항목 | 에이전트 없음 | EDOT Java | Elastic APM Java 에이전트 |
|---|---:|---:|---:|
| 시작 시간 | 5.55s | 6.82s | 6.87s |
| 요청 지연 p95 | 1.96ms | 2.06ms | 2.08ms |
| 전체 CPU 사용률 | 53.82% | 54.25% | 56.92% |
| 최대 힙 사용량 | 436.71MB | 478.46MB | 573.92MB |

출처: [Performance overhead of the Elastic Distribution of OpenTelemetry Java](https://www.elastic.co/docs/reference/opentelemetry/edot-sdks/java/overhead)

지연은 0.1ms 수준이지만 **시작 시간이 1.3초 늘어납니다.** 23% 증가입니다. day82-health-check.md에서 다룬 `health_check_grace_period`를 빠듯하게 잡아둔 환경이라면, 에이전트를 붙인 배포가 무한 교체 루프의 방아쇠가 될 수 있습니다. OpenTelemetry 공식 문서도 단일 오버헤드 수치는 제시할 수 없다고 하면서, 스팬 양이 주된 변수이고 JDBC·Redis 계측이 스팬을 많이 만드는 대표적 발생원이라고 적습니다.

출처: [OpenTelemetry Java agent Performance](https://opentelemetry.io/docs/zero-code/java/agent/performance/)

**비용 구조.** 요금이 트래픽이 아니라 **호스트 수와 스팬 양**에 붙습니다. Datadog APM 기준입니다.

- APM 호스트 월 $31 (Pro $35, Continuous Profiler 포함 Enterprise $40)
- 호스트당 인덱싱 스팬 100만 개 + 수집 스팬 150GB 포함
- 초과 시 수집 스팬 GB당 $0.10, 인덱싱 스팬 100만 개당 $1.70

출처: [Datadog APM Tracing and Profiler Billing](https://docs.datadoghq.com/account_management/billing/apm_tracing_profiler/) (리전·플랜별로 다릅니다)

두 줄을 눈여겨봐야 합니다. 첫째, 호스트는 **매시간 측정**되고 월말에 상위 1%를 버린 값으로 계산됩니다. 같은 문서가 이걸 "9번째로 높은 시간당 측정값"(2월은 8번째)과 "99 백분위" 두 표현으로 설명합니다. 결과적으로 몇 시간짜리 오토스케일 급증은 과금에 거의 안 걸리고, 하루 넘게 유지되는 증설은 그대로 걸립니다. 둘째, Datadog은 호스트당 에이전트 하나를 권장하고 **컨테이너마다 에이전트를 띄우면 컨테이너 하나하나가 호스트로 계산됩니다.** 사이드카 패턴으로 깔면 청구서가 파드 수를 따라갑니다. 쿠버네티스에서는 노드가 호스트이고 파드는 아닙니다.

**종속.** OpenTelemetry를 쓰면 계측 코드의 종속은 사라집니다. 남는 것은 백엔드입니다. 대시보드, 알림 규칙, 저장된 쿼리, 샘플링 설정은 전부 제품 고유 형식이고, 이게 실제 전환 비용의 대부분입니다. 에이전트를 OTel로 통일해 두는 선택은 "언제든 옮길 수 있다"가 아니라 **"옮길 때 애플리케이션은 안 건드린다"** 까지입니다.

---

## 5. 예제 — 에이전트만 붙인 상태의 함정

에이전트를 붙이고 화면을 열었는데 엔드포인트 목록에 항목이 하나뿐입니다. 이름은 `GET`입니다. 또는 전부 `/api/**` 하나로 뭉쳐 있습니다.

원인은 **스팬 이름의 저카디널리티 규칙**입니다. OpenTelemetry HTTP 서버 스팬 규약은 이름을 메서드 + route 템플릿으로 정하고, **저카디널리티 route를 구할 수 없으면 이름을 `{method}` 하나로 둬야 한다(SHOULD)** 고 규정합니다. URL 경로로 대체하지 않습니다. 메트릭 규약은 더 못을 박습니다 — 프레임워크가 지원하지 않으면 `http.route`를 채우지 말라고, URI 경로는 route를 대체할 수 **없다**고 적습니다.

출처: [Semantic conventions for HTTP spans](https://opentelemetry.io/docs/specs/semconv/http/http-spans/), [How to Name Your Spans](https://opentelemetry.io/blog/2025/how-to-name-your-spans/)

Spring MVC에서 `@GetMapping("/orders/{orderId}")`를 쓰면 `RequestMappingHandlerMapping`이 패턴을 노출하므로 route가 정상적으로 나옵니다. 문제는 패턴을 스스로 무의미하게 만들어 둔 코드입니다.

### 5-1. route를 뭉개는 코드 ❌

```java
// ❌ 매핑 패턴이 /api/** 하나 — 모든 요청의 http.route가 "/api/**"로 동일합니다
@RestController
public class LegacyApiController {

    private final OrderService orderService;
    private final PaymentService paymentService;

    public LegacyApiController(OrderService orderService, PaymentService paymentService) {
        this.orderService = orderService;
        this.paymentService = paymentService;
    }

    @RequestMapping("/api/**")
    public ResponseEntity<?> dispatch(HttpServletRequest request) {
        String path = request.getRequestURI();
        if (path.startsWith("/api/orders")) {
            return ResponseEntity.ok(orderService.findAll());
        }
        if (path.startsWith("/api/payments")) {
            return ResponseEntity.ok(paymentService.findAll());
        }
        return ResponseEntity.notFound().build();
    }
}
```

결제가 느려져도 주문과 같은 버킷에 섞여 평균이 희석됩니다. 엔드포인트별 지연이라는 축 자체가 사라집니다.

### 5-2. 개선한 코드 ✔️

```java
// ✔️ 매핑을 실제 경로로 쪼개면 http.route가 엔드포인트별로 갈립니다
@RestController
@RequestMapping("/api")
public class OrderApiController {

    private final OrderService orderService;

    public OrderApiController(OrderService orderService) {
        this.orderService = orderService;
    }

    @GetMapping("/orders")
    public List<OrderSummary> findOrders() {
        return orderService.findAll();
    }

    @GetMapping("/orders/{orderId}")
    public OrderDetail findOrder(@PathVariable Long orderId) {
        return orderService.findById(orderId);
    }
}
```

당장 쪼갤 수 없다면 현재 서버 스팬의 이름을 직접 바꿀 수는 있습니다.

```java
io.opentelemetry.api.trace.Span.current().updateName("GET /api/orders");
```

단 이건 스팬 **이름**만 바꿉니다. `http.route` 속성은 그대로이므로, 백엔드가 엔드포인트를 이름으로 묶는지 속성으로 묶는지 확인해야 효과가 있습니다. 근본 해법은 매핑을 쪼개는 쪽입니다.

<!-- TODO: 주요 APM 백엔드(Datadog, Grafana, Elastic)가 엔드포인트 그룹핑에 스팬 이름과 http.route 중 무엇을 쓰는지는 제품별로 다릅니다. 각 제품 문서에서 확인이 필요합니다. -->

---

## 6. 함정

### 6-1. 메이저 업그레이드가 대시보드와 알림을 조용히 깨뜨립니다

- **증상**: 에이전트 버전을 올린 뒤 패널이 "No data"로 비고, 알림은 울리지 않습니다. 애플리케이션은 정상입니다.
- **원인**: 속성 이름과 단위가 바뀝니다. OpenTelemetry Java 에이전트 3.0(2026년 10월 목표, 2.32.0에서 미리보기 가능)은 DB·code 규약을 기본값으로 올리면서 `db.system` → `db.system.name`, `code.namespace`+`code.function` → `code.function.name`으로 바꾸고, **커넥션 풀 지속 시간 메트릭의 단위를 밀리초에서 초로** 변경합니다. Kafka 스팬 이름 순서도 바뀌고, Hibernate·Hystrix·Twilio 계측은 기본 비활성화됩니다. Zipkin 익스포터는 제거됩니다.
- **해법**: 2.32.0에서 미리보기 플래그를 켜 스테이징에 먼저 올리고, 속성 이름을 참조하는 대시보드·알림·샘플링 규칙을 목록으로 뽑아 대조합니다. 단위가 바뀐 메트릭은 이름이 같아서 "비는" 게 아니라 **1000배 작은 값으로 보입니다** — 임계값 기반 알림이 영구히 침묵합니다.

출처: [The OpenTelemetry Java agent 3.0 is almost here](https://opentelemetry.io/blog/2026/java-agent-3.0-preview)

### 6-2. 에이전트가 시크릿을 백엔드로 내보냅니다

- **증상**: APM 화면의 쿼리나 요청 헤더에 토큰·비밀번호가 보입니다. 백엔드는 외부 SaaS입니다.
- **원인**: SQL 리터럴은 기본 보호됩니다 — `otel.instrumentation.common.db-statement-sanitizer.enabled` 기본값이 `true`이고, `where password="secret"`은 `where password=?`로 기록됩니다. 문제는 **내가 직접 켜는 것들**입니다. 요청·응답 헤더 캡처, 바디 캡처, 커스텀 속성에는 그런 기본 보호가 없습니다.
- **해법**: 헤더 캡처 설정에 `Authorization`·`Cookie`를 넣지 않습니다. 커스텀 속성은 화이트리스트로만 추가합니다. sanitizer를 끄는 설정은 로컬에서만 씁니다.

출처: [Agent instrumentation configuration](https://opentelemetry.io/docs/zero-code/java/agent/instrumentation/)

### 6-3. 비용이 트래픽과 무관하게 움직입니다

- **증상**: 트래픽이 줄었는데 청구액이 올랐습니다.
- **원인**: 과금 축이 호스트 수와 스팬 양입니다. 파드를 잘게 쪼개면서 사이드카로 에이전트를 깔면 호스트 수가 파드 수가 됩니다. 배치 작업이 JDBC 스팬을 수백만 개 뿜으면 수집 GB가 뜁니다.
- **해법**: 에이전트 배치 단위를 노드로 고정합니다. 배치·크론 애플리케이션은 샘플링 비율을 따로 낮추거나 시끄러운 계측만 끕니다 — `-Dotel.instrumentation.jdbc.enabled=false` 처럼 계측 단위로 비활성화할 수 있습니다. 호스트 수 메트릭에 알림을 걸어 두는 쪽이 월말 청구서보다 빠릅니다.

### 6-4. 프로파일러가 다른 SKU입니다

- **증상**: APM을 샀는데 3절의 3단계를 할 수 없습니다.
- **원인**: 상시 프로파일링은 보통 상위 플랜입니다. Datadog은 Continuous Profiler를 Enterprise($40/호스트)에 포함시키고, 호스트당 프로파일 대상 컨테이너 4개까지 포함, 추가 컨테이너는 호스트 기준 $2씩 가산합니다.
- **해법**: 도입 검토 단계에서 **3단계를 하려는 것인지 2단계까지인지 먼저 정합니다.** 2단계까지라면 OpenTelemetry + Tempo로 충분하고, 3단계가 목적이면 JFR을 직접 돌려보고 그 결과로 플랜을 고릅니다. 1~2% 오버헤드로 상시 기록이 가능하니 유료 계약 전에 실측할 수 있습니다.

### 6-5. 에이전트를 끄는 경로가 없습니다

- **증상**: 장애 중에 에이전트가 원인 후보로 올라왔지만 확인할 방법이 없습니다.
- **원인**: 에이전트는 애플리케이션과 같은 프로세스에서 돕니다. 바이트코드를 고치고, 메모리를 쓰고, 네트워크로 내보냅니다. 장애 원인이 될 수 있는 컴포넌트인데 배포 설정에 상수로 박혀 있습니다.
- **해법**: `-javaagent` 부착 여부를 환경변수로 분기해 두고, 에이전트 없이 뜨는 경로를 **실제로 한 번 배포해 봅니다.** 끌 수 있다는 걸 장애 때 처음 시험하면 안 됩니다. 에이전트 버전도 애플리케이션 버전처럼 롤백 가능한 대상으로 관리합니다.

---

## 7. 정리

APM 도입 판단은 세 질문으로 압축됩니다.

1. **계측을 사람이 넣을 수 있는 규모인가** — 아니면 에이전트가 유일한 길입니다
2. **조사가 스팬 아래로 자주 내려가는가** — 그렇다면 프로파일이 필요하고, 그게 APM의 고유 영역입니다
3. **호스트 수와 스팬 양을 통제할 사람이 있는가** — 없으면 비용이 먼저 터집니다

반대로 **"관측성이 부족해서"** 는 도입 근거가 아닙니다. 그 상태에서 에이전트를 붙이면 아무도 안 보는 데이터가 돈을 쓰면서 쌓입니다. 질문이 먼저입니다.

## 8. 참고자료

- [OpenTelemetry Java agent — Performance](https://opentelemetry.io/docs/zero-code/java/agent/performance/)
- [OpenTelemetry Java agent 3.0 preview](https://opentelemetry.io/blog/2026/java-agent-3.0-preview)
- [OpenTelemetry Profiles Public Alpha](https://opentelemetry.io/blog/2026/profiles-alpha)
- [Semantic conventions for HTTP spans](https://opentelemetry.io/docs/specs/semconv/http/http-spans/)
- [Datadog APM Tracing and Profiler Billing](https://docs.datadoghq.com/account_management/billing/apm_tracing_profiler/)
- [Elastic — EDOT Java 오버헤드](https://www.elastic.co/docs/reference/opentelemetry/edot-sdks/java/overhead)
- [Oracle — Flight Recorder Configurations](https://docs.oracle.com/en/java/javase/24/jfapi/flight-recorder-configurations.html)
- [OpenTelemetry eBPF Instrumentation v1.0.0](https://opentelemetry.io/blog/2026/obi-v1-release/)
- 관련 챕터: day54-golden-signals.md, day66-prometheus-basics.md, day72-dashboard-design.md, day78-distributed-tracing.md, day60-alert-fatigue.md, day82-health-check.md

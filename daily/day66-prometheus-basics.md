# Prometheus는 왜 끌어가고, 그 방식이 내 계측을 어떻게 제약하는가

> 이 문서가 답할 질문: **Prometheus는 내 애플리케이션의 숫자를 어떤 방식으로 가져가고, 그 방식이 내가 쓸 수 있는 메트릭 타입과 쿼리를 어떻게 제약하는가?**
>
> 분류: 기술이해형. "Prometheus 설치법"이 아니라 **Pull이라는 선택과 네 가지 메트릭 타입이 원래 어떤 문제를 풀려고 생긴 것인지**를 묻습니다. 여러 출처에서 공통으로 등장하는 "왜 이렇게 설계했는가" 설명을 찾는 관점으로 조사했습니다.
>
> 기준: Prometheus 3.15 (최신 릴리스 3.15.1, 2026-10-21 확인) · Spring Boot 4.1 Actuator 문서. 무엇을 지표로 잴지는 `day54-golden-signals.md`, 언제 사람을 부를지는 `day60-alert-fatigue.md`에서 다뤘습니다. 이 문서는 **그 숫자가 어떻게 수집되고 어떤 타입으로 저장되는지**만 다룹니다.

## 1. 핵심 개념 — Prometheus가 저장하는 것은 "숫자 시계열" 하나뿐입니다

Prometheus의 데이터 모델은 놀랄 만큼 작습니다. 저장 단위는 `메트릭 이름 + 라벨 집합`으로 식별되는 시계열이고, 그 안에 `(타임스탬프, float64)` 샘플이 쌓입니다. 끝입니다. 문자열 값도, 중첩 구조도, 이벤트 하나하나의 기록도 없습니다.

Prometheus는 이 시계열을 **주기적으로 타깃의 HTTP 엔드포인트를 긁어와서(scrape)** 채웁니다. 애플리케이션이 보내주는 게 아니라 Prometheus가 가지러 옵니다. 기본 주기는 1분(`scrape_interval: 1m`), 기본 경로는 `/metrics`, 기본 타임아웃은 10초입니다([Configuration](https://prometheus.io/docs/prometheus/latest/configuration/configuration/)).

> 이 두 가지 — 숫자만 저장한다는 것과 주기적으로 긁어온다는 것 — 를 모르면 어떻게 되는지가 이 챕터의 전부입니다. 긁어오는 순간들 **사이에 일어난 일은 영원히 사라집니다.** 그래서 1분 사이에 요청이 300건 들어왔다는 사실을 "현재 요청 수"라는 숫자로 재면 그 300은 복원할 방법이 없습니다. 복원이 되게 만드는 장치가 메트릭 타입이고, 특히 Counter입니다. 메트릭 타입은 저장 포맷이 아니라 **샘플링 손실을 어떻게 다룰 것인가에 대한 합의**입니다.

## 2. Pull — 왜 가지러 오는가

### 2-1. 공식 문서가 드는 이유는 생각보다 소박합니다

Prometheus FAQ가 pull의 장점으로 드는 것은 셋입니다: 필요할 때 모니터링 인스턴스를 더 띄울 수 있다(개발 중 노트북에서도), 타깃이 죽었는지 판정하기 쉽다, 브라우저로 열어서 직접 확인할 수 있다. 그러면서 **"pull이 push보다 약간 낫지만 모니터링 시스템을 고르는 주요 기준으로 볼 일은 아니다"**라고 스스로 못을 박습니다([FAQ](https://prometheus.io/docs/introduction/faq/)). 종교가 아니라는 뜻입니다. 그런데 실무에서 체감하는 차이는 두 번째 항목에 거의 다 들어 있습니다.

### 2-2. Pull이 공짜로 주는 것 — `up`

Prometheus는 scrape 할 때마다 타깃마다 메트릭을 자동으로 만들어 넣습니다([Jobs and instances](https://prometheus.io/docs/concepts/jobs_instances/)).

| 메트릭 | 의미 |
|---|---|
| `up` | scrape 성공이면 1, 실패면 0 |
| `scrape_duration_seconds` | scrape에 걸린 시간 |
| `scrape_samples_scraped` | 타깃이 노출한 샘플 개수 |
| `scrape_series_added` | 이번 scrape에서 새로 등장한 시계열 수(근사) |

`up`이 핵심입니다. Push 모델에서 "데이터가 안 온다"는 두 가지를 뜻합니다 — 프로세스가 죽었거나, 보낼 게 없었거나. 구분할 수 없습니다. Pull에서는 **Prometheus가 가지러 갔는데 실패했다**는 사실이 남으므로 `up == 0`이 그대로 가용성 신호가 됩니다. 가장 먼저 만들 알림이 `up == 0`인 이유입니다.

`scrape_series_added`가 계속 양수라면 매 scrape마다 새 시계열이 생긴다는 뜻이고, 그건 §6-1의 카디널리티 폭발이 진행 중이라는 신호입니다.

### 2-3. Pull이 거는 제약 — 짧게 사는 프로세스

Pull은 **타깃이 scrape 당할 때까지 살아 있어야** 성립합니다. 30초 돌고 끝나는 배치 잡은 `/metrics`를 노출해도 아무도 긁어가지 않습니다. 이때 쓰는 게 Pushgateway인데, 공식 문서는 사용 조건을 꽤 좁게 적어 뒀습니다([When to use the Pushgateway](https://prometheus.io/docs/practices/pushing/)).

- 유효한 용도는 거의 **서비스 수준 배치 잡**(특정 머신에 묶이지 않는 잡)의 결과를 남기는 것뿐입니다.
- Pushgateway 자체가 단일 장애점이자 병목이 됩니다.
- scrape마다 얻던 `up` 기반 헬스 모니터링이 사라집니다.
- **한 번 push된 시계열을 스스로 잊지 않습니다.** API로 삭제하기 전까지 계속 노출하므로, 인스턴스 이름을 바꾸거나 잡을 없애면 유령 시계열이 남습니다.

즉 "push가 편해서" 쓰는 물건이 아닙니다. Spring Boot에서 배치 잡에만 켤 때는 `io.prometheus:prometheus-metrics-exporter-pushgateway` 의존성을 넣고 `management.prometheus.metrics.export.pushgateway.enabled=true`로 켭니다([Spring Boot 4.1 — Metrics](https://docs.spring.io/spring-boot/reference/actuator/metrics.html)).

## 3. 메트릭 타입 — 네 개가 아니라 두 개의 질문입니다

타입은 Counter·Gauge·Histogram·Summary 네 개지만, 고르는 기준은 질문 두 개입니다.

**질문 1: 이 값은 줄어들 수 있는가?**

| | Counter | Gauge |
|---|---|---|
| 값의 성질 | 누적. 증가만, 재시작 시 0으로 리셋 | 올라가고 내려감 |
| 예 | 처리한 요청 수, 발생한 예외 수 | 현재 동시 요청 수, 큐 길이, 메모리 사용량 |
| 샘플링 손실 | **없음** — 두 샘플의 차이가 그 사이의 증가분 | 있음 — scrape 사이의 변화는 사라짐 |
| 쿼리 | `rate()`, `increase()` | 그대로, 또는 `avg_over_time()` |

Counter의 설계 의도가 여기서 드러납니다. **값을 누적시켜 두면 두 샘플의 차이만으로 그 사이에 벌어진 일을 복원할 수 있습니다.** 그래서 1분 간격으로 긁어도 요청 수를 놓치지 않습니다. 반대로 "지난 1분간 요청 수"를 Gauge로 재면, scrape가 한 번 실패하면 그 1분은 그냥 없어집니다.

공식 instrumentation 가이드의 표현이 명확합니다. **값이 내려갈 수 있으면 Gauge, 아니면 Counter**이고, **Gauge에는 절대 `rate()`를 쓰지 않습니다**([Instrumentation](https://prometheus.io/docs/practices/instrumentation/)).

**질문 2: 분포가 필요한가 — 그리고 그 분포를 합칠 필요가 있는가?**

평균 응답시간은 거의 항상 거짓말입니다. 그래서 분포를 재는 타입이 둘 있습니다.

| | Histogram | Summary |
|---|---|---|
| 계산 위치 | 버킷만 노출, 분위수는 **서버에서** `histogram_quantile()` | **애플리케이션 안에서** φ-분위수 계산 후 노출 |
| 노출 시계열 | `_bucket{le="..."}`, `_sum`, `_count` | `{quantile="..."}`, `_sum`, `_count` |
| 인스턴스 간 합산 | 가능 (버킷 경계가 같으면) | **불가능** |
| 분위수 변경 | 쿼리에서 언제든 | 계측 코드를 고치고 재배포 |
| 오차의 방향 | 관측값 축 — 버킷 폭만큼 | φ 축 — 0.95±0.01 같은 형태 |

핵심은 **합산 가능성**입니다. 공식 histogram 가이드는 Summary를 두고 그냥 "Not aggregatable"이라고 적습니다([Histograms and summaries](https://prometheus.io/docs/practices/histograms/)). 인스턴스가 12대면 Summary로는 전체 서비스의 p99를 구할 방법이 없습니다. 그래서 권고 순서가 이렇습니다 — **네이티브 히스토그램이 가능하면 그것, 아니면 클래식 히스토그램, 집계가 정말 필요 없을 때만 Summary.**

`_bucket`의 `le` 라벨은 **누적** 상한입니다. `le="0.5"`는 0.5초 이하의 모든 관측을 셉니다. `_count`는 `le="+Inf"` 버킷과 같은 값입니다([Metric types](https://prometheus.io/docs/concepts/metric_types/)).

### 3-1. 네이티브 히스토그램

클래식 히스토그램의 문제는 버킷 경계를 계측 시점에 못 박는다는 점입니다. 응답시간이 30ms 대역인데 버킷이 `[0.1, 0.5, 1, 5]`면 p99가 전부 "0.1초 이하"로만 보입니다. 네이티브 히스토그램은 경계를 미리 정하지 않고 지수 버킷을 동적으로 쓰며, **서로 항상 합산 가능합니다.**

버전 주의가 필요합니다. Prometheus 3.9부터 `native-histograms` 피처 플래그는 아무 일도 하지 않고, scrape 설정의 `scrape_native_histograms` 옵션(3.8 추가)으로 켭니다. 클래식 버킷을 함께 받으려면 `always_scrape_classic_histograms`를 씁니다([Migration guide](https://prometheus.io/docs/prometheus/latest/migration/)).

## 4. 흐름 — 코드에서 쿼리까지

### 4-1. 코드로 보는 구성

Spring Boot에서는 Micrometer가 Prometheus 포맷으로 번역해 줍니다. Actuator + `micrometer-registry-prometheus`가 런타임 클래스패스에 있으면 레지스트리가 자동 구성되고, `/actuator/prometheus`가 생깁니다. 단 **기본 노출이 아니므로 직접 열어야 합니다.**

```yaml
management:
  endpoints:
    web:
      exposure:
        include: health,prometheus
  metrics:
    distribution:
      percentiles-histogram:
        order.processing: true          # 서버 집계 가능한 버킷을 노출
      maximum-expected-value:
        order.processing: 10s           # 버킷 개수를 줄임
```

```java
@Service
public class OrderService {

    private final Counter rejectedCounter;
    private final Timer processingTimer;
    private final BlockingQueue<OrderCommand> pendingQueue = new LinkedBlockingQueue<>(1000);

    public OrderService(MeterRegistry registry) {
        // ❌가 아닌 이유: 거절은 줄어들지 않습니다 → Counter
        this.rejectedCounter = Counter.builder("order.rejected")
                .description("결제 검증에서 거절된 주문 수")
                .tag("reason", "payment_declined")   // 값의 종류가 유한한 라벨만
                .register(registry);

        this.processingTimer = Timer.builder("order.processing")
                .description("주문 처리 소요 시간")
                .register(registry);

        // 큐 길이는 올라가고 내려갑니다 → Gauge.
        // pendingQueue는 이 빈이 강한 참조를 들고 있어야 합니다 (§7 참고)
        Gauge.builder("order.pending.size", pendingQueue, Collection::size)
                .register(registry);
    }

    public OrderResult place(OrderCommand command) {
        return processingTimer.record(() -> {
            if (!command.paymentVerified()) {
                rejectedCounter.increment();
                return OrderResult.rejected();
            }
            return OrderResult.accepted(command.orderId());
        });
    }
}
```

### 4-2. 노출되는 시계열

`/actuator/prometheus`를 열면 이렇게 보입니다. Prometheus 레지스트리는 시간을 **초** 단위로 바꾸고 이름을 스네이크 케이스로 바꿉니다.

```
# 이름이 order.processing → order_processing_seconds
order_processing_seconds_bucket{le="0.1"} 842
order_processing_seconds_bucket{le="0.5"} 1193
order_processing_seconds_bucket{le="+Inf"} 1204
order_processing_seconds_sum 97.41
order_processing_seconds_count 1204
order_processing_seconds_max 3.02
order_rejected_total{reason="payment_declined"} 37
order_pending_size 12
```

`_max`는 Micrometer가 추가하는 **시간 창 최대값**이고 Counter가 아니라 Gauge입니다. 새 창이 시작되고 기록이 없으면 0으로 떨어집니다([Micrometer — Timers](https://docs.micrometer.io/micrometer/reference/concepts/timers.html)). Prometheus 표준 히스토그램에는 없는 시계열이라 `rate()`를 걸면 안 됩니다.

### 4-3. scrape 설정

```yaml
global:
  scrape_interval: 15s        # 기본값은 1m. 줄이면 저장량과 부하가 비례해서 늘어납니다
  evaluation_interval: 15s

scrape_configs:
  - job_name: "order-service"
    metrics_path: "/actuator/prometheus"
    static_configs:
      - targets: ["10.0.1.21:8080", "10.0.1.22:8080"]
```

`job_name`은 `job` 라벨이 되고, 각 타깃의 `host:port`는 `instance` 라벨이 됩니다. 이 두 라벨은 Prometheus가 붙여 주므로 **애플리케이션 코드에서 인스턴스 식별 라벨을 직접 달 필요가 없습니다.**

### 4-4. 쿼리

```promql
# 초당 거절 건수 — Counter는 반드시 rate()를 거칩니다
rate(order_rejected_total[5m])

# 서비스 전체 p99 — 버킷을 먼저 합산하고 분위수를 계산합니다
histogram_quantile(0.99, sum by (le) (rate(order_processing_seconds_bucket[5m])))

# 평균 처리 시간 — _sum / _count. 둘 다 Counter라 양쪽에 rate()
rate(order_processing_seconds_sum[5m]) / rate(order_processing_seconds_count[5m])
```

`rate()`는 **카운터 리셋을 자동 보정**합니다. 배포로 프로세스가 재시작해 0으로 돌아가도 그래프에 음수 절벽이 생기지 않습니다. 대신 구간 양끝으로 **외삽**하기 때문에 `increase()`의 결과가 정수가 아닐 수 있습니다 — 공식 문서가 명시하는 동작이니 버그로 의심하지 마세요([Functions](https://prometheus.io/docs/prometheus/latest/querying/functions/)).

## 5. 예제 — 나쁜 계측에서 좋은 계측으로

### 5-1. 흔히 보는 코드 ❌

```java
@Service
public class PaymentService {

    private final MeterRegistry registry;
    private final AtomicInteger requestCount = new AtomicInteger();

    public void pay(PaymentCommand command) {
        // ❌ 1. 셀 수 있는 걸 Gauge로 재고, 매 분 리셋합니다
        Gauge.builder("payment.request.count", requestCount, AtomicInteger::get)
                .register(registry);
        requestCount.incrementAndGet();

        // ❌ 2. 메트릭 이름을 코드로 조립합니다 → 시계열 이름이 무한 증식
        registry.counter("payment." + command.method() + ".attempt").increment();

        // ❌ 3. 라벨에 사용자 ID와 원본 URI를 넣습니다 → 카디널리티 폭발
        registry.timer("payment.latency",
                "userId", command.userId(),
                "uri", command.requestUri()).record(doPay(command));
    }
}
```

1번은 요청 수를 복원 불가능하게 만듭니다. 2번은 `payment_card_attempt`, `payment_kakao_attempt`처럼 이름이 갈라져서 `sum()`으로 전체 시도 수를 구할 수 없습니다. 공식 네이밍 가이드가 **"라벨 이름을 메트릭 이름에 넣지 말라"**고 적는 이유입니다([Naming](https://prometheus.io/docs/practices/naming/)). 3번은 §6-1의 함정입니다.

### 5-2. 개선한 코드 ✔️

```java
@Service
public class PaymentService {

    private final MeterRegistry registry;

    public PaymentService(MeterRegistry registry) {
        this.registry = registry;
    }

    public void pay(PaymentCommand command) {
        Timer.Sample sample = Timer.start(registry);
        String outcome = "success";
        try {
            doPay(command);
        } catch (PaymentDeclinedException e) {
            outcome = "declined";
            throw e;
        } finally {
            // ✔️ 이름은 리터럴로 고정하고, 갈라지는 축만 라벨로 뺍니다.
            //    같은 이름+라벨이면 register()는 기존 미터를 돌려줍니다
            sample.stop(Timer.builder("payment.latency")
                    .publishPercentileHistogram()                // 합산 가능한 버킷
                    .tag("method", command.method().name())      // enum — 가짓수가 유한
                    .tag("outcome", outcome)
                    .register(registry));
        }
    }
}
```

이름은 `payment_latency_seconds` 하나로 고정하고, 갈라지는 축은 전부 라벨로 뺐습니다. 이제 `sum by (outcome) (rate(payment_latency_seconds_count[5m]))` 한 줄로 성공/거절 비율이 나옵니다. 그리고 `method`는 enum이라 라벨 값의 가짓수가 코드에 의해 상한이 잡혀 있습니다.

## 6. 함정

### 6-1. 라벨에 유한하지 않은 값을 넣습니다

- **증상**: 처음엔 잘 돌다가 몇 주 뒤 Prometheus 메모리가 꾸준히 늘고, 쿼리가 느려지고, 결국 OOM으로 재시작합니다. `scrape_series_added`가 계속 양수입니다.
- **원인**: 라벨 조합 하나가 시계열 하나입니다. 공식 문서 표현대로 **"각 라벨 집합은 RAM·CPU·디스크·네트워크 비용이 드는 추가 시계열"**입니다. 사용자 ID, 이메일, 주문 번호, 정규화하지 않은 URI(`/orders/10294`), 예외 메시지를 라벨에 넣으면 상한이 없습니다.
- **해법**: 라벨 값의 가짓수에 **코드 수준의 상한**이 있는지 확인합니다. enum, HTTP 상태 코드, 경로 템플릿(`/orders/{id}`)은 안전하고 식별자는 아닙니다. 공식 가이드의 경험 법칙은 **메트릭 하나의 카디널리티를 10 미만**으로, 100을 넘거나 넘을 수 있으면 대안을 찾으라는 것입니다. 개별 식별자로 추적할 일은 메트릭이 아니라 로그·트레이스의 일입니다(`day42-structured-log-trace-id.md`).

### 6-2. `rate()` 구간을 scrape 간격보다 짧게 줍니다

- **증상**: 그래프가 비거나 중간중간 끊깁니다. 특히 Prometheus 2.x에서 3.x로 올린 직후 서브쿼리를 쓴 패널이 빕니다.
- **원인**: `rate()`는 구간 안에 최소 두 샘플이 필요합니다. `scrape_interval: 1m`인데 `[1m]`을 주면 샘플이 하나뿐일 수 있습니다. 게다가 Prometheus 3부터 **구간 선택자가 왼쪽 열림·오른쪽 닫힘**으로 바뀌어서 왼쪽 경계에 정확히 걸친 샘플이 빠집니다. 공식 문서는 `foo[1m:1m]` 같은 서브쿼리가 점 두 개가 아니라 하나만 반환할 수 있다고 적습니다.
- **해법**: 구간을 **scrape 간격의 4배 이상**으로 둡니다(1분 간격이면 `[5m]`). 서브쿼리는 창을 넓힙니다(`foo[2m:1m]`).

### 6-3. 분위수를 평균 냅니다

- **증상**: 인스턴스를 늘렸는데 p99 그래프가 오히려 낮아지고 평탄해집니다. 실제 사용자 체감과 안 맞습니다.
- **원인**: `avg(payment_latency_seconds{quantile="0.99"})`처럼 분위수를 평균 낸 겁니다. 공식 문서가 이 쿼리에 **"BAD!"**를 붙이고 **"분위수를 평균 내면 통계적으로 무의미한 값이 나온다"**고 적습니다. 분위수는 평균 가능한 양이 아닙니다.
- **해법**: `histogram_quantile(0.99, sum by (le) (rate(..._bucket[5m])))`으로 **버킷을 먼저 합산**하고 분위수를 계산합니다. 즉 Summary(`publishPercentiles`)를 쓰면 이 해법이 불가능하므로, 여러 인스턴스를 합쳐 볼 거면 처음부터 `percentiles-histogram`을 켭니다.

### 6-4. Micrometer Gauge의 대상이 GC 됩니다

- **증상**: 배포 직후 몇 분은 값이 나오다가 `NaN`이 되거나 시계열이 사라집니다.
- **원인**: Micrometer Gauge는 관측 대상을 **약한 참조(weak reference)로만** 잡습니다. GC를 막지 않기 위한 설계입니다. 지역 변수로 만든 컬렉션을 Gauge에 걸면 수집되고, 레지스트리는 `NaN` 또는 아무것도 보고하지 않게 됩니다([Micrometer — Gauges](https://docs.micrometer.io/micrometer/reference/concepts/gauges.html)).
- **해법**: 관측 대상을 **빈의 필드로 두어 강한 참조를 유지**합니다. 그리고 Micrometer 문서의 경고를 그대로 따릅니다 — **"Counter로 셀 수 있는 것을 Gauge로 재지 말 것."**

### 6-5. Prometheus 3으로 올린 뒤 `le="1"` 쿼리가 안 맞습니다

- **증상**: 2.x에서 잘 돌던 패널이 3.x에서 빈 결과를 냅니다. 대시보드 일부만 깨집니다.
- **원인**: Prometheus 3부터 `le`와 `quantile` 라벨 값이 OpenMetrics 정규형으로 정규화됩니다. `le="1"`이 `le="1.0"`이 됩니다. 정수로 적어 둔 매처가 전부 빗나갑니다. 같은 릴리스에서 **Content-Type 헤더가 없거나 인식 불가면 scrape가 실패**하도록 바뀌었고(필요하면 `fallback_scrape_protocol`), 타깃 라벨에 기본 포트를 더 이상 붙이지 않습니다.
- **해법**: 업그레이드 전에 `le=`·`quantile=` 리터럴 매처를 전수 검색해 소수점 형태로 고칩니다. 메트릭 이름 검증을 예전처럼 두려면 `metric_name_validation_scheme: legacy`를 씁니다.

### 6-6. 타깃을 내렸는데 그래프에 마지막 값이 계속 남습니다

- **증상**: 서버를 내린 뒤에도 메모리 사용량 그래프가 5분간 평평하게 이어집니다. 알림이 늦게 풀립니다.
- **원인**: Prometheus는 쿼리 시점 기준으로 **기본 5분(`--query.lookback-delta`) 안의 가장 최신 샘플**을 씁니다. 정상적으로는 타깃이 사라지면 곧 stale 마커가 붙어 그 시점부터 값이 안 나옵니다. 그런데 **익스포터가 샘플에 자기 타임스탬프를 직접 붙이면** 동작이 달라서, 노출이 끊긴 뒤에도 마지막 값이 기본 5분간 유지됩니다.
- **해법**: 가용성은 값의 유무로 판단하지 말고 `up`으로 판단합니다. 타임스탬프를 직접 붙이는 익스포터라면 `track_timestamps_staleness` 설정을 확인합니다.

## 7. 정리

Pull과 메트릭 타입은 별개의 주제가 아니라 같은 전제에서 나옵니다. **주기적으로 숫자 하나씩만 긁어간다**는 전제입니다.

- scrape 사이는 사라집니다. 셀 것은 **누적 Counter**로 두고 `rate()`로 복원합니다. Gauge로 세면 복원이 안 됩니다
- Pull이 주는 가장 값진 것은 `up`입니다. 첫 알림은 여기서 시작합니다
- Pushgateway는 "push가 편해서" 쓰는 게 아닙니다. 서비스 수준 배치 잡 전용이고, 넣은 시계열을 스스로 잊지 않습니다
- 분포는 **합산할 수 있는 형태로** 재야 의미가 있습니다. Summary는 합산 불가이고, 분위수 평균은 통계적으로 무의미합니다
- 라벨 값의 가짓수에 코드 수준 상한이 없으면 그건 메트릭이 아니라 로그로 가야 할 정보입니다
- 메트릭 이름은 조립하지 않습니다. 이름을 고정해야 `sum by`가 성립합니다

Prometheus를 잘 쓰는 일의 대부분은 쿼리 실력이 아니라 **계측 시점에 타입과 라벨을 바르게 고르는 일**입니다. 잘못 고른 타입은 쿼리로 고칠 수 없습니다.

## 8. 참고자료

- [Prometheus — FAQ (왜 pull인가)](https://prometheus.io/docs/introduction/faq/)
- [Prometheus — Metric types (Counter·Gauge·Histogram·Summary·네이티브 히스토그램)](https://prometheus.io/docs/concepts/metric_types/)
- [Prometheus — Jobs and instances (`up`, `scrape_*` 자동 메트릭)](https://prometheus.io/docs/concepts/jobs_instances/)
- [Prometheus — Instrumentation best practices (카디널리티 경험 법칙)](https://prometheus.io/docs/practices/instrumentation/)
- [Prometheus — Histograms and summaries (합산 가능성, 분위수 평균 금지)](https://prometheus.io/docs/practices/histograms/)
- [Prometheus — Metric and label naming (`_total`, 기본 단위)](https://prometheus.io/docs/practices/naming/)
- [Prometheus — When to use the Pushgateway](https://prometheus.io/docs/practices/pushing/)
- [Prometheus — Configuration (기본값)](https://prometheus.io/docs/prometheus/latest/configuration/configuration/) · [Query functions (리셋 보정·외삽)](https://prometheus.io/docs/prometheus/latest/querying/functions/) · [Querying basics / Staleness](https://prometheus.io/docs/prometheus/latest/querying/basics/) · [Migration guide (3.0 변경점)](https://prometheus.io/docs/prometheus/latest/migration/)
- [Spring Boot 4.1 — Actuator Metrics](https://docs.spring.io/spring-boot/reference/actuator/metrics.html) · [Micrometer — Gauges](https://docs.micrometer.io/micrometer/reference/concepts/gauges.html) · [Timers](https://docs.micrometer.io/micrometer/reference/concepts/timers.html)
- 관련 문서: `day54-golden-signals.md`, `day60-alert-fatigue.md`, `day42-structured-log-trace-id.md`, `day30-application-healthcheck.md`

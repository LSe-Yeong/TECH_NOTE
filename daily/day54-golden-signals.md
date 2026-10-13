# 무엇을 재야 하는가 — 네 가지 골든 시그널

> 이 문서가 답할 질문: **지표를 무한히 늘리지 않으면서 "서비스가 지금 고장났다"를 알아차리려면 무엇을 재야 하는가?**
>
> 분류: 기술이해형. 네 개를 고르는 선택처럼 보이지만 실제 질문은 "왜 이 네 축으로 정리됐는가"입니다. 그래서 여러 출처가 공통으로 말하는 "원래 어떤 문제를 풀려 했는가"를 찾는 관점으로 조사했습니다.
>
> 기준: Spring Boot 4.1 · Micrometer · Prometheus (2026년 10월 확인). 로그로 무엇을 남길지는 `day36-log-design.md`, 요청을 잇는 식별자는 `day42-structured-log-trace-id.md`에서 다뤘습니다. 이 문서는 **메트릭으로 무엇을 잴지**만 다룹니다. 알림 임계값과 SLO·에러 예산 설계는 범위 밖입니다.

## 1. 핵심 개념 — 지표를 고르는 일은 지표를 버리는 일입니다

모니터링 도구를 붙이면 지표가 수백 개 생깁니다. CPU, 힙, GC 횟수, 스레드 수, 커넥션 수, 캐시 적중률. 전부 공짜로 따라오니 전부 대시보드에 올립니다. 그리고 장애가 납니다.

> 그때 벌어지는 일은 이렇습니다. 패널 40개 중 어떤 것도 빨갛지 않습니다. CPU는 55%, 힙은 60%, 에러 로그도 평소 수준입니다. 그런데 사용자는 결제가 안 된다고 합니다. 반대 방향도 똑같이 흔합니다. GC가 튀었다는 알림이 새벽 3시에 울려서 깼는데, 응답시간은 아무 변화가 없었습니다. 지표가 많아서 생기는 문제가 아닙니다. **고른 지표가 "사용자가 지금 서비스를 쓸 수 있는가"와 연결되지 않아서** 생기는 문제입니다.

Google SRE 책은 이 구분을 증상(symptom)과 원인(cause)으로 부릅니다. 모니터링은 "무엇이 고장났고, 왜 고장났는가"에 답해야 하는데, 앞쪽이 증상이고 뒤쪽이 원인입니다. 그리고 **원인보다 증상을 잡는 데 훨씬 많은 노력을 쓰는 편이 낫다**고 못을 박습니다. 원인을 감시하는 것은 그 원인이 아주 확실하고 아주 임박한 경우로 제한하라는 겁니다([Google SRE — Monitoring Distributed Systems](https://sre.google/sre-book/monitoring-distributed-systems/)).

CPU 55%는 원인 쪽 지표입니다. 높다고 사용자가 불편한지 알 수 없고, 낮다고 멀쩡한지도 알 수 없습니다. 골든 시그널은 **증상 쪽에서 먼저 네 축을 세우고, 원인 쪽 지표는 그 네 축을 설명할 때만 끌어오자**는 제안입니다. 같은 문서는 네 신호를 재고 그중 하나가 문제일 때 사람을 호출한다면 서비스가 "적어도 괜찮게 커버되고 있다"고 말합니다.

## 2. 네 신호와 각각이 답하는 질문

| 신호 | 답하는 질문 | 흔한 실수 |
|---|---|---|
| 지연시간(Latency) | 느려졌는가 | 성공만 재고 평균으로 본다 |
| 트래픽(Traffic) | 지금 얼마나 들어오는가 | 아예 안 잰다 |
| 에러(Errors) | 실패하고 있는가 | 5xx만 센다 |
| 포화도(Saturation) | 얼마나 버틸 수 있는가 | 사용률로 대체한다 |

### 2-1. 지연시간 — 실패한 요청을 빼면 안 됩니다

요청 하나를 처리하는 데 걸린 시간입니다. 여기서 SRE 책의 지침 하나가 실무 감각을 바꿉니다. **성공 요청과 실패 요청의 지연시간을 분리해서 보되, 실패를 버리지는 말라**는 것입니다. 실패는 빨리 끝나는 경우가 많아서 섞으면 전체 지연시간이 좋아 보입니다. 그렇다고 실패를 제외하면 "느린 에러"를 놓칩니다. 같은 문서의 표현은 이렇습니다. **느린 에러가 빠른 에러보다 더 나쁩니다.**

### 2-2. 트래픽 — 나머지 셋의 분모입니다

시스템에 걸리는 수요입니다. 웹 서비스면 초당 HTTP 요청 수, 키-값 저장소면 초당 트랜잭션 수처럼 서비스마다 다른 고수준 지표를 씁니다.

트래픽을 "현황판용 숫자"로 취급해서 빠뜨리는 경우가 많습니다. 그런데 트래픽이 없으면 나머지 셋을 해석할 수 없습니다. 에러 50건은 트래픽이 100건일 때와 100만 건일 때 완전히 다른 사건입니다. 지연시간이 좋아진 것도 트래픽이 90% 빠진 결과일 수 있습니다. **에러와 포화도는 거의 항상 트래픽에 대한 비율로 봐야 합니다.**

### 2-3. 에러 — 명시적·암묵적·정책적 세 종류입니다

실패한 요청의 비율입니다. 그런데 "실패"가 한 종류가 아닙니다. SRE 책은 세 갈래로 나눕니다.

1. **명시적 실패** — HTTP 500 같은 것. 로드밸런서에서 5xx를 세는 것만으로도 완전히 실패한 요청은 꽤 잡힙니다.
2. **암묵적 실패** — 200으로 응답했지만 내용이 틀린 경우. 이건 엔드투엔드 테스트로만 잡힙니다.
3. **정책적 실패** — 약속한 임계값보다 느린 응답. 1초를 약속했는데 3초에 성공한 응답은 성공이 아닙니다.

3번이 지연시간과 에러의 경계를 흐립니다. 실무에서는 이렇게 처리합니다. 지표는 지연시간 분포로 하나만 만들고, **"임계값 안에 들어온 비율"을 쿼리 시점에 계산**합니다(§4-3). 느림을 에러 카운터로 따로 올리면 같은 사실이 두 지표에 중복으로 들어갑니다.

### 2-4. 포화도 — 사용률이 아니라 대기열입니다

가장 많이 틀리는 신호입니다. "얼마나 가득 찼는가"인데, 가장 제약이 되는 자원을 기준으로 봅니다. 그리고 SRE 책은 **많은 시스템이 100% 사용률에 도달하기 전에 이미 성능이 나빠진다**고 지적합니다. 그래서 100%가 아닌 별도의 목표치가 필요합니다.

USE 방법을 만든 Brendan Gregg는 사용률과 포화도를 아예 다른 축으로 정의합니다. 사용률은 "자원이 일을 처리하느라 바빴던 평균 시간"이고, 포화도는 **"자원이 처리하지 못해 남은 일의 양, 보통 큐에 쌓인 것"**입니다. 그리고 결정적인 한 문장이 붙습니다. **포화도는 0이 아니면 어떤 수준이든 문제일 수 있습니다**([Brendan Gregg — The USE Method](https://www.brendangregg.com/usemethod.html)).

사용률 60%와 대기 스레드 3개는 전혀 다른 정보입니다. 전자는 "여유 있어 보인다", 후자는 "이미 누군가 기다리고 있다"입니다. 같은 문서는 평균 구간이 버스트를 가린다는 점도 짚습니다. 사용률 70%가 짧은 100% 구간을 숨길 수 있고, 5분 평균으로 80%처럼 보이던 CPU가 실제로는 몇 초씩 100%를 치고 있던 사례를 듭니다.

그래서 포화도는 이런 걸 잽니다.

- 커넥션 풀에서 **커넥션을 기다리는 스레드 수**, 획득 대기 시간
- 스레드 풀의 **큐 길이**와 거부 건수
- 메시지 큐의 **컨슈머 랙**
- 디스크·힙처럼 고갈까지 시간을 예측할 수 있는 자원은 **남은 시간**

마지막 항목이 SRE 책이 말하는 "임박한 포화 예측"입니다. 데이터베이스가 네 시간 뒤에 디스크를 다 쓸 것이라는 예측이 그 예입니다. 그리고 **지연시간 증가 자체가 포화의 선행 지표**라는 점도 적혀 있습니다.

### 2-5. RED와 USE — 같은 걸 다른 쪽에서 봅니다

골든 시그널만 놓고 보면 "요청"과 "자원"이 한 자리에 섞여 있어 헷갈립니다. 다른 두 방법론과 대조하면 축이 선명해집니다.

| 방법론 | 구성 | 보는 대상 |
|---|---|---|
| 네 골든 시그널 | 지연시간·트래픽·에러·포화도 | 서비스 전반 |
| RED | Rate·Errors·Duration | 요청을 받는 쪽 (엔드포인트) |
| USE | Utilization·Saturation·Errors | 자원 쪽 (CPU, 큐, 풀) |

RED는 Tom Wilkie가 마이크로서비스용으로 정리한 방법으로, 서비스마다 초당 요청 수·초당 실패 수·지연시간 분포 세 개를 심습니다([Grafana — The RED Method](https://grafana.com/blog/the-red-method-how-to-instrument-your-services/)). 보시면 RED는 골든 시그널에서 포화도가 빠진 모양이고, USE는 그 빠진 자리를 자원별로 채우는 모양입니다. 두 방법론을 경쟁 관계로 소개하는 자료도 있지만, 실제로는 **엔드포인트에는 RED, 자원에는 USE를 붙이면 골든 시그널 네 개가 채워집니다.**

실무 배치는 이렇게 정리됩니다.

```
엔드포인트별 → Rate, Errors, Duration     (증상. 알림의 1차 후보)
자원별       → Utilization, Saturation    (원인. 조사할 때 보는 것)
```

## 3. 평균을 쓰면 안 되는 이유 — 어떻게 저장하는가

신호를 골랐으면 저장 형태를 골라야 합니다. 여기서 틀리면 네 신호를 다 재고도 아무것도 모릅니다.

SRE 책의 예시가 직관적입니다. 초당 1,000건에서 평균 응답시간이 100ms라면 괜찮아 보입니다. 그런데 **1%가 5초씩 걸리고 있어도 그 평균이 나옵니다.** 그래서 같은 문서는 평균을 기준으로 알림을 설계하는 것은 위험하다고 말하고, 평균만 기록하는 대신 **요청 수를 지연시간 구간별로 담은 히스토그램**을 쓰라고 권합니다. 구간 경계는 대략 3배씩 커지는 지수형으로 두라고 되어 있습니다.

그럼 분위수를 애플리케이션에서 계산해서 보내면 안 될까요. Micrometer는 두 방식을 모두 제공하지만 성질이 다릅니다.

| 방식 | Micrometer 설정 | 성질 |
|---|---|---|
| 애플리케이션에서 분위수 계산 | `percentiles` | **합산 불가**. 미터 ID(이름+태그)마다 따로 계산됨 |
| 버킷 카운트를 보내고 쿼리 때 계산 | `percentiles-histogram` | 차원 간 버킷 합산 가능 → 분위수 합산 가능 |

Micrometer 문서는 전자에 대해 **"분위수 근사값은 태그 간에 합산할 수 없다"**고 명시합니다. 후자는 Prometheus·Atlas·Wavefront처럼 서버 측 분위수 계산을 지원하는 시스템에서만 의미가 있고, 그런 시스템에서는 전자가 보통 불필요하다고도 적혀 있습니다([Micrometer — Histograms and percentiles](https://docs.micrometer.io/micrometer/reference/concepts/histogram-quantiles.html)).

이게 왜 치명적인지는 Prometheus 문서가 더 세게 말합니다. 미리 계산된 분위수를 합산하는 것은 거의 의미가 없고, **분위수를 평균하면 통계적으로 무의미한 값이 나옵니다**([Prometheus — Histograms and summaries](https://prometheus.io/docs/practices/histograms/)).

인스턴스가 4대일 때 각 인스턴스의 p99를 평균한 값은 전체 p99가 아닙니다. 아무 값도 아닙니다. 대시보드에서 `avg(p99)`를 그리는 순간 숫자는 그럴듯하게 나오지만 의미가 사라집니다. 인스턴스가 1대일 때는 맞는 값이었다가 오토스케일이 붙는 순간 조용히 틀려지므로, 틀렸다는 사실조차 알아차리기 어렵습니다.

버킷 방식의 비용은 시계열 개수입니다. Micrometer의 기본 생성기는 276개 버킷을 만들 수 있고, 타이머 기본 범위(1ms~1분)에서는 차원당 73개가 들어갑니다(같은 문서). 그래서 `minimum-expected-value`·`maximum-expected-value`로 범위를 좁히는 게 선택이 아니라 필수에 가깝습니다.

## 4. 코드와 쿼리

### 4-1. 설정 — HTTP 요청에 히스토그램을 켭니다

Spring Boot는 Spring MVC 요청을 `http.server.requests`라는 이름으로 계측합니다([Spring Boot 4.1 — Metrics](https://docs.spring.io/spring-boot/reference/actuator/metrics.html)). 기본값은 카운트와 합계뿐이라 분포를 따로 켜야 합니다.

```yaml
management:
  endpoints:
    web:
      exposure:
        include: health,info,prometheus
  metrics:
    distribution:
      percentiles-histogram:
        http.server.requests: true      # 합산 가능한 버킷
      slo:
        http.server.requests: 200ms,500ms,1s   # 이 경계에 버킷을 보장
      maximum-expected-value:
        http.server.requests: 5s        # 시계열 수를 제한
  observations:
    key-values:
      application: order-api
server:
  tomcat:
    mbeanregistry:
      enabled: true                     # tomcat.* 메트릭 조건
```

`slo`는 서비스 수준 목표 경계로 누적 히스토그램을 만드는 설정입니다. 이걸 넣는 이유는 뒤의 §4-3과 함정 6-4에 있습니다. **쿼리에서 쓸 임계값에 버킷 경계가 없으면 그 쿼리는 틀린 답을 줍니다.**

Tomcat 메트릭은 MBean 레지스트리가 켜져 있어야 수집됩니다. 기본값은 비활성입니다(같은 문서).

### 4-2. 포화도는 직접 심어야 합니다

지연시간·트래픽·에러는 프레임워크가 공짜로 줍니다. 포화도는 "무엇이 가장 먼저 마르는 자원인가"를 내가 알아야 하므로 공짜가 아닙니다. 내 서비스의 제약 자원이 외부 결제사 호출 슬롯이라면 그걸 직접 잽니다.

```java
package com.example.order.payment;

import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.concurrent.Semaphore;

@Component
public class PaymentGatewayGate {

    private static final int PERMITS = 20;

    private final Semaphore permits = new Semaphore(PERMITS);
    private final Timer waitTimer;

    public PaymentGatewayGate(MeterRegistry registry) {
        // 포화도: 지금 "기다리고 있는" 스레드 수 — 0이 아니면 이미 문제입니다
        Gauge.builder("payment.gateway.queued", permits, Semaphore::getQueueLength)
             .description("결제사 호출 슬롯을 기다리는 스레드 수")
             .register(registry);

        // 사용률: 쓰이고 있는 슬롯 비율 — 참고용입니다
        Gauge.builder("payment.gateway.utilization", permits,
                      p -> (double) (PERMITS - p.availablePermits()) / PERMITS)
             .register(registry);

        // 대기 시간 분포 — 포화가 지연시간으로 번지는 지점
        this.waitTimer = Timer.builder("payment.gateway.wait")
             .publishPercentileHistogram()
             .maximumExpectedValue(Duration.ofSeconds(3))
             .register(registry);
    }

    public <T> T call(PaymentCall<T> call) throws InterruptedException {
        long start = System.nanoTime();
        permits.acquire();
        waitTimer.record(Duration.ofNanos(System.nanoTime() - start));
        try {
            return call.execute();
        } finally {
            permits.release();
        }
    }

    public interface PaymentCall<T> {
        T execute();
    }
}
```

두 게이지를 같이 심은 건 §2-4의 차이를 코드로 보여주기 위한 것입니다. 알림을 걸 대상은 `queued` 쪽입니다. `utilization`은 사후 조사용이고, 혼자서는 "문제인가"에 답하지 못합니다.

커넥션 풀처럼 이미 계측된 자원은 직접 심지 않습니다. Spring Boot는 모든 `DataSource` 빈을 `jdbc.connections` 접두사로, HikariCP는 `hikaricp` 접두사로 풀 이름 태그와 함께 계측합니다(같은 문서). <!-- TODO: 확인 필요 — hikaricp 개별 게이지 이름(대기 스레드·획득 시간 등)은 Spring Boot 문서가 접두사만 명시하고 개별 이름을 나열하지 않습니다. 통합 솔루션마다 이름이 다르게 매핑되는 사례도 확인했으므로, 쓰는 버전에서 `/actuator/metrics`로 실제 이름을 확인하고 쓰세요. -->

### 4-3. 네 신호를 네 줄로 보기

Micrometer가 Prometheus로 내보낼 때 이름이 변환됩니다. `http.server.requests` → `http_server_requests_seconds_*` 형태이고, 실제 이름은 `/actuator/prometheus` 출력으로 확인합니다.

```promql
# 트래픽 — 초당 요청 수
sum(rate(http_server_requests_seconds_count[5m]))

# 에러 — 전체 대비 5xx 비율
sum(rate(http_server_requests_seconds_count{status=~"5.."}[5m]))
  / sum(rate(http_server_requests_seconds_count[5m]))

# 지연시간 — 인스턴스를 합산한 뒤 분위수를 구합니다. 순서가 중요합니다
histogram_quantile(0.99,
  sum by (le, uri) (rate(http_server_requests_seconds_bucket{outcome="SUCCESS"}[5m])))

# 정책적 실패 — 500ms 안에 들어온 비율 (§2-3의 3번)
sum(rate(http_server_requests_seconds_bucket{le="0.5"}[5m]))
  / sum(rate(http_server_requests_seconds_count[5m]))
```

세 번째 쿼리의 `sum by (le, ...)`가 §3의 결론입니다. **먼저 `rate`를 구하고, `le`별로 합산하고, 마지막에 분위수를 계산합니다.** Prometheus 문서의 고전 히스토그램 예시가 정확히 이 형태입니다. 네 번째 쿼리는 `le="0.5"` 버킷이 존재할 때만 동작합니다. 같은 문서는 **해당 경계의 버킷이 설정돼 있지 않으면 보간이 적용되지 않는다**고 경고합니다. §4-1에서 `slo`에 `500ms`를 넣은 이유입니다.

`outcome="SUCCESS"` 필터를 성공 쪽에만 걸었다면, 실패 쪽 분위수를 **반드시 따로 그려야 합니다.** §2-1의 "느린 에러"가 숨는 자리가 여기입니다.

## 5. 어디서 재는가 — 서버 타이머는 자기 앞의 줄을 못 봅니다

네 신호를 어디서 재느냐가 신호의 의미를 바꿉니다.

- **블랙박스** — 바깥에서 실제로 요청을 쏴보는 방식. SRE 책은 이쪽이 증상 지향이고 "지금 당장 시스템이 제대로 동작하지 않는다"를 잡아내므로 호출(paging)에 적합하다고 말합니다. 대신 임박한 문제에는 거의 도움이 되지 않습니다.
- **화이트박스** — 애플리케이션 내부 지표. 임박한 문제와 재시도에 가려진 실패를 잡고, 디버깅에는 이쪽이 필수입니다.

`http.server.requests`는 화이트박스입니다. 그리고 구조적인 한계가 하나 있습니다. **타이머는 요청이 계측된 계층에 도달한 뒤에 시작합니다.** 워커 스레드를 기다리며 수락 큐에 머문 시간은 이 숫자에 들어 있지 않습니다. 그래서 스레드 풀이 포화되면 사용자 체감은 3초인데 서버 타이머는 50ms를 보고합니다.

부하 테스트에서도 같은 왜곡이 생깁니다. Gil Tene이 coordinated omission이라 부르는 문제로, 정해진 속도로 요청을 쏘는 부하 생성기는 응답이 늦으면 다음 요청을 자동으로 미루기 때문에 **느린 구간의 표본 자체가 기록되지 않습니다.** 이 왜곡이 분위수 데이터를 못 쓰게 만들 수 있다고 말합니다([Gil Tene — How NOT to Measure Latency](https://qconsf.com/sf2012/dl/qcon-sanfran-2012/slides/GilTene_HowNotToMeasureLatency.pdf), [Coordinated Omission 토론](https://groups.google.com/g/mechanical-sympathy/c/icNZJejUHfE/m/BfDekfBEs_sJ)).

결론은 둘을 같이 둔다는 겁니다. 지연시간과 에러는 **가능한 한 사용자에 가까운 경계**(로드밸런서, 합성 모니터링)에서 한 벌 더 재고, 포화도는 **애플리케이션 안쪽**에서 잽니다. 이 두 숫자가 벌어지는 구간이 곧 "내가 못 보던 큐"입니다.

## 6. 함정

### 6-1. 대시보드는 전부 초록인데 사용자는 못 씁니다

- **증상**: CPU·힙·GC 패널이 모두 정상인데 장애 문의가 들어옵니다.
- **원인**: 올려둔 지표가 전부 원인 쪽(자원)입니다. 증상 쪽 네 축이 없습니다.
- **해법**: 엔드포인트별 Rate·Errors·Duration을 먼저 세우고, 자원 지표는 그 아래에 둡니다. 알림은 증상 쪽에만 겁니다.

### 6-2. p99가 배포 후에 오히려 좋아졌습니다

- **증상**: 장애 중인데 p99 그래프가 내려갑니다.
- **원인**: 두 가지가 겹칩니다. 타임아웃된 요청이 짧은 실패로 기록되고, 그 실패가 지연시간 집계에서 필터로 빠집니다. 그리고 큐에 밀린 요청은 애초에 측정 구간에 들어오지 않습니다(§5).
- **해법**: 지연시간은 성공·실패를 분리해서 **둘 다** 그립니다. 그리고 지연시간 그래프 바로 옆에 트래픽을 둡니다. 트래픽이 꺾이면서 좋아진 지연시간은 개선이 아닙니다.

### 6-3. CPU는 60%인데 응답이 느립니다

- **증상**: 자원 사용률에 여유가 있는데 지연시간이 올라갑니다.
- **원인**: 포화도를 사용률로 대체했습니다. 대기열은 사용률이 100%가 아니어도 생기고, 평균 구간은 버스트를 가립니다(Gregg: 70% 평균이 짧은 100%를 숨길 수 있습니다).
- **해법**: 대기 중인 요청 수와 획득 대기 시간을 지표로 심습니다(§4-2). 사용률 패널은 남기되 알림에서 내립니다.

### 6-4. 분위수가 특정 값에 붙어서 안 움직입니다

- **증상**: p99가 계속 `5s` 같은 한 값으로 고정됩니다. 또는 임계값 준수율이 실제보다 나쁘게 나옵니다.
- **원인**: 버킷 경계 문제입니다. `maximum-expected-value`를 넘는 값은 상한 버킷에 몰리고, 쿼리에 쓴 경계에 버킷이 없으면 보간이 적용되지 않습니다. Prometheus 문서는 **오차가 해당 분위수가 위치한 버킷의 폭으로 제한된다**고 설명하며, 서비스가 괜찮은데도 임계값을 거의 넘길 것처럼 보이는 사례를 듭니다.
- **해법**: 쿼리에 쓸 임계값을 `slo`에 명시해 버킷을 보장합니다. 범위는 실제 응답시간 분포를 보고 정합니다. 가능하면 네이티브 히스토그램을 씁니다 — 같은 문서는 **가능하다면 고전 히스토그램과 서머리보다 네이티브 히스토그램을 쓰라**고 권합니다.

### 6-5. 지표를 추가하자 메트릭 수집이 터졌습니다

- **증상**: 시계열 수가 폭발하고 Prometheus 메모리가 올라갑니다.
- **원인**: 태그 카디널리티입니다. URI 태그에 `/orders/10231` 같은 실제 ID가 들어가면 주문 수만큼 시계열이 생깁니다. 거기에 히스토그램 버킷 수가 곱해집니다(§3).
- **해법**: 경로 변수는 템플릿으로 유지합니다. OpenTelemetry 규약도 `http.route`는 저카디널리티여야 하고 동적 구간은 플레이스홀더로 치환하라고 규정하며, 알 수 없는 HTTP 메서드는 원문이 아니라 `_OTHER`로 보고하라고 명시합니다([OTel — HTTP metrics](https://opentelemetry.io/docs/specs/semconv/http/http-metrics/)). 태그를 하나 추가할 때마다 "이 값의 가능한 종류가 몇 개인가"를 먼저 셉니다.

### 6-6. 지표 이름을 바꿀 수 없게 됐습니다

- **증상**: 메트릭 이름·단위가 팀마다 달라서 대시보드를 재사용할 수 없습니다.
- **원인**: 자체 작명으로 시작했습니다. 알림과 대시보드가 이름에 종속되면 나중에 못 바꿉니다.
- **해법**: HTTP 서버 지연시간은 규약을 따릅니다. OpenTelemetry는 `http.server.request.duration`을 **히스토그램·초(`s`) 단위·안정(stable)** 상태로 정의하고, 권장 버킷 경계까지 명시합니다(0.005 / 0.01 / 0.025 / 0.05 / 0.075 / 0.1 / 0.25 / 0.5 / 0.75 / 1 / 2.5 / 5 / 7.5 / 10초). 단위를 밀리초로 두면 이후 모든 쿼리가 규약과 어긋납니다.

## 7. 정리

무엇을 재야 하는가의 답은 "네 개"가 아니라 **"증상 네 축을 먼저, 원인은 그 아래"**입니다.

- 지연시간·트래픽·에러·포화도가 증상 축입니다. 자원 지표는 이 축을 설명할 때 끌어옵니다
- 트래픽은 나머지 셋의 분모입니다. 비율로 보지 않으면 숫자가 의미를 못 가집니다
- 포화도는 사용률이 아니라 **대기열**입니다. 0이 아니면 이미 누군가 기다리고 있습니다
- 평균과 인스턴스별 분위수 평균은 둘 다 아무 값도 아닙니다. 버킷을 보내고 **합산 후에** 분위수를 계산합니다
- 서버 타이머는 자기 앞의 줄을 못 봅니다. 사용자에 가까운 경계에서 한 벌 더 잽니다

네 축을 세우는 실제 보상은 지표가 늘어나는 게 아니라 **줄어드는 것**입니다. 알림을 걸 대상이 명확해지면 나머지는 조사용으로 내려도 되고, 그때부터 새벽에 울리는 알림이 실제 장애와 일치하기 시작합니다.

## 8. 참고자료

- [Google SRE Book — Monitoring Distributed Systems (네 골든 시그널·증상 대 원인)](https://sre.google/sre-book/monitoring-distributed-systems/)
- [Brendan Gregg — The USE Method (사용률 대 포화도)](https://www.brendangregg.com/usemethod.html)
- [Grafana — The RED Method: how to instrument your services](https://grafana.com/blog/the-red-method-how-to-instrument-your-services/)
- [Prometheus — Histograms and summaries (분위수 합산·버킷 경계)](https://prometheus.io/docs/practices/histograms/)
- [Micrometer — Histograms and percentiles](https://docs.micrometer.io/micrometer/reference/concepts/histogram-quantiles.html)
- [Spring Boot 4.1 Reference — Metrics](https://docs.spring.io/spring-boot/reference/actuator/metrics.html)
- [OpenTelemetry — Semantic conventions for HTTP metrics](https://opentelemetry.io/docs/specs/semconv/http/http-metrics/)
- [Gil Tene — How NOT to Measure Latency (QCon SF 2012 슬라이드)](https://qconsf.com/sf2012/dl/qcon-sanfran-2012/slides/GilTene_HowNotToMeasureLatency.pdf)
- 관련 문서: `day36-log-design.md`, `day42-structured-log-trace-id.md`, `day30-application-healthcheck.md`, `day45-local-cache.md`

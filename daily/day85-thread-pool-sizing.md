# 스레드 200개는 왜 나쁜가 — 요청 처리 스레드 풀 크기를 정하는 기준

> 이 문서가 답할 질문: **요청 처리 스레드 풀의 크기는 무엇으로 정해지는가 — 왜 숫자를 올리는 것이 답이 아닌가?**

기준 버전: **Spring Boot 4.2 문서 기준 기본값**, **Apache Tomcat 11.0**, **JDK 25 (LTS) / 27**, **HikariCP `dev` 브랜치 README 기준**. 유형은 문제해결형입니다 — "스레드를 늘렸는데 더 느려졌다"는 증상에서 출발해 원인과 해법으로 내려갑니다.

## 1. 핵심 개념 — 스레드 수는 처방이 아니라 결과입니다

스레드 풀 크기는 "동시에 몇 개를 처리하고 싶은가"가 아닙니다. **"병목 자원을 몇 명이 나눠 쓸 것인가"** 입니다. 이 구분을 놓치면 숫자를 올리는 것이 유일한 손잡이로 보입니다.

> 주문 API가 응답이 밀립니다. 스레드 덤프를 뜨니 Tomcat 워커 200개 중 190개가 `HikariPool.getConnection`에서 `WAITING` 상태입니다. 풀이 모자란 것 같아 `server.tomcat.threads.max`를 500으로 올리고 재배포합니다. 결과는 더 나빠집니다. 이번에는 490개가 같은 자리에서 기다리고, 30초 뒤 `SQLTransientConnectionException: Connection is not available, request timed out after 30000ms`가 쏟아집니다. 커넥션 풀은 그대로 10개였으니까요. **늘린 것은 처리 능력이 아니라 대기열의 길이였습니다.** 그리고 대기열이 길어진 만큼 모든 요청이 느려집니다.

이 현상은 리틀의 법칙(Little's Law)으로 설명됩니다. JEP 444는 서버 애플리케이션의 확장성이 이 법칙에 지배된다고 명시하면서, 지연시간 50ms에 동시 10건을 처리하면 초당 200건이고, 초당 2000건으로 올리려면 동시 100건을 처리해야 한다는 예시를 듭니다([JEP 444](https://openjdk.org/jeps/444)).

```
동시 처리 건수(L) = 초당 도착 요청(λ) × 요청당 소요 시간(W)
```

여기서 중요한 건 방향입니다. 이 식은 **"스레드를 늘리면 처리량이 늘어난다"고 말하지 않습니다.** W가 고정일 때 λ를 받아내려면 L이 그만큼 필요하다는 **하한**을 말합니다. L을 하한보다 키워도 λ는 늘지 않습니다. λ를 정하는 것은 병목 자원이고, 스레드는 그 자원 앞에 줄을 서는 주체일 뿐입니다.

---

## 2. 스레드 하나의 원가

### 2-1. 메모리 — 스택은 힙 밖에 있습니다

플랫폼 스레드 하나는 고정 크기 스택을 받습니다. JDK 25 `java` 명령 문서는 `-Xss` 기본값을 플랫폼별로 명시합니다 — Linux/x64는 1024KB, Linux/Aarch64와 macOS/Aarch64는 2048KB입니다([Oracle, java 명령](https://docs.oracle.com/en/java/javase/25/docs/specs/man/java.html)).

이 메모리는 **힙이 아닙니다.** 그래서 `-Xmx`로 통제되지 않고, 컨테이너 메모리 리밋에는 그대로 잡힙니다. Aarch64에서 스레드 500개를 띄우면 스택만으로 약 1GB의 예약 영역이 생깁니다. 힙을 아무리 잘 맞춰놔도 `OutOfMemoryError: unable to create native thread` 또는 컨테이너 OOMKill로 끝나는 경로가 이쪽입니다.

### 2-2. 스케줄링 — 코어는 한 번에 하나만 실행합니다

HikariCP 위키의 풀 사이징 문서는 이 부분을 직설적으로 씁니다. 코어 하나는 실제로는 한 번에 한 스레드만 실행하고, 타임 슬라이싱은 동시성을 **모방할** 뿐이라고요. 그래서 스레드가 코어 수를 넘어서면 추가되는 스레드는 속도를 떨어뜨립니다. 같은 문서의 요약은 이렇습니다 — "더 많은 스레드는 블로킹이 실행 기회를 만들어줄 때만 더 나은 성능을 냅니다"([HikariCP, About Pool Sizing](https://github.com/brettwooldridge/HikariCP/wiki/About-Pool-Sizing)).

뒤집으면 이 말입니다. 스레드를 늘려서 이득이 나는 유일한 이유는 **기존 스레드가 I/O로 블로킹되어 CPU를 비워주기 때문**입니다. 블로킹 비율이 낮은 작업이라면 늘릴 이유가 없고, 블로킹 비율이 높다면 늘릴 수는 있지만 이번에는 블로킹의 대상인 하류 자원이 먼저 막힙니다.

### 2-3. 하류 자원 — 이미 정해진 숫자가 있습니다

HikariCP의 `maximumPoolSize` 기본값은 **10**이고 `connectionTimeout` 기본값은 **30000ms**입니다([HikariCP README](https://github.com/brettwooldridge/HikariCP#gear-configuration-knobs-baby)). DB를 쓰는 엔드포인트라면 애플리케이션의 실질 동시 처리 한도는 200이 아니라 10입니다. 나머지 190은 30초를 기다린 뒤 예외를 받습니다.

같은 위키는 더 극적인 사례를 인용합니다. Oracle Real-World Performance 그룹 영상에서 **다른 변경 없이 커넥션 풀 크기만 2048에서 96으로 줄여** 응답 시간이 약 100ms에서 약 2ms로, 50배 이상 개선됐다는 내용입니다. 저자는 16코어나 32코어 머신이 아니라면 96조차 많을 수 있다고 덧붙입니다.

| 스레드 200개가 실제로 거는 비용 | 값 |
|---|---|
| 스택 예약 (Linux/x64) | 약 200MB, 힙 밖 |
| 동시에 CPU를 쓸 수 있는 수 | 코어 수만큼 |
| 동시에 DB를 쓸 수 있는 수 | `maximumPoolSize` (기본 10) |
| 나머지 스레드가 하는 일 | 대기 |

---

## 3. 기본값의 구조 — Tomcat이 쓰는 네 개의 숫자

Spring Boot 4.2 문서 기준 내장 Tomcat의 기본값은 이렇습니다.

| 속성 | 기본값 | 의미 |
|---|---:|---|
| `server.tomcat.max-connections` | 8192 | 동시에 받아서 처리할 커넥션 수 |
| `server.tomcat.threads.max` | 200 | 요청 처리 워커 스레드 최대 수 |
| `server.tomcat.threads.min-spare` | 10 | 항상 유지하는 워커 수 |
| `server.tomcat.accept-count` | 100 | `max-connections` 초과 시 OS 큐 길이 |

출처는 [Spring Boot 공통 애플리케이션 속성](https://docs.spring.io/spring-boot/appendix/application-properties/index.html)과 [Tomcat 11 HTTP 커넥터 문서](https://tomcat.apache.org/tomcat-11.0-doc/config/http.html)입니다. 두 문서의 값이 일치합니다.

요청이 지나가는 순서는 이렇습니다.

```
OS accept 큐 (accept-count: 100)
  → Tomcat이 수용·처리 중인 커넥션 (max-connections: 8192)
    → 워커 스레드 (threads.max: 200)
      → 커넥션 풀 (maximumPoolSize: 10)
        → DB
```

여기서 눈에 들어와야 하는 것은 **8192와 10의 간격**입니다. Tomcat은 커넥션 8192개까지 받아들이는데, 그 뒤에 실제로 일할 수 있는 창구는 10개입니다. 기본값만으로도 애플리케이션은 "받을 수 있는 양"을 "처리할 수 있는 양"보다 800배 크게 설정해 둔 상태입니다. 이 간격이 전부 지연시간으로 나타납니다.

Tomcat의 워커 풀은 표준 `ThreadPoolExecutor`와 큐 정책이 다릅니다. `TaskQueue.offer()`는 풀 크기가 최대치에 도달하기 전까지 `false`를 반환해 **스레드 생성을 강제**하고, 최대치에 닿은 뒤에야 큐에 쌓습니다([Tomcat TaskQueue 소스](https://github.com/apache/tomcat/blob/11.0.x/java/org/apache/tomcat/util/threads/TaskQueue.java)). 그래서 Tomcat은 `threads.max`까지 실제로 스레드를 만듭니다. 이 동작이 4절의 계산을 의미 있게 만들고, 동시에 8절의 함정 하나를 만듭니다.

---

## 4. 그래서 몇 개인가

세 가지 계산을 각각 해보고 **가장 작은 값**을 택합니다.

### 4-1. 블로킹 비율로 뽑는 값

Brian Goetz의 『Java Concurrency in Practice』에서 온 공식이 널리 쓰입니다.

```
스레드 수 = 코어 수 × 목표 CPU 사용률 × (1 + 대기 시간 / 계산 시간)
```

Zalando 엔지니어링 블로그의 예시는 듀얼 코어에서 대기 50ms, 계산 5ms일 때 `2 × (1 + 50/5) = 22`를 얻습니다([Zalando Engineering](https://engineering.zalando.com/posts/2019/04/how-to-set-an-ideal-thread-pool-size.html)). 같은 글이 리틀의 법칙으로 역산해 `22 / 0.055 ≈ 400 RPS`를 계산하고, 이 공식들은 "은총알이 아니다"라고 못 박습니다. 평균 부하를 전제하므로 버스트에는 잘 맞지 않습니다.

<!-- TODO: 확인 필요 — 위 공식의 정확한 원문 표기와 장·절 번호는 책 본문을 직접 확인하지 못했습니다. 2차 출처(Zalando 블로그)의 인용 형태로만 확인됐습니다. -->

핵심은 숫자가 아니라 구조입니다. 코어 2개짜리 컨테이너에서 이 공식이 200을 내놓으려면 대기/계산 비율이 99:1이어야 합니다. 그 정도로 기다리는 중이라면 **고쳐야 할 것은 스레드 수가 아니라 그 대기**입니다.

### 4-2. 하류 자원이 정해놓은 값

HikariCP 위키의 출발점 공식은 PostgreSQL 프로젝트에서 왔다고 밝히고 있습니다.

```
커넥션 수 = (코어 수 × 2) + 유효 스핀들 수
```

같은 문서는 하이퍼스레딩 논리 코어를 코어 수에 포함하지 말라고 하고, 데이터셋이 전부 캐시에 들어오면 스핀들 수는 0이라고 설명합니다. 4코어 i7에 디스크 1개면 9, 반올림해 10이라는 예시도 함께 제시합니다. 그리고 이 값은 **출발점이지 정답이 아니며**, 그 주변에서 부하 테스트로 조정하라고 명시합니다.

DB를 타는 엔드포인트의 워커 스레드를 커넥션 풀 크기보다 크게 잡는 것은 "대기자 수"를 늘리는 설정입니다. 처리량은 커넥션 풀이 정합니다.

### 4-3. SLO가 허용하는 대기열 길이

이게 실무에서 가장 유용한 계산입니다. p99 목표가 1초이고 요청당 서비스 시간이 50ms라면, 창구 10개 뒤에 줄을 설 수 있는 사람은 최대 `(1000 / 50) × 10 = 200`명이 아니라 **그보다 훨씬 적어야** 합니다. 앞사람 전부의 처리 시간이 내 응답 시간에 더해지기 때문입니다. 200번째가 1초 안에 끝나려면 평균 대기가 950ms 이내여야 하고, 그건 창구 10개로는 불가능합니다.

즉 큐를 길게 허용하는 설정은 **"느리게 성공하는" 요청을 만들어냅니다.** 타임아웃 없이 29초를 기다린 뒤 응답받은 요청은 사용자에게 실패와 다르지 않습니다. 게다가 그 29초 동안 스레드·소켓·추적 컨텍스트를 점유합니다.

---

## 5. 설정 대비

### 5-1. 숫자만 올린 설정 ❌

```yaml
# ❌ 워커를 500개로 늘렸지만 창구는 10개 그대로
server:
  tomcat:
    threads:
      max: 500          # 490개가 커넥션을 기다립니다
    max-connections: 8192
spring:
  datasource:
    hikari:
      maximum-pool-size: 10   # 실질 처리량은 여기서 결정됩니다
      # connection-timeout 기본 30000ms — 490개가 30초를 붙잡습니다
```

증상은 이렇게 나타납니다. CPU 사용률은 낮고, DB는 한가하고, 애플리케이션 응답만 느립니다. 모니터링 그래프에서 아무 자원도 포화로 보이지 않기 때문에 원인을 못 찾습니다. 포화된 것은 자원이 아니라 **대기열**입니다.

### 5-2. 간격을 좁힌 설정 ✔️

```yaml
# ✔️ 코어 4개 기준. 워커는 커넥션 풀의 약 2배로 맞추고, 초과분은 빨리 거부합니다
server:
  tomcat:
    threads:
      max: 40
      min-spare: 10
    max-connections: 400     # 8192 → 수용량도 함께 내립니다
    accept-count: 50
spring:
  datasource:
    hikari:
      maximum-pool-size: 10  # (4 × 2) + 2
      connection-timeout: 2000   # 30초 대기는 장애를 길게 만듭니다
      validation-timeout: 1000
```

`connection-timeout`을 2초로 줄이는 것이 핵심입니다. 30초를 기다려 성공하는 것보다 2초에 실패하고 재시도 정책에 넘기는 편이 전체 시스템에 낫습니다. 이 판단은 day82-health-check.md에서 다룬 "빨리 실패해서 교체 가능한 상태를 만든다"와 같은 방향입니다.

워커 수를 커넥션 풀의 2배로 두는 이유는, DB를 전혀 타지 않는 요청(헬스체크, 캐시 히트, 정적 응답)이 커넥션 대기에 막히지 않게 하기 위한 여유입니다. 이 비율은 출발점이고 부하 테스트로 조정합니다.

---

## 6. 스레드를 늘리는 대신 할 일

1. **타임아웃을 전 구간에 넣습니다** — 커넥션 획득, 쿼리, HTTP 클라이언트 각각. 타임아웃 없는 구간이 하나라도 있으면 스레드는 거기서 영구히 붙잡힙니다.
2. **자원별로 동시 접근을 제한합니다** — 외부 API 호출과 DB 작업이 같은 워커 풀을 공유하면, 외부 API 장애가 DB 요청까지 끌고 갑니다. `Semaphore`나 Resilience4j 벌크헤드로 자원별 한도를 따로 둡니다.
3. **큐를 짧게 하고 거부를 설계합니다** — `accept-count`를 줄이고 503을 빨리 반환하는 쪽이, 전부 받아서 전부 느려지는 쪽보다 복구가 빠릅니다.
4. **대기의 원인을 없앱니다** — N+1 쿼리 하나를 고치면 대기/계산 비율이 바뀌고, 4-1의 필요 스레드 수가 함께 내려갑니다. 이게 유일하게 처리량을 실제로 늘리는 방법입니다.

2번을 코드로 보면 이렇습니다. 외부 결제 게이트웨이 호출만 동시 8건으로 묶어, 그쪽이 느려져도 워커 전체가 거기 잠기지 않게 합니다.

```java
// ❌ 워커 스레드가 곧 동시 호출 한도 — 게이트웨이가 느려지면 워커 전부가 거기 묶인다
@Service
public class PaymentClient {

    private final RestClient restClient;

    public PaymentClient(RestClient.Builder builder) {
        this.restClient = builder.baseUrl("https://payment.example.com").build();
    }

    public PaymentResult confirm(String orderId) {
        return restClient.post()
                .uri("/v1/confirm/{orderId}", orderId)
                .retrieve()
                .body(PaymentResult.class);
    }
}
```

```java
// ✔️ 자원별 동시 접근 한도를 세마포어로 명시 — 초과분은 기다리지 않고 거부한다
@Service
public class PaymentClient {

    private static final int MAX_CONCURRENT_CALLS = 8;
    private static final Duration ACQUIRE_TIMEOUT = Duration.ofMillis(200);

    private final Semaphore permits = new Semaphore(MAX_CONCURRENT_CALLS);
    private final RestClient restClient;

    public PaymentClient(RestClient.Builder builder) {
        this.restClient = builder.baseUrl("https://payment.example.com").build();
    }

    public PaymentResult confirm(String orderId) {
        boolean acquired;
        try {
            acquired = permits.tryAcquire(ACQUIRE_TIMEOUT.toMillis(), TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new PaymentUnavailableException("결제 호출이 중단되었습니다", e);
        }
        if (!acquired) {
            // 200ms 안에 자리가 안 나면 기다리지 않고 포기한다
            throw new PaymentUnavailableException("결제 게이트웨이 동시 호출 한도 초과");
        }
        try {
            return restClient.post()
                    .uri("/v1/confirm/{orderId}", orderId)
                    .retrieve()
                    .body(PaymentResult.class);
        } finally {
            permits.release();
        }
    }
}
```

두 예제의 `PaymentResult`와 `PaymentUnavailableException`은 프로젝트에서 정의하는 타입입니다. 임포트는 `java.time.Duration`, `java.util.concurrent.Semaphore`, `java.util.concurrent.TimeUnit`, `org.springframework.web.client.RestClient`입니다.

`tryAcquire`에 타임아웃을 주는 것이 요점입니다. 무기한 `acquire()`를 쓰면 한도만 바뀌고 무한 대기는 그대로 남습니다. 그리고 이 방식은 7절에서 본 JEP 444의 권고(동시성 제한에는 풀이 아니라 세마포어)와 그대로 맞물려서, 가상 스레드로 전환해도 코드를 고치지 않아도 됩니다.

---

## 7. 가상 스레드는 이 질문을 없애는가

절반만 없앱니다.

`spring.threads.virtual.enabled=true`(기본값 `false`)로 켜면 Tomcat이 가상 스레드로 요청을 처리합니다. Spring Boot 속성 문서는 `threads.max`와 `threads.min-spare` 설명에 **"가상 스레드가 활성화되면 효과가 없습니다"**라고 명시합니다. 즉 "워커를 몇 개로 할까"라는 질문 자체가 사라집니다.

JEP 444는 플랫폼 스레드의 한계를 이렇게 정리합니다 — 요청마다 OS 스레드를 하나씩 쓰면 CPU나 네트워크 커넥션 같은 다른 자원이 바닥나기 **한참 전에 스레드 수가 제한 요인**이 되고, 스레드를 풀링해도 이건 해결되지 않습니다. 풀링은 생성 비용을 피할 뿐 총 스레드 수를 늘려주지 않기 때문입니다.

그래서 1절의 L 상한은 크게 올라갑니다. 하지만 **2-3절의 10은 그대로입니다.** 가상 스레드를 켜면 커넥션 풀 앞에서 기다리는 주체가 플랫폼 스레드에서 가상 스레드로 바뀔 뿐입니다. 메모리는 아끼지만 처리량은 그대로입니다. 병목은 제거되지 않고 **이동**합니다.

JEP 444가 직접 경고하는 지점도 둘 있습니다.

- **가상 스레드를 풀링하지 마십시오.** 가상 스레드는 비싸지 않아 풀링할 이유가 없고, 동시성 제한이 목적이라면 세마포어처럼 그 목적으로 만들어진 장치를 쓰라고 명시합니다.
- **`ThreadLocal`에 비싼 자원을 캐싱하는 관용구를 조심하십시오.** 풀 기반 코드에서 스레드 로컬에 커넥션 같은 자원을 담아두던 코드를 그대로 옮기면, 가상 스레드마다 그 자원을 새로 만들어 성능이 크게 나빠질 수 있다고 경고합니다.

핀닝(pinning)은 많이 개선됐습니다. JEP 491이 JDK 24에서 Delivered 상태로 들어가, `synchronized` 블록 안에서도 가상 스레드가 캐리어를 놓아줄 수 있게 됐습니다([JEP 491](https://openjdk.org/jeps/491)). JDK 21에서 `synchronized`를 피해 `ReentrantLock`으로 바꿔야 했던 제약이 JDK 24 이상에서는 대부분 사라집니다. 다만 네이티브 코드 경계 등 일부 경우는 여전히 핀닝됩니다.

가상 스레드 스케줄러는 work-stealing `ForkJoinPool`이고, 기본 병렬도는 **사용 가능한 프로세서 수**이며 `jdk.virtualThreadScheduler.parallelism`으로 조정합니다(JEP 444). 즉 CPU 바운드 구간의 처리량은 가상 스레드로도 늘지 않습니다.

---

## 8. 함정

### 8-1. 큐가 먼저 차서 `max-size`가 무시됩니다

- **증상**: `@Async` 작업이 밀리는데 스레드 수는 8개에서 늘지 않습니다. `spring.task.execution.pool.max-size`를 200으로 올려도 그대로입니다.
- **원인**: 표준 `ThreadPoolExecutor`는 코어 스레드가 다 차면 **새 스레드보다 큐를 먼저 선택**합니다. 공식 javadoc은 무제한 큐를 쓰면 "`corePoolSize`보다 많은 스레드가 만들어지지 않으며, 따라서 `maximumPoolSize` 값은 아무 효과가 없다"고 적습니다([ThreadPoolExecutor javadoc](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/concurrent/ThreadPoolExecutor.html)). Spring의 `ThreadPoolTaskExecutor`는 `maxPoolSize`와 `queueCapacity` 기본값이 모두 `Integer.MAX_VALUE`이고, `spring.task.execution.pool.core-size` 기본값은 8입니다. Spring Boot 속성 문서도 `queue-capacity` 설명에 "무제한 용량은 풀을 늘리지 않으며 따라서 `max-size` 속성을 무시합니다"라고 명시합니다.
- **해법**: `queue-capacity`를 유한한 값으로 지정합니다. 그래야 `max-size`가 의미를 갖습니다. Tomcat 워커 풀은 3절에서 본 `TaskQueue` 때문에 이 함정이 없으니, 두 풀을 같은 직관으로 다루면 안 됩니다.

### 8-2. 컨테이너 CPU 리밋과 `availableProcessors`가 어긋납니다

- **증상**: 4-1의 공식대로 계산해 넣었는데 기대만큼 처리량이 안 나오고, 스로틀링 메트릭(`container_cpu_cfs_throttled_seconds_total`)만 올라갑니다.
- **원인**: 공식의 "코어 수"를 호스트 코어 수로 계산한 경우입니다. JVM은 Linux에서 컨테이너 감지를 기본으로 켜두며(`-XX:+UseContainerSupport`, 기본값 `true`), 컨테이너에 할당된 프로세서 수를 기준으로 시스템 자원을 배분합니다([Oracle, java 명령](https://docs.oracle.com/en/java/javase/25/docs/specs/man/java.html)). CPU 리밋이 1코어인 파드에서 공식의 기준값은 1입니다.
- **해법**: `Runtime.getRuntime().availableProcessors()`를 **실행 중인 컨테이너 안에서** 확인합니다. 값이 의도와 다르면 `-XX:ActiveProcessorCount`로 명시하거나 CPU 리밋을 조정합니다. `-Xlog:os+container=trace`로 JVM이 무엇을 읽었는지 볼 수 있습니다.

### 8-3. 스레드 덤프를 안 보고 숫자를 조정합니다

- **증상**: `threads.max`를 올리고 내리며 수치를 바꿔 보지만 개선이 들쭉날쭉합니다.
- **원인**: 어느 지점에서 막혔는지 모르는 상태에서 숫자를 조정하고 있습니다. 1절의 상황에서 필요한 정보는 "스레드가 몇 개냐"가 아니라 "스레드 200개가 **어느 스택 프레임에** 모여 있냐"입니다.
- **해법**: `jcmd <pid> Thread.print`를 30초 간격으로 세 번 뜨고, 같은 메서드에 몰린 스레드를 셉니다. `HikariPool.getConnection`이면 4-2, 외부 HTTP 클라이언트면 6-2, 애플리케이션 코드의 `synchronized`면 락 경합입니다. 세 경우의 해법이 전부 다르고, **그중 스레드 수를 올리는 것은 하나도 없습니다.**

### 8-4. 가상 스레드를 켜고 커넥션 풀을 그대로 둡니다

- **증상**: 가상 스레드를 켠 뒤 처리량은 그대로인데 `SQLTransientConnectionException` 발생량이 오히려 늘어납니다.
- **원인**: 워커 스레드 한도 200이 사실은 과부하 보호 장치였습니다. 그게 사라지면서 수천 개의 요청이 동시에 커넥션 풀 10개에 도달합니다. 7절의 "병목은 이동한다"가 그대로 나타난 것입니다.
- **해법**: 사라진 한도를 명시적으로 복원합니다. JEP 444의 권고대로 풀이 아니라 세마포어로 자원별 동시 접근 수를 제한하고, `connection-timeout`을 짧게 잡습니다. 가상 스레드 도입은 **동시성 제한을 없애는 작업이 아니라, 암묵적 제한을 명시적 제한으로 바꾸는 작업**입니다.

---

## 9. 정리

스레드 풀 크기를 정하는 질문은 세 단계로 압축됩니다.

1. **어느 자원이 병목인가** — 스레드 덤프로 확인합니다. 추측하지 않습니다.
2. **그 자원이 허용하는 동시 처리 수는 몇인가** — DB라면 커넥션 풀 크기이고, 그 값은 코어 수에서 나옵니다.
3. **워커 수를 그 숫자에 가깝게 맞추고, 초과분을 빨리 거부합니다** — 받아놓고 느려지는 것보다 거부하고 빠른 쪽이 낫습니다.

"스레드 200개는 왜 나쁜가"의 답은 "200이 큰 숫자이기 때문"이 아닙니다. **200은 어떤 계산의 결과도 아니기 때문**입니다. 기본값이라서 거기 있는 숫자이고, 그 뒤의 커넥션 풀 10과 아무 관계도 없습니다. 계산해서 나온 40이 계산 없이 쓰는 200보다 낫습니다.

## 10. 참고자료

- [JEP 444: Virtual Threads](https://openjdk.org/jeps/444) — 리틀의 법칙, 스레드가 제한 요인이 되는 구조, 풀링 금지 권고
- [JEP 491: Synchronize Virtual Threads without Pinning](https://openjdk.org/jeps/491) — JDK 24 Delivered
- [Oracle — `java` 명령 문서 (JDK 25)](https://docs.oracle.com/en/java/javase/25/docs/specs/man/java.html) — `-Xss`, `-XX:ActiveProcessorCount`, `-XX:UseContainerSupport`
- [`ThreadPoolExecutor` javadoc (JDK 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/concurrent/ThreadPoolExecutor.html) — 큐 정책 세 가지
- [HikariCP — About Pool Sizing](https://github.com/brettwooldridge/HikariCP/wiki/About-Pool-Sizing)
- [HikariCP README — 설정 기본값](https://github.com/brettwooldridge/HikariCP#gear-configuration-knobs-baby)
- [Spring Boot — 공통 애플리케이션 속성](https://docs.spring.io/spring-boot/appendix/application-properties/index.html)
- [Apache Tomcat 11 — HTTP 커넥터 설정](https://tomcat.apache.org/tomcat-11.0-doc/config/http.html)
- [Tomcat `TaskQueue` 소스](https://github.com/apache/tomcat/blob/11.0.x/java/org/apache/tomcat/util/threads/TaskQueue.java)
- [Zalando Engineering — How to set an ideal thread pool size](https://engineering.zalando.com/posts/2019/04/how-to-set-an-ideal-thread-pool-size.html)
- 관련 챕터: day07-jvm-memory.md, day82-health-check.md, day84-apm.md

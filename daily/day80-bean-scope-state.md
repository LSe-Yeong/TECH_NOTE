# 싱글톤 빈에 상태를 두면 — 테스트는 통과하는데 운영에서 값이 섞이는 이유

> 이 문서가 답할 질문: **빈의 필드에 값을 담으면 정확히 무엇이 깨지고, 그 상태는 어디로 옮겨야 하는가?**

기준 버전: **Spring Framework 7.0 / Spring Boot 4.1**, **Java 25**

---

## 1. 핵심 개념 — 빈의 필드는 사실상 전역 변수입니다

`@Service`를 붙이면 스코프를 안 적어도 싱글톤입니다. 공식 문서는 이걸 "하나의 공유 인스턴스만 관리되고, 해당 빈 정의에 매칭되는 모든 요청이 그 하나의 인스턴스를 돌려받는다"로 설명하고, 그 인스턴스는 컨테이너의 싱글톤 캐시에 저장된다고 명시합니다.

여기서 "모든 요청"이 결정적입니다. 내장 Tomcat은 요청을 스레드 풀로 처리하고, `maxThreads`를 지정하지 않으면 200입니다([Tomcat 11 HTTP Connector](https://tomcat.apache.org/tomcat-11.0-doc/config/http.html) — "If not specified, this attribute is set to 200."). 즉 최대 200개 스레드가 **같은 객체의 같은 필드**를 동시에 읽고 씁니다. 메서드 안에서 `this.something = ...`을 한 줄 쓰면, 그 줄은 전역 변수에 대입하는 줄입니다.

> 이 버그가 위험한 건 터지지 않기 때문입니다. 단위 테스트는 스레드 하나로 돌아서 절대 재현되지 않고, 로컬에서 눌러보는 것도 요청 하나씩입니다. 운영에 올라가 동시 요청이 겹치는 순간 증상은 예외가 아니라 **틀린 값**으로 나타납니다. A 사용자 응답에 B 사용자 이름이 섞이고, 집계 숫자가 미묘하게 안 맞고, 날짜가 1970년으로 찍힙니다. 스택트레이스가 없으니 어디를 봐야 할지도 모릅니다.

공식 문서는 이 문제에 한 줄짜리 규칙을 줍니다 — 상태를 가지는 빈에는 prototype 스코프를, 상태가 없는 빈에는 singleton 스코프를 쓰라는 것입니다([Bean Scopes](https://docs.spring.io/spring-framework/reference/core/beans/factory-scopes.html)). 실무에서는 이 규칙을 거꾸로 적용하는 쪽이 훨씬 자주 맞습니다. **스코프를 바꾸지 말고 상태를 없앱니다.** 이유는 6절에서 봅니다.

---

## 2. 구조 — 상태가 들어오는 네 경로

### 경로 1. 인스턴스 필드

가장 흔합니다. 메서드가 길어지면서 중간 결과를 필드로 꺼내는 리팩터링이 보통 시작점입니다.

### 경로 2. `static` 필드

`static`은 스코프와 무관합니다. 빈을 prototype으로 바꿔도, 요청 스코프로 바꿔도 `static` 필드는 그대로 공유됩니다. 스코프를 조정해서 고치려는 시도가 통하지 않는 유일한 경로입니다.

### 경로 3. 주입받은 가변 협력자

내 필드에 직접 값을 안 담아도, 스레드 안전하지 않은 객체를 필드로 들고 있으면 같은 문제입니다. `SimpleDateFormat` Javadoc은 "날짜 포맷은 동기화되지 않으며, 스레드마다 별도 인스턴스를 만들 것"을 권고합니다. `java.util.regex.Matcher`, `SAXParser`, 직접 만든 가변 빌더가 모두 여기 들어갑니다.

### 경로 4. 스코프 미스매치

수명이 긴 빈이 수명이 짧은 빈을 직접 필드로 들고 있는 경우입니다. 이건 값이 섞이는 게 아니라 **값이 멈춥니다**. 공식 문서 표현대로, 싱글톤은 정확히 한 번 인스턴스화되고 의존성도 한 번만 주입되므로 "원래 주입된 바로 그 객체 하나만 가지고 동작"합니다.

| 스코프 | 하나의 인스턴스가 사는 범위 | 상태를 둘 수 있는가 |
|---|---|---|
| `singleton` (기본) | 컨테이너당 1개 | ❌ |
| `prototype` | 주입/조회 요청마다 1개 | 조건부 (6절) |
| `request` | HTTP 요청 1건 | ✔️ |
| `session` | HTTP 세션 | ✔️ (크기 주의) |
| `application` | `ServletContext` | ❌ (싱글톤과 같음) |
| `websocket` | WebSocket 세션 | ✔️ |

`request` 이하 네 개는 웹을 인식하는 `ApplicationContext`에서만 동작합니다. 스레드 스코프는 존재하지만 기본 등록되어 있지 않다고 공식 문서가 명시합니다 — 즉 "스레드당 하나"가 필요하면 7절의 다른 수단을 씁니다.

---

## 3. 흐름 — 어떻게 섞이는가

### 3-1. 재현 코드

```java
@Service
public class OrderReportService {

    // ❌ 경로 3 — SimpleDateFormat은 스레드 안전하지 않습니다
    private final SimpleDateFormat dateFormat = new SimpleDateFormat("yyyy-MM-dd");

    // ❌ 경로 1 — 호출 간에 값이 남습니다
    private long totalAmount;
    private String requesterName;

    public OrderReport report(String requesterName, List<Order> orders) {
        this.requesterName = requesterName;
        this.totalAmount = 0;

        for (Order order : orders) {
            this.totalAmount += order.amount();
        }

        return new OrderReport(
                this.requesterName,
                this.totalAmount,
                dateFormat.format(new Date())
        );
    }
}
```

단일 스레드로는 완벽하게 동작합니다. 테스트도 통과합니다.

### 3-2. 실행 흐름

스레드 둘이 겹칠 때의 한 가지 가능한 순서입니다.

1. 스레드 A: `requesterName = "kim"`, `totalAmount = 0`
2. 스레드 A: 합산 중 — `totalAmount = 12000`
3. 스레드 B: `requesterName = "lee"`, `totalAmount = 0` ← **A의 중간 합계가 지워집니다**
4. 스레드 B: 합산 — `totalAmount = 500`
5. 스레드 A: 남은 항목 합산 — `totalAmount = 3500` (12000은 사라졌습니다)
6. 스레드 A: `new OrderReport("lee", 3500, ...)` ← **이름도 금액도 둘 다 남이 아닙니다**

200 스레드 환경에서는 이 순서가 셀 수 없이 많습니다. 그리고 6번 결과는 예외를 던지지 않습니다. 그냥 그럴듯하게 틀린 리포트가 응답으로 나갑니다.

`dateFormat`은 더 고약합니다. `SimpleDateFormat`은 내부 `Calendar` 하나를 포맷·파싱 중에 공유해서 씁니다. 동시에 들어오면 날짜가 뒤섞이거나 `ArrayIndexOutOfBoundsException`, `NumberFormatException`이 전혀 무관한 지점에서 튀어나옵니다.

### 3-3. 왜 테스트에서 안 잡히는가

- 단위 테스트는 스레드 1개입니다. 필드가 있어도 간섭할 상대가 없습니다.
- `@SpringBootTest` + MockMvc도 기본은 요청을 순차로 보냅니다.
- 부하 테스트는 보통 "응답 시간"과 "에러율"을 봅니다. 틀린 값은 둘 다에 안 걸립니다.

**이 버그를 잡는 유일한 자동 수단은 동시성 테스트입니다.** 상태 있는 빈이 의심되면 같은 메서드를 여러 스레드로 때리고 결과가 전부 기대값인지 검증합니다.

```java
@Test
void 동시_요청에서_리포트가_섞이지_않습니다() throws Exception {
    int threads = 50;
    var executor = Executors.newVirtualThreadPerTaskExecutor();
    var futures = new ArrayList<Future<OrderReport>>();

    for (int i = 0; i < threads; i++) {
        String requester = "user-" + i;
        futures.add(executor.submit(() ->
                reportService.report(requester, List.of(new Order(1_000L)))));
    }

    for (Future<OrderReport> future : futures) {
        OrderReport report = future.get();
        assertThat(report.totalAmount()).isEqualTo(1_000L);
    }
    executor.close();
}
```

---

## 4. 그래도 싱글톤이 기본인 이유

트레이드오프 없이 기본값이 정해지지는 않습니다.

**장점**

- 인스턴스 생성·GC 비용이 요청 경로에서 사라집니다. 요청마다 서비스 객체 그래프를 다시 조립하지 않습니다.
- 의존성 그래프가 기동 시점에 전부 확정됩니다. 빈이 없거나 순환 참조면 첫 요청이 아니라 기동에서 터집니다.
- AOP 프록시, 캐시, 커넥션 풀 같은 "하나여야 하는 것"이 자연스럽게 하나가 됩니다.

**트레이드오프**

- 상태를 두면 즉시 공유 자원이 됩니다. 컴파일러도 스프링도 경고하지 않습니다.
- 스프링이 보장하는 건 수명주기입니다. 언제 만들고 무엇을 주입하는지는 보장하지만, **한 스레드의 쓰기가 다른 스레드에 어떻게 보이는지는 보장 대상이 아닙니다.** 그건 JMM과 내 코드의 몫입니다.
- 참고로 싱글톤 스코프는 GoF 싱글톤과 다릅니다. 공식 문서 표현으로 "컨테이너당·빈 정의당"입니다. 같은 클래스로 빈 정의를 둘 만들면 인스턴스는 둘입니다.

---

## 5. 상태를 어디로 옮기는가

### 5-1. 지역 변수 — 90%의 정답

필드로 뺀 중간 결과를 되돌리면 끝입니다. 비용도 0입니다.

```java
@Service
public class OrderReportService {

    // ✔️ DateTimeFormatter는 불변이고 스레드 안전합니다 (java.time 설계 목표)
    private static final DateTimeFormatter DATE_FORMAT =
            DateTimeFormatter.ofPattern("yyyy-MM-dd");

    private final Clock clock;

    public OrderReportService(Clock clock) {
        this.clock = clock;
    }

    public OrderReport report(String requesterName, List<Order> orders) {
        long totalAmount = orders.stream()      // ✔️ 지역 변수 — 스레드마다 별개입니다
                .mapToLong(Order::amount)
                .sum();

        String reportedAt = LocalDate.now(clock).format(DATE_FORMAT);
        return new OrderReport(requesterName, totalAmount, reportedAt);
    }
}
```

`Clock`과 `DateTimeFormatter`를 필드로 두는 건 안전합니다. 둘 다 불변이기 때문입니다. **필드에 둬도 되는 것과 안 되는 것의 기준은 "주입받았는가"가 아니라 "불변인가"입니다.** 시간 타입 선택은 day79-datetime-api.md를 참고합니다.

### 5-2. 호출마다 새 인스턴스가 필요하면 — `ObjectProvider`

상태 자체가 설계의 일부일 때가 있습니다. 여러 단계를 거치며 값을 쌓는 빌더형 객체가 그렇습니다.

```java
@Service
public class SettlementService {

    private final ObjectProvider<SettlementAccumulator> accumulators;

    public SettlementService(ObjectProvider<SettlementAccumulator> accumulators) {
        this.accumulators = accumulators;
    }

    public Settlement settle(List<Order> orders) {
        SettlementAccumulator accumulator = accumulators.getObject();  // ✔️ 호출마다 새 인스턴스
        orders.forEach(accumulator::add);
        return accumulator.toSettlement();
    }
}

@Component
@Scope("prototype")
public class SettlementAccumulator { /* 가변 필드를 가져도 됩니다 */ }
```

공식 문서가 권하는 형태가 이것입니다. 주입 지점을 `ObjectProvider<T>`로 선언하면 필요할 때마다 `getObject()`로 **현재 인스턴스를 그때그때 받습니다**. 다만 이 패턴을 쓸 바에는 `new SettlementAccumulator()`가 더 단순한 경우가 많습니다. 누적기가 다른 빈을 주입받아야 할 때만 의미가 있습니다.

### 5-3. 요청 단위 상태 — `@RequestScope`

요청 하나 안에서 여러 계층이 같은 값을 봐야 하면 요청 스코프가 맞습니다.

```java
@Component
@RequestScope   // proxyMode 기본값이 TARGET_CLASS입니다 (Javadoc)
public class AuditTrail {

    private final List<String> steps = new ArrayList<>();

    public void record(String step) { steps.add(step); }
    public List<String> steps() { return List.copyOf(steps); }
}
```

이걸 싱글톤 서비스에 그냥 주입해도 동작하는 이유가 프록시입니다. 스프링은 대상과 같은 public 인터페이스를 노출하는 프록시 객체를 만들어 싱글톤에 주입하고, 프록시는 호출 시점에 스코프 메커니즘에서 실제 객체를 찾아옵니다. 싱글톤은 자기가 프록시를 들고 있는 줄 모릅니다.

프록시의 한계는 day44-proxy-aop.md와 같습니다. CGLIB 프록시는 private 메서드를 가로채지 못하고, 공식 문서 표현으로 "그런 프록시에서 private 메서드를 호출하면 실제 스코프 대상 객체로 위임되지 않습니다."

### 5-4. 진짜 공유해야 하면 — 연산을 원자적으로 만듭니다

캐시나 카운터처럼 공유가 목적인 상태도 있습니다. 이때 `ConcurrentHashMap`으로 바꾸는 것만으로는 부족합니다.

```java
// ❌ 자료구조는 안전하지만 "확인 후 조작"이 원자적이지 않습니다
if (!rateLimits.containsKey(userId)) {
    rateLimits.put(userId, new AtomicInteger());
}
rateLimits.get(userId).incrementAndGet();
```

```java
// ✔️ 한 번의 원자적 연산으로 묶습니다
rateLimits.computeIfAbsent(userId, key -> new AtomicInteger()).incrementAndGet();
```

스레드 안전한 컬렉션이 보장하는 건 **개별 연산**입니다. 두 연산 사이에 다른 스레드가 끼어들 수 없다는 보장은 아닙니다. 이 구분은 day71-isolation-anomaly.md의 Lost Update와 구조가 완전히 같습니다.

---

## 6. prototype이 기대를 배신하는 두 지점

"상태 있는 빈은 prototype으로"가 그대로 먹히지 않는 이유입니다.

**첫째, 주입은 한 번뿐입니다.** 공식 문서가 직접 말합니다 — prototype 빈을 싱글톤에 주입하면 그 시점에 하나가 만들어져 주입되고, "그 prototype 인스턴스가 해당 싱글톤 빈에 공급되는 유일한 인스턴스"입니다. 문서는 더 분명하게 "주입이 한 번만 일어나므로 prototype 빈을 싱글톤 빈에 의존성 주입할 수 없다"고 못 박습니다. `@Scope("prototype")`을 붙이고 안심한 채 생성자 주입을 받으면, 스코프만 바뀌고 공유 상태는 그대로 남습니다. 증상이 전혀 달라지지 않습니다.

**둘째, 소멸 콜백이 호출되지 않습니다.** 공식 문서 표현으로 스프링은 prototype 빈의 전체 수명주기를 관리하지 않습니다. 조립해서 넘겨준 뒤로는 그 인스턴스를 기록하지 않으므로, 초기화 콜백은 모든 스코프에서 호출되지만 **prototype의 소멸 콜백은 호출되지 않습니다.** 자원을 쥔 객체를 prototype으로 만들고 `@PreDestroy`에 정리를 적어두면 그 코드는 영원히 실행되지 않습니다. 문서는 정리 책임이 클라이언트 코드에 있다고 명시합니다. 자원 정리는 day67-try-with-resources.md 쪽이 맞는 수단입니다.

---

## 7. `ThreadLocal`은 되지만 공짜가 아닙니다

"스레드마다 하나"는 `ThreadLocal`로 만들 수 있습니다. 실제로 많이 쓰입니다. 다만 JEP 506(Scoped Values, Java 25에서 정식 반영)이 `ThreadLocal`의 설계 결함 세 가지를 공식적으로 정리해 두었습니다.

1. **무제한 가변성** — `get`을 호출할 수 있는 코드는 언제든 `set`도 호출할 수 있습니다. 어느 메서드가 공유 상태를 어떤 순서로 바꾸는지 알기 어려워집니다.
2. **무제한 수명** — 한 번 `set`한 값은 스레드가 죽거나 `remove`를 부를 때까지 남습니다. JEP는 **스레드 풀을 쓸 때 제대로 비우지 않은 값이 무관한 다음 작업으로 새어 들어갈 수 있고, 이것이 위험한 보안 취약점이 될 수 있다**고 직접 지적합니다. Tomcat 스레드 풀이 정확히 이 상황입니다.
3. **값비싼 상속** — 자식 스레드가 상속하면 부모가 쓴 모든 값에 대해 저장 공간을 새로 할당합니다.

그래서 `ThreadLocal`을 쓰면 `finally`의 `remove()`가 선택이 아니라 필수입니다. 그리고 그 `remove()`를 업무 코드 각자에게 맡기면 언젠가 빠집니다. 필터나 인터셉터 한 곳에서 일괄 정리하는 쪽이 지켜집니다.

```java
public class TenantContext {
    private static final ThreadLocal<String> CURRENT = new ThreadLocal<>();

    public static void set(String tenantId) { CURRENT.set(tenantId); }
    public static String get() { return CURRENT.get(); }
    public static void clear() { CURRENT.remove(); }   // ⚠️ 호출을 빠뜨리면 다음 요청에 새어 나갑니다
}
```

```java
@Component
public class TenantFilter extends OncePerRequestFilter {
    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        TenantContext.set(request.getHeader("X-Tenant-Id"));
        try {
            chain.doFilter(request, response);
        } finally {
            TenantContext.clear();   // ✔️ 예외가 나도 반드시 비웁니다
        }
    }
}
```

가상 스레드를 켜면(`spring.threads.virtual.enabled=true`) 상황이 조금 달라집니다. 요청마다 새 가상 스레드가 생기고 금방 끝나므로 재사용으로 인한 누수는 완화됩니다. JEP도 "스레드가 빨리 끝나면 종료가 알아서 값을 제거하므로 `remove` 호출이 불필요하다"고 적습니다. 대신 스레드가 수십만 개가 되면 사본의 메모리 발자국이 무시할 수 없어진다고 덧붙입니다.

`ScopedValue`가 이 자리를 대체하려는 API입니다. `ScopedValue.where(...).run(...)` 블록을 벗어나면 바인딩이 사라져서 수명이 코드 구조로 고정되고, 값이 불변입니다. 다만 스프링과 서블릿 스택이 요청 컨텍스트를 `ScopedValue`로 옮기는 작업은 현재진행형입니다.

<!-- TODO: 확인 필요 — Spring Framework 7.x / Boot 4.x에서 RequestContextHolder·SecurityContextHolder가 ScopedValue 기반 저장 전략을 공식 지원하는지는 확인하지 못했습니다. 지금은 ThreadLocal 전략을 전제로 작성했습니다. -->

---

## 8. 실무에서 찾아보는 패턴 — 스프링 자신은 어떻게 하는가

스프링 자체가 요청별 상태를 싱글톤 필드에 두지 않는 좋은 예시입니다.

- `RequestContextHolder` — 현재 요청의 속성을 스레드에 묶어 두고 정적 메서드로 꺼냅니다. `DispatcherServlet`이나 `RequestContextFilter`가 요청 시작에 넣고 끝에 비웁니다.
- `SecurityContextHolder` — 인증 주체를 같은 방식으로 들고 있습니다. 그래서 `@Service` 어디서든 현재 사용자를 꺼낼 수 있습니다.
- `@RequestScope` 빈 — 5-3의 스코프 프록시가 위 홀더 위에 올라간 설탕입니다.

이 구조의 대가가 **요청 스레드를 벗어나면 끊긴다**는 것입니다. `@Async` 메서드나 직접 만든 `ExecutorService`로 넘어간 작업은 다른 스레드에서 실행되므로 요청 스코프가 활성이 아닙니다. 요청 스코프 빈을 거기서 건드리면 스코프가 활성이 아니라는 예외로 실패합니다. 설령 요청 속성을 복사해 넘기더라도 원래 요청이 먼저 끝나면 그 속성은 이미 무효입니다.

**해법은 컨텍스트를 전파하려 애쓰는 게 아니라 필요한 값을 평범한 파라미터로 넘기는 것입니다.** 비동기 경계를 넘길 땐 `tenantId`, `userId`를 인자로 전달합니다. 로깅용 MDC나 추적 컨텍스트처럼 정말 전파가 필요한 것만 `TaskDecorator`로 처리합니다(day78-distributed-tracing.md).

---

## 9. 함정

**(1) `@Scope("prototype")`으로 바꿨는데 증상이 그대로입니다**

- **증상**: 상태 공유 버그를 발견해 prototype으로 바꿨지만 동시 요청에서 값이 여전히 섞입니다.
- **원인**: 싱글톤이 생성자 주입으로 받는 순간 prototype 인스턴스 하나가 고정됩니다. 주입은 한 번뿐입니다.
- **해법**: `ObjectProvider<T>.getObject()`나 메서드 주입으로 호출 시점에 받습니다(5-2). 또는 상태를 지역 변수로 되돌립니다.

**(2) `@PreDestroy`에 적은 정리 코드가 실행되지 않습니다**

- **증상**: prototype 빈이 쥔 커넥션·스트림이 반납되지 않고 누적됩니다.
- **원인**: 스프링은 prototype 인스턴스를 기록하지 않으므로 소멸 콜백을 호출하지 않습니다.
- **해법**: 자원 수명을 스프링에 맡기지 않고 `try-with-resources`로 호출자가 닫습니다.

**(3) `ThreadLocal` 값이 다음 요청에 보입니다**

- **증상**: A 사용자가 로그아웃한 뒤 B 사용자 요청에 A의 테넌트·권한이 적용됩니다. 재현이 트래픽 의존적입니다.
- **원인**: 스레드 풀이 스레드를 재사용하는데 `remove()`를 안 불렀습니다. 예외 경로에서 빠뜨린 경우가 특히 많습니다.
- **해법**: 필터의 `finally`에서 일괄 정리합니다(7절). 비동기 태스크는 `TaskDecorator`에서 같은 처리를 합니다.

**(4) `@Async` 안에서 요청 스코프 빈이 터집니다**

- **증상**: 스코프가 활성이 아니라는 메시지와 함께 `scopedTarget.*` 빈 생성이 실패합니다.
- **원인**: 요청 스코프는 요청 스레드에 묶여 있고, `@Async`는 다른 스레드 풀에서 실행됩니다.
- **해법**: 필요한 값을 메서드 파라미터로 넘깁니다. 요청 스코프 빈 자체를 비동기 경계 밖으로 내보내지 않습니다.

**(5) `ConcurrentHashMap`으로 바꿨는데 카운트가 안 맞습니다**

- **증상**: 집계값이 실제보다 작게 나옵니다. 부하가 높을수록 오차가 커집니다.
- **원인**: `containsKey` → `put`, `get` → `put` 같은 "확인 후 조작"은 원자적이지 않습니다.
- **해법**: `computeIfAbsent`, `merge`, `AtomicLong`처럼 한 번의 원자적 연산으로 묶습니다(5-4).

**(6) `static` 필드를 스코프로 고치려 합니다**

- **증상**: 어떤 스코프로 바꿔도 값이 공유됩니다.
- **원인**: `static`은 클래스에 붙으므로 빈 스코프와 무관합니다.
- **해법**: `static`을 제거하거나, 불변으로 만들거나(`static final` + 불변 객체), 5-4의 원자적 자료구조로 바꿉니다.

---

## 10. 한 줄로 판단하는 기준

빈의 필드를 볼 때 질문 하나면 됩니다. **"이 필드는 요청이 끝난 뒤 다음 요청이 봐도 괜찮은 값인가?"**

- 괜찮다 → 설정값·협력 빈·불변 객체입니다. 필드로 둡니다.
- 안 괜찮다 → 이 요청만의 값입니다. 지역 변수·파라미터·반환값으로 옮깁니다.
- 의도적으로 공유해야 한다 → 5-4로 가서, 자료구조가 아니라 **연산 단위**를 원자적으로 만듭니다.

스코프를 바꾸는 선택은 셋 다 안 될 때 마지막에 꺼냅니다. 스코프를 바꾸면 수명주기 보장과 프록시 동작이 함께 바뀌고, 그쪽에서 6절의 함정이 기다립니다.

---

## 11. 참고자료

- [Spring Framework Reference — Bean Scopes](https://docs.spring.io/spring-framework/reference/core/beans/factory-scopes.html)
- [Spring Framework Reference — Scoped Beans as Dependencies](https://docs.spring.io/spring-framework/reference/core/beans/factory-scopes.html#beans-factory-scopes-other-injection)
- [Spring Framework Reference — Method Injection](https://docs.spring.io/spring-framework/reference/core/beans/dependencies/factory-method-injection.html)
- [Spring Framework Javadoc — `@RequestScope`](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/web/context/annotation/RequestScope.html)
- [Spring Framework Javadoc — `RequestContextHolder`](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/web/context/request/RequestContextHolder.html)
- [Apache Tomcat 11 — HTTP Connector (`maxThreads`)](https://tomcat.apache.org/tomcat-11.0-doc/config/http.html)
- [JEP 506: Scoped Values (JDK 25, Delivered)](https://openjdk.org/jeps/506)
- [JEP 491: Synchronize Virtual Threads without Pinning (JDK 24)](https://openjdk.org/jeps/491)
- 관련 챕터: day08-di-why.md, day32-bean-lifecycle.md, day44-proxy-aop.md, day67-try-with-resources.md, day71-isolation-anomaly.md, day78-distributed-tracing.md, day79-datetime-api.md

# 이벤트 기반 설계의 첫 단계 — "이벤트를 쏜다"는 실제로 무엇을 바꾸는가

## 1. 핵심 개념

이벤트는 **이미 일어난 사실의 기록**입니다. 명령은 "이걸 해라"이고 이벤트는 "이런 일이 있었다"입니다. 차이는 문법이 아니라 **수신자를 아는 쪽이 누구인가**입니다. 명령은 보내는 쪽이 받는 쪽을 알아야 하고, 이벤트는 몰라도 됩니다.

> 이걸 분리하지 않으면 **도메인 서비스가 다른 모든 기능의 목록이 됩니다.** 주문을 저장하려고 만든 `placeOrder()`에 재고 차감이 붙고, 쿠폰 확정이 붙고, 알림이 붙고, 통계 갱신이 붙습니다. 6개월 뒤 "주문 완료 시 적립금 지급" 요구가 오면 또 `OrderService`를 고칩니다. 주문 로직을 한 줄도 건드리지 않는 기능인데 주문 테스트가 깨집니다.

이 문서는 하나의 질문에 답합니다. **이벤트 기반으로 바꾼다는 것은 코드에서 무엇을 바꾸는 일이고, 브로커를 들이기 전에 할 수 있는 첫 단계는 무엇인가.**

브로커를 끼웠을 때 무엇이 분리되고 어떤 대가가 생기는지는 `daily/day69-message-queue-why.md`에서 다뤘습니다. 여기서는 그 앞 단계, **이벤트 자체를 어떻게 정의하고 어디에 경계를 두는가**를 봅니다.

## 2. 명령과 이벤트를 가르는 선

### 2-1. 이름이 설계를 결정합니다

이벤트 이름은 **과거형 + 도메인 사실**입니다. `OrderPlaced`, `PaymentApproved`, `CouponExpired`처럼 씁니다. 수신자가 무엇을 할지는 이름에 들어가지 않습니다.

```java
// ❌ 이벤트 모양이지만 사실은 명령 — 발행자가 수신자의 할 일을 알고 있습니다
public record SendOrderMailEvent(Long orderId, String email) {}
public record DecreaseStockEvent(Long productId, int quantity) {}

// ✔️ 사실만 적습니다 — 누가 무엇을 하는지는 수신자가 정합니다
public record OrderPlaced(Long orderId, Long memberId, List<OrderLine> lines, Instant placedAt) {}
```

`SendOrderMailEvent`를 쓰면 **메일 발송이라는 결정이 주문 쪽에 남습니다.** 메일을 카카오 알림톡으로 바꾸는 순간 이벤트 이름부터 고쳐야 합니다. 이건 이벤트 발행이 아니라 메서드 호출을 한 단계 우회한 것입니다.

판별법은 간단합니다. **그 이벤트의 수신자를 0개로 만들었을 때 이름이 어색해지면 이벤트가 아닙니다.** 아무도 메일을 안 보내는데 `SendOrderMailEvent`가 날아가는 건 말이 안 되고, 아무도 안 받아도 `OrderPlaced`는 여전히 참입니다.

### 2-2. 둘의 성질이 다릅니다

| | 명령 (Command) | 이벤트 (Event) |
|---|---|---|
| 의미 | 아직 안 일어난 일의 요청 | 이미 일어난 사실 |
| 수신자 | 정확히 1개, 발행자가 지정 | 0~N개, 발행자가 모름 |
| 거절 | 가능 (검증 실패, 거부) | 불가 — 과거를 거절할 수 없습니다 |
| 실패의 책임 | 보낸 쪽이 결과를 책임짐 | 받은 쪽이 자기 처리를 책임짐 |
| 반환값 | 있음 | 없음 |

실무에서 제일 많이 어기는 건 세 번째 줄입니다. 재고가 부족해서 주문을 거절해야 한다면 그건 이벤트로 풀 문제가 아닙니다. **거절이 필요한 건 명령이고, 동기로 호출해야 합니다.** 이벤트로 바꿔놓고 "재고 부족이면 주문을 취소 처리"하는 보상 로직을 짜기 시작하면, 동기 호출 한 줄로 끝날 일을 분산 트랜잭션으로 만든 겁니다.

## 3. 이벤트에 무엇을 담는가

Martin Fowler는 사람들이 "이벤트 기반"이라는 한 단어로 서로 다른 네 가지를 부른다고 정리합니다. **이벤트 통지(Event Notification)**, **이벤트에 상태를 실어 보내기(Event-Carried State Transfer)**, **이벤트 소싱(Event Sourcing)**, **CQRS**입니다. 뒤의 둘은 이벤트가 진실의 원천이 되거나 읽기/쓰기 모델을 쪼개는 훨씬 큰 결정이고, 앞의 둘이 첫 단계에서 실제로 고르는 선택지입니다([What do you mean by "Event-Driven"?](https://martinfowler.com/articles/201701-event-driven.html)).

### 3-1. 통지 — ID만 보냅니다

```java
public record OrderPlaced(Long orderId) {}
```

가장 가볍고, 가장 많이 쓰입니다. 그런데 수신자가 주문 정보를 알아야 하니 **다시 주문 쪽에 물어봅니다.** 결합이 "호출"에서 "조회"로 모습만 바꿔 돌아옵니다. 조회 API가 죽으면 수신자도 같이 죽고, 이벤트 한 건에 조회 한 번이 붙으니 트래픽도 N배가 됩니다.

더 고약한 함정은 **되묻는 시점의 상태가 이벤트 시점의 상태가 아니라는 것**입니다. `OrderPlaced`를 받아서 조회했더니 그 주문은 이미 취소돼 있습니다. "주문 완료 알림"을 보내려다 취소된 주문의 알림을 보냅니다.

### 3-2. 상태 전달 — 그때의 값을 담아 보냅니다

```java
public record OrderPlaced(
        Long orderId, Long memberId, long totalAmount,
        List<OrderLine> lines, Instant placedAt) {}
```

수신자가 스스로 처리를 끝낼 수 있습니다. 발행자가 내려가 있어도 동작하고, 이벤트는 "그 시점의 사실"이라 시간이 지나도 의미가 변하지 않습니다.

대가는 두 개입니다. 첫째, **이벤트 스키마가 공개 API가 됩니다.** 필드를 지우거나 의미를 바꾸면 모든 수신자가 깨집니다. 둘째, 수신자가 같은 데이터의 복사본을 들고 있게 되므로 어디까지가 최신인지를 관리해야 합니다.

### 3-3. 고르는 기준

- 수신자가 **그 순간의 사실**로 판단해야 한다 → 상태를 담습니다 (알림, 정산, 감사 로그)
- 수신자가 **항상 최신값**이 필요하다 → ID만 보내고 조회합니다 (화면 캐시 무효화)
- 둘 다 애매하면 **상태를 담는 쪽**이 안전합니다. 과거의 사실은 변하지 않으므로 재처리에도 같은 결과가 나옵니다.

## 4. 코드로 보는 첫 단계

브로커 없이 한 애플리케이션 안에서 시작할 수 있습니다. Spring은 `ApplicationEventPublisher`를 기본 제공하고, Spring 4.2부터 이벤트가 `ApplicationEvent`를 상속할 필요가 없습니다. 임의 객체를 발행하면 프레임워크가 감싸줍니다([Standard and Custom Events](https://docs.spring.io/spring-framework/reference/core/beans/context-introduction.html)).

### 4-1. 직접 호출 ❌

```java
@Service
@RequiredArgsConstructor
public class OrderService {

    private final OrderRepository orderRepository;
    private final StockService stockService;
    private final CouponService couponService;
    private final NotificationService notificationService;
    private final PointService pointService;

    @Transactional
    public Long placeOrder(OrderCommand command) {
        Order order = orderRepository.save(Order.from(command));
        stockService.decrease(order.getLines());
        couponService.confirmUse(order.getCouponId());
        notificationService.sendOrderPlaced(order);
        pointService.accumulate(order.getMemberId(), order.getTotalAmount());
        return order.getId();
    }
}
```

의존성이 5개입니다. 기능이 늘면 6개가 됩니다. 단위 테스트를 쓰려면 쓰지도 않는 목(mock)을 네 개 만들어야 합니다.

### 4-2. 사실만 발행 ✔️

```java
@Service
@RequiredArgsConstructor
public class OrderService {

    private final OrderRepository orderRepository;
    private final ApplicationEventPublisher eventPublisher;

    @Transactional
    public Long placeOrder(OrderCommand command) {
        Order order = orderRepository.save(Order.from(command));
        eventPublisher.publishEvent(OrderPlaced.from(order));
        return order.getId();
    }
}

@Component
@RequiredArgsConstructor
public class PointAccumulator {

    private final PointService pointService;

    @EventListener
    public void on(OrderPlaced event) {
        pointService.accumulate(event.memberId(), event.totalAmount());
    }
}
```

적립금 지급을 추가할 때 `OrderService`를 열지 않습니다. 리스너 클래스 하나를 추가합니다. 호출 순서가 필요하면 리스너에 `@Order`를 붙입니다.

### 4-3. 그런데 여기서 아무것도 분리되지 않았습니다 ⚠️

이게 "이벤트로 바꿨는데 왜 여전히 같이 죽는가"의 답입니다. 기본 동작을 정확히 알아야 합니다.

1. **동기입니다.** 기본 멀티캐스터의 `setTaskExecutor` 기본값은 "모든 리스너를 호출 스레드에서 동기 실행"하는 것과 같고, `publishEvent()`는 모든 리스너가 끝날 때까지 블로킹합니다([SimpleApplicationEventMulticaster](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/context/event/SimpleApplicationEventMulticaster.html)).
2. **발행자의 트랜잭션 안에서 돕니다.** 레퍼런스는 이 동기·단일 스레드 방식의 장점으로 "트랜잭션 컨텍스트가 있으면 리스너가 발행자의 트랜잭션 컨텍스트 안에서 동작한다"를 꼽습니다.
3. **예외가 발행자에게 올라갑니다.** 에러 핸들러를 지정하지 않은 기본 상태에서는 "리스너 예외가 현재 멀티캐스트를 중단시키고 이벤트 발행자에게 전파"됩니다(위 Javadoc).

즉 적립금 로직이 터지면 **주문이 롤백됩니다.** 뒤에 등록된 리스너들도 실행되지 않습니다. 결합을 없앤 게 아니라 컴파일러가 보는 결합을 런타임에 숨긴 상태입니다. 직접 호출보다 나쁠 수 있습니다 — 호출 스택에 안 보이니까요.

### 4-4. 경계를 넘기기

그래서 "주문과 같이 성공해야 하는 일"과 "주문 후에 따라오는 일"을 나눠야 합니다. 후자는 커밋 뒤로 보냅니다.

```java
@Component
@RequiredArgsConstructor
public class PointAccumulator {

    private final PointService pointService;

    @Async
    @TransactionalEventListener                       // 기본 phase = AFTER_COMMIT
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void on(OrderPlaced event) {
        pointService.accumulate(event.memberId(), event.totalAmount());
    }
}
```

세 애너테이션이 각각 하는 일이 다릅니다.

- `@TransactionalEventListener`: 발행 시점이 아니라 **커밋 후**에 리스너를 호출합니다. 유효한 단계는 `BEFORE_COMMIT`, `AFTER_COMMIT`(기본), `AFTER_ROLLBACK`, `AFTER_COMPLETION`입니다. 롤백된 주문의 적립금이 지급되는 사고를 이게 막습니다([Transaction-bound Events](https://docs.spring.io/spring-framework/reference/data-access/transaction/event.html)).
- `@Async`: 발행자 스레드에서 떼어냅니다. 안 붙이면 커밋 후에 실행될 뿐 응답 시간에는 그대로 더해집니다.
- `@Transactional(REQUIRES_NEW)`: 자기 트랜잭션을 엽니다. **이게 없으면 쓰기가 조용히 사라집니다** (다음 절).

Spring Modulith를 쓰면 이 조합에 `@ApplicationModuleListener`라는 이름이 붙어 있습니다. 문서가 `@Async` + `@Transactional(propagation = REQUIRES_NEW)` + `@TransactionalEventListener`의 축약이라고 명시합니다([Working with Application Events](https://docs.spring.io/spring-modulith/reference/events.html)).

## 5. 흐름이 코드에서 사라집니다

이게 이벤트 기반의 진짜 비용이고, 도입 후 몇 달 뒤에 청구됩니다.

여러 이벤트를 거쳐 흐르는 전체 논리는 **어느 소스 파일에도 적혀 있지 않습니다.** Fowler는 이 흐름이 프로그램 텍스트에 명시되지 않아 동작 중인 시스템을 관찰해야만 파악되는 경우가 많고, 그래서 디버깅과 변경이 어려워진다고 지적합니다. 팀이 결합을 줄이는 데 집중하다가 큰 흐름에 대한 시야를 잃은 걸 모르고 지나치는 게 위험이라고 말합니다([What do you mean by "Event-Driven"?](https://martinfowler.com/articles/201701-event-driven.html)).

실무에서는 이렇게 나타납니다. 신입이 "주문하면 적립금이 왜 2번 들어오죠?"라고 묻는데, `OrderService`를 아무리 읽어도 적립금이라는 단어가 없습니다. 리스너를 전부 찾아야 하고, IDE 검색으로는 `OrderPlaced`를 받는 곳만 나오지 그 리스너가 다시 발행한 이벤트까지는 따라가지 못합니다.

최소한 두 가지는 같이 깔아야 합니다.

1. **trace id를 이벤트에 태워 로그를 잇습니다.** `@Async` 리스너는 스레드가 바뀌는데, 레퍼런스는 "ThreadLocal과 로깅 컨텍스트는 이벤트 처리에 기본적으로 전파되지 않는다"고 명시합니다. MDC가 끊기면 요청 하나를 끝까지 못 따라갑니다(`daily/day42-structured-log-trace-id.md`).
2. **이벤트 흐름을 문서로 남깁니다.** 코드가 못 보여주는 걸 어딘가는 보여줘야 합니다. `OrderPlaced → (재고, 적립금, 알림)` 수준의 목록이라도 있어야 합니다.

## 6. 로컬 이벤트에서 브로커로 — 유실이 드러나는 지점

`@Async` + 커밋 후 발행까지 오면 꽤 좋아 보입니다. 그런데 큐가 **힙에 있습니다.** 커밋은 됐고 리스너는 실행 전인 상태에서 프로세스가 죽으면 그 이벤트는 사라집니다. 주문은 있고 적립금은 없습니다. 에러 로그도 없습니다. 배포할 때마다 조금씩 생깁니다.

여기서 선택지가 둘입니다.

**이벤트를 DB에 적고 처리 여부를 기록합니다.** Spring Modulith의 이벤트 발행 레지스트리가 이 구조입니다. 발행 시점에 수신할 트랜잭셔널 리스너를 찾아 각각에 대한 로그 항목을 **원래 비즈니스 트랜잭션에 포함시켜** 기록하고, 리스너가 성공하면 완료로 표시하고, 실패하면 항목을 남겨둬 재시도할 수 있게 합니다. `spring.modulith.events.republish-outstanding-events-on-restart`를 켜면 재시작 시 미완료 이벤트를 자동 재발행합니다(2.0부터 발행 상태가 `PUBLISHED`/`PROCESSING`/`COMPLETED`/`FAILED`/`RESUBMITTED`로 관리됩니다 — [Working with Application Events](https://docs.spring.io/spring-modulith/reference/events.html), 2.1.2 기준).

**브로커로 넘깁니다.** 이벤트를 다른 애플리케이션이 받아야 할 때입니다. 이때부터는 중복·순서·이중 쓰기가 전부 따라옵니다(`daily/day69-message-queue-why.md`).

순서를 뒤집지 않는 게 중요합니다. **먼저 이벤트를 정의하고, 그다음에 전달 수단을 고릅니다.** 이벤트 정의가 엉망이면 Kafka를 깔아도 `SendOrderMailEvent`가 토픽을 타고 날아다닐 뿐입니다.

## 7. 이벤트 계약 — 봉투를 먼저 정합니다

프로세스 밖으로 나가는 순간 이벤트는 **버전이 있는 공개 계약**입니다. 바퀴를 다시 만들 필요는 없고, CNCF의 CloudEvents가 필수 속성으로 정한 네 개가 그대로 체크리스트가 됩니다([CloudEvents v1.0 spec](https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md)).

| 속성 | 뜻 | 실무에서 쓰는 곳 |
|---|---|---|
| `id` | 이벤트 식별자 | 중복 판정 |
| `source` | 발생한 컨텍스트(URI 참조) | 어디서 왔는지 추적 |
| `type` | 이벤트 종류 (역 DNS 접두 권장) | 라우팅·필터링 |
| `specversion` | 스펙 버전 | 파싱 호환성 |

여기서 바로 쓸 수 있는 규칙이 하나 나옵니다. 스펙은 **`source` + `id` 조합이 각 이벤트마다 유일**해야 한다고 요구하고, 소비자는 이 조합이 같은 이벤트를 중복으로 취급할 수 있다고 적습니다. 즉 이 두 값이 **그대로 멱등 키**입니다. 처리한 `(source, id)`를 테이블에 유니크 제약으로 쌓으면 중복 수신을 방어할 수 있습니다(`daily/day21-idempotency.md`).

스키마 진화 규칙도 처음에 정해두는 게 싸게 끝납니다.

- 필드 **추가**는 괜찮습니다. 모르는 필드를 무시하도록 역직렬화를 설정해두면 수신자가 안 깨집니다.
- 필드 **삭제·의미 변경**은 호환되지 않습니다. 새 `type`을 만들고 한동안 둘을 같이 발행합니다.
- 통화 단위, 시간대 같은 건 이름에 박아둡니다. `amount`보다 `totalAmountKrw`가 1년 뒤에 유용합니다.

## 8. 이벤트로 바꾸지 말아야 할 때

- **수신자가 정확히 하나이고 앞으로도 하나입니다.** 그냥 호출하는 게 읽기 쉽습니다.
- **결과가 응답에 필요합니다.** 재고 확인 결과로 주문 성공/실패가 갈리면 명령입니다.
- **거절이 비즈니스 규칙입니다.** 과거의 사실은 거절할 수 없습니다(§2-2).
- **같은 트랜잭션 안에서 반드시 함께 성공해야 합니다.** 이건 이벤트가 아니라 한 집합체(aggregate)의 일부일 가능성이 높습니다.

반대로 다음 신호가 보이면 이벤트가 맞습니다. 핵심 도메인 서비스의 의존성이 계속 늘어나고, 그 서비스를 고치는 이유 대부분이 **그 도메인과 무관한 기능 추가**일 때입니다.

## 9. 함정

**이벤트로 바꿨는데 리스너 하나가 터져서 주문이 롤백됩니다**
- **증상**: 알림 서버 장애 시간 동안 주문이 전부 실패합니다. 직접 호출하던 때와 똑같습니다.
- **원인**: `@EventListener`는 동기이고 발행자의 트랜잭션·스레드에서 돌며, 리스너 예외가 발행자에게 전파됩니다(§4-3).
- **해법**: 함께 커밋될 필요가 없는 리스너는 `@TransactionalEventListener`(기본 `AFTER_COMMIT`)로 옮기고 `@Async`를 붙입니다. 동기로 남겨야 한다면 그건 분리 대상이 아니라 같은 트랜잭션의 일부라고 인정하는 게 맞습니다.

**`AFTER_COMMIT` 리스너에서 저장한 데이터가 조용히 사라집니다** ⚠️
- **증상**: 예외도 없고 로그도 정상인데 리스너가 저장한 행이 DB에 없습니다.
- **원인**: Javadoc이 경고로 적어둔 동작입니다. `AFTER_COMMIT`·`AFTER_ROLLBACK`·`AFTER_COMPLETION` 단계에서는 트랜잭션이 이미 커밋/롤백됐지만 트랜잭션 자원은 아직 살아 있을 수 있어서, 이 시점에 수행된 데이터 접근 코드는 원래 트랜잭션에 "참여"하지만 **변경은 커밋되지 않습니다**([TransactionalEventListener Javadoc](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/transaction/event/TransactionalEventListener.html)).
- **해법**: 리스너에 `@Transactional(propagation = Propagation.REQUIRES_NEW)`를 붙여 새 트랜잭션을 엽니다. 리스너가 호출하는 하위 서비스까지 같은 기준으로 확인합니다.

**테스트에서는 리스너가 아예 호출되지 않습니다**
- **증상**: 서비스 메서드를 단독 호출하는 테스트에서 리스너가 한 번도 실행되지 않습니다.
- **원인**: 트랜잭션 안에서 발행되지 않은 이벤트는 폐기됩니다. `fallbackExecution` 플래그를 명시적으로 켜지 않으면 리스너가 호출되지 않습니다(위 Javadoc).
- **해법**: 테스트가 트랜잭션 경계를 만들도록 바꾸거나, 그 리스너에 한해 `fallbackExecution = true`를 둡니다. 운영 코드에서 발행 지점이 트랜잭션 밖인 경우가 없는지도 같이 확인합니다.

**비동기 리스너가 실패했는데 아무 기록이 없습니다**
- **증상**: 적립금이 안 들어왔는데 에러 로그가 없습니다. 재현도 안 됩니다.
- **원인**: 비동기 리스너가 던진 예외는 호출자에게 전파되지 않습니다. 그리고 ThreadLocal과 로깅 컨텍스트가 기본적으로 전파되지 않아 trace id도 끊깁니다([Standard and Custom Events](https://docs.spring.io/spring-framework/reference/core/beans/context-introduction.html)).
- **해법**: `AsyncUncaughtExceptionHandler`를 등록해 미처리 예외를 반드시 로그로 남깁니다. 유실이 돈으로 이어지면 §6의 발행 레지스트리나 아웃박스로 올립니다.

**이벤트를 받아서 조회했더니 상태가 이미 달라져 있습니다**
- **증상**: 취소된 주문에 "주문 완료" 알림이 나갑니다.
- **원인**: ID만 담은 통지 방식에서, 되묻는 시점의 상태는 이벤트 시점의 상태가 아닙니다(§3-1). 비동기 지연이 길수록 자주 생깁니다.
- **해법**: 그 순간의 사실로 판단해야 하는 리스너에는 상태를 실어 보냅니다. 조회가 필요하다면 이벤트의 시각·버전과 조회 결과를 비교해 더 최신이면 건너뜁니다.

**리스너가 늘어나면서 실행 순서에 의존하기 시작합니다**
- **증상**: 리스너 클래스 하나를 추가했더니 무관한 기능이 깨집니다.
- **원인**: 리스너 간 암묵적 순서 의존입니다. `@Order`로 순서를 고정하는 순간 그 리스너들은 사실 하나의 절차이고, 이벤트로 쪼갤 대상이 아니었습니다.
- **해법**: 순서가 필요한 묶음은 하나의 리스너(또는 서비스 메서드)로 합칩니다. 이벤트는 **서로 순서를 모르는 일들** 사이에만 둡니다.

## 10. 참고자료

- [What do you mean by "Event-Driven"? — Martin Fowler](https://martinfowler.com/articles/201701-event-driven.html)
- [Spring Framework — Standard and Custom Events](https://docs.spring.io/spring-framework/reference/core/beans/context-introduction.html)
- [Spring Framework — Transaction-bound Events](https://docs.spring.io/spring-framework/reference/data-access/transaction/event.html)
- [TransactionalEventListener Javadoc](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/transaction/event/TransactionalEventListener.html)
- [SimpleApplicationEventMulticaster Javadoc](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/context/event/SimpleApplicationEventMulticaster.html)
- [Spring Modulith — Working with Application Events](https://docs.spring.io/spring-modulith/reference/events.html)
- [CloudEvents Specification v1.0](https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md)
- 관련 문서: `daily/day69-message-queue-why.md`, `daily/day21-idempotency.md`, `daily/day42-structured-log-trace-id.md`, `daily/day20-service-layer-design.md`

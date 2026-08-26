# 서비스 계층의 책임은 어디까지인가

> 이 문서가 답할 질문: **서비스 계층에 무엇을 넣고 무엇을 빼야 하며, 그 경계는 무엇이 정하는가?**
>
> 분류: 기술이해형(왜 존재하는가). "서비스를 안 만들면 무슨 일이 벌어지는가"에서 출발해, 실무에서 실제로 경계를 긋는 기준까지 내려갑니다.
>
> 기준: Spring Boot 4.1(2026-06-10 GA, [릴리스 공지](https://spring.io/blog/2026/06/10/spring-boot-4/)) · Spring Framework 7 기준으로 서술합니다.

## 1. 핵심 개념 — 서비스는 "유스케이스 하나"의 이름입니다

서비스 계층은 **애플리케이션이 제공하는 작업 하나를 이름 붙이고, 그 작업이 성공하거나 실패하는 단위를 정하는 계층**입니다. `cancelOrder`, `registerMember` 같은 메서드 하나가 곧 유스케이스 하나입니다.

여기서 중요한 건 "비즈니스 로직을 담는 곳"이라는 흔한 정의가 **틀렸다**는 점입니다. 그 정의를 그대로 따르면 서비스가 3000줄이 됩니다.

> 서비스를 안 만들고 컨트롤러에서 리포지터리를 바로 쓰면 어떻게 될까요. 처음엔 잘 됩니다. 그러다 같은 "주문 취소"가 웹 API, 관리자 배치, Kafka 컨슈머 세 군데에서 필요해집니다. 세 곳에 로직이 복사되고, 어느 날 취소 정책이 바뀌면 **두 곳만 고쳐집니다.** 남은 한 곳은 6개월 뒤 정산이 안 맞을 때 발견됩니다.
>
> 반대 방향도 똑같이 아픕니다. 서비스를 만들긴 했는데 검증·조회·계산·알림·로깅을 전부 밀어 넣으면, `OrderService`는 800줄이 되고 필드로 주입받은 빈이 12개가 됩니다. 이 클래스는 **테스트를 쓸 수 없습니다.** 목(mock)을 12개 세워야 메서드 하나가 돌아가기 때문입니다.

두 실패는 같은 원인에서 나옵니다. **경계를 "무엇을 넣을까"로 정했기 때문입니다.** 경계는 "무엇이 함께 성공하고 함께 실패해야 하는가"로 정합니다.

## 2. 구조 — 서비스가 실제로 지는 책임

서비스가 **져야 하는** 책임은 네 가지입니다.

| 책임 | 구체적으로 | 왜 여기인가 |
|---|---|---|
| 유스케이스 조율 | 무엇을 어떤 순서로 부를지 | 이 순서를 아는 유일한 곳 |
| 트랜잭션 경계 | 어디서 시작하고 어디서 커밋할지 | 원자적으로 묶일 범위를 아는 유일한 곳 |
| 인가(authorization) | 이 사용자가 이 주문을 건드려도 되는가 | 도메인 규칙이자 유스케이스마다 다름 |
| 외부 세계 조율 | 결제 게이트웨이 호출, 이벤트 발행 | 도메인 객체가 알면 안 되는 것 |

서비스가 **지면 안 되는** 책임은 이렇습니다.

- **HTTP를 아는 것** — `HttpServletRequest`, `ResponseEntity`, `MultipartFile`을 파라미터로 받으면 그 서비스는 배치에서 못 씁니다.
- **SQL을 아는 것** — 서비스에 JPQL 문자열이 있으면 리포지터리가 존재할 이유가 없습니다.
- **도메인 규칙 자체** — "취소 가능한 상태인가", "환불액은 얼마인가"는 `Order`가 압니다.

세 번째가 가장 자주 무너집니다. Martin Fowler는 도메인 객체가 getter·setter 뭉치로 전락하고 로직이 전부 서비스로 빠져나간 상태를 **빈약한 도메인 모델(Anemic Domain Model)** 이라 부르며, 도메인 모델의 비용은 다 내면서 이득은 하나도 못 얻는 상태라고 정리했습니다([Fowler, 2003](https://martinfowler.com/bliki/AnemicDomainModel.html)).

여기서 오해를 하나 짚습니다. Fowler는 **서비스 계층 자체를 비판한 게 아닙니다.** 서비스 계층은 얇게 유지하고, 그 아래의 도메인 객체가 행동을 갖게 하라는 쪽입니다. 서비스에서 발견되는 행동이 많을수록 도메인 모델의 이득을 스스로 깎아먹는다는 것이 요지입니다.

## 3. 흐름

### 3-1. 계층이 각각 결정하는 것

```
HTTP 요청
  → 컨트롤러      : 형식 검증(@Valid), DTO 변환, 상태 코드 결정
  → 서비스        : 트랜잭션 시작 → 조회 → 인가 → 도메인 호출 → 이벤트 발행 → 커밋
  → 도메인(Entity): 상태 전이 규칙, 금액 계산, 불변식 유지
  → 리포지터리    : 어떤 쿼리로 가져오는가
```

각 계층이 답하는 질문이 다릅니다.

| 계층 | 답하는 질문 |
|---|---|
| 컨트롤러 | 이 요청이 문법적으로 말이 되는가 |
| 서비스 | 지금 이 작업을 해도 되는가, 무엇과 함께 커밋되는가 |
| 도메인 | 이 상태에서 이 변경이 허용되는가 |
| 리포지터리 | 이걸 어떻게 꺼내오는가 |

**"이 코드가 답하는 질문이 이 계층의 질문인가"** — 이게 실무에서 가장 빨리 쓰는 판단 기준입니다.

### 3-2. 최소 구성 코드

```java
@Service
@RequiredArgsConstructor
public class OrderCancelService {

    private final OrderRepository orderRepository;
    private final ApplicationEventPublisher eventPublisher;

    @Transactional
    public void cancel(Long orderId, Long requesterId, String reason) {
        Order order = orderRepository.findById(orderId)
                .orElseThrow(() -> new OrderNotFoundException(orderId));

        order.verifyOwner(requesterId);        // 인가 — 도메인이 판단, 서비스가 호출
        RefundAmount refund = order.cancel(reason);   // 상태 전이 + 계산 — 도메인

        eventPublisher.publishEvent(new OrderCancelledEvent(orderId, refund.value()));
    }
}
```

서비스 메서드가 6줄입니다. 이게 정상입니다. `order.cancel()` 안에 "배송 시작된 주문은 취소 불가", "부분 환불 계산" 같은 규칙이 들어갑니다. 서비스는 **그 규칙을 모릅니다. 언제 부르는지만 압니다.**

`save()` 호출이 없다는 점도 눈여겨봅니다. 영속 상태의 엔티티는 더티 체킹으로 커밋 시점에 UPDATE가 나갑니다. 습관적으로 `save()`를 부르는 코드는 대개 트랜잭션 경계를 이해하지 못한 신호입니다.

## 4. 판단 기준 — 이 로직은 어디에 두는가

가장 자주 막히는 지점입니다. 순서대로 물어봅니다.

**1) 엔티티 하나의 상태만으로 판단되는가?** → 엔티티 안에 둡니다.
`order.isCancellable()`, `order.applyCoupon(coupon)` 같은 것들입니다.

**2) 여러 도메인 객체가 필요한데, 특정 하나의 것이라 말하기 애매한가?** → 도메인 서비스로 뺍니다.
"이 회원 등급과 이 상품 카테고리 조합의 할인율"처럼 어느 한쪽 객체에 넣으면 억지가 되는 계산입니다. 도메인 서비스는 **트랜잭션도 리포지터리도 모릅니다.** 값을 받아 값을 돌려주는 순수 객체입니다.

**3) 조회·저장·외부 호출·이벤트가 필요한가?** → 애플리케이션 서비스(우리가 보통 `@Service`라 부르는 것)입니다.

**4) 요청 형식과 응답 형태에만 관계된 일인가?** → 컨트롤러입니다.

경계 사례를 하나 봅시다. **"이메일 중복 확인"은 어디에 둘까요.** 회원 엔티티는 다른 회원들의 이메일을 모릅니다. 리포지터리 조회가 필요하죠. 그래서 애플리케이션 서비스입니다.

```java
@Transactional
public Long register(String email, String rawPassword) {
    if (memberRepository.existsByEmail(email)) {   // 조회가 필요 → 서비스
        throw new DuplicateEmailException(email);
    }
    Member member = Member.create(email, passwordEncoder.encode(rawPassword));
    return memberRepository.save(member).getId();
}
```

다만 이 검사는 **경합(race)에 안전하지 않습니다.** 두 요청이 동시에 들어오면 둘 다 통과합니다. 최종 방어선은 DB의 UNIQUE 제약이고, 서비스의 `exists` 검사는 사용자에게 친절한 메시지를 주기 위한 것입니다. 둘 다 필요합니다.

## 5. 예제

### 5-1. 클린하지 않은 코드 ❌

```java
@Transactional
public OrderCancelResponse cancel(HttpServletRequest request, Long orderId) {
    Long userId = (Long) request.getSession().getAttribute("userId");

    Order order = orderRepository.findById(orderId).orElseThrow();

    if (!order.getMemberId().equals(userId)) {
        throw new IllegalStateException("권한 없음");
    }
    if (order.getStatus() == OrderStatus.SHIPPED
            || order.getStatus() == OrderStatus.DELIVERED) {
        throw new IllegalStateException("이미 배송됨");
    }

    BigDecimal refund = order.getTotalAmount();
    if (order.getStatus() == OrderStatus.PREPARING) {
        refund = refund.subtract(new BigDecimal("2500"));   // 준비 시작 시 수수료
    }
    order.setStatus(OrderStatus.CANCELLED);

    paymentClient.refund(order.getPaymentKey(), refund);    // 외부 HTTP 호출
    mailSender.send(order.getEmail(), "주문이 취소되었습니다");

    return new OrderCancelResponse(orderId, refund);
}
```

무너진 지점이 다섯 개입니다.

- **HTTP를 압니다.** 이 메서드는 배치·컨슈머에서 재사용할 수 없습니다.
- **도메인 규칙이 서비스에 있습니다.** 상태 판정과 수수료 계산이 전부 밖에 나와 있어서, 취소 정책이 바뀌면 이 서비스를 고쳐야 합니다. 같은 규칙이 필요한 다른 유스케이스는 복붙합니다.
- **`setStatus`로 상태를 바꿉니다.** 어떤 상태에서 어떤 상태로 갈 수 있는지 아무도 강제하지 않습니다.
- **트랜잭션 안에서 외부 HTTP를 호출합니다.** 이게 가장 위험합니다(§6에서 자세히).
- **메일 발송 실패가 취소를 롤백시킵니다.** 돈은 이미 환불됐는데 주문은 취소 안 된 상태가 됩니다.

### 5-2. 개선한 코드 ✔️

먼저 도메인이 규칙을 가져갑니다.

```java
@Entity
public class Order {

    private static final BigDecimal PREPARING_FEE = new BigDecimal("2500");

    @Enumerated(EnumType.STRING)
    private OrderStatus status;

    public void verifyOwner(Long memberId) {
        if (!this.memberId.equals(memberId)) {
            throw new OrderAccessDeniedException(this.id, memberId);
        }
    }

    public RefundAmount cancel(String reason) {
        if (!status.isCancellable()) {
            throw new OrderNotCancellableException(this.id, status);
        }
        BigDecimal amount = status == OrderStatus.PREPARING
                ? totalAmount.subtract(PREPARING_FEE)
                : totalAmount;

        this.status = OrderStatus.CANCELLED;
        this.cancelReason = reason;
        return new RefundAmount(amount);
    }
}
```

서비스는 §3-2의 6줄로 돌아갑니다. 컨트롤러가 인증 정보를 꺼냅니다.

```java
@PostMapping("/orders/{orderId}/cancel")
public OrderCancelResponse cancel(
        @PathVariable Long orderId,
        @AuthenticationPrincipal MemberPrincipal principal,
        @Valid @RequestBody OrderCancelRequest request) {

    orderCancelService.cancel(orderId, principal.getId(), request.reason());
    return OrderCancelResponse.accepted(orderId);
}
```

환불과 메일은 커밋 이후로 밀어냅니다.

```java
@Component
@RequiredArgsConstructor
public class OrderCancelledHandler {

    private final PaymentClient paymentClient;

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void refund(OrderCancelledEvent event) {
        paymentClient.refund(event.orderId(), event.refundAmount());
    }
}
```

`@TransactionalEventListener`의 기본 phase는 `AFTER_COMMIT`이고, **트랜잭션이 없으면 리스너는 아예 호출되지 않습니다**(`fallbackExecution = true`로 바꿀 수 있습니다) ([Spring Framework — Transaction-bound Events](https://docs.spring.io/spring-framework/reference/data-access/transaction/event.html)). 커밋되지 않은 변경을 근거로 외부에 부수효과를 내는 사고를 구조적으로 막아줍니다.

**공짜는 아닙니다.** `AFTER_COMMIT` 리스너는 기본적으로 같은 스레드에서 커밋 직후 실행되므로, 여기서 예외가 나도 이미 커밋된 트랜잭션은 되돌아오지 않습니다. 환불이 실패하면 "취소됐지만 환불 안 된 주문"이 남습니다. 재시도 큐나 보상 배치가 필요합니다. 이 부분을 설계하지 않으면 문제를 옮긴 것뿐입니다.

## 6. 트랜잭션 경계가 곧 서비스 경계입니다

Spring에서 서비스 설계가 어려운 진짜 이유는 `@Transactional`이 **프록시로 동작하기 때문**입니다.

### 6-1. 같은 클래스 안에서 부르면 안 걸립니다

공식 문서가 명시합니다. 기본인 프록시 모드에서는 **프록시를 통해 들어오는 외부 호출만 가로채기 때문에, 같은 객체 내부의 메서드 호출(self-invocation)은 대상 메서드에 `@Transactional`이 붙어 있어도 런타임에 트랜잭션이 생기지 않습니다**([Spring Framework — Using @Transactional](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/annotations.html)).

같은 문서에서 확인되는 것 두 가지를 더 적어둡니다.

- 롤백 기본 규칙은 **`RuntimeException`과 `Error`만 롤백하고, 체크 예외는 롤백하지 않습니다.** 6.2부터 `@EnableTransactionManagement(rollbackOn = ALL_EXCEPTIONS)`로 이 기본값을 전역 변경할 수 있습니다.
- Spring 팀은 인터페이스가 아니라 **구현 클래스의 메서드에 붙일 것**을 권장합니다. 6.0부터 클래스 기반 프록시에서는 `protected`·package-private 메서드도 지원되지만, 인터페이스 기반 프록시는 여전히 `public`이어야 합니다.

이 사실이 설계에 주는 결론: **`REQUIRES_NEW`가 필요하다는 건 대개 클래스를 나누라는 신호입니다.** 자기 자신을 주입해서 프록시를 우회하는 트릭은 돌긴 하지만, "이 안에 사실 두 개의 트랜잭션 단위가 들어 있다"는 사실을 숨깁니다.

### 6-2. 트랜잭션 안에서 외부 API를 부르지 않습니다

트랜잭션이 열려 있는 동안 커넥션은 그 스레드에 묶여 있습니다. 여기서 응답이 5초 걸리는 결제 API를 호출하면, **DB는 아무 일도 안 하면서 커넥션 하나가 5초 동안 점유됩니다.** 풀 크기가 10이면 동시 10건에서 나머지 요청은 커넥션을 못 받습니다. DB 부하는 0인데 서비스는 멈춰 있습니다.

지연 시간만 문제가 아닙니다. 외부 호출이 성공한 뒤 커밋이 실패하면, 롤백은 DB만 되돌립니다. **이미 나간 결제는 못 되돌립니다.**

Spring Boot 4.1에는 관련해서 도움이 되는 옵션이 들어왔습니다. `spring.datasource.connection-fetch`를 `lazy`로 두면 자동 구성된 DataSource가 `LazyConnectionDataSourceProxy`로 감싸져 **실제 JDBC 문장이 필요한 시점에야 풀에서 물리 커넥션을 가져옵니다**([Spring Boot 4.1 릴리스 노트](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.1-Release-Notes)). 트랜잭션은 열렸지만 아직 쿼리를 안 쏜 구간에서 커넥션을 놀리지 않게 해줍니다.

<!-- TODO: 확인 필요 — `spring.datasource.connection-fetch`의 기본값이 `eager`인지 릴리스 노트 서술로는 그렇게 읽히지만, Common Application Properties 문서에서 기본값 표기를 직접 확인하지 못했습니다. -->

다만 이건 **완화지 해결이 아닙니다.** 트랜잭션 중간에 이미 쿼리를 한 번이라도 날렸다면 커넥션은 그때부터 커밋까지 붙잡혀 있습니다. 순서를 바꾸는 게 근본 해법입니다.

```java
// ✅ 트랜잭션은 짧게, 외부 호출은 밖에서
public void cancel(Long orderId, Long requesterId, String reason) {
    RefundAmount refund = transactionTemplate.execute(status -> {
        Order order = orderRepository.findById(orderId)
                .orElseThrow(() -> new OrderNotFoundException(orderId));
        order.verifyOwner(requesterId);
        return order.cancel(reason);
    });
    paymentClient.refund(orderId, refund.value());   // 커밋 이후
}
```

`TransactionTemplate`은 메서드 전체가 아니라 **코드 블록**을 트랜잭션으로 묶습니다. 애너테이션으로 표현이 안 되는 경계에 씁니다. `@TransactionalEventListener`와 목적은 같고, 이쪽은 호출 순서가 코드에 그대로 보인다는 차이가 있습니다.

## 7. 서비스가 서비스를 호출해도 되는가

됩니다. 다만 방향을 정합니다.

- **같은 층의 서비스끼리 서로 부르면** 순환 참조가 생기고, 트랜잭션 경계가 겹쳐서 어디까지 롤백되는지 아무도 모르게 됩니다.
- **위에서 아래로만** 부릅니다. 여러 유스케이스를 묶어야 하면 그 위에 파사드 성격의 서비스를 하나 두고, 아래 서비스들은 서로를 모르게 합니다.
- 서로 알아야 할 것 같으면 **이벤트로 뒤집습니다.** `OrderService`가 `PointService`를 부르는 대신 이벤트를 발행하고, 포인트 쪽이 구독합니다. 주문은 포인트를 몰라도 됩니다.

클래스를 나누는 기준은 엔티티 개수가 아니라 **유스케이스 묶음**입니다. `OrderService` 하나에 조회·생성·취소·정산을 다 넣지 말고, `OrderCancelService`처럼 나눕니다. 이렇게 하면 주입받는 빈이 2~3개로 줄고, 테스트에서 세울 목도 그만큼 줄어듭니다.

## 8. 트레이드오프 — 얇은 서비스의 비용

장점만 쓰면 거짓말입니다.

- **클래스 수가 늘어납니다.** CRUD가 대부분인 프로젝트에서 도메인 서비스·이벤트 핸들러까지 나누면 파일 탐색이 더 힘들어집니다.
- **흐름이 코드에서 안 보입니다.** 이벤트로 뒤집는 순간 "취소하면 환불된다"는 사실이 호출 스택에 안 나타납니다. IDE에서 따라갈 수 없고, 신규 입사자가 못 찾습니다.
- **엔티티에 로직을 넣으면 엔티티가 커집니다.** 빈약한 도메인 모델을 피하려다 3000줄짜리 `Order`를 만드는 건 문제를 옮긴 것뿐입니다.
- **JPA 엔티티는 순수한 도메인 객체가 아닙니다.** 기본 생성자, 지연 로딩 프록시, 식별자 생성 시점 같은 제약이 붙습니다. 도메인 로직을 넣을수록 이 제약과 부딪힙니다.

**언제 얇게 안 나눠도 되는가**도 정해둡시다. 관리자 화면 CRUD, 외부 연동 없는 단순 조회, 한 달 뒤 버릴 프로토타입이면 컨트롤러 → 리포지터리 직행도 합리적입니다. 기준은 **"이 작업이 실패했을 때 되돌려야 할 것이 두 개 이상인가"**입니다. 하나면 굳이 계층을 세울 이유가 약합니다.

## 9. 함정

### 9-1. 서비스에 `@Transactional`을 붙였는데 롤백이 안 됩니다

- **증상**: 예외를 던졌는데 데이터가 그대로 저장돼 있습니다.
- **원인**: 세 가지 중 하나입니다. ① 같은 클래스 내부에서 호출했습니다(프록시 우회). ② 체크 예외를 던졌습니다(기본 롤백 대상 아님). ③ 중간에서 `try-catch`로 예외를 삼켰습니다.
- **해법**: ①은 클래스를 분리합니다. ②는 `@Transactional(rollbackFor = ...)`을 명시하거나 언체크 예외로 바꿉니다. ③은 catch 안에서 로그만 찍고 넘어가지 않는지 확인합니다. 삼켜야 한다면 `TransactionAspectSupport.currentTransactionStatus().setRollbackOnly()`를 명시합니다.

### 9-2. `@Transactional`을 클래스 전체에 붙여둡니다

- **증상**: 단순 조회 API인데 커넥션 풀이 마릅니다.
- **원인**: 클래스 레벨 `@Transactional` 때문에 조회 메서드까지 쓰기 트랜잭션이 열립니다. 조회 후 응답을 만드는 동안 커넥션이 계속 잡혀 있습니다.
- **해법**: 조회는 `@Transactional(readOnly = true)`로 분리합니다. 더 나은 방향은 메서드마다 붙이는 것입니다. 클래스에 붙은 애너테이션은 새로 추가되는 메서드에 조용히 상속되는데, 그 메서드가 트랜잭션을 원했는지는 아무도 검토하지 않습니다.

### 9-3. 서비스 메서드가 컨트롤러 개수만큼 늘어납니다

- **증상**: `getOrderForList`, `getOrderForDetail`, `getOrderForAdmin`이 생깁니다. 안은 거의 같습니다.
- **원인**: 응답 형태의 차이를 서비스 시그니처로 표현하고 있습니다. 화면이 서비스를 지배하는 상태입니다.
- **해법**: 서비스는 유스케이스 단위로 유지하고, 화면별 차이는 조회 전용 경로로 분리합니다. 목록·통계처럼 도메인 로직 없이 읽기만 하는 요청은 서비스를 거치지 않고 조회 전용 컴포넌트가 프로젝션으로 바로 가져오는 편이 낫습니다([day14-dto-vs-entity.md](day14-dto-vs-entity.md) §6).

### 9-4. 인가를 컨트롤러에서만 합니다

- **증상**: 웹에서는 막히는데, 배치나 내부 API로 같은 서비스를 부르면 남의 주문이 취소됩니다.
- **원인**: "이 사용자가 이 리소스를 건드려도 되는가"는 URL이 아니라 데이터에 달린 판단인데, 컨트롤러의 URL 기반 규칙으로만 막았습니다.
- **해법**: 역할 기반 접근 제어(`ROLE_ADMIN` 같은 것)는 컨트롤러 앞단에서, **소유권 검사는 서비스나 도메인 안에서** 합니다. 두 개는 다른 종류의 판단입니다.

### 9-5. 서비스에 `null`을 리턴합니다

- **증상**: 컨트롤러마다 `if (result == null)` 분기가 생기고, 어느 하나가 빠져 NPE가 납니다.
- **원인**: "없음"을 표현할 방법을 정하지 않았습니다.
- **해법**: 유스케이스 관점에서 "없으면 실패"인지 "없어도 정상"인지 먼저 정합니다. 실패면 예외를 던지고(`@ControllerAdvice`가 상태 코드로 번역), 정상이면 `Optional`이나 빈 리스트를 돌려줍니다. 한 서비스 안에서 두 방식을 섞지 않습니다.

## 10. 참고자료

- [Spring Framework — Using `@Transactional`](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/annotations.html) — 프록시 모드의 self-invocation 한계, 기본 롤백 규칙, 메서드 가시성
- [Spring Framework — Transaction-bound Events](https://docs.spring.io/spring-framework/reference/data-access/transaction/event.html) — `@TransactionalEventListener`의 phase와 `fallbackExecution`
- [Spring Boot 4.1 Release Notes](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.1-Release-Notes) — `spring.datasource.connection-fetch`
- [Martin Fowler — AnemicDomainModel (2003-11-25)](https://martinfowler.com/bliki/AnemicDomainModel.html) — 서비스 계층은 얇아야 한다는 논지의 원문
- 관련 문서: [day08-di-why.md](day08-di-why.md) — 의존 방향을 바깥으로 옮긴다는 것의 의미
- 관련 문서: [day14-dto-vs-entity.md](day14-dto-vs-entity.md) — 경계에서 무엇을 주고받는가
- 관련 문서: [day02-spring-request-flow.md](day02-spring-request-flow.md) — 컨트롤러 앞단에서 무엇이 끝나 있는가
- 관련 문서: [day03-api-error-format.md](day03-api-error-format.md) — 서비스가 던진 예외를 응답으로 번역하기

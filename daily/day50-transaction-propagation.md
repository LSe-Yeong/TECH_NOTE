# `REQUIRES_NEW`가 필요한 순간 — 트랜잭션 전파

> 이 문서가 답할 질문: **메서드 하나에 트랜잭션 하나가 아닌 이유는 무엇이고, 호출된 쪽만 따로 커밋·롤백하려면 무엇을 치러야 하는가?**
>
> 분류: 기술이해형(왜 존재하는가). 전파 옵션 목록은 어디에나 있지만, 여러 출처가 공통으로 "원래 풀려던 문제"로 드는 것은 **논리적 경계와 물리적 트랜잭션이 1:1이 아니라는 사실**이라서 그 축으로 정리했습니다. 다만 실무에서 이 챕터를 찾아보게 되는 계기는 거의 항상 `UnexpectedRollbackException` 하나이므로 3절을 문제해결형으로 끼워 넣었습니다.
>
> 기준: **Spring Boot 4.1 / Spring Framework 7.0** 레퍼런스와 `spring-tx` 7.0.x Javadoc을 확인해 썼습니다. 프록시를 안 거치면 애노테이션이 무시되는 문제는 `daily/day44-proxy-aop.md`에서 다뤘으므로 여기서는 전파에 걸리는 부분만 짚습니다. 격리 수준은 범위 밖입니다.

## 1. 핵심 개념 — 논리적 트랜잭션과 물리적 트랜잭션은 개수가 다릅니다

전파(Propagation)는 "하위 메서드가 트랜잭션을 쓸지"를 정하는 스위치가 아닙니다. **`@Transactional`이 붙은 메서드마다 생기는 논리적 경계를, 실제 DB 커넥션 위의 물리적 트랜잭션에 어떻게 매핑할지**를 정합니다.

기본값 `REQUIRED`에서는 이 매핑이 N:1입니다. 아래 호출에서 논리적 경계는 세 개지만 물리적 트랜잭션은 하나입니다.

```java
@Transactional                                  // 논리 경계 1 — 물리 트랜잭션 시작
public void placeOrder(OrderCommand command) {
    Order order = orderRepository.save(command.toOrder());
    inventoryService.deduct(order);             // 논리 경계 2 — 같은 물리 트랜잭션에 참여
    pointService.use(order.getUserId(), order.getAmount());  // 논리 경계 3 — 동일
}
```

> 이 구분을 모르면 반드시 두 번 데입니다. 한 번은 "하위 메서드에서 예외를 `try-catch`로 삼켰는데 전체가 롤백됐다", 다른 한 번은 "따로 커밋하려고 `REQUIRES_NEW`를 붙였더니 부하가 오르자 스레드가 전부 멈췄다"입니다. 둘 다 코드만 보면 정상이고, 둘 다 테스트에서는 재현되지 않습니다. 커넥션이 하나면 풀이 마르지 않으니까요.

## 2. 구조 — 일곱 개를 두 질문으로 압축하기

전파 옵션은 일곱 개지만, 결정 축은 "현재 트랜잭션이 없을 때"와 "있을 때" 두 개뿐입니다.

| | 트랜잭션이 없으면 | 트랜잭션이 있으면 |
|---|---|---|
| `REQUIRED` (기본값) | 새로 시작 | **참여** |
| `SUPPORTS` | 트랜잭션 없이 실행 | 참여 |
| `MANDATORY` | **예외** | 참여 |
| `REQUIRES_NEW` | 새로 시작 | **보류하고 새로 시작** |
| `NOT_SUPPORTED` | 트랜잭션 없이 실행 | 보류하고 트랜잭션 없이 실행 |
| `NEVER` | 트랜잭션 없이 실행 | **예외** |
| `NESTED` | 새로 시작 | **세이브포인트 생성** |

출처: [Propagation Javadoc](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/transaction/annotation/Propagation.html).

실무에서 실제로 고민하는 건 `REQUIRED` · `REQUIRES_NEW` · `NESTED` 셋입니다. 나머지 넷은 용도가 좁습니다.

- `MANDATORY` — "이 메서드는 반드시 누군가의 트랜잭션 안에서 불려야 한다"를 **계약으로 선언**할 때. 혼자 불리면 조용히 자동 커밋으로 도는 대신 기동 즉시 예외가 납니다. 리포지토리 바로 위 계층에 쓸 만합니다.
- `NOT_SUPPORTED` / `NEVER` — 긴 조회나 외부 호출을 트랜잭션 밖으로 빼낼 때. 다만 `NOT_SUPPORTED`도 **보류(suspend)이므로 외부 커넥션은 계속 점유**합니다. 트랜잭션만 벗어나고 커넥션은 안 놓습니다.
- `SUPPORTS` — 트랜잭션 동기화 때문에 "아무것도 안 하는 것"과 다릅니다. 트랜잭션 범위는 정의하므로 같은 범위 안에서 커넥션이 공유됩니다.

### 2-1. 참여하면 내가 쓴 설정은 조용히 무시됩니다

`REQUIRED`로 기존 트랜잭션에 참여하는 메서드의 `isolation`, `timeout`, `readOnly`는 **적용되지 않고 무시됩니다**. 외부 트랜잭션의 설정이 그대로 유지됩니다. 예외도 경고 로그도 없습니다.

```java
@Transactional                          // 외부: 읽기-쓰기, 기본 격리 수준
public void settleOrder(Long orderId) {
    reportService.summarize(orderId);   // @Transactional(readOnly = true) — 무시됨
}
```

무시되는 대신 실패하게 만들고 싶으면 트랜잭션 매니저에 `validateExistingTransaction`을 켭니다. 기본값은 `false`입니다([AbstractPlatformTransactionManager Javadoc](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/transaction/support/AbstractPlatformTransactionManager.html)).

```java
// org.springframework.boot.transaction.autoconfigure.TransactionManagerCustomizer
// — Spring Boot 4.0부터 이 패키지입니다 (3.2~3.x에서는 ...autoconfigure.transaction)
@Bean
TransactionManagerCustomizer<AbstractPlatformTransactionManager> strictTransactionValidation() {
    return transactionManager -> transactionManager.setValidateExistingTransaction(true);
}
```

프로덕션에서 바로 켤 설정은 아닙니다. 지금까지 조용히 무시되던 조합이 전부 예외로 바뀌므로 깨지는 곳이 한 번에 드러납니다. 신규 프로젝트 초반이나, 설정이 적용되는지 확인하려는 테스트 프로파일에서 쓰는 쪽이 현실적입니다.

## 3. 흐름 — `REQUIRED`에서 롤백이 번지는 이유

가장 자주 겪는 증상부터 봅니다. 하위 호출을 `try-catch`로 감싸 "실패해도 주문은 살리자"고 썼는데, 결과적으로 전부 롤백됩니다.

```java
@Transactional
public void placeOrder(OrderCommand command) {
    Order order = orderRepository.save(command.toOrder());
    try {
        couponService.redeem(command.getCouponId());   // @Transactional — REQUIRED
    } catch (CouponAlreadyUsedException e) {
        log.warn("쿠폰 적용 실패, 주문은 계속 진행: orderId={}", order.getId());
    }
}
```

실행 순서는 이렇습니다.

1. `placeOrder` 진입 → 물리 트랜잭션 시작
2. `redeem` 진입 → 같은 물리 트랜잭션에 **참여**
3. `redeem`에서 `RuntimeException` → 참여 중인 트랜잭션이므로 커밋하지 않고, **물리 트랜잭션 전체를 rollback-only로 표시**
4. `placeOrder`가 예외를 잡아 정상 종료 → 커밋 시도
5. rollback-only 표시가 있으므로 커밋 대신 롤백 → 호출자에게 `UnexpectedRollbackException`

3번이 핵심입니다. 트랜잭션 매니저의 `globalRollbackOnParticipationFailure` 기본값이 `true`입니다. Javadoc의 설명은 분명합니다 — 참여 트랜잭션이 실패하면 전역으로 rollback-only가 되고, **트랜잭션을 시작한 쪽은 더 이상 커밋할 수 없습니다.**

5번에서 조용히 넘어가지 않고 예외를 던지는 것도 의도된 설계입니다. 레퍼런스는 그 이유를 "커밋했다고 믿게 만들지 않기 위해서"라고 설명합니다([Transaction Propagation](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/tx-propagation.html)).

로그에는 이렇게 남습니다.

```
org.springframework.transaction.UnexpectedRollbackException:
  Transaction silently rolled back because it has been marked as rollback-only
```

`try-catch`가 있는 곳과 예외가 터지는 곳이 다르다는 점 때문에 원인 찾기가 오래 걸립니다. 실패한 메서드가 아니라 **최외곽 커밋 지점**에서 터지니까요. `failEarlyOnGlobalRollbackOnly`를 `true`로 켜면 표시된 즉시 터뜨릴 수 있습니다(기본값 `false`).

### 3-1. 그래서 하위 실패를 삼키려면 선택지가 셋입니다

| 방법 | 성립 조건 |
|---|---|
| 하위 메서드에서 `@Transactional`을 뗀다 | 하위가 혼자 불릴 일이 없을 때. 가장 싸고 가장 자주 맞는 답 |
| `@Transactional(noRollbackFor = ...)`를 하위에 지정 | 그 예외가 **DB 상태를 깨지 않는** 경우만. 제약 위반 뒤라면 못 씁니다 |
| `REQUIRES_NEW`로 분리 | 하위가 **정말로 독립 커밋되어야** 할 때 (4절) |

기본 롤백 규칙은 `RuntimeException`과 `Error`이고, **체크 예외는 기본 설정에서 롤백을 일으키지 않습니다**([Rolling Back](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/rolling-back.html)). `noRollbackFor`를 쓰기 전에 그 예외가 체크 예외인지부터 보면 애초에 필요 없는 경우가 많습니다.

## 4. `REQUIRES_NEW` — 무엇을 사고 무엇을 지불하는가

`REQUIRES_NEW`는 외부 트랜잭션을 **보류(suspend)**하고 완전히 독립된 물리 트랜잭션을 시작합니다. 둘은 서로 모릅니다. 내부가 롤백돼도 외부는 커밋할 수 있고, 반대도 됩니다.

사는 것은 그 독립성 하나이고, 지불하는 것은 셋입니다.

### 4-1. 커넥션을 두 개 동시에 점유합니다 ⚠️

보류는 "커넥션을 반납한다"가 아닙니다. **외부 트랜잭션의 커넥션은 그대로 묶인 채** 내부가 풀에서 새 커넥션을 하나 더 꺼냅니다. 한 스레드가 커넥션 두 개를 쥡니다.

여기서 스레드 데드락이 나옵니다. HikariCP의 `maximumPoolSize` 기본값은 **10**입니다([HikariCP README](https://github.com/brettwooldridge/HikariCP)). 동시 요청 10개가 각자 외부 커넥션을 하나씩 쥔 상태에서 전부 `REQUIRES_NEW`에 들어가면, 열 스레드가 모두 열한 번째 커넥션을 기다립니다. 아무도 양보할 수 없으니 풀의 타임아웃이 터질 때까지 전부 멈춥니다.

레퍼런스도 같은 경고를 명시합니다 — 풀 크기가 동시 스레드 수보다 **최소 하나 이상 크지 않으면 쓰지 말라**는 문장이 Transaction Propagation 문서에 그대로 있습니다. 이건 "넉넉하게 잡아라"가 아니라 계산식입니다. `REQUIRES_NEW`를 타는 경로가 섞인 서비스의 실질 동시성 상한은 풀 크기가 아니라 **풀 크기 ÷ 2** 쪽에 가깝습니다.

### 4-2. 외부가 방금 쓴 데이터를 내부가 못 봅니다

물리 트랜잭션이 다르면 커넥션이 다르고, 커넥션이 다르면 **외부의 미커밋 변경은 내부에게 보이지 않습니다.** JPA라면 한 겹 더 있습니다. 외부의 변경은 아직 영속성 컨텍스트에만 있고 flush되지 않았을 수 있는데, 전파는 flush를 유발하지 않습니다.

```java
// ❌ 내부가 order를 조회하면 없습니다 — 외부 트랜잭션이 아직 커밋 전입니다
@Transactional
public void placeOrder(OrderCommand command) {
    Order order = orderRepository.save(command.toOrder());
    auditService.recordByOrderId(order.getId());   // REQUIRES_NEW → 조회 실패
}
```

해법은 flush가 아니라 **값을 인자로 넘기는 것**입니다. 독립 트랜잭션에게 "내가 아직 커밋 안 한 데이터를 읽어와라"고 시키는 설계 자체가 모순입니다.

### 4-3. 외부가 잡은 락을 내부가 건드리면 끝입니다

외부 트랜잭션이 `order` 행을 수정해 배타 락을 쥔 상태에서, 내부 `REQUIRES_NEW`가 같은 행을 수정하려 하면 내부는 외부의 커밋을 기다립니다. 그런데 외부는 내부 호출이 리턴되기를 기다리고 있습니다. 같은 스레드 안에서 만든 교착이라 DB의 데드락 감지에도 잡히지 않고, 락 타임아웃이 날 때까지 멈춥니다.

**`REQUIRES_NEW`가 만지는 테이블은 외부 트랜잭션이 쓰는 테이블과 겹치지 않아야 합니다.** 이게 "감사 로그, 실패 이력, 알림 발송 기록" 같은 용도에만 `REQUIRES_NEW`가 어울리는 이유입니다. 전용 테이블에 INSERT만 하니까요.

### 4-4. 자기 호출이면 애초에 안 걸립니다

같은 클래스 안에서 `this.saveAuditLog()`로 부르면 프록시를 거치지 않으므로 전파 설정이 **아예 적용되지 않습니다.** 예외도 로그도 없이 외부 트랜잭션에 그대로 포함됩니다. 롤백되는 감사 로그가 됩니다. `daily/day44-proxy-aop.md`의 그 문제가 전파에서는 결과가 더 조용합니다.

## 5. `NESTED` — 왜 답처럼 보이고 왜 못 쓰는가

`NESTED`는 매력적으로 들립니다. 물리 트랜잭션은 하나로 두고 **세이브포인트**를 찍어서, 내부만 세이브포인트까지 되돌리고 외부는 계속 진행합니다. 커넥션이 하나니까 4-1의 풀 문제가 없습니다.

문제는 지원 범위입니다.

- `nestedTransactionAllowed` 기본값은 `false`이고, 구현체가 적절한 기본값으로 초기화합니다. 바로 쓸 수 있는 건 JDBC `DataSourceTransactionManager`입니다.
- `JtaTransactionManager`는 지원하지 않습니다.
- **JPA를 쓰면 사실상 선택지가 아닙니다.** `JpaTransactionManager` Javadoc은 플래그를 켤 수 있지만 세이브포인트가 JDBC 커넥션에만 적용되고 `EntityManager`와 그 캐시에는 적용되지 않는다고 못 박습니다. 그리고 "JPA 자체는 중첩 트랜잭션을 지원하지 않으므로 JPA 접근 코드가 의미적으로 참여한다고 기대하지 말라"고 덧붙입니다([JpaTransactionManager Javadoc](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/orm/jpa/JpaTransactionManager.html)).

롤백해도 영속성 컨텍스트에는 되돌려진 엔티티가 그대로 남아 있다는 뜻입니다. 그 상태로 외부가 커밋하면 되돌린 변경이 다시 나갑니다. **Spring Data JPA 기반 서비스에서는 `NESTED`를 후보에서 지웁니다.** `JdbcTemplate`이나 `JdbcClient`로 직접 쓰는 배치성 코드에서만 제값을 합니다.

## 6. 예제 — 실패 이력은 남기고 주문은 롤백하기

요구사항: 결제가 실패하면 주문은 전부 롤백하되, **왜 실패했는지는 DB에 남아야** 합니다.

### 6-1. 안 되는 코드 ❌

```java
@Service
@RequiredArgsConstructor
public class OrderService {

    private final OrderRepository orderRepository;
    private final PaymentClient paymentClient;
    private final OrderFailureRepository failureRepository;

    @Transactional
    public void placeOrder(OrderCommand command) {
        Order order = orderRepository.save(command.toOrder());
        try {
            paymentClient.pay(order.getPaymentRequest());
        } catch (PaymentFailedException e) {
            // ❌ 같은 트랜잭션 — 아래 롤백과 함께 사라집니다
            failureRepository.save(OrderFailure.of(command, e.getMessage()));
            throw e;
        }
    }
}
```

이력 INSERT가 같은 물리 트랜잭션에 있으므로 `throw e`와 함께 롤백됩니다. 장애 조사용으로 만든 테이블이 정작 장애 때 비어 있습니다.

### 6-2. 개선한 코드 ✔️

별도 빈으로 빼고 `REQUIRES_NEW`를 붙입니다. 4-3 기준을 지킵니다 — `order_failure` 테이블은 주문 흐름이 건드리지 않는 전용 테이블이고, INSERT만 합니다.

```java
@Service
@RequiredArgsConstructor
public class OrderFailureRecorder {

    private final OrderFailureRepository failureRepository;

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void record(OrderCommand command, String reason) {
        failureRepository.save(OrderFailure.of(command, reason));
    }
}
```

```java
@Transactional
public void placeOrder(OrderCommand command) {
    Order order = orderRepository.save(command.toOrder());
    try {
        paymentClient.pay(order.getPaymentRequest());
    } catch (PaymentFailedException e) {
        failureRecorder.record(command, e.getMessage());  // 독립 커밋
        throw e;
    }
}
```

인자로 `command`를 넘기고 `order.getId()`를 넘기지 않은 게 의도입니다(4-2). 아직 커밋되지 않은 주문의 ID를 넘기면 외래 키 제약이 바로 깨집니다.

### 6-3. 호출 지점을 아예 빼는 방법

`try-catch`로 감싸는 자리가 늘어나면 이벤트로 뒤집는 게 깔끔합니다.

```java
@Component
@RequiredArgsConstructor
public class OrderFailureListener {

    private final OrderFailureRepository failureRepository;

    @TransactionalEventListener(phase = TransactionPhase.AFTER_ROLLBACK)
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void on(OrderFailedEvent event) {
        failureRepository.save(OrderFailure.of(event.command(), event.reason()));
    }
}
```

`@Transactional(REQUIRES_NEW)`를 같이 붙인 게 필수입니다. Javadoc은 `AFTER_COMMIT`·`AFTER_ROLLBACK`·`AFTER_COMPLETION` 시점에는 트랜잭션 자원이 아직 살아 있어서 데이터 접근 코드가 원래 트랜잭션에 "참여"하지만 **변경은 커밋되지 않는다**고 경고합니다([TransactionalEventListener Javadoc](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/transaction/event/TransactionalEventListener.html)). 이걸 모르고 쓰면 예외도 로그도 없이 INSERT가 사라집니다. 6-1과 증상이 똑같습니다.

## 7. 함정

**① 커밋했다고 생각한 지점에서 `UnexpectedRollbackException`**

- **증상**: `try-catch`로 다 처리했는데 최외곽에서 `Transaction silently rolled back because it has been marked as rollback-only`가 납니다. 예외를 잡은 메서드의 스택은 트레이스에 없습니다.
- **원인**: 참여 트랜잭션이 실패해 물리 트랜잭션이 전역 rollback-only로 표시됐습니다(`globalRollbackOnParticipationFailure` 기본 `true`).
- **해법**: 하위 메서드의 `@Transactional`을 떼는 것이 1순위입니다. 떼면 논리 경계가 사라져 표시가 생기지 않습니다. 독립 커밋이 진짜 필요하면 `REQUIRES_NEW`로 분리합니다. 원인 지점을 찾아야 할 때만 `failEarlyOnGlobalRollbackOnly=true`를 켜서 표시된 즉시 터지게 합니다.

**② 부하 테스트에서만 스레드가 전부 멈춤**

- **증상**: 기능 테스트는 전부 통과하는데 동시 요청을 올리면 응답이 멈추고 커넥션 획득 타임아웃이 쏟아집니다. DB의 CPU는 한가합니다.
- **원인**: `REQUIRES_NEW` 경로가 스레드당 커넥션 두 개를 요구합니다. 동시 요청 수가 풀 크기에 닿으면 전원이 서로를 기다립니다(4-1).
- **해법**: `REQUIRES_NEW`가 붙은 메서드를 전부 찾아 "정말 독립 커밋이 필요한가"를 다시 묻습니다. 대부분은 롤백돼도 되는 기록이라 `REQUIRED`로 충분합니다. 남겨야 하는 것은 호출 깊이를 1단으로 제한하고, 풀 크기가 톰캣 최대 스레드 수를 고려해 동시성 상한보다 크게 잡혀 있는지 확인합니다.

**③ `REQUIRES_NEW`를 붙였는데 같이 롤백됨**

- **증상**: 분명히 `REQUIRES_NEW`인데 외부 롤백 시 함께 사라집니다. 로그에 트랜잭션 관련 메시지가 전혀 없습니다.
- **원인**: 같은 클래스 내부 호출이라 프록시를 거치지 않았습니다. 또는 `@TransactionalEventListener`의 `AFTER_*` 단계에서 `@Transactional`을 안 붙였습니다(6-3).
- **해법**: 별도 빈으로 분리합니다. 확인은 로그로 합니다. `logging.level.org.springframework.transaction.interceptor=TRACE`를 켜면 트랜잭션이 실제로 열리는 지점이 전부 찍히므로, 안 찍히면 프록시를 안 거친 것입니다.

**④ JPA에서 `NESTED`가 롤백한 변경이 되살아남**

- **증상**: 내부 `NESTED` 블록이 롤백됐는데 외부 커밋 후 DB에 그 변경이 들어가 있습니다.
- **원인**: 세이브포인트는 JDBC 커넥션 레벨이고 영속성 컨텍스트에는 적용되지 않습니다. 되돌려진 엔티티가 더티 상태로 남아 외부 flush에 다시 실려 나갑니다.
- **해법**: JPA 코드에서는 `NESTED`를 쓰지 않습니다. 부분 롤백이 필요하면 `REQUIRES_NEW`로 물리 트랜잭션을 나누거나, 저장 단위를 쪼개 재시도 가능하게 만듭니다.

## 8. 참고자료

- [Spring Framework Reference — Transaction Propagation](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/tx-propagation.html)
- [Spring Framework Reference — Rolling Back a Declarative Transaction](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/rolling-back.html)
- [Javadoc — `Propagation`](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/transaction/annotation/Propagation.html)
- [Javadoc — `AbstractPlatformTransactionManager`](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/transaction/support/AbstractPlatformTransactionManager.html)
- [Javadoc — `JpaTransactionManager`](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/orm/jpa/JpaTransactionManager.html)
- [HikariCP — 설정 기본값](https://github.com/brettwooldridge/HikariCP)
- `daily/day44-proxy-aop.md` — 프록시를 안 거치면 애노테이션이 무시되는 이유
- `daily/day20-service-layer-design.md` — 트랜잭션 경계를 어디에 두는가

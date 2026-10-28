# ACID는 무엇을 약속하고, 무엇을 약속하지 않는가

> 이 문서가 답할 질문: **"이 DB는 ACID를 지킵니다"라는 문장은 내 코드에 정확히 무엇을 보장해주고, 무엇을 여전히 내 책임으로 남기는가?**
>
> 분류: 기술이해형(왜 존재하는가). 네 글자의 정의 자체는 어디에나 있고 외우기도 쉽습니다. 실무에서 문제가 되는 건 정의가 아니라 **경계** — ACID를 지킨다는 DB 위에서도 데이터가 깨지는 지점이 어디냐는 것이고, 여러 출처가 공통으로 드는 "원래 풀려던 문제"도 그 경계에 모입니다.
>
> 기준: **MySQL 8.4**, **PostgreSQL 현행(18)** 매뉴얼과 **Spring Framework** 레퍼런스를 확인해 썼습니다. 격리 수준별 이상현상은 `daily/day56-transaction-isolation.md`에서 다뤘으므로 여기서는 "I가 약속하는 범위"만 짚고 넘어갑니다. 전파는 `daily/day50-transaction-propagation.md`에 있습니다.

## 1. 핵심 개념 — 네 개의 기능이 아니라, 한 단위의 네 측면입니다

ACID는 DB가 제공하는 네 개의 독립된 기능 목록이 아닙니다. **트랜잭션이라는 단위 하나가 성립하기 위해 동시에 필요한 네 가지 조건**입니다. 하나가 빠지면 나머지 셋이 의미를 잃습니다.

| 글자 | 약속 | 빠지면 |
|---|---|---|
| Atomicity | 전부 반영되거나 전부 없던 일이 됩니다 | 절반만 반영된 상태가 영구히 남습니다 |
| Consistency | 선언한 제약을 깨는 상태로는 커밋되지 않습니다 | 커밋된 데이터를 신뢰할 수 없습니다 |
| Isolation | 동시에 도는 다른 트랜잭션의 중간 상태를 보지 않습니다 | 원자성이 성립해도 남이 중간을 읽어갑니다 |
| Durability | 커밋 응답이 돌아왔으면 장애 후에도 남아 있습니다 | 원자적으로 커밋해도 사라집니다 |

용어는 Jim Gray가 1981년에 원자성·일관성·지속성을 묶어 정의하고, Härder와 Reuter가 1983년 논문에서 격리를 더해 머리글자로 만든 것으로 알려져 있습니다([Härder & Reuter, *Principles of Transaction-Oriented Database Recovery*, ACM Computing Surveys 15(4)](https://doi.org/10.1145/289.291)).

<!-- TODO: 원 논문 본문(PDF)이 스캔 이미지라 "머리글자 ACID를 이 논문이 처음 썼다"는 부분은 1차 출처로 확인하지 못했습니다. 2차 출처 기반 서술입니다. 서지 정보(ACM CSUR 15(4), 1983, pp.287-317)만 확인됐습니다. -->

> 신입 때 이 네 글자를 외우고도 데는 이유는, 네 글자가 전부 **"트랜잭션 경계 안에서, DB가 관리하는 데이터에 대해서만"** 성립한다는 조건이 정의에 안 쓰여 있기 때문입니다. 주문을 저장하고 결제 API를 호출하는 메서드에 `@Transactional`을 붙이면, 결제가 터졌을 때 주문 행은 롤백됩니다. 결제는 안 됩니다. 코드는 한 덩어리로 보이는데 원자성이 적용되는 범위는 그 중 일부뿐이고, 남은 절반은 아무도 되돌려주지 않습니다.

## 2. 구조 — 네 글자를 지키는 주체가 다릅니다

이게 이 챕터의 핵심입니다. 네 글자는 전부 DB가 공짜로 지켜주는 게 아닙니다.

| 글자 | 메커니즘 | 지키는 주체 |
|---|---|---|
| A | undo 로그 — 변경 전 이미지를 적어두고 롤백 때 되감습니다 | **DB 엔진** (단, 경계는 내가 긋습니다) |
| C | 제약조건(PK, FK, UNIQUE, CHECK, NOT NULL) 검사 | **내가 선언한 만큼만** DB가 검사합니다 |
| I | 락 + MVCC, 그리고 격리 수준 다이얼 | **DB 엔진** (단, 수준을 내가 고릅니다) |
| D | redo 로그 / WAL을 디스크에 `fsync` | **설정값**이 결정합니다 |

MySQL 글로서리는 InnoDB의 ACID 준수를 설명하면서 격리는 락으로, 지속성은 doublewrite buffer 같은 디스크 쓰기 중복으로 달성한다고 적고 있습니다([MySQL 8.4 Glossary: ACID](https://dev.mysql.com/doc/refman/8.4/en/glossary.html#glos_acid)).

여기서 바로 읽어야 할 것은 **C와 D는 내 손에 있다**는 점입니다.

- 제약조건을 테이블에 걸지 않으면 C가 검사할 대상이 없습니다. "일관성"은 DB가 알아서 지키는 추상적인 무언가가 아니라, **내가 DDL로 선언한 명제의 집합**입니다.
- 지속성은 설정 한 줄로 끌 수 있습니다. 그리고 실제로 성능 때문에 끕니다(6절).

## 3. 흐름 — 커밋 한 번이 지나는 길

### 3-1. 코드로 보는 경계

```java
@Service
@RequiredArgsConstructor
public class OrderService {

    private final OrderRepository orderRepository;
    private final StockRepository stockRepository;

    @Transactional
    public Long placeOrder(Long productId, int quantity) {
        Stock stock = stockRepository.findByProductIdForUpdate(productId)
                .orElseThrow(() -> new ProductNotFoundException(productId));

        stock.decrease(quantity);               // CHECK 제약으로 음수 차단 (C)
        Order order = orderRepository.save(Order.of(productId, quantity));
        return order.getId();
    }
}
```

`stock.decrease()`가 예외를 던지면 `orderRepository.save()`도 없던 일이 됩니다. 이 두 줄이 한 단위가 되는 범위가 `placeOrder`의 시작과 끝입니다. 트랜잭션 경계는 **메서드가 아니라 프록시가 그립니다** — 같은 클래스 내부 호출로 들어오면 경계 자체가 안 생깁니다(`daily/day44-proxy-aop.md`).

### 3-2. 실행 흐름

커밋 한 번이 실제로 거치는 순서입니다.

1. `BEGIN` — 트랜잭션 ID 할당
2. `UPDATE` 실행 → **undo 로그**에 변경 전 이미지 기록 (A의 재료, 그리고 MVCC 읽기의 재료)
3. 메모리 버퍼의 데이터 페이지 수정 → 아직 디스크에는 안 갔습니다
4. **redo 로그 / WAL 버퍼**에 "무엇을 바꿨는지" 기록
5. `COMMIT` → redo 로그를 디스크에 쓰고 **`fsync`**
6. 클라이언트에 성공 응답
7. (한참 뒤) 더티 페이지를 디스크에 기록

5번과 6번의 순서가 지속성의 전부입니다. **`fsync`를 먼저 하고 응답을 보내기 때문에** 6번 직후 전원이 꺼져도 복구가 됩니다. 7번이 안 끝났어도 redo 로그로 다시 적용할 수 있으니까요.

이 순서를 바꾸는 게 6절의 설정값들입니다. 응답을 먼저 보내고 `fsync`를 나중에 하면 빨라집니다. 그리고 그 틈에 꺼지면 커밋했다고 응답한 데이터가 없습니다.

## 4. 네 글자가 약속하지 않는 것

정의를 외우는 것보다 이게 실무에서 쓸모가 있습니다.

### 4-1. A — "예외가 나면 다 롤백된다"가 아닙니다

세 군데에서 깨집니다.

**① DB 밖은 범위가 아닙니다.** 트랜잭션 안에서 보낸 HTTP 요청, 발행한 메시지, 쓴 파일은 롤백 대상이 아닙니다. 되돌릴 방법이 없으므로 설계로 풀어야 합니다 — 커밋 후로 미루거나, 재시도가 안전하게 만들거나(`daily/day21-idempotency.md`).

**② 에러 종류에 따라 롤백 범위가 다릅니다.** MySQL InnoDB는 에러에 따라 **트랜잭션 전체**를 되감거나 **문장 하나만** 되감습니다.

| 에러 | 롤백 범위 |
|---|---|
| 데드락 | 트랜잭션 전체 |
| Lock wait timeout | **현재 문장만** (기본값) |
| 중복 키 | **현재 문장만** |

출처: [MySQL 8.4 — InnoDB Error Handling](https://dev.mysql.com/doc/refman/8.4/en/innodb-error-handling.html). 매뉴얼은 lock wait timeout에서 전체를 되감고 싶으면 `innodb_rollback_on_timeout`을 켜라고 안내하고, 문장 하나만 되감을 때는 **락이 풀리지 않는다**고 명시합니다.

즉 `try-catch`로 중복 키 예외를 삼키면 그 문장만 사라지고 앞의 변경은 트랜잭션 안에 그대로 살아 있습니다. PostgreSQL은 다릅니다. 에러가 나면 트랜잭션 블록이 aborted 상태로 떨어지고, `ROLLBACK TO` 세이브포인트 외에는 통째로 되감는 수밖에 없습니다([PostgreSQL — Transactions](https://www.postgresql.org/docs/current/tutorial-transactions.html)).

**③ Spring은 검사 예외를 롤백하지 않습니다.** 기본 규칙은 `RuntimeException`과 `Error`뿐이고, 검사 예외는 기본 설정에서 롤백을 일으키지 않습니다([Spring Framework — Rolling Back a Declarative Transaction](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/rolling-back.html)). 검사 예외로 실패를 표현하는 코드라면 `rollbackFor`를 직접 지정해야 합니다.

**④ DDL은 커밋을 끼워 넣습니다.** MySQL에서 `CREATE TABLE`, `ALTER TABLE`, `TRUNCATE TABLE` 같은 문장은 실행 전에 **암묵적 커밋**을 일으킵니다([MySQL 8.4 — Statements That Cause an Implicit Commit](https://dev.mysql.com/doc/refman/8.4/en/implicit-commit.html)).

```sql
START TRANSACTION;
INSERT INTO orders (product_id, quantity) VALUES (1001, 2);
TRUNCATE TABLE order_audit;   -- 여기서 암묵적 COMMIT. 위 INSERT가 확정됩니다
ROLLBACK;                     -- 되감을 게 없습니다
```

마이그레이션 스크립트를 "실패하면 롤백되니까"라고 생각하고 짜면 여기서 당합니다. 매뉴얼은 `CREATE TEMPORARY TABLE`도 커밋은 안 일으키지만 롤백도 안 된다고 적고 있습니다.

### 4-2. C — 비즈니스 불변식은 포함되지 않습니다

ACID의 C는 "데이터가 업무 규칙에 맞다"는 뜻이 아닙니다. **선언된 제약조건을 위반한 상태로는 커밋되지 않는다**는 뜻입니다. 제약을 선언하지 않았으면 C가 지켜줄 게 없습니다.

"재고는 음수가 될 수 없다"를 코드로만 검사하면, 그건 C가 아니라 I의 문제로 넘어갑니다. 두 트랜잭션이 동시에 `SELECT`로 재고 10을 읽고 각각 8을 빼면, 둘 다 자기 기준으로는 올바른 트랜잭션입니다. ACID를 완벽히 지켜도 결과는 -6입니다.

그래서 불변식은 DB로 내리는 게 제일 싸게 끝납니다.

```sql
ALTER TABLE stock ADD CONSTRAINT ck_stock_quantity_non_negative
    CHECK (quantity >= 0);
```

이렇게 걸면 위 동시 실행에서 두 번째 커밋이 **DB에서 거부**됩니다. 애플리케이션 코드는 그 예외를 잡아 재시도하거나 실패를 알려주면 됩니다. 코드로만 막을 때와 달리, 어떤 경로로 들어온 쓰기든 빠져나갈 수 없습니다.

### 4-3. I — 기본값은 완전한 격리가 아닙니다

표준 격리 수준 중 "동시 실행 결과가 순차 실행과 같다"를 약속하는 건 SERIALIZABLE뿐입니다. 그리고 **어느 DB도 그걸 기본값으로 쓰지 않습니다.**

| DB | 기본 격리 수준 | 출처 |
|---|---|---|
| MySQL InnoDB | REPEATABLE READ | [InnoDB Transaction Isolation Levels](https://dev.mysql.com/doc/refman/8.4/en/innodb-transaction-isolation-levels.html) |
| PostgreSQL | Read Committed | [Transaction Isolation](https://www.postgresql.org/docs/current/transaction-iso.html) |

"ACID를 지키는 DB를 쓰니까 동시성은 괜찮다"는 문장이 틀린 지점이 여기입니다. ACID의 I는 **"어느 수준으로 격리할지 고를 수 있다"**는 약속이고, 기본값은 성능을 위해 일부 이상현상을 허용한 자리에 있습니다. 자세한 건 `daily/day56-transaction-isolation.md`.

참고로 PostgreSQL은 네 수준을 받아들이지만 내부적으로 셋만 구현해서, Read Uncommitted를 요청해도 Read Committed로 동작합니다. 같은 매뉴얼에 명시돼 있습니다.

### 4-4. D — 복제본까지 간다는 뜻이 아닙니다

지속성은 **그 서버의 디스크**에 대한 약속입니다. 서버가 돌아오지 않으면 끝입니다.

MySQL 복제는 기본이 비동기입니다. 소스가 커밋하고 응답을 보낸 시점에 그 트랜잭션이 복제본에 도착했는지는 소스가 모릅니다. 소스가 죽고 복제본으로 페일오버하면, **커밋 성공 응답을 받은 트랜잭션이 사라질 수 있습니다.** 매뉴얼은 반동기 복제가 "소스가 커밋한 모든 트랜잭션이 최소 한 대의 복제본에 전달됐음"을 보장한다고 설명하면서, 페일오버 후 죽은 소스는 어떤 복제본도 ack 하지 않은 트랜잭션을 가지고 있을 수 있으니 재사용하지 말고 폐기하라고 경고합니다([MySQL 8.4 — Semisynchronous Replication](https://dev.mysql.com/doc/refman/8.4/en/replication-semisync.html)).

ACID는 단일 노드의 속성입니다. 다중 노드에서 "커밋됐으면 살아남는다"를 원하면 복제 설정으로 따로 사야 합니다.

## 5. 예제 — 경계를 잘못 그은 코드

### 5-1. 클린하지 않은 코드 ❌

```java
@Transactional
public void placeOrder(OrderCommand command) {
    Order order = orderRepository.save(command.toOrder());

    // ❌ 외부 호출이 트랜잭션 안에 있습니다
    PaymentResult result = paymentClient.charge(order.getId(), order.getAmount());
    order.markPaid(result.getTransactionId());

    // ❌ 커밋 전에 발행합니다
    eventPublisher.publish(new OrderPlacedEvent(order.getId()));

    try {
        stockService.decrease(command.getProductId(), command.getQuantity());
    } catch (DuplicateKeyException e) {
        // ❌ 삼켰지만 트랜잭션은 깨끗하지 않습니다
        log.warn("재고 차감 중복", e);
    }
}
```

세 군데가 전부 ACID 바깥입니다.

1. 결제 API 응답을 기다리는 동안 DB 커넥션과 락을 잡고 있습니다. 뒤 문장이 터지면 주문은 롤백되고 **결제만 남습니다.**
2. 이벤트를 커밋 전에 발행했습니다. 롤백되면 구독자는 존재하지 않는 주문을 처리합니다.
3. 중복 키 예외를 삼켰습니다. MySQL이라면 그 문장만 되감겨서 **락은 안 풀린 채로** 트랜잭션이 계속됩니다.

### 5-2. 개선한 코드 ✔️

```java
public void placeOrder(OrderCommand command) {
    // 1단계: DB 트랜잭션은 DB 작업만 — 짧게 열고 닫습니다
    Long orderId = orderRegistrar.register(command);

    // 2단계: 외부 호출은 트랜잭션 밖에서
    PaymentResult result = paymentClient.charge(orderId, command.getAmount());

    // 3단계: 결과 반영도 별도 트랜잭션
    orderRegistrar.markPaid(orderId, result.getTransactionId());
}
```

```java
@Service
@RequiredArgsConstructor
public class OrderRegistrar {

    private final OrderRepository orderRepository;
    private final StockRepository stockRepository;
    private final ApplicationEventPublisher eventPublisher;

    @Transactional
    public Long register(OrderCommand command) {
        Stock stock = stockRepository.findByProductIdForUpdate(command.getProductId())
                .orElseThrow(() -> new ProductNotFoundException(command.getProductId()));
        stock.decrease(command.getQuantity());   // CHECK 제약이 최종 방어선

        Order order = orderRepository.save(command.toOrder());

        // 커밋 후에만 발행됩니다
        eventPublisher.publishEvent(new OrderPlacedEvent(order.getId()));
        return order.getId();
    }
}
```

```java
@Component
public class OrderPlacedListener {

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void on(OrderPlacedEvent event) {
        // 커밋이 확정된 뒤 실행됩니다. 롤백되면 호출되지 않습니다
        notificationSender.sendOrderConfirmation(event.getOrderId());
    }
}
```

달라진 것은 세 가지입니다.

- 트랜잭션 경계가 DB 작업만 감쌉니다. 외부 호출이 락 유지 시간에 영향을 주지 않습니다.
- 발행 시점을 `AFTER_COMMIT`으로 옮겨서, 롤백된 트랜잭션의 이벤트가 새어나가지 않습니다.
- 예외를 삼키지 않습니다. 결제까지 성공한 상태에서 뒤가 실패하는 경우는 "트랜잭션"이 아니라 보상 처리로 풀 문제이고, 그러려면 실패가 보여야 합니다.

2단계와 3단계 사이에서 죽으면 결제는 됐고 주문은 미결제로 남습니다. 이건 ACID로 해결되지 않습니다. **멱등 키를 두고 재조정하는 쪽으로 설계를 옮기는 것**이 정답이고, 그게 `daily/day21-idempotency.md`의 주제입니다.

## 6. ACID는 설정으로 끌 수 있습니다

지속성은 성능과 직접 교환됩니다. 그래서 끄는 스위치가 있습니다.

### MySQL

`innodb_flush_log_at_trx_commit`의 **기본값은 1**이고, 매뉴얼은 1이 "완전한 ACID 준수에 필요한 설정"이라고 명시합니다([InnoDB Startup Options and System Variables](https://dev.mysql.com/doc/refman/8.4/en/innodb-parameters.html#sysvar_innodb_flush_log_at_trx_commit)).

| 값 | 동작 | 잃는 것 |
|---:|---|---|
| 1 | 커밋마다 로그를 쓰고 `fsync` | 없음 (기본값) |
| 2 | 커밋마다 OS 캐시에 쓰고 `fsync`는 1초에 한 번 | **OS 크래시·전원 장애** 시 최근 커밋 |
| 0 | 1초에 한 번 쓰고 `fsync` | **mysqld 크래시**만으로도 최근 커밋 |

매뉴얼은 0과 2에서 "1초에 한 번"이 보장되지는 않는다는 것, 그리고 바이너리 로그를 쓸 때 지속성을 원하면 `sync_binlog=1`을 함께 써야 한다는 것도 적고 있습니다.

### PostgreSQL

`synchronous_commit`의 기본값은 `on`입니다. 끌 수도 있는데, 매뉴얼은 끄는 것의 위험이 `fsync`를 끄는 것과 **질적으로 다르다**고 선을 긋습니다 — `off`는 최근 커밋이 **깔끔하게 중단된 것처럼** 사라질 뿐 DB 상태가 깨지지는 않고, `fsync = off`는 복구 불가능한 데이터 손상으로 이어질 수 있다고 적고 있습니다([Write Ahead Log 설정](https://www.postgresql.org/docs/current/runtime-config-wal.html)).

이 구분이 실무에서 중요합니다. **"지속성을 조금 포기한다"와 "일관성을 포기한다"는 복구 난이도가 다릅니다.** 최근 몇백 ms의 커밋이 사라지는 건 대개 재처리로 메울 수 있습니다. 데이터 파일이 깨지는 건 백업에서 복구하는 수밖에 없습니다.

> 끌 거면 **무엇이 사라져도 되는 데이터인지** 먼저 답해야 합니다. 배치 적재용 임시 인스턴스라면 2가 합리적입니다. 결제 원장이라면 성능 때문에 건드리는 설정이 아닙니다.

## 7. 함정

**① 트랜잭션 안에서 외부 API를 호출합니다**

- **증상**: 평소엔 괜찮다가 외부 서비스가 느려지면 커넥션 풀이 마르고 전체가 멈춥니다. 그리고 결제는 됐는데 주문이 없는 데이터가 생깁니다.
- **원인**: 외부 호출 대기 시간이 트랜잭션 유지 시간에 더해집니다. 그리고 외부 호출은 롤백되지 않아서, 부분 실패가 그대로 남습니다.
- **해법**: 트랜잭션 경계를 DB 작업으로 좁힙니다. 외부 호출은 커밋 전후로 꺼내고, 중간에 죽는 경우는 멱등 키 + 재조정으로 처리합니다.

**② 검사 예외를 던졌는데 롤백이 안 됩니다**

- **증상**: 비즈니스 실패를 검사 예외로 설계했는데, 예외가 올라갔음에도 앞서 저장한 행이 DB에 남아 있습니다.
- **원인**: Spring의 기본 롤백 규칙은 `RuntimeException`과 `Error`뿐입니다.
- **해법**: `@Transactional(rollbackFor = ...)`로 명시하거나, 롤백돼야 하는 실패는 비검사 예외로 설계합니다(`daily/day61-checked-unchecked.md`).

**③ 중복 키 예외를 `try-catch`로 삼킵니다**

- **증상**: "이미 있으면 무시"를 의도했는데 뒤에서 `Lock wait timeout`이 나거나, 커밋 결과가 기대와 다릅니다.
- **원인**: MySQL은 중복 키에서 그 문장만 되감습니다. 획득한 락은 풀리지 않고, 트랜잭션은 계속 열려 있습니다. JPA라면 flush 실패 후 영속성 컨텍스트 상태를 신뢰할 수 없습니다.
- **해법**: 삼키지 말고 트랜잭션을 끝냅니다. "있으면 무시"가 필요하면 `INSERT ... ON DUPLICATE KEY UPDATE`(MySQL)나 `ON CONFLICT DO NOTHING`(PostgreSQL)처럼 **DB에게 한 문장으로 맡기거나**, 삼켜야 할 구간을 세이브포인트로 감쌉니다.

**④ 마이그레이션 스크립트가 반만 적용됩니다**

- **증상**: 배포 중 실패했는데 스키마가 중간 상태로 남아 재실행도 안 됩니다.
- **원인**: MySQL에서 DDL은 암묵적 커밋을 일으킵니다. 여러 DDL을 `START TRANSACTION`으로 감싸도 묶이지 않습니다.
- **해법**: MySQL에서는 DDL 하나를 마이그레이션 하나로 쪼개고, 각 단계가 다시 실행돼도 안전하게 짭니다. 여러 DDL의 원자적 적용이 필요하면 PostgreSQL처럼 트랜잭션 DDL을 지원하는 DB에서만 기대합니다.

**⑤ 페일오버 후 데이터가 사라졌습니다**

- **증상**: 장애 복구 후 "주문했는데 내역이 없다"는 문의가 들어옵니다. 애플리케이션 로그에는 커밋 성공이 찍혀 있습니다.
- **원인**: 복제가 비동기여서, 커밋이 복제본에 도달하기 전에 소스가 죽었습니다. ACID는 이 경우를 약속하지 않습니다.
- **해법**: 손실을 허용할 수 없으면 반동기 복제(MySQL)나 동기 스탠바이(PostgreSQL)를 씁니다. 지연이 늘어나므로 공짜가 아닙니다. 그리고 **페일오버한 구 소스는 다시 소스로 쓰지 않습니다.**

## 8. 참고자료

- [MySQL 8.4 — Glossary: ACID](https://dev.mysql.com/doc/refman/8.4/en/glossary.html#glos_acid)
- [MySQL 8.4 — InnoDB Error Handling](https://dev.mysql.com/doc/refman/8.4/en/innodb-error-handling.html)
- [MySQL 8.4 — Statements That Cause an Implicit Commit](https://dev.mysql.com/doc/refman/8.4/en/implicit-commit.html)
- [MySQL 8.4 — `innodb_flush_log_at_trx_commit`](https://dev.mysql.com/doc/refman/8.4/en/innodb-parameters.html#sysvar_innodb_flush_log_at_trx_commit)
- [MySQL 8.4 — Semisynchronous Replication](https://dev.mysql.com/doc/refman/8.4/en/replication-semisync.html)
- [PostgreSQL — Transaction Isolation](https://www.postgresql.org/docs/current/transaction-iso.html)
- [PostgreSQL — Write Ahead Log 설정](https://www.postgresql.org/docs/current/runtime-config-wal.html)
- [Spring Framework — Rolling Back a Declarative Transaction](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/rolling-back.html)
- 관련 챕터: `daily/day56-transaction-isolation.md`, `daily/day50-transaction-propagation.md`, `daily/day21-idempotency.md`, `daily/day44-proxy-aop.md`, `daily/day61-checked-unchecked.md`

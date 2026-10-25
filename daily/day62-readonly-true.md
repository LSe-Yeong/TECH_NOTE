# `readOnly = true`는 실제로 무엇을 하는가

> 이 문서가 답할 질문: **`@Transactional(readOnly = true)`를 붙이면 어느 계층에서 무슨 일이 일어나고, 무엇은 끝까지 보장되지 않는가?**
>
> 분류: 기술이해형. "붙이면 빨라진다"는 말만 듣고 쓰는 설정이라, 비교 기준보다 **이 플래그가 원래 무엇을 하려고 만들어졌는지**를 먼저 세워야 나머지가 설명됩니다. 다만 "읽기 전용 메서드에서 수정했는데 저장이 안 됐다"는 증상이 너무 흔해서 5절과 10절은 문제해결형으로 썼습니다.
>
> 기준: **Spring Framework 7.0 / Spring Boot 4.1** 레퍼런스와 Javadoc, Spring Data JPA 레퍼런스, **MySQL 8.4** 매뉴얼, **MySQL Connector/J**와 **PostgreSQL JDBC** 드라이버 문서를 확인해 썼습니다. 트랜잭션이 프록시를 타는 과정은 `daily/day44-proxy-aop.md`, 전파는 `daily/day50-transaction-propagation.md`, 격리 수준은 `daily/day56-transaction-isolation.md`에 있습니다.

## 1. 핵심 개념 — 하나의 boolean이 세 계층에서 각각 다른 일을 합니다

`readOnly`는 "이 트랜잭션은 읽기만 한다"는 **선언**입니다. 선언이 통과하는 계층마다 하는 일이 다릅니다.

| 계층 | 하는 일 | 성격 |
|---|---|---|
| Spring 트랜잭션 동기화 | 현재 트랜잭션이 읽기 전용이라는 사실을 기록 | 조회 가능한 상태값 |
| JPA / Hibernate | flush 모드를 `MANUAL`로, 세션 기본값을 read-only로 | 최적화 + 쓰기 무력화 |
| JDBC 커넥션 | `Connection.setReadOnly(true)` | 드라이버에 주는 힌트 |

> 여기서 반드시 한 번 데입니다. Spring Data JPA 레퍼런스는 이 플래그에 대해 **"조작 쿼리를 트리거하지 않는지 검사하는 역할은 하지 않는다"**고 못 박고, 플래그는 "성능 최적화를 위해 JDBC 드라이버에 힌트로 전달된다"고 설명합니다([Transactions](https://docs.spring.io/spring-data/jpa/reference/jpa/transactions.html)). 즉 Spring은 쓰기를 **막지 않습니다.** 대신 flush를 꺼버립니다. 그 결과 `readOnly = true`인 메서드 안에서 엔티티 필드를 바꾸면 예외도, 경고 로그도 없이 **그냥 없던 일이 됩니다.** 테스트는 통과하고, 응답도 정상이고, DB만 그대로입니다.

이 플래그가 존재하는 이유는 성능보다 **정보 전달**에 가깝습니다. 애플리케이션만 아는 사실("이 작업은 읽기다")을 JPA 구현체와 드라이버와 DB에 내려보내면, 각 계층이 자기가 할 수 있는 최적화를 선택합니다. 안 내려보내면 모든 계층이 최악을 가정하고 준비합니다.

## 2. 구조 — 플래그가 실제로 닿는 세 지점

### 2-1. Spring 트랜잭션 동기화 — 읽기 전용이라는 "사실"

가장 단순한 계층입니다. 트랜잭션이 시작되면 읽기 전용 여부가 스레드에 묶여 기록되고, 아무 코드에서나 꺼내 볼 수 있습니다.

```java
boolean readOnly = TransactionSynchronizationManager.isCurrentTransactionReadOnly();
```

이 값은 최적화에 쓰이는 게 아닙니다. **분기 근거**로 쓰입니다. 7절의 리플리카 라우팅이 전부 여기서 출발합니다.

### 2-2. JPA / Hibernate — 여기가 체감 효과의 대부분입니다

`HibernateJpaDialect.beginTransaction()`이 읽기 전용 트랜잭션에서 두 가지를 합니다.

1. `prepareFlushMode(session, true)` — flush 모드가 `MANUAL`이 아니면 `FlushMode.MANUAL`로 바꾸고, 원래 값을 보관합니다.
2. 트랜잭션 전용 `EntityManager`인 경우 `session.setDefaultReadOnly(true)`를 호출합니다.

1번이 **더티 체킹 결과가 SQL이 되지 않게** 합니다. 더티 체킹은 flush 시점에 돌기 때문에, flush가 아예 없으면 변경 감지 자체가 의미를 잃습니다. 레퍼런스는 이걸 "큰 객체 트리에서 눈에 띄는 개선"이라고 설명합니다.

2번은 **로드 시점 스냅샷을 보관하지 않게** 해서 영속성 컨텍스트의 메모리 사용을 줄입니다. 읽기 전용 플래그를 Hibernate `Session`까지 내려보내는 동작은 Spring Framework 5.1에 들어왔습니다(SPR-16956, [Vlad Mihalcea의 정리](https://vladmihalcea.com/spring-read-only-transaction-hibernate-optimization/)). 그 전에는 flush 모드만 바꿨습니다.

### 2-3. JDBC 커넥션 — 여기부터는 Spring 소관이 아닙니다

`HibernateJpaDialect`의 `prepareConnection` 플래그(기본값 `true`)가 켜져 있으면 `DataSourceUtils.prepareConnectionForTransaction()`을 거쳐 `Connection.setReadOnly(true)`가 호출됩니다. Javadoc은 이 플래그를 끄면 "읽기 전용 트랜잭션에서 `Connection.setReadOnly(true)`를 더 이상 호출하지 않는다"고 적습니다([HibernateJpaDialect](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/orm/jpa/vendor/HibernateJpaDialect.html)).

문제는 `Connection.setReadOnly()`가 **JDBC 스펙상 힌트**라는 점입니다. 실제로 무슨 일이 벌어지는지는 드라이버가 정합니다.

| 드라이버 | 기본 설정에서의 동작 |
|---|---|
| MySQL Connector/J | `readOnlyPropagatesToServer` 기본값 `true` — 서버 측 트랜잭션 접근 모드를 설정하는 문장을 보냅니다. 문서는 "InnoDB 읽기 전용 최적화를 활성화하지만 왕복 1회가 추가된다"고 명시합니다([Performance Extensions](https://dev.mysql.com/doc/connector-j/en/connector-j-connp-props-performance-extensions.html)) |
| PostgreSQL pgjdbc | `readOnlyMode` 기본값 `transaction` — autocommit이 꺼진 상태면 `BEGIN READ ONLY`를 보냅니다([Connection Parameters](https://jdbc.postgresql.org/documentation/use/)) |

**둘 다 기본 설정에서 DB가 실제로 쓰기를 거부합니다.** MySQL은 `ERROR 1792 (25006): Cannot execute statement in a READ ONLY transaction`을 돌려줍니다([Optimizing InnoDB Read-Only Transactions](https://dev.mysql.com/doc/refman/8.4/en/innodb-performance-ro-txn.html)).

여기서 혼란이 생깁니다. Spring 문서는 "막지 않는다"고 하는데 실제로는 막히는 경우가 있습니다. 둘 다 맞습니다. **막는 주체가 Spring이 아니라 드라이버와 DB**일 뿐입니다. 드라이버 설정 한 줄로 그 방어는 사라집니다.

## 3. 흐름

### 3-1. 코드로 보는 구성

```java
@Service
@Transactional(readOnly = true)
public class OrderQueryService {

    private final OrderRepository orderRepository;

    public OrderQueryService(OrderRepository orderRepository) {
        this.orderRepository = orderRepository;
    }

    public List<OrderSummary> findRecentOrders(Long customerId) {
        return orderRepository.findTop20ByCustomerIdOrderByIdDesc(customerId)
                .stream()
                .map(OrderSummary::from)
                .toList();
    }
}
```

### 3-2. 실행 흐름

1. 프록시가 `readOnly = true`인 `TransactionDefinition`을 만듭니다 (`daily/day44-proxy-aop.md`)
2. `JpaTransactionManager` → `HibernateJpaDialect.beginTransaction()`
3. `DataSourceUtils.prepareConnectionForTransaction()` → `Connection.setReadOnly(true)` → (MySQL 기본 설정) 서버로 접근 모드 전송
4. `entityManager.getTransaction().begin()`
5. `prepareFlushMode()` → flush 모드 `MANUAL`, 이전 값 보관
6. 메서드 본문 실행 — 조회 SQL만 나갑니다
7. 커밋 — flush 단계가 없으므로 `COMMIT`만
8. `cleanupTransaction()`이 flush 모드를 원복하고, `resetConnectionAfterTransaction()`이 `setReadOnly`를 되돌린 뒤 커넥션을 풀에 반납

8번을 빼면 안 됩니다. 커넥션은 풀에서 **재사용**되므로, 복원하지 않으면 다음 요청이 남의 읽기 전용 커넥션을 집어 들고 쓰기를 시도하게 됩니다. Spring은 복원하지만, 그 복원도 왕복 비용입니다(10절 함정 4).

## 4. 특징

### 4-1. 얻는 것

- **더티 체킹과 flush 제거.** 조회 결과가 많을수록 커집니다.
- **영속성 컨텍스트 메모리 절감.** 로드 시점 스냅샷을 들고 있지 않습니다.
- **DB 측 읽기 전용 최적화.** MySQL은 읽기 전용으로 확정된 트랜잭션에 트랜잭션 ID를 할당하지 않고, 그 결과 read view를 만들 때 뒤지는 내부 구조가 작아집니다.
- **의도 선언.** 메서드 시그니처만 보고 "이건 안 쓴다"를 알 수 있고, 코드가 아닌 인프라(라우팅)도 그 선언을 읽을 수 있습니다.

구체적인 개선 폭을 숫자로 적은 공식 자료는 확인하지 못했습니다. <!-- TODO: 확인 필요 — Spring/Hibernate 공식 벤치마크 수치 없음. 출처 없는 수치는 쓰지 않습니다 -->

### 4-2. 지불하는 것

- **커넥션 준비·복원 왕복.** MySQL 기본 설정에서는 트랜잭션마다 접근 모드 설정이 한 번 더 오갑니다.
- **쓰기 실수가 런타임까지 숨습니다.** 컴파일러는 아무것도 모릅니다.
- **라우팅을 붙이는 순간 플래그의 의미가 바뀝니다.** 최적화 힌트가 "어느 DB로 보낼지"의 결정이 되고, 잘못 붙이면 복제 지연 문제로 바뀝니다.
- **참여 트랜잭션에서는 조용히 무시됩니다**(10절 함정 2).

## 5. 예제 — 쓰기가 조용히 사라지는 코드

### 5-1. 클린하지 않은 코드 ❌

```java
@Transactional(readOnly = true)
public OrderSummary viewOrder(Long orderId) {
    Order order = orderRepository.findById(orderId).orElseThrow();
    order.markViewed(Instant.now());   // 더티 체킹을 기대했지만 flush가 없어 UPDATE가 나가지 않습니다
    return OrderSummary.from(order);
}
```

**증상이 "아무 일도 안 일어남"이라 디버깅이 오래 걸립니다.** 예외 없음, 응답 정상, `viewedAt`만 영원히 `null`입니다.

그런데 같은 메서드에서 이렇게 쓰면 결과가 다릅니다.

```java
@Transactional(readOnly = true)
public Long saveDraft(OrderDraft draft) {
    return orderRepository.save(draft.toOrder()).getId();   // 전략에 따라 즉시 INSERT → DB가 거부
}
```

`GenerationType.IDENTITY`는 식별자를 알아야 엔티티를 영속성 컨텍스트에 넣을 수 있어서, Hibernate가 `persist` 시점에 INSERT를 바로 실행합니다. 그래서 이쪽은 조용히 사라지는 대신 `ERROR 1792`로 터집니다. <!-- TODO: 확인 필요 — IDENTITY의 즉시 INSERT는 Hibernate 포럼의 개발자 설명과 "IDENTITY에서는 JDBC 배치가 꺼진다"는 문서 서술에 근거합니다. Hibernate 7 공식 문서의 명시적 문장은 찾지 못했습니다 -->

**같은 "쓰기"인데 하나는 침묵하고 하나는 예외입니다.** `readOnly = true`를 "쓰면 터지니까 안전하다"고 이해하면 안 되는 이유가 이것입니다. 터지는 건 운이 좋은 쪽입니다.

### 5-2. 개선한 코드 ✔️

읽기와 쓰기를 **메서드 단위로** 가릅니다. 클래스에 읽기 전용을 깔고, 쓰는 메서드만 덮어씁니다.

```java
@Service
@Transactional(readOnly = true)
public class OrderService {

    private final OrderRepository orderRepository;

    public OrderService(OrderRepository orderRepository) {
        this.orderRepository = orderRepository;
    }

    public OrderSummary viewOrder(Long orderId) {
        return OrderSummary.from(orderRepository.findById(orderId).orElseThrow());
    }

    @Transactional   // 메서드 선언이 우선합니다 — readOnly는 기본값 false
    public void markViewed(Long orderId) {
        orderRepository.findById(orderId).orElseThrow().markViewed(Instant.now());
    }
}
```

레퍼런스가 보여주는 형태가 정확히 이것입니다. "가장 파생된 위치의 설정이 우선한다"는 규칙 때문에 클래스 레벨 `readOnly = true` 위에 메서드 레벨 선언을 얹을 수 있습니다([Annotations](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/annotations.html)).

두 가지를 같이 기억해야 합니다. `viewOrder`가 `markViewed`를 **같은 클래스 안에서** 호출하면 프록시를 거치지 않아 아무 효과가 없고(`daily/day44-proxy-aop.md`), 프록시를 거치더라도 **바깥 트랜잭션이 읽기 전용이면 안쪽 선언은 무시됩니다**(함정 2).

## 6. 힌트를 규칙으로 바꾸는 두 개의 스위치

침묵이 싫다면 강제할 수 있습니다. 단, 성격이 다른 두 개입니다.

**(a) `enforceReadOnly`** — `DataSourceTransactionManager`의 속성이고 기본값은 `false`입니다. 켜면 `Connection.setReadOnly()` 힌트 대신 `SET TRANSACTION READ ONLY`를 명시적으로 실행합니다. Javadoc은 이 방식이 "Spring이 기본으로 적용하는 `Connection.setReadOnly(boolean)` 힌트를 넘어서, 데이터 조작 문장이 엄격히 금지되는 연결 모드를 강제한다"고 설명합니다([DataSourceTransactionManager](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/jdbc/datasource/DataSourceTransactionManager.html)). **JPA를 쓰면 이 속성은 없습니다.** `JpaTransactionManager`에는 해당하지 않습니다.

**(b) `validateExistingTransaction`** — `AbstractPlatformTransactionManager`의 속성이라 JPA에서도 씁니다. 기본값은 `false`이고, 켜면 "읽기 전용 외부 스코프에 읽기-쓰기 내부 트랜잭션이 참여하려는" 불일치를 거부합니다([Transaction Propagation](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/tx-propagation.html)).

```java
// Spring Boot 4.x — org.springframework.boot.transaction.autoconfigure.TransactionManagerCustomizer
@Bean
TransactionManagerCustomizer<AbstractPlatformTransactionManager> strictReadOnlyValidation() {
    return transactionManager -> transactionManager.setValidateExistingTransaction(true);
}
```

(b)는 "조용히 무시"를 "예외"로 바꿉니다. 기존 코드에 켜면 그동안 무시되던 선언들이 한꺼번에 터지므로, 스테이징에서 먼저 켜고 세어 봅니다.

## 7. 확장 지점 응용 — 읽기 전용 트랜잭션을 리플리카로 보내기

2-1에서 기록된 "읽기 전용이라는 사실"을 가장 크게 써먹는 곳입니다.

순진하게 구현하면 실패합니다. 트랜잭션 시작 시점에 커넥션을 먼저 잡아버리면, 읽기 전용 여부를 보기 전에 어느 DB인지가 이미 정해집니다. 그래서 **커넥션 획득을 첫 `Statement` 생성 시점까지 미루는** 프록시가 필요합니다.

```java
@Bean
DataSource dataSource(@Qualifier("writerDataSource") DataSource writer,
                      @Qualifier("readerDataSource") DataSource reader) {
    LazyConnectionDataSourceProxy proxy = new LazyConnectionDataSourceProxy(writer);
    proxy.setReadOnlyDataSource(reader);
    return proxy;
}
```

`setReadOnlyDataSource`는 Spring Framework 6.1.2에 추가됐습니다. Javadoc의 설계 의도가 분명합니다 — 읽기 전용으로 표시된 트랜잭션에서는 이 DataSource의 커넥션을 지연 획득하고, **`Connection.setReadOnly()`는 건드리지 않습니다.** 해당 DataSource에 읽기 전용이 기본값으로 미리 설정돼 있을 것으로 보고, 매 트랜잭션 시작·종료마다 토글하는 오버헤드를 없애는 겁니다([LazyConnectionDataSourceProxy](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/jdbc/datasource/LazyConnectionDataSourceProxy.html)).

여기서부터 `readOnly = true`는 성능 플래그가 아닙니다. **트래픽을 어디로 보낼지 정하는 라우팅 키**입니다. 빼먹으면 조회 부하가 전부 마스터로 가고, 쓰기 직후 조회에 잘못 붙이면 복제 지연 때문에 방금 쓴 데이터가 안 보입니다.

## 8. 실무에서 찾아보는 `readOnly`

Spring Data JPA의 `SimpleJpaRepository`에 클래스 레벨 `@Transactional(readOnly = true)`가 걸려 있습니다. 그래서 서비스에 `@Transactional`을 안 붙여도 `findById` 호출 하나에 읽기 전용 트랜잭션이 열립니다. 쓰기 메서드(`save`, `delete` 등)만 `@Transactional`로 덮여 있습니다.

레퍼런스가 권장하는 사용자 레포지토리 형태도 같습니다.

```java
@Transactional(readOnly = true)
interface UserRepository extends JpaRepository<User, Long> {

    List<User> findByLastname(String lastname);

    @Modifying
    @Transactional
    @Query("delete from User u where u.active = false")
    void deleteInactiveUsers();
}
```

`@Modifying` 쿼리는 영속성 컨텍스트를 거치지 않고 JDBC로 바로 나갑니다. 그래서 flush 모드와 무관하게 **실행됩니다.** 위 코드가 `@Transactional`을 다시 붙여 덮는 이유가 그것입니다. 안 덮으면 드라이버와 DB 설정에 따라 "통과"와 "ERROR 1792" 사이에서 결과가 갈립니다.

## 10. 함정

**함정 1 — 수정이 조용히 사라집니다**
- **증상**: 읽기 전용 메서드에서 엔티티 필드를 바꿨는데 UPDATE가 안 나갑니다. 예외도 로그도 없습니다.
- **원인**: flush 모드가 `MANUAL`이라 더티 체킹 결과가 SQL로 변환되는 단계 자체가 없습니다.
- **해법**: 쓰기를 별도 메서드로 분리하고 `@Transactional`로 덮습니다. 운영 중 검증이 필요하면 `validateExistingTransaction`을 켭니다.

**함정 2 — 바깥이 읽기 전용이면 안쪽 선언이 무시됩니다**
- **증상**: `@Transactional`을 제대로 붙인 쓰기 메서드인데 저장이 안 됩니다. 단위 테스트에서는 됩니다.
- **원인**: 레퍼런스가 명시합니다 — 참여하는 트랜잭션은 외부 스코프의 특성을 따르고, 지역 격리 수준·타임아웃·읽기 전용 플래그를 **조용히 무시**합니다. 클래스 레벨 `readOnly = true`인 조회 메서드가 쓰기 메서드를 부르는 구조에서 흔합니다.
- **해법**: 쓰기를 포함하는 호출 경로의 **가장 바깥** 메서드가 읽기 전용이 아니어야 합니다. 읽기 흐름과 쓰기 흐름의 진입점을 아예 다른 클래스로 분리하는 편이 안전합니다.

**함정 3 — 드라이버 설정 한 줄로 방어가 사라집니다**
- **증상**: 개발 환경에서는 읽기 전용 트랜잭션의 쓰기가 에러로 걸렸는데, 다른 환경에서는 그대로 커밋됩니다.
- **원인**: 쓰기를 거부하는 주체는 Spring이 아니라 드라이버와 DB입니다. MySQL에서 `readOnlyPropagatesToServer=false`로 두거나, pgjdbc에서 `readOnlyMode=ignore`로 두면 서버는 읽기 전용인 줄 모릅니다. 환경별 JDBC URL이 다르면 바로 벌어집니다.
- **해법**: JDBC URL의 드라이버 옵션을 환경 간에 맞춥니다. DB 레벨 보장이 필요하면 리플리카 계정에 쓰기 권한을 주지 않는 쪽이 설정보다 확실합니다.

**함정 4 — 읽기 전용인데 왕복이 늘어납니다**
- **증상**: 짧은 조회에 `readOnly = true`를 일괄 적용했는데 기대한 만큼 빨라지지 않습니다.
- **원인**: MySQL Connector/J 문서가 적어 둔 그대로입니다. 서버 측 접근 모드를 설정하려면 **왕복이 한 번 추가**되고, 트랜잭션이 끝나면 복원하면서 또 한 번 오갑니다. 조회가 가벼울수록 이 고정비의 비중이 커집니다.
- **해법**: 드라이버 옵션을 끄는 것은 함정 3을 자초하므로 권하지 않습니다. 7절처럼 `LazyConnectionDataSourceProxy` + 읽기 전용 DataSource로 **토글 자체를 없애거나**, 결과 집합이 크고 영속성 컨텍스트가 무거워지는 트랜잭션에 우선 적용합니다.

## 11. 참고자료

- [Spring Data JPA — Transactions](https://docs.spring.io/spring-data/jpa/reference/jpa/transactions.html)
- [Spring Framework — Using `@Transactional`](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/annotations.html)
- [Spring Framework — Transaction Propagation](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/tx-propagation.html)
- [`HibernateJpaDialect` Javadoc](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/orm/jpa/vendor/HibernateJpaDialect.html)
- [`DataSourceTransactionManager` Javadoc](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/jdbc/datasource/DataSourceTransactionManager.html)
- [`LazyConnectionDataSourceProxy` Javadoc](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/jdbc/datasource/LazyConnectionDataSourceProxy.html)
- [MySQL 8.4 — Optimizing InnoDB Read-Only Transactions](https://dev.mysql.com/doc/refman/8.4/en/innodb-performance-ro-txn.html)
- [MySQL Connector/J — Performance Extensions](https://dev.mysql.com/doc/connector-j/en/connector-j-connp-props-performance-extensions.html)
- [PostgreSQL JDBC — Connection Parameters](https://jdbc.postgresql.org/documentation/use/)
- [Vlad Mihalcea — Spring read-only transaction Hibernate optimization](https://vladmihalcea.com/spring-read-only-transaction-hibernate-optimization/)
- 관련 챕터: `daily/day44-proxy-aop.md`, `daily/day50-transaction-propagation.md`, `daily/day56-transaction-isolation.md`

# 격리 수준을 올리면 무엇이 생기는가

> 이 문서가 답할 질문: **동시성 버그를 만났을 때 `@Transactional(isolation = ...)`을 올리는 것이 답인가, 그리고 올리면 무엇을 지불하는가?**
>
> 분류: 선택형(A vs B). 실무에서 이 애노테이션을 건드리게 되는 상황은 거의 항상 "격리 수준을 올릴까, 락이나 버전으로 범위를 좁힐까"의 선택이고, 여러 출처가 공통으로 드는 비교 기준도 거기에 모입니다. 다만 "붙였는데 안 먹는다"는 증상이 너무 흔해서 3절만 문제해결형으로 끼워 넣었습니다.
>
> 기준: **Spring Boot 4.1 / Spring Framework 7.0** 레퍼런스와 Javadoc, **MySQL 8.4** 매뉴얼, **PostgreSQL 현행** 매뉴얼을 확인해 썼습니다. 이상현상(dirty read, phantom 등)의 정의 자체와 DB별 락 종류는 데이터베이스 챕터 범위이고, 여기서는 **Spring에서 이 값을 바꿀 때 벌어지는 일**만 다룹니다. 전파는 `daily/day50-transaction-propagation.md`에 있습니다.

## 1. 핵심 개념 — 올려서 사는 것은 보장 하나뿐입니다

격리 수준은 "동시성 버그를 끄는 스위치"가 아닙니다. **어떤 이상현상까지 발생하지 않도록 DB가 보장해줄지**를 고르는 다이얼입니다. 올리면 특정 이상현상 하나가 사라지고, 그 대가로 **락 범위가 넓어지거나 트랜잭션이 더 자주 실패**합니다.

Spring의 `Isolation` enum은 다섯 개이고 기본값은 `DEFAULT`입니다. `DEFAULT`는 "데이터 저장소의 기본 격리 수준을 쓴다"는 뜻이고, 나머지 넷은 JDBC 격리 수준에 그대로 대응합니다([Isolation Javadoc](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/transaction/annotation/Isolation.html)).

> 여기서 반드시 한 번 데입니다. 재고가 음수로 떨어지는 버그를 보고 `isolation = Isolation.SERIALIZABLE`을 붙이면 로컬 테스트는 통과합니다. 동시 요청이 없으니까요. 프로덕션에서는 `Lock wait timeout exceeded`가 쏟아지거나(MySQL), `could not serialize access`로 요청의 일부가 그냥 실패합니다(PostgreSQL). **격리 수준을 올리는 것은 버그를 고치는 게 아니라, 버그가 성립하는 동시 실행을 DB가 거부하게 만드는 것입니다.** 거부 방식이 "기다리게"인지 "죽이기"인지는 DB가 정하고, 그 차이가 애플리케이션 코드에 요구하는 것이 전혀 다릅니다.

## 2. 구조 — 이 값이 실제로 거치는 경로

`@Transactional(isolation = ...)`은 SQL을 바꾸지 않습니다. **커넥션 설정**을 바꿉니다.

1. 프록시가 `@Transactional`을 읽어 `TransactionDefinition`을 만듭니다 (`daily/day44-proxy-aop.md`)
2. 트랜잭션 매니저가 커넥션을 꺼내고 `DataSourceUtils.prepareConnectionForTransaction()`을 호출합니다
3. 이 메서드가 `Connection.setTransactionIsolation()`을 호출하고 **원래 격리 수준을 리턴**합니다
4. 트랜잭션이 끝나면 `resetConnectionAfterTransaction()`이 그 값으로 되돌립니다

출처: [DataSourceUtils Javadoc](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/jdbc/datasource/DataSourceUtils.html) — `prepareConnectionForTransaction`의 리턴값이 "the previous isolation level, if any"이고, `resetConnectionAfterTransaction`이 그것을 복원합니다.

3번과 4번이 세트라는 게 중요합니다. 커넥션은 풀에서 재사용되므로, 복원하지 않으면 다음 요청이 남의 격리 수준으로 돕니다. Spring은 복원하지만 **DB 클라이언트나 마이그레이션 툴이 SQL로 직접 `SET TRANSACTION ISOLATION LEVEL`을 날리면 풀이 그 변화를 못 봅니다.** HikariCP FAQ는 이 경우를 명시적으로 경고하고, 바꿀 때는 SQL이 아니라 `Connection.setTransactionIsolation()`을 쓰라고 안내합니다([HikariCP FAQ](https://github.com/brettwooldridge/HikariCP/wiki/FAQ)).

### 2-1. 트랜잭션 매니저마다 지원 여부가 다릅니다

| 매니저 | 커스텀 격리 수준 |
|---|---|
| `DataSourceTransactionManager` | 지원. JDBC 커넥션에 직접 적용 |
| `JpaTransactionManager` + Hibernate | 지원하지만 **조건부** |
| `JtaTransactionManager` | **미지원** |

JPA 쪽 조건은 `HibernateJpaDialect`의 `prepareConnection` 플래그입니다. 기본값은 `true`이고, Javadoc은 "이 플래그를 끄면 JPA 트랜잭션 관리가 더 이상 트랜잭션별 격리 수준을 지원하지 않는다"고 명시합니다([HibernateJpaDialect Javadoc](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/orm/jpa/vendor/HibernateJpaDialect.html)). 기본 JPA 다이얼렉트(`DefaultJpaDialect`)는 기본값이 아닌 격리 수준이 오면 `InvalidIsolationLevelException`을 던집니다.

JTA는 더 분명합니다. `JtaTransactionManager` Javadoc은 "이 순수 JTA 구현은 타임아웃은 지원하지만 트랜잭션별 격리 수준은 지원하지 않는다"고 하고, `applyIsolationLevel`의 기본 구현은 `ISOLATION_DEFAULT` 외의 모든 값에 예외를 던집니다([JtaTransactionManager Javadoc](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/transaction/jta/JtaTransactionManager.html)).

## 3. 먼저 확인할 것 — 붙여도 조용히 무시되는 경우

올리기 전에 이것부터 봅니다. **외부 트랜잭션에 참여하면 내가 적은 격리 수준은 적용되지 않습니다.** 레퍼런스 문장이 분명합니다 — 참여하는 트랜잭션은 외부 스코프의 특성을 따르고, 지역 격리 수준·타임아웃·읽기 전용 플래그를 **조용히 무시**합니다([Transaction Propagation](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/tx-propagation.html)).

```java
@Transactional                                  // 외부: DB 기본 격리 수준
public void settleOrder(Long orderId) {
    stockService.deductStrictly(orderId);       // isolation = SERIALIZABLE → 무시됨
}
```

예외도 경고 로그도 없습니다. 테스트에서 `deductStrictly`를 단독 호출하면 격리 수준이 적용되고, 프로덕션에서 `settleOrder`를 타면 적용되지 않습니다. **같은 코드가 호출 경로에 따라 다른 격리 수준으로 돕니다.**

`@Transactional` 설정 표는 `isolation`에 대해 "`REQUIRED` 또는 `REQUIRES_NEW` 전파에만 적용된다"고 적습니다([Annotations](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/annotations.html)). `REQUIRED`는 참여도 하므로, 실제로 적용이 보장되는 것은 **그 트랜잭션을 시작하는 쪽**뿐입니다.

무시되는 대신 실패하게 만들려면 트랜잭션 매니저의 `validateExistingTransaction`을 `true`로 켭니다. 레퍼런스는 이 비관용 모드가 격리 수준 선언과 읽기 전용 불일치를 모두 거부한다고 설명합니다. 기본값은 `false`입니다.

```java
// Spring Boot 4.x — org.springframework.boot.transaction.autoconfigure.TransactionManagerCustomizer
@Bean
TransactionManagerCustomizer<AbstractPlatformTransactionManager> strictIsolationValidation() {
    return transactionManager -> transactionManager.setValidateExistingTransaction(true);
}
```

**결론부터 말하면 격리 수준은 트랜잭션 경계를 시작하는 메서드에만 적는 설정입니다.** 하위 서비스에 붙은 `isolation`은 대부분 아무 일도 하지 않습니다.

## 4. 올리면 DB에서 실제로 벌어지는 일

먼저 내 DB의 기본값을 알아야 합니다. 둘이 다릅니다.

| DB | 기본 격리 수준 | 출처 |
|---|---|---|
| MySQL (InnoDB) | `REPEATABLE READ` | [InnoDB Transaction Isolation Levels](https://dev.mysql.com/doc/refman/8.4/en/innodb-transaction-isolation-levels.html) |
| PostgreSQL | `READ COMMITTED` | [Transaction Isolation](https://www.postgresql.org/docs/current/transaction-iso.html) |

MySQL을 쓰면 이미 한 칸 위에서 돌고 있습니다. "올려야 한다"고 느낀 문제가 사실은 `REPEATABLE READ`**이기 때문에** 생긴 문제일 수도 있습니다.

### 4-1. MySQL에서 올리면 갭 락이 켜집니다

MySQL의 두 수준 차이는 "보이는 데이터"만이 아니라 **잠그는 범위**입니다.

- `REPEATABLE READ`에서 locking read·`UPDATE`·`DELETE`가 범위 검색이면, InnoDB는 스캔한 인덱스 범위를 **갭 락 또는 넥스트키 락**으로 잠가 다른 세션이 그 범위에 INSERT하지 못하게 합니다. 유니크 인덱스로 단일 행을 찾을 때는 그 레코드만 잠급니다.
- `READ COMMITTED`에서는 인덱스 레코드만 잠그고 갭은 잠그지 않습니다. 갭 락은 외래 키 검사와 중복 키 검사에만 씁니다. 매뉴얼은 그래서 팬텀이 발생할 수 있다고 명시합니다.

둘 다 위 InnoDB 매뉴얼 문서의 내용입니다. 실무 결과는 이렇습니다. **`READ COMMITTED`에서 잘 돌던 서비스를 `REPEATABLE READ`로 올리면 INSERT가 막히기 시작하고, 서로 다른 범위를 잡는 두 트랜잭션이 교차하면서 데드락이 늘어납니다.** 반대로 데드락을 줄이려고 `READ COMMITTED`로 내리는 선택이 실제로 존재하는 이유도 같습니다.

### 4-2. MySQL `SERIALIZABLE`은 모든 조회를 락으로 바꿉니다

매뉴얼은 이 수준이 `REPEATABLE READ`와 같지만 **`autocommit`이 꺼져 있으면 모든 평범한 `SELECT`를 `SELECT ... FOR SHARE`로 암묵 변환**한다고 설명합니다.

Spring은 트랜잭션을 시작할 때 커넥션의 `autocommit`을 끕니다. 즉 `@Transactional` 안에서는 **예외 없이 모든 조회가 공유 락을 잡습니다.** 읽기 전용 조회 한 줄이 다른 트랜잭션의 쓰기를 막습니다. 서비스 메서드 하나에 `SERIALIZABLE`을 붙이는 것이 그 메서드가 읽는 모든 행을 쓰기 금지로 만드는 일이라는 뜻입니다.

### 4-3. PostgreSQL은 막는 대신 실패시킵니다

PostgreSQL은 접근 방식이 다릅니다. 올리면 대기가 늘어나는 게 아니라 **트랜잭션이 롤백됩니다.**

- `REPEATABLE READ`: 트랜잭션 시작 후 다른 트랜잭션이 변경·삭제한 행을 수정하려 하면 `ERROR: could not serialize access due to concurrent update`로 롤백됩니다. 매뉴얼은 애플리케이션이 이 메시지를 받으면 **현재 트랜잭션을 중단하고 처음부터 전체를 재시도해야 한다**고 못 박습니다.
- `SERIALIZABLE`: Serializable Snapshot Isolation(SSI)으로 구현됩니다. 추가 블로킹은 없지만 모니터링 비용이 있고, 직렬화 이상이 감지되면 직렬화 실패가 납니다. 매뉴얼은 이 수준을 쓰는 환경이 **SQLSTATE `40001`을 처리하는 일반화된 방법을 갖추고 있어야** 한다고 요구합니다.
- `READ UNCOMMITTED`는 내부적으로 `READ COMMITTED`처럼 동작합니다. 쓸 이유가 없습니다.

전부 위 PostgreSQL Transaction Isolation 문서의 내용입니다. 핵심은 **재시도가 선택이 아니라 전제조건**이라는 것입니다. PostgreSQL 매뉴얼은 재시도가 "어떤 SQL을 날릴지, 어떤 값을 쓸지 결정하는 로직까지 포함한 전체 트랜잭션"이어야 하고, 한 번의 재시도로 성공한다는 보장도 없다고 설명합니다.

반대로 `READ COMMITTED`에서는 재시도가 필요 없습니다. 같은 행을 노린 두 번째 `UPDATE`는 첫 번째의 커밋을 기다렸다가 **갱신된 버전에 대해 `WHERE` 조건을 다시 평가**하고 진행합니다. 다만 매뉴얼은 이게 한 행 단위 재평가라서 복잡한 검색 조건이 걸린 명령에는 적합하지 않다고 경고합니다.

> **정리:** 같은 `isolation = REPEATABLE_READ` 한 줄이 MySQL에서는 "락 범위 확대", PostgreSQL에서는 "재시도 루프 필수"를 의미합니다. DB를 모른 채 이 값을 바꾸는 건 불가능합니다.

## 5. 예제 — 재고가 음수로 떨어지는 버그

요구사항: 재고를 차감하는데, 동시 요청에서 재고가 음수가 되지 않아야 합니다.

### 5-1. 격리 수준으로 막으려 한 코드 ❌

```java
@Service
@RequiredArgsConstructor
public class StockService {

    private final ProductRepository productRepository;

    // ❌ 전체 메서드의 격리 수준을 올려 해결하려는 시도
    @Transactional(isolation = Isolation.SERIALIZABLE)
    public void deduct(Long productId, int quantity) {
        Product product = productRepository.findById(productId).orElseThrow();
        if (product.getStock() < quantity) {
            throw new OutOfStockException(productId);
        }
        product.decreaseStock(quantity);   // 더티 체킹으로 UPDATE
    }
}
```

문제는 셋입니다.

1. 이 메서드가 다른 `@Transactional`에서 호출되면 설정이 무시됩니다(3절)
2. MySQL이면 이 메서드가 읽는 **모든 행**이 공유 락 대상이 됩니다(4-2). 상품 조회만 하는 다른 트랜잭션까지 영향을 받습니다
3. PostgreSQL이면 동시 차감의 일부가 `40001`로 실패합니다. 재시도 코드가 없으므로 그대로 500 응답입니다

읽기-판단-쓰기 사이의 틈 하나를 막으려고 **메서드 전체의 동시성을 포기**한 셈입니다.

### 5-2. 범위를 좁혀서 푼 코드 ✔️

틈이 생기는 행은 하나입니다. 그 행만 다룹니다.

```java
public interface ProductRepository extends JpaRepository<Product, Long> {

    @Modifying
    @Query("""
            update Product p
               set p.stock = p.stock - :quantity
             where p.id = :productId
               and p.stock >= :quantity
            """)
    int deductStock(@Param("productId") Long productId, @Param("quantity") int quantity);
}
```

```java
@Transactional                              // 격리 수준은 DB 기본값 그대로
public void deduct(Long productId, int quantity) {
    int updated = productRepository.deductStock(productId, quantity);
    if (updated == 0) {
        throw new OutOfStockException(productId);
    }
}
```

조건을 `WHERE`에 넣어 **판단과 쓰기를 한 문장으로 합쳤습니다.** 격리 수준을 건드리지 않아도 음수가 되지 않습니다. 영향받은 행 수가 조건 검사 결과를 그대로 알려줍니다.

이게 가능한 이유도 매뉴얼에 있습니다. InnoDB의 일관된 읽기 스냅샷은 `SELECT`에 적용되는 것이고 DML에는 그렇지 않습니다 — `UPDATE`는 스냅샷 이후에 커밋된 행에도 영향을 줍니다([Consistent Nonlocking Reads](https://dev.mysql.com/doc/refman/8.4/en/innodb-consistent-read.html)). `REPEATABLE READ`에서 `SELECT`로 읽은 값이 낡아 있어도 `UPDATE ... WHERE stock >= :quantity`는 최신 상태로 판단합니다.

### 5-3. 한 문장으로 안 될 때의 선택지

계산이 복잡해 한 문장으로 합칠 수 없으면, 격리 수준이 아니라 **대상을 특정한 수단**을 씁니다.

| 수단 | 성립 조건 | 비용 |
|---|---|---|
| 원자적 `UPDATE ... WHERE` (5-2) | 조건을 SQL로 표현할 수 있을 때 | 거의 없음. 1순위 |
| `@Version` (낙관적 락) | 충돌이 드물고, 재시도가 가능할 때 | 충돌 시 `OptimisticLockingFailureException` → 재시도 필요 |
| `@Lock(PESSIMISTIC_WRITE)` | 충돌이 잦고, 잠글 행이 소수로 특정될 때 | 그 행에 대한 대기. 락 순서를 맞추지 않으면 데드락 |
| 격리 수준 올리기 | 위 셋으로 표현이 안 되는 **범위 조건**이 핵심일 때 | 4절 전체 |

맨 아래 칸은 실제로 존재합니다. "조회한 집합에 새 행이 끼어들면 안 된다" 같은 조건은 행 단위 락으로 표현되지 않습니다. 다만 그 판단에 도달하기 전에 위 세 칸을 먼저 소진했는지 확인합니다.

### 5-4. 재시도는 트랜잭션 바깥에 둡니다

낙관적 락(`@Version`)과 PostgreSQL의 직렬화 실패는 해법의 모양이 같습니다. **둘 다 실패를 전제로 하고 재시도로 해결합니다.** 그리고 둘 다 같은 자리에서 틀립니다 — 재시도 루프를 트랜잭션 안에 두는 것입니다.

```java
// ❌ 롤백된 트랜잭션 안에서 재시도 — 어떤 쿼리도 실행되지 않습니다
@Transactional
public void deductWithRetry(Long productId, int quantity) {
    for (int attempt = 0; attempt < 3; attempt++) {
        try {
            doDeduct(productId, quantity);
            return;
        } catch (OptimisticLockingFailureException e) {
            // 이미 rollback-only 상태입니다
        }
    }
}
```

트랜잭션 경계를 재시도의 **안쪽**에 둬야 합니다. 시도마다 트랜잭션과 영속성 컨텍스트가 새로 만들어집니다.

```java
@Slf4j
@Service
@RequiredArgsConstructor
public class StockFacade {

    private static final int MAX_ATTEMPTS = 3;

    private final StockService stockService;   // 별도 빈 — 프록시를 거쳐야 합니다

    public void deduct(Long productId, int quantity) {
        for (int attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
            try {
                stockService.deduct(productId, quantity);   // @Transactional
                return;
            } catch (OptimisticLockingFailureException e) {
                if (attempt == MAX_ATTEMPTS) {
                    throw e;
                }
                log.warn("재고 차감 재시도: productId={}, attempt={}", productId, attempt);
            }
        }
    }
}
```

같은 클래스 안에서 `this.deduct()`로 부르면 프록시를 거치지 않아 트랜잭션이 아예 새로 열리지 않습니다(`daily/day44-proxy-aop.md`). 재시도 패턴에서는 이 실수가 특히 조용합니다 — 세 번 다 같은 트랜잭션에서 돌고 세 번 다 실패합니다.

PostgreSQL의 `40001`도 같은 틀에 들어갑니다. Spring의 예외 변환은 직렬화 실패를 `CannotAcquireLockException`이나 `ConcurrencyFailureException` 계열로 매핑하므로, `catch` 대상만 바꾸면 구조는 그대로입니다. 단, PostgreSQL 매뉴얼이 요구하는 대로 **어떤 값을 쓸지 결정하는 로직까지** 재시도 범위에 들어가야 합니다. 트랜잭션 메서드 안에서 전부 다시 계산하는 구조여야 한다는 뜻입니다.

<!-- TODO: 확인 필요 — PostgreSQL JDBC의 40001이 Spring의 어느 DataAccessException 하위 타입으로 변환되는지는 SQLErrorCodes/SQLState 매핑 설정에 따라 달라집니다. 실제 사용 중인 조합에서 한 번 잡아보고 확정하세요. -->


## 6. 그래서 언제 무엇을 고르는가

- **기본은 `DEFAULT`를 유지합니다.** 바꿀 이유를 문서화할 수 없으면 바꾸지 않습니다
- MySQL에서 데드락과 갭 락 대기가 문제면, 올리는 게 아니라 **`READ COMMITTED`로 내리는 것**이 후보입니다. 대신 팬텀을 받아들여야 하고, 복제 포맷·기존 쿼리 전제를 함께 확인해야 합니다
- PostgreSQL에서 `REPEATABLE READ` 이상을 쓰려면 **`40001` 재시도 핸들러를 먼저 만들고** 나서 올립니다. 순서를 바꾸면 장애입니다
- 올리기로 했다면 **트랜잭션을 시작하는 메서드에만** 적고, 그 메서드가 읽고 쓰는 범위를 최소로 줄입니다. 외부 API 호출은 그 안에 두지 않습니다

## 7. 함정

**① `isolation`을 붙였는데 아무 변화가 없음**

- **증상**: `SERIALIZABLE`을 붙였는데 동시성 버그가 그대로 재현됩니다. 로그에 락 대기도, 직렬화 실패도 없습니다.
- **원인**: 상위 `@Transactional` 메서드에서 호출돼 외부 트랜잭션에 참여했습니다. 참여 시 지역 격리 수준은 조용히 무시됩니다(3절). 또는 JTA 환경이거나 `prepareConnection`이 꺼져 있습니다(2-1).
- **해법**: 트랜잭션 경계를 시작하는 최외곽 메서드로 설정을 옮깁니다. 참여 시 예외가 나게 하려면 `validateExistingTransaction=true`를 테스트 프로파일에 켭니다. 적용 여부 확인은 DB에서 직접 합니다 — MySQL이면 `SELECT @@transaction_isolation`, PostgreSQL이면 `SHOW transaction_isolation`을 트랜잭션 안에서 실행해봅니다.

**② 다음 요청이 남의 격리 수준으로 돎**

- **증상**: 아무 설정도 하지 않은 서비스가 간헐적으로 다른 격리 수준으로 동작합니다. 재현되지 않고 요청마다 다릅니다.
- **원인**: 커넥션 풀의 커넥션에 격리 수준이 남았습니다. HikariCP는 변경을 **감지했을 때만** 복원하므로, JDBC API가 아니라 SQL로 바꾼 변경은 감지하지 못합니다(HikariCP FAQ).
- **해법**: 격리 수준은 `SET TRANSACTION ISOLATION LEVEL` SQL이 아니라 `@Transactional(isolation = ...)`이나 `Connection.setTransactionIsolation()`으로 바꿉니다. 풀 전체의 기준을 정하고 싶으면 `spring.datasource.hikari.transaction-isolation`으로 명시합니다. 미지정이면 JDBC 드라이버 기본값이 쓰입니다.

**③ MySQL에서 격리 수준을 올린 뒤 데드락이 급증**

- **증상**: 기능은 정상인데 `Deadlock found when trying to get lock`과 `Lock wait timeout exceeded`가 늘어납니다. 충돌하는 두 트랜잭션이 **서로 다른 행**을 건드리고 있어 원인이 안 보입니다.
- **원인**: `REPEATABLE READ`의 갭 락·넥스트키 락입니다. 범위 조건으로 `UPDATE`/`DELETE`/locking read를 하면 스캔한 인덱스 범위 전체가 잠기므로, 겹치지 않는 행을 노린 트랜잭션끼리도 범위가 겹칩니다(4-1).
- **해법**: 먼저 `SHOW ENGINE INNODB STATUS`의 `LATEST DETECTED DEADLOCK`에서 잠긴 인덱스와 범위를 확인합니다. 범위 스캔을 유니크 인덱스 단일 행 조회로 바꾸면 갭 락이 사라집니다 — 인덱스 설계 문제인 경우가 많습니다. 그게 안 되면 `READ COMMITTED`로 내리는 것을 검토합니다.

**④ PostgreSQL에서 올린 뒤 요청 일부가 500**

- **증상**: 부하가 오르면 일정 비율의 요청이 실패합니다. 에러는 `could not serialize access due to read/write dependencies among transactions` 또는 `... due to concurrent update`입니다.
- **원인**: 버그가 아니라 설계된 동작입니다. PostgreSQL은 `REPEATABLE READ` 이상에서 충돌을 대기로 해결하지 않고 트랜잭션을 롤백합니다(4-3).
- **해법**: SQLSTATE `40001`을 잡아 **트랜잭션 전체를 재시도**합니다. 재시도는 반드시 트랜잭션 경계 바깥에 둡니다(5-4). 재시도 횟수에 상한을 두고, 재시도율을 메트릭으로 내보냅니다. 재시도율이 계속 오르면 격리 수준이 아니라 트랜잭션 범위가 너무 넓다는 신호입니다.

## 8. 참고자료

- [Spring Framework Reference — Transaction Propagation](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/tx-propagation.html)
- [Spring Framework Reference — Using `@Transactional`](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/annotations.html)
- [Javadoc — `Isolation`](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/transaction/annotation/Isolation.html)
- [Javadoc — `DataSourceUtils`](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/jdbc/datasource/DataSourceUtils.html)
- [Javadoc — `HibernateJpaDialect`](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/orm/jpa/vendor/HibernateJpaDialect.html)
- [Javadoc — `JtaTransactionManager`](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/transaction/jta/JtaTransactionManager.html)
- [MySQL 8.4 — Transaction Isolation Levels](https://dev.mysql.com/doc/refman/8.4/en/innodb-transaction-isolation-levels.html)
- [MySQL 8.4 — Consistent Nonlocking Reads](https://dev.mysql.com/doc/refman/8.4/en/innodb-consistent-read.html)
- [PostgreSQL — Transaction Isolation](https://www.postgresql.org/docs/current/transaction-iso.html)
- [HikariCP — FAQ](https://github.com/brettwooldridge/HikariCP/wiki/FAQ)
- `daily/day50-transaction-propagation.md` — 전파가 격리 수준을 무시하는 구조
- `daily/day44-proxy-aop.md` — 프록시를 안 거치면 애노테이션이 무시되는 이유

# 락은 행에 걸리지 않습니다 — 공유락·배타락·갭락이 실제로 잠그는 것

주문 하나를 취소하는 쿼리를 던집니다.

```sql
UPDATE orders SET status = 'CANCELED' WHERE receiver_name = '김민수';
```

한 행만 바뀌었고, 응답도 빨랐습니다. 그런데 몇 초 동안 그 테이블에 들어오던 신규 주문 `INSERT`가 전부 `ERROR 1205 (Lock wait timeout exceeded)`로 떨어집니다. 취소한 주문과 아무 관계도 없는 주문들입니다.

`receiver_name`에 인덱스가 없었기 때문입니다. 이 문서는 질문 하나에 답합니다. **InnoDB의 락은 정확히 무엇 위에 걸리는가.**

기준 버전은 MySQL 8.4(InnoDB)입니다. 비교 대상으로 PostgreSQL 18을 한 번 언급합니다.

---

## 1. 핵심 개념 — 잠기는 대상은 행이 아니라 인덱스 레코드입니다

InnoDB의 행 락은 테이블의 행이 아니라 **인덱스 레코드**에 걸립니다. 그래서 어떤 인덱스를 어디까지 훑었는지가 잠긴 범위를 결정합니다.

> InnoDB는 `WHERE` 조건을 기억하지 않습니다. **어떤 인덱스 구간을 스캔했는지만** 압니다. 그래서 조건에서 제외될 행이라도 스캔 경로에 있었다면 잠깁니다. 맞는 인덱스가 없어 전체 스캔으로 떨어지면 테이블의 모든 행이 잠기고, 결과적으로 다른 세션의 `INSERT`가 전부 막힙니다. ([InnoDB 문장별 락](https://dev.mysql.com/doc/refman/8.4/en/innodb-locks-set.html))

이 문장 하나가 이 챕터의 전부입니다. 나머지는 "그 구간이 어떻게 계산되는가"입니다.

인덱스가 하나도 없는 테이블이라면 락이 없는 게 아니라, 숨겨진 클러스터 인덱스를 통해 걸립니다. 피할 방법은 없습니다.

---

## 2. 모드는 두 개, 범위는 세 개

락을 이야기할 때 섞이기 쉬운 두 축을 분리해야 합니다.

| 축 | 값 | 질문 |
|---|---|---|
| 모드 | S, X | 무엇을 허용하는가 |
| 범위 | 레코드, 갭, 넥스트키 | 어디를 잠그는가 |

### 2-1. 모드 — 공유락(S)과 배타락(X)

- **공유락(S, Shared)** — 보유자가 그 행을 읽을 수 있습니다.
- **배타락(X, Exclusive)** — 보유자가 그 행을 수정·삭제할 수 있습니다.

T1이 S를 들고 있으면 T2는 S를 즉시 얻지만 X는 기다립니다. T1이 X를 들고 있으면 T2는 S든 X든 기다립니다.

| 보유 ＼ 요청 | S | X |
|---|---|---|
| **S** | 호환 | 대기 |
| **X** | 대기 | 대기 |

중요한 건 이 표에 **일반 `SELECT`가 없다는 점**입니다. MVCC 스냅샷 읽기는 락을 보지 않고 지나갑니다(`SERIALIZABLE` 제외). S락은 `SELECT ... FOR SHARE`를 써야 걸립니다. 자세한 건 `daily/day77-mvcc.md`를 봅니다.

### 2-2. 의도락(IS, IX) — 테이블 레벨에 미리 꽂아두는 깃발

행 락만 있으면 문제가 생깁니다. 누군가 `LOCK TABLES ... WRITE`로 테이블 전체를 잠그려 할 때, 그 안에 잠긴 행이 하나라도 있는지 알려면 행을 전부 뒤져야 합니다.

그래서 InnoDB는 행에 락을 걸기 전에 테이블에 **의도락**을 먼저 걸어둡니다.

- `SELECT ... FOR SHARE` → 테이블에 IS
- `SELECT ... FOR UPDATE`, `UPDATE`, `DELETE` → 테이블에 IX

| 보유 ＼ 요청 | X | IX | S | IS |
|---|---|---|---|---|
| **X** | 대기 | 대기 | 대기 | 대기 |
| **IX** | 대기 | 호환 | 대기 | 호환 |
| **S** | 대기 | 대기 | 호환 | 호환 |
| **IS** | 대기 | 호환 | 호환 | 호환 |

IX끼리는 호환입니다. 즉 **의도락은 테이블 전체 요청만 막고, 평소에는 아무것도 막지 않습니다.** 실무에서 의도락이 범인인 경우는 거의 없습니다. `data_locks`에서 `LOCK_TYPE = TABLE`, `LOCK_MODE = IX` 행이 보여도 그건 범인이 아니라 영수증입니다. ([InnoDB 락 종류](https://dev.mysql.com/doc/refman/8.4/en/innodb-locking.html))

### 2-3. 범위 — 레코드락, 갭락, 넥스트키락

인덱스에 주문 ID `10, 11, 13, 20`이 있다고 하면, InnoDB가 잠글 수 있는 구간은 이렇게 나뉩니다.

```
(-∞, 10]   (10, 11]   (11, 13]   (13, 20]   (20, +∞)
```

- **레코드락** — 인덱스 레코드 하나만. `13` 자체.
- **갭락** — 레코드 사이의 빈 공간. `(11, 13)`. 여기에 `12`를 못 넣게 합니다.
- **넥스트키락** — 레코드락 + **그 앞 갭**의 갭락. `(11, 13]`.

마지막 구간 `(20, +∞)`는 supremum이라는 가상 레코드로 표현됩니다. 실제로는 최댓값 뒤의 갭만 잠그는 것입니다.

**`REPEATABLE READ`에서 범위 검색의 기본은 넥스트키락입니다.** 레코드락이 아닙니다. 이걸 모르면 "한 행만 잠갔는데 왜 다른 행 삽입이 막히는가"라는 질문에 답할 수 없습니다.

공식 문서는 두 모드를 더해 쓴 표기를 씁니다. 개념적으로 `X = X,GAP + X,REC_NOT_GAP`입니다. 넥스트키락은 갭과 레코드를 동시에 잠근 상태라는 뜻입니다. ([InnoDB Data Locking Part 2.5](https://dev.mysql.com/blog-archive/innodb-data-locking-part-2-5-locks-deeper-dive/))

---

## 3. 갭락은 왜 존재하는가

갭락은 S/X와 같은 층위의 개념이 아닙니다. **목적이 하나뿐인 특수 장치**입니다.

`REPEATABLE READ`에서 같은 범위를 두 번 읽었는데 없던 행이 생기는 것이 팬텀입니다. 이미 있는 행을 잠가도 팬텀은 막히지 않습니다. 막아야 할 대상이 "아직 존재하지 않는 행"이기 때문입니다. 잠글 행이 없으니 **행 사이의 공간을 잠그는** 수밖에 없습니다.

목적이 "삽입 금지" 하나라서 갭락은 성질이 특이합니다.

- **갭락끼리는 충돌하지 않습니다.** 같은 갭에 두 트랜잭션이 갭락을 동시에 들 수 있습니다. S 갭락과 X 갭락도 구분이 없습니다. 공식 문서는 갭락을 "purely inhibitive"라고 표현합니다.
- 공식 블로그는 더 단정적으로 씁니다 — **`*,GAP` 요청은 무엇도 기다리지 않습니다.**

그럼 갭락은 무엇을 막는 걸까요. 삽입입니다.

### 3-1. 삽입 의도락(Insert Intention Lock)

`INSERT`는 행을 쓰기 전에 들어갈 갭에 **삽입 의도락**을 먼저 요청합니다.

1. `INSERT`가 들어갈 위치를 찾습니다.
2. 그 다음 레코드에 `*,GAP` / `S` / `X` 락이 있는지 확인합니다.
3. 있으면 `WAITING` 상태의 `INSERT_INTENTION` 락을 만들고 대기합니다.
4. 허가되면 삽입을 재시도합니다.

삽입 의도락끼리는 위치가 다르면 충돌하지 않습니다. `4`와 `7` 사이에 `5`와 `6`을 넣는 두 트랜잭션은 서로 안 기다립니다. 그래서 정상적인 동시 삽입은 빠릅니다.

막히는 건 **갭락 ↔ 삽입 의도락** 조합 하나입니다. 갭락은 자기들끼리는 호환이고 삽입만 세웁니다. 서문의 1205가 여기서 나옵니다.

### 3-2. 갭락이 사라지는 조건

`READ COMMITTED`로 내리면 갭 락킹이 명시적으로 비활성화됩니다. 검색과 인덱스 스캔에서는 쓰이지 않고, **외래키 제약 검사와 중복키 검사에만** 남습니다.

즉 갭락은 격리 수준에 딸린 기능입니다. 영구적인 성질이 아닙니다.

---

## 4. 유니크 인덱스라는 예외

여기가 실무에서 가장 크게 갈리는 지점입니다.

**유니크 인덱스로 유니크한 한 행을 찾는 경우, 갭락이 필요 없습니다.** 찾은 인덱스 레코드만 잠깁니다. 앞 갭에 다른 세션이 뭘 넣든 상관없습니다.

```sql
-- id가 PK(유니크). 레코드락만 걸립니다.
SELECT * FROM orders WHERE id = 1042 FOR UPDATE;
```

예외의 예외가 둘 있습니다.

1. **다중 컬럼 유니크 인덱스의 일부 컬럼만** 쓰면 갭락이 걸립니다.
2. 컬럼에 인덱스가 없거나 **논유니크 인덱스**면 앞 갭까지 잠깁니다.

`(coupon_id, user_id)` 유니크 인덱스에서 `WHERE coupon_id = 100`만 쓰면 유니크 검색이 아니므로 갭락이 붙습니다. 그리고 이 차이가 쿠폰 발급 전체를 직렬화시킵니다.

<!-- TODO: 확인 필요 — 유니크 인덱스에 '존재하지 않는 값'을 FOR UPDATE로 조회하면 갭락이 걸린다는 동작은
     공식 문서와 공식 블로그에서 명시된 문장을 찾지 못했습니다. 문서가 보장하는 것은 '유니크 인덱스로
     유니크한 행을 찾은 경우' 레코드락만 걸린다는 것까지입니다. 운영 버전에서 직접 측정 후 보강 필요. -->

---

## 5. 지금 무엇이 잠겼는지 보는 법

추측하지 말고 봅니다. MySQL 8.0부터 `performance_schema.data_locks`가 걸린 락을 그대로 보여줍니다.

```sql
SELECT ENGINE_TRANSACTION_ID AS trx,
       OBJECT_NAME           AS tbl,
       INDEX_NAME            AS idx,
       LOCK_TYPE, LOCK_MODE, LOCK_STATUS, LOCK_DATA
FROM performance_schema.data_locks
WHERE OBJECT_SCHEMA = 'shop';
```

`LOCK_MODE`를 읽는 법이 핵심입니다.

| LOCK_MODE | 의미 |
|---|---|
| `X` / `S` | **넥스트키락** — 레코드 + 앞 갭 |
| `X,REC_NOT_GAP` | 레코드만 |
| `X,GAP` | 앞 갭만 |
| `X,GAP,INSERT_INTENTION` | 삽입 대기 중 |
| `IX` / `IS` (+`LOCK_TYPE=TABLE`) | 테이블 의도락 |

수식어가 없는 `X`가 "레코드 하나"라고 읽히기 쉽지만 **넥스트키락**입니다. 이 오독이 "분명히 한 행만 잠갔는데"의 출발점입니다.

`LOCK_DATA`에는 잠긴 레코드의 인덱스 값이 들어갑니다. 보조 인덱스 락이면 보조 인덱스 값에 PK가 덧붙습니다. 최댓값 뒤 갭은 `supremum pseudo-record`로 표시됩니다. 값이 `NULL`이면 락이 없는 게 아니라 해당 페이지가 버퍼 풀에 없어서 못 읽은 것입니다.

누가 누구를 막는지는 조인해서 봅니다.

```sql
SELECT waiting_trx_id, waiting_pid, waiting_query,
       blocking_trx_id, blocking_pid, blocking_query
FROM sys.innodb_lock_waits;
```

`blocking_query`가 `NULL`로 나오는 경우가 많습니다. 범인 세션이 쿼리를 끝내고 트랜잭션만 열어둔 채 유휴 상태이기 때문입니다. 그때는 스레드를 거쳐 마지막 문장을 찾습니다.

```sql
SELECT w.blocking_engine_transaction_id AS blocking_trx_id,
       t.THREAD_ID,
       esc.SQL_TEXT                      AS last_statement
FROM performance_schema.data_lock_waits w
JOIN information_schema.innodb_trx b
  ON b.trx_id = w.blocking_engine_transaction_id
JOIN performance_schema.threads t
  ON t.PROCESSLIST_ID = b.trx_mysql_thread_id
LEFT JOIN performance_schema.events_statements_current esc
  ON esc.THREAD_ID = t.THREAD_ID;
```

`events_statements_history`는 스레드별 최근 10개 문장을 들고 있어서, 이미 끝난 쿼리가 범인일 때 여기서 찾습니다.

---

## 6. 예제 — 쿠폰 발급이 한 줄로 줄어드는 코드

쿠폰 중복 발급을 막는 코드입니다. 조회해서 없으면 넣는 흔한 패턴입니다.

### 6-1. 클린하지 않은 코드 ❌

```sql
CREATE TABLE coupon_issue (
    id         BIGINT      NOT NULL AUTO_INCREMENT,
    coupon_id  BIGINT      NOT NULL,
    user_id    BIGINT      NOT NULL,
    issued_at  DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    KEY idx_coupon (coupon_id)          -- 논유니크 인덱스
) ENGINE = InnoDB;
```

```java
@Transactional
public void issue(long couponId, long userId) {
    // coupon_id로만 좁히고 user_id는 애플리케이션에서 걸러냅니다
    List<CouponIssue> issued = couponIssueRepository.findForUpdateByCouponId(couponId);

    boolean already = issued.stream().anyMatch(i -> i.getUserId() == userId);
    if (already) {
        throw new DuplicateIssueException(couponId, userId);
    }
    couponIssueRepository.save(new CouponIssue(couponId, userId, LocalDateTime.now()));
}
```

```java
@Lock(LockModeType.PESSIMISTIC_WRITE)
@Query("select ci from CouponIssue ci where ci.couponId = :couponId")
List<CouponIssue> findForUpdateByCouponId(@Param("couponId") long couponId);
```

무엇이 잠겼는지 봅니다.

```
idx_coupon RECORD X                   coupon_id=100, id=51
idx_coupon RECORD X                   coupon_id=100, id=52
idx_coupon RECORD X                   coupon_id=100, id=53
idx_coupon RECORD X                   supremum pseudo-record
PRIMARY    RECORD X,REC_NOT_GAP       51
...
```

`idx_coupon`은 논유니크 인덱스이므로 스캔한 구간 전체에 넥스트키락이 걸립니다. 그래서 **`coupon_id = 100`인 모든 발급 이력 + 그 사이 갭**이 잠깁니다. 다른 사용자의 발급도 같은 갭에 들어가야 하니 전부 대기합니다. 한 쿠폰의 발급이 완전히 직렬화됩니다.

발급 이력이 늘어나면 잠기는 레코드 수도 같이 늘어납니다. 테스트에서는 몇 건뿐이라 안 보입니다.

### 6-2. 개선한 코드 ✔️

락 범위는 인덱스가 결정합니다. 그러니 인덱스를 고칩니다.

```sql
ALTER TABLE coupon_issue
    ADD UNIQUE KEY uk_coupon_user (coupon_id, user_id),
    DROP KEY idx_coupon;
```

```java
@Transactional
public void issue(long couponId, long userId) {
    try {
        couponIssueRepository.save(new CouponIssue(couponId, userId, LocalDateTime.now()));
        couponIssueRepository.flush();   // 제약 위반을 이 지점에서 받습니다
    } catch (DataIntegrityViolationException e) {
        throw new DuplicateIssueException(couponId, userId);
    }
}
```

바뀐 것은 두 가지입니다.

1. **중복 판정을 유니크 제약에 넘겼습니다.** "조회 후 삽입"은 조회와 삽입 사이에 틈이 있어 애초에 락 없이는 안전하지 않습니다. 유니크 인덱스는 그 틈이 없습니다.
2. **잠기는 범위가 레코드 하나로 줄었습니다.** 유니크 인덱스에 중복이 생기면 그 레코드에만 락이 걸립니다. 서로 다른 `user_id`의 삽입은 위치가 달라 삽입 의도락끼리 충돌하지 않습니다.

읽고 판단할 값이 꼭 필요하다면 범위가 아니라 **한 행을 유니크 조건으로** 잠급니다.

```java
// 유니크 인덱스 + 유니크 검색 조건 → 레코드락만
@Lock(LockModeType.PESSIMISTIC_WRITE)
@Query("select ci from CouponIssue ci where ci.couponId = :couponId and ci.userId = :userId")
Optional<CouponIssue> findForUpdate(@Param("couponId") long couponId,
                                    @Param("userId") long userId);
```

Hibernate 6은 `PESSIMISTIC_WRITE`를 `for update`로, `PESSIMISTIC_READ`를 지원 방언에서 `for share`로 내보냅니다. `for share`를 지원하지 않는 DB에서는 `PESSIMISTIC_READ`도 `for update`가 됩니다. ([LockMode javadoc](https://docs.hibernate.org/orm/6.6/javadocs/org/hibernate/LockMode.html))

---

## 7. 대기를 설계하기

락은 결국 "기다림"입니다. 얼마나 기다릴지는 선택할 수 있습니다.

```sql
SELECT * FROM orders WHERE id = 1042 FOR UPDATE NOWAIT;
-- ERROR 3572 (HY000): Do not wait for lock.

SELECT * FROM orders WHERE status = 'PENDING' FOR UPDATE SKIP LOCKED LIMIT 10;
-- 잠긴 행을 결과에서 빼고 즉시 반환합니다
```

- **`NOWAIT`** — 잠겨 있으면 기다리지 않고 바로 실패합니다. 사용자 요청처럼 빨리 실패하는 게 나은 경로에 씁니다.
- **`SKIP LOCKED`** — 잠긴 행을 결과에서 제외합니다. 공식 문서가 직접 경고합니다 — **일관성 없는 결과를 돌려주므로 일반적인 트랜잭션 작업에 적합하지 않습니다.** 큐 테이블에서 워커가 서로 다른 작업을 집어가게 할 때만 씁니다.
- 아무것도 안 쓰면 `innodb_lock_wait_timeout`을 따릅니다. **기본값 50초**, 범위 1~1073741824초, 글로벌·세션 모두 설정 가능합니다. ([InnoDB 시스템 변수](https://dev.mysql.com/doc/refman/8.4/en/innodb-parameters.html))

50초는 API 타임아웃보다 거의 항상 깁니다. 클라이언트는 이미 끊었는데 서버 스레드와 커넥션은 50초를 더 붙잡고 있습니다. 세션 단위로 줄여두는 편이 안전합니다.

```sql
SET SESSION innodb_lock_wait_timeout = 3;
```

`NOWAIT`와 `SKIP LOCKED`는 행 락에만 적용되고, 문장 기반 복제에서는 안전하지 않습니다.

---

## 8. PostgreSQL과 비교 — 갭락이 없는 쪽

같은 문제를 다르게 푼 쪽을 보면 갭락이 무엇의 대가인지 분명해집니다.

PostgreSQL에는 갭락·넥스트키락이 없습니다. 대신 행 락 모드를 네 개로 쪼갰습니다.

| 모드 | 성격 |
|---|---|
| `FOR UPDATE` | 가장 강함. 다른 모든 행 락과 충돌 |
| `FOR NO KEY UPDATE` | 일반 `UPDATE`가 잡음. `FOR KEY SHARE`를 막지 않음 |
| `FOR SHARE` | 공유. `FOR SHARE`·`FOR KEY SHARE`끼리 호환 |
| `FOR KEY SHARE` | 가장 약함. 키 변경과 삭제만 막음 |

`FOR KEY SHARE`가 따로 있는 이유가 핵심입니다. 외래키 검사는 "참조 대상이 사라지지 않음"만 보장받으면 됩니다. 그래서 자식 행 삽입이 부모 행의 일반 `UPDATE`를 막지 않습니다. InnoDB는 이 경우 공유 레코드 락을 잡습니다.

팬텀은 다르게 막습니다. 갭을 잠그는 대신 `SERIALIZABLE`에서 읽은 범위를 추적하고, 충돌이 실제로 성립하면 트랜잭션 하나를 직렬화 실패로 중단시킵니다. **대기 대신 재시도**를 택한 것입니다.

그래서 축이 이렇게 갈립니다.

- InnoDB — 갭을 잠가 **미리 막습니다.** 팬텀이 안 생기는 대신, 범위 쿼리가 의도보다 넓게 잠깁니다.
- PostgreSQL — 잠그지 않고 **나중에 거부합니다.** 넓게 안 잠기는 대신, 애플리케이션에 재시도 로직이 있어야 합니다.

PostgreSQL은 행 락을 메모리 목록으로 들고 있지 않고 행에 표시하므로, `SELECT FOR UPDATE`가 디스크 쓰기를 유발할 수 있습니다. 대신 동시에 잠글 행 개수에 제한이 없습니다. ([PostgreSQL 18 Explicit Locking](https://www.postgresql.org/docs/18/explicit-locking.html))

---

## 9. 함정

### 9-1. 인덱스 없는 `WHERE`로 테이블 전체가 잠깁니다

- **증상**: `UPDATE` 한 건이 끝났는데 그동안 그 테이블의 모든 `INSERT`가 1205로 실패합니다. 대시보드에서는 CPU도 디스크도 한가합니다.
- **원인**: 맞는 인덱스가 없어 전체 스캔으로 떨어졌습니다. InnoDB는 `WHERE` 조건을 기억하지 않고 스캔한 인덱스 구간만 알기 때문에, 조건에서 걸러질 행까지 모두 넥스트키락이 걸립니다.
- **해법**: 배치성 `UPDATE`/`DELETE`는 `EXPLAIN`으로 `type`과 `rows`를 먼저 확인합니다. 인덱스를 만들 수 없다면 PK 범위로 쪼개 여러 트랜잭션으로 나눕니다.

### 9-2. `LOCK_MODE`의 `X`를 레코드락으로 읽습니다

- **증상**: `data_locks`에 `X` 두 줄만 보이는데 "두 행만 잠겼다"고 결론 내리고, 왜 삽입이 막히는지 설명하지 못합니다.
- **원인**: 수식어 없는 `X`는 넥스트키락입니다. 레코드만 잠긴 상태는 `X,REC_NOT_GAP`입니다.
- **해법**: `LOCK_MODE`를 끝까지 읽습니다. `GAP`이 붙었는지, `REC_NOT_GAP`이 붙었는지, 아무것도 안 붙었는지 세 가지를 구분합니다.

### 9-3. 삭제된 행의 갭락이 살아남습니다

- **증상**: 분명히 지운 행인데 그 자리에 삽입하려는 트랜잭션이 대기합니다.
- **원인**: 레코드가 purge되면서 갭이 합쳐지고, 기존 락이 갭락으로 상속됩니다. 공식 블로그는 삽입 후 `S,GAP`이 이웃 레코드로 상속되는 예를 보여줍니다. 갭락은 레코드가 아니라 공간에 대한 권리이므로 레코드가 없어져도 남습니다.
- **해법**: 범위 삭제 후 같은 구간에 삽입하는 작업을 같은 트랜잭션 안에 두거나, 삭제 트랜잭션을 짧게 끊습니다.

### 9-4. `READ COMMITTED`로 내렸는데 아직 갭락이 보입니다

- **증상**: 격리 수준을 낮췄는데 `data_locks`에 `X,GAP`이 나옵니다.
- **원인**: `READ COMMITTED`에서 갭 락킹은 검색·인덱스 스캔에서만 비활성화됩니다. **외래키 제약 검사와 중복키 검사에는 그대로 남습니다.** 격리 수준으로 끌 수 없는 영역입니다.
- **해법**: 그 경로가 병목이라면 격리 수준이 아니라 외래키 구성이나 중복 판정 방식을 봅니다.

### 9-5. 1205를 받고 트랜잭션이 살아 있습니다

- **증상**: 락 대기 타임아웃 후 롤백됐다고 생각하고 다음 쿼리를 보내는데 데이터가 반쯤 반영됩니다.
- **원인**: 락 대기 타임아웃은 **대기하던 문장만** 롤백합니다. 트랜잭션은 열려 있고 이전 변경도 남아 있습니다.
- **해법**: 1205를 잡으면 명시적으로 롤백합니다. 서버 차원에서 바꾸려면 `--innodb-rollback-on-timeout`으로 시작해야 하고, 이 옵션은 런타임에 변경할 수 없습니다. ([InnoDB 에러 처리](https://dev.mysql.com/doc/refman/8.4/en/innodb-error-handling.html))

### 9-6. 외래키 검사가 의도 없는 공유락을 만듭니다

- **증상**: 서로 다른 테이블을 건드리는 트랜잭션들이 대기하거나 데드락을 만듭니다.
- **원인**: 제약 검사가 필요한 `INSERT`/`UPDATE`/`DELETE`는 검사한 레코드에 공유 레코드 락을 겁니다. **제약 검사가 실패한 경우에도 걸립니다.** 코드에는 그 테이블을 잠그라고 쓴 곳이 없습니다.
- **해법**: `data_locks`의 `OBJECT_NAME`을 보고 내가 안 건드린 테이블이 나오는지 확인합니다. 참조 대상이 되는 공통 테이블(코드값, 설정)은 외래키 연결 자체를 재검토합니다.

### 9-7. `SKIP LOCKED`를 일반 조회에 씁니다

- **증상**: 목록 조회에서 건수가 호출마다 달라지고, 재현이 안 됩니다.
- **원인**: `SKIP LOCKED`는 잠긴 행을 결과에서 뺍니다. 공식 문서가 일관성 없는 결과를 돌려준다고 명시합니다.
- **해법**: 큐 테이블에서 워커가 작업을 집어가는 경로에만 씁니다. 사용자에게 보여줄 목록에는 쓰지 않습니다.

---

## 10. 정리

판단 순서는 세 단계입니다.

1. **어떤 인덱스를 타는가** — `EXPLAIN`으로 확인합니다. 락 범위를 결정하는 건 `WHERE`가 아니라 실행계획입니다.
2. **그 인덱스가 유니크한가, 조건이 유니크한가** — 둘 다 예라면 레코드락 하나입니다. 하나라도 아니면 갭이 따라옵니다.
3. **얼마나 기다릴 것인가** — 기본 50초를 그대로 두지 않습니다.

`FOR UPDATE`를 지우는 게 해법인 경우는 드뭅니다. **범위를 좁히는 것**이 해법입니다. 그리고 범위를 좁히는 수단은 코드가 아니라 인덱스입니다.

---

## 11. 참고자료

- [MySQL 8.4 — InnoDB Locking](https://dev.mysql.com/doc/refman/8.4/en/innodb-locking.html)
- [MySQL 8.4 — Locks Set by Different SQL Statements in InnoDB](https://dev.mysql.com/doc/refman/8.4/en/innodb-locks-set.html)
- [MySQL 8.4 — Transaction Isolation Levels](https://dev.mysql.com/doc/refman/8.4/en/innodb-transaction-isolation-levels.html)
- [MySQL 8.4 — Locking Reads](https://dev.mysql.com/doc/refman/8.4/en/innodb-locking-reads.html)
- [MySQL 8.4 — The data_locks Table](https://dev.mysql.com/doc/refman/8.4/en/performance-schema-data-locks-table.html)
- [MySQL Blog — InnoDB Data Locking Part 2.5 "Locks" (Deeper dive)](https://dev.mysql.com/blog-archive/innodb-data-locking-part-2-5-locks-deeper-dive/)
- [PostgreSQL 18 — Explicit Locking](https://www.postgresql.org/docs/18/explicit-locking.html)
- 관련 문서: `daily/day71-isolation-anomaly.md`, `daily/day77-mvcc.md`

# 격리 수준을 올려도 남는 이상현상은 무엇인가

> 이 문서가 답할 질문: **지금 겪는 동시성 버그는 격리 수준으로 막히는 이상현상인가, 아닌가?**
>
> 분류: 문제해결형(증상 → 원인 → 해법). 실무에서 이 주제를 찾아보는 시점은 거의 항상 "데이터가 틀어졌는데 원인을 모르겠다"입니다. 그래서 이상현상의 정의를 나열하는 대신, **증상에서 이상현상 이름까지 가는 경로**를 중심으로 썼습니다.
>
> 기준: **MySQL 8.4** 매뉴얼, **PostgreSQL 현행** 매뉴얼, 그리고 이상현상 분류의 출처인 Berenson et al. 1995를 확인해 썼습니다. Spring에서 `isolation` 값을 바꿀 때 벌어지는 일은 `daily/day56-transaction-isolation.md`, ACID의 I가 약속하는 범위는 `daily/day65-acid.md`에 있습니다.

## 1. 핵심 개념 — 표준이 이름 붙인 이상현상은 세 개뿐입니다

SQL 표준은 격리 수준을 "무엇을 보장하는가"로 정의하지 않습니다. **어떤 이상현상이 발생해도 괜찮은가**로 정의합니다. 그리고 그 목록은 세 개입니다.

| 이상현상 | 무슨 일이 벌어지나 |
|---|---|
| Dirty Read | 커밋되지 않은 다른 트랜잭션의 변경을 읽습니다 |
| Non-repeatable Read | 같은 행을 두 번 읽었는데 값이 달라집니다 |
| Phantom Read | 같은 조건으로 두 번 조회했는데 행의 개수가 달라집니다 |

격리 수준은 이 셋을 위에서부터 하나씩 끄는 다이얼입니다. `READ UNCOMMITTED`는 셋 다 허용하고, `READ COMMITTED`는 첫 번째를 끄고, `REPEATABLE READ`는 두 번째까지 끄고, `SERIALIZABLE`은 셋 다 끕니다.

> 문제는 실무에서 만나는 동시성 버그가 **대부분 이 셋 중 어디에도 해당하지 않는다**는 점입니다. 재고가 음수로 내려가고, 선착순 쿠폰이 정원보다 많이 발급되고, 포인트 잔액이 맞지 않습니다. 그래서 `isolation = REPEATABLE READ`를 붙입니다. 그런데 안 고쳐집니다. **표준의 세 이상현상 목록으로는 그 버그에 이름조차 붙일 수 없기 때문입니다.** 이름을 붙이지 못하면 격리 수준을 올려야 할 문제인지, 락이나 버전으로 가야 할 문제인지 판단할 근거가 없습니다.

## 2. 표준이 빠뜨린 이상현상

표준의 세 개 목록이 부족하다는 지적은 1995년 Berenson, Bernstein, Gray, Melton, O'Neil, O'Neil의 논문 [A Critique of ANSI SQL Isolation Levels](https://www.microsoft.com/en-us/research/publication/a-critique-of-ansi-sql-isolation-levels/)에서 나왔습니다. 이 논문이 추가로 이름 붙인 것 중 실무에서 중요한 셋입니다.

읽기는 `r`, 쓰기는 `w`, 커밋은 `c`, 숫자는 트랜잭션 번호입니다.

**Lost Update (P4)** — `r1[x] w2[x] w1[x] c1`

T1이 x를 읽습니다. T2가 x를 바꾸고 커밋합니다. T1이 자기가 읽은 값을 기준으로 계산한 결과를 씁니다. **T2의 변경이 흔적도 없이 사라집니다.**

**Read Skew (A5A)** — `r1[x] w2[x] w2[y] c2 r1[y]`

T1이 x를 읽습니다. T2가 x와 y를 함께 바꾸고 커밋합니다. T1이 y를 읽습니다. 두 값 각각은 어느 시점엔가 유효했지만, **T1이 본 x와 y의 조합은 한 번도 존재한 적이 없습니다.** 계좌 이체 중간 상태를 읽어 합계가 안 맞는 경우가 이것입니다.

**Write Skew (A5B)** — `r1[x] r2[y] w1[y] w2[x] c1 c2`

T1과 T2가 서로가 쓸 값을 읽고, 각자 상대가 읽은 쪽을 씁니다. **두 트랜잭션이 같은 행을 쓰지 않으므로 쓰기 충돌이 없습니다.** 그런데 둘이 함께 커밋되면 둘 다 읽고 검사했던 조건이 깨집니다.

이 셋의 공통점이 중요합니다. **Dirty Read도 아니고, 같은 행을 두 번 읽지도 않고, 행 개수가 달라지지도 않습니다.** 그래서 표준 표를 아무리 봐도 "내 격리 수준에서 이게 발생하는가"를 알 수 없습니다.

## 3. 표준 표와 내 DB의 실제 동작은 다릅니다

여기가 실무에서 가장 많이 틀리는 지점입니다. 교과서 표를 외워도 내 DB의 동작은 그 표가 아닙니다.

### 3-1. PostgreSQL — `REPEATABLE READ`가 표준보다 강합니다

PostgreSQL 매뉴얼은 자기 구현을 표준과 나란히 비교한 표를 직접 제공합니다([Transaction Isolation](https://www.postgresql.org/docs/current/transaction-iso.html)).

| 수준 | Dirty Read | Non-repeatable | Phantom | Serialization Anomaly |
|---|---|---|---|---|
| Read Uncommitted (표준) | 허용 | 발생 | 발생 | 발생 |
| Read Uncommitted (PG) | **불가** | 발생 | 발생 | 발생 |
| Read Committed (PG 기본값) | 불가 | 발생 | 발생 | 발생 |
| Repeatable Read (표준) | 불가 | 불가 | **허용** | 발생 |
| Repeatable Read (PG) | 불가 | 불가 | **불가** | 발생 |
| Serializable | 불가 | 불가 | 불가 | 불가 |

두 줄이 표준과 다릅니다. PostgreSQL은 `READ UNCOMMITTED`를 요청해도 `READ COMMITTED`로 동작하므로 **Dirty Read를 발생시킬 방법이 없습니다.** 그리고 `REPEATABLE READ`에서 Phantom Read가 발생하지 않습니다. 매뉴얼은 이 구현을 **Snapshot Isolation**이라고 명시합니다.

그래서 PostgreSQL에는 맨 오른쪽 칸이 따로 있습니다. **Serialization Anomaly** — 각 트랜잭션은 성공했는데, 그 결과가 어떤 순차 실행으로도 만들어질 수 없는 상태입니다. Write Skew가 여기에 들어갑니다. 그리고 `SERIALIZABLE`만 이걸 막습니다.

막는 방식이 "기다리게"가 아니라 **"실패시키기"**입니다. PostgreSQL은 직렬화 실패를 전부 SQLSTATE `40001`로 돌려주고, 메시지는 수준에 따라 다릅니다.

- `REPEATABLE READ`에서 같은 행을 동시에 수정: `could not serialize access due to concurrent update`
- `SERIALIZABLE`에서 읽기/쓰기 의존성 충돌: `could not serialize access due to read/write dependencies among transactions`

**이 말은 PostgreSQL에서 `READ COMMITTED` 위로 올리는 순간 재시도 코드가 애플리케이션 책임이 된다는 뜻입니다.** 올리기만 하고 재시도를 안 붙이면, 막은 이상현상이 500 응답으로 바뀝니다.

### 3-2. MySQL InnoDB — `SELECT`와 `UPDATE`가 다른 시점을 봅니다

MySQL의 기본값은 `REPEATABLE READ`입니다([InnoDB Transaction Isolation Levels](https://dev.mysql.com/doc/refman/8.4/en/innodb-transaction-isolation-levels.html)). 그리고 PostgreSQL과 전혀 다른 방식으로 표준에서 벗어납니다.

매뉴얼의 문장이 핵심입니다 — **"스냅숏은 트랜잭션 안의 `SELECT`에 적용되고, DML에는 반드시 적용되지 않는다"**([Consistent Nonlocking Reads](https://dev.mysql.com/doc/refman/8.4/en/innodb-consistent-read.html)). 매뉴얼이 직접 보여주는 예제입니다.

```sql
-- REPEATABLE READ 트랜잭션 안에서
SELECT COUNT(c2) FROM t1 WHERE c2 = 'abc';
-- 0건. 내 스냅숏에는 해당 행이 없습니다.

UPDATE t1 SET c2 = 'cba' WHERE c2 = 'abc';
-- 10건 변경. 다른 트랜잭션이 방금 커밋한 행들입니다.

SELECT COUNT(c2) FROM t1 WHERE c2 = 'cba';
-- 10건. 내가 건드렸으므로 이제 보입니다.
```

조회에는 0건인 행을 수정은 10건 바꿉니다. **`SELECT`는 트랜잭션 시작 시점의 스냅숏을, 쓰기는 최신 커밋 상태를 봅니다.** 매뉴얼이 같은 트랜잭션에서 락 없는 `SELECT`와 락 걸리는 문장을 섞지 말라고 권고하는 이유가 이것입니다. 섞으면 두 문장이 서로 다른 DB 상태를 읽습니다.

이 동작이 실무에 주는 결과는 양면적입니다.

- **좋은 쪽** — `UPDATE stock SET quantity = quantity - 1 WHERE ...`처럼 SQL 한 문장 안에서 읽고 쓰면 Lost Update가 생기지 않습니다. 쓰기가 최신 값을 다시 읽기 때문입니다.
- **나쁜 쪽** — 애플리케이션이 `SELECT`로 읽어서 자바에서 계산하고 다시 쓰면, 읽은 값은 스냅숏입니다. **Lost Update가 그대로 발생합니다.** 매뉴얼은 일관된 읽기가 락을 전혀 걸지 않는다고 명시합니다.

`READ COMMITTED`로 내리면 또 다른 것이 바뀝니다. 매뉴얼에 따르면 락 걸리는 읽기와 `UPDATE`/`DELETE`에서 **갭 락이 비활성화**됩니다. 그래서 잠긴 레코드 옆에 다른 세션이 행을 끼워넣을 수 있고, 즉 Phantom이 발생합니다. 반대로 `REPEATABLE READ`에서는 범위 조건에 next-key 락이 걸려 그 범위로의 `INSERT`가 막힙니다. 유니크 인덱스에 유니크 조건이면 갭을 잠그지 않고 찾은 레코드만 잠급니다.

**MySQL에서 격리 수준을 내리는 것은 "읽기 보장을 포기하는" 선택이 아니라 "잠그는 범위를 바꾸는" 선택입니다.** 데드락이 줄어드는 대신 Phantom이 들어옵니다.

### 3-3. 그래서 같은 코드가 DB에 따라 다르게 끝납니다

`UPDATE accounts SET balance = balance + 100 WHERE id = 1`을 두 트랜잭션이 동시에 실행한다고 합시다.

| DB / 수준 | 결과 |
|---|---|
| MySQL `REPEATABLE READ` | 뒤쪽이 락을 기다린 뒤, 최신 값에 +100. 둘 다 성공 |
| PostgreSQL `READ COMMITTED` | 뒤쪽이 기다린 뒤 갱신된 버전으로 `WHERE`를 재평가하고 적용. 둘 다 성공 |
| PostgreSQL `REPEATABLE READ` | 뒤쪽이 `40001`로 **실패**. 재시도해야 합니다 |

PostgreSQL 매뉴얼은 `READ COMMITTED`의 재평가 동작을 바로 이 `balance + 100` 예제로 설명합니다. 세 경우 모두 Lost Update는 없습니다. 하지만 **실패하는 경우가 하나 있고, 거기엔 재시도 코드가 필요합니다.** 로컬에서 MySQL로 개발하고 운영에서 PostgreSQL을 쓰면 여기서 처음 터집니다.

## 4. 증상에서 이상현상 이름까지

실제로 쓰게 되는 판별 표입니다.

| 증상 | 이상현상 | 격리 수준을 올리면 막히나 | 해법 |
|---|---|---|---|
| 롤백된 데이터가 집계에 들어갔습니다 | Dirty Read | 막힙니다 (`READ COMMITTED`) | 기본값을 쓰면 이미 막혀 있습니다 |
| 한 요청 안에서 같은 행의 값이 중간에 바뀝니다 | Non-repeatable Read | 막힙니다 (`REPEATABLE READ`) | 격리 수준 또는 조회 1회로 줄이기 |
| 집계 합계와 상세 목록의 합이 안 맞습니다 | Read Skew | 막힙니다 (Snapshot Isolation 이상) | 한 트랜잭션 안에서 함께 읽기 |
| 조건에 맞는 행이 조회 때는 없었는데 `INSERT`에서 중복 키가 납니다 | Phantom Read | DB에 따라 다릅니다 (3-1, 3-2) | 유니크 제약 + 중복 키 예외 처리 |
| 두 사람이 수정했는데 한쪽 수정만 남았습니다 | **Lost Update** | **막히지 않습니다** | `FOR UPDATE` 또는 버전 컬럼 |
| 각자 조건을 검사하고 통과했는데 전체 조건이 깨졌습니다 | **Write Skew** | `SERIALIZABLE`만 | 검사 대상을 잠그거나 제약으로 옮기기 |

아래 두 줄이 이 챕터의 결론입니다. **실무 동시성 버그의 대부분은 아래 두 줄이고, 격리 수준을 한 칸 올려서는 안 고쳐집니다.**

## 5. 예제

### 5-1. 격리 수준을 올려서 막으려 한 코드 ❌

```java
@Service
@RequiredArgsConstructor
public class CouponIssueService {

    private final CouponRepository couponRepository;
    private final CouponIssueRepository couponIssueRepository;

    // 선착순 100장. 격리 수준을 올려서 막아보려는 시도
    @Transactional(isolation = Isolation.REPEATABLE_READ)
    public void issue(Long couponId, Long userId) {
        Coupon coupon = couponRepository.findById(couponId)
                .orElseThrow(() -> new CouponNotFoundException(couponId));

        if (coupon.getIssuedCount() >= coupon.getTotalCount()) {
            throw new CouponSoldOutException(couponId);
        }

        coupon.increaseIssuedCount();              // 읽은 값 + 1
        couponIssueRepository.save(new CouponIssue(couponId, userId));
    }
}
```

전형적인 Lost Update입니다. 동시 요청 50개가 전부 `issuedCount = 99`를 읽고, 전부 검사를 통과하고, 전부 `100`을 씁니다. **150장이 발급되고 카운터는 100입니다.**

`REPEATABLE READ`는 이걸 막지 않습니다. 오히려 MySQL에서는 스냅숏 때문에 더 확실하게 오래된 값을 읽습니다. `SERIALIZABLE`까지 올리면 막히긴 하지만, 선착순 트래픽 전체를 직렬화하므로 락 대기나 데드락으로 요청이 쏟아져 실패합니다.

### 5-2. 범위를 좁힌 코드 ✔️

읽고-계산하고-쓰는 구간을 **SQL 한 문장으로 합치는 것**이 가장 싼 해법입니다.

```java
public interface CouponRepository extends JpaRepository<Coupon, Long> {

    @Modifying(clearAutomatically = true)
    @Query("""
           update Coupon c
              set c.issuedCount = c.issuedCount + 1
            where c.id = :couponId
              and c.issuedCount < c.totalCount
           """)
    int increaseIssuedCount(@Param("couponId") Long couponId);
}
```

```java
@Transactional
public void issue(Long couponId, Long userId) {
    int updated = couponRepository.increaseIssuedCount(couponId);
    if (updated == 0) {                            // 조건이 깨졌다는 뜻
        throw new CouponSoldOutException(couponId);
    }
    couponIssueRepository.save(new CouponIssue(couponId, userId));
}
```

쓰기는 스냅숏이 아니라 최신 커밋 값을 보고 `WHERE`를 재평가합니다(3-2, 3-3). 그래서 101번째 요청은 `updated == 0`을 받습니다. **격리 수준은 기본값 그대로 두고, 검사와 갱신을 원자적으로 만든 것입니다.**

애플리케이션에서 계산해야 한다면 둘 중 하나를 씁니다.

```java
// 비관적 — 읽을 때 잠급니다
@Lock(LockModeType.PESSIMISTIC_WRITE)
Optional<Coupon> findWithLockById(Long id);

// 낙관적 — 버전이 바뀌었으면 커밋에서 실패합니다
@Entity
public class Coupon {
    @Version
    private Long version;
}
```

### 5-3. Write Skew는 범위를 좁혀도 안 막힙니다

당직자가 최소 1명이어야 하는 테이블입니다. 두 사람이 동시에 당직을 뺍니다.

```java
@Transactional
public void cancelOnCall(Long memberId, LocalDate date) {
    long remaining = onCallRepository.countByDateAndActiveTrue(date);
    if (remaining <= 1) {
        throw new MinimumOnCallException(date);
    }
    onCallRepository.deactivate(memberId, date);   // 자기 행만 수정
}
```

둘이 각각 `remaining = 2`를 읽고, 각각 검사를 통과하고, **각자 다른 행을 수정합니다.** 쓰기 충돌이 없으니 Lost Update 방어책이 전부 무효입니다. 버전 컬럼은 서로 다른 행이라 안 걸리고, `FOR UPDATE`로 자기 행을 잠가도 상대 행과 무관합니다. 커밋 후 당직자가 0명입니다.

PostgreSQL 매뉴얼이 `SERIALIZABLE` 절에서 드는 예제가 정확히 이 구조입니다. 두 트랜잭션이 각각 상대 그룹의 합계를 읽고 상대 그룹에 쓰는데, `REPEATABLE READ`에서는 둘 다 커밋되고 `SERIALIZABLE`에서는 한쪽이 read/write 의존성 오류로 실패합니다.

해법은 셋입니다.

1. **읽은 범위를 잠근다** — `SELECT ... FOR UPDATE`로 그날 당직 행 전체를 잠급니다. 검사 대상과 잠근 대상을 일치시키는 것입니다.
2. **조건을 DB 제약으로 옮긴다** — 날짜별 당직 수를 집계 컬럼으로 두고 거기에 `CHECK`를 걸면, 조건 검사가 쓰기 충돌로 바뀝니다.
3. **PostgreSQL이면 `SERIALIZABLE` + 재시도** — SQLSTATE `40001`을 잡아 재시도합니다.

MySQL의 `SERIALIZABLE`은 다릅니다. 매뉴얼에 따르면 autocommit이 꺼진 상태에서 모든 일반 `SELECT`를 `SELECT ... FOR SHARE`로 바꿉니다. 즉 두 트랜잭션이 서로 공유 락을 쥔 채 쓰기로 넘어가게 되고, 한쪽은 락 대기나 데드락으로 실패합니다. **결과적으로 막히지만 "직렬화 검증"이 아니라 "공유 락 충돌"로 막는 것이고, 비용은 읽기 전체에 붙습니다.**

<!-- TODO: 확인 필요 — MySQL SERIALIZABLE에서 위 Write Skew 시나리오가 데드락으로 끝나는지 락 대기 타임아웃으로 끝나는지는 매뉴얼에 직접 적혀 있지 않습니다. 암묵적 FOR SHARE 변환만 문서화된 사실이고, 그 뒤 실패 형태는 실제 재현으로 확인해야 합니다. -->

## 6. 함정

**격리 수준을 올렸는데 실패율이 올라갔습니다**

- **증상**: 동시성 버그는 줄었는데 `40001`이나 `Lock wait timeout exceeded`가 늘어납니다.
- **원인**: 격리 수준을 올리는 것은 이상현상이 성립하는 동시 실행을 DB가 거부하게 만드는 것입니다. 거부는 대기 또는 실패로 나타납니다.
- **해법**: 올리기 전에 재시도 경로를 먼저 만듭니다. PostgreSQL이면 `40001` 재시도가 사실상 필수입니다. 특정 구간만 문제라면 전체 격리 수준 대신 그 구간의 락이나 버전 컬럼으로 좁힙니다.

**조회에서 안 보이던 행이 `INSERT`에서 중복 키로 터집니다**

- **증상**: `SELECT`로 없음을 확인하고 `INSERT`했는데 `DuplicateKeyException`이 납니다.
- **원인**: MySQL `REPEATABLE READ`에서 락 없는 `SELECT`는 스냅숏을 봅니다. 그 사이 다른 트랜잭션이 커밋한 행은 보이지 않지만 유니크 인덱스에는 존재합니다.
- **해법**: 중복 키 예외를 정상 분기로 처리합니다. **"조회해서 없으면 넣는다"는 코드로는 중복을 막을 수 없습니다.** 유니크 제약이 유일한 방어선이고, 애플리케이션 검사는 사용자 메시지를 위한 것입니다.

**같은 트랜잭션 안에서 `SELECT` 결과와 `UPDATE` 건수가 안 맞습니다**

- **증상**: `COUNT`는 0인데 같은 조건의 `UPDATE`가 10건을 바꿉니다.
- **원인**: MySQL에서 일관된 읽기와 DML이 서로 다른 시점을 봅니다(3-2).
- **해법**: 같은 트랜잭션에서 락 없는 `SELECT`와 락 걸리는 문장을 섞지 않습니다. 최신 상태로 판단해야 하면 그 `SELECT`에 `FOR SHARE` 또는 `FOR UPDATE`를 붙여 둘을 같은 시점으로 맞춥니다.

**테스트에서는 재현되지 않습니다**

- **증상**: 운영에서만 나고 로컬·CI에서는 통과합니다.
- **원인**: 이상현상은 **두 트랜잭션이 겹칠 때만** 성립합니다. 순차 호출 테스트는 겹치지 않습니다.
- **해법**: 두 스레드가 같은 자원을 치는 테스트를 작성합니다. `CountDownLatch`로 두 트랜잭션의 시작을 맞추고, 결과를 검증합니다. 한쪽이 실패하는 것이 정상 동작인 경우가 많으므로, **"둘 다 성공"을 기대값으로 두지 않습니다.**

## 7. 참고자료

- [PostgreSQL — Transaction Isolation](https://www.postgresql.org/docs/current/transaction-iso.html) — 표준과 PostgreSQL의 이상현상 비교표, Snapshot Isolation 명시, `40001`
- [MySQL 8.4 — Transaction Isolation Levels](https://dev.mysql.com/doc/refman/8.4/en/innodb-transaction-isolation-levels.html) — 수준별 락 범위, 갭 락 동작
- [MySQL 8.4 — Consistent Nonlocking Reads](https://dev.mysql.com/doc/refman/8.4/en/innodb-consistent-read.html) — 스냅숏이 DML에 적용되지 않는다는 문장과 예제
- [A Critique of ANSI SQL Isolation Levels (Berenson et al., SIGMOD 1995)](https://www.microsoft.com/en-us/research/publication/a-critique-of-ansi-sql-isolation-levels/) — Lost Update, Read Skew, Write Skew의 출처
- `daily/day56-transaction-isolation.md` — Spring에서 `isolation` 값이 실제로 거치는 경로와 무시되는 경우
- `daily/day65-acid.md` — ACID의 I가 약속하는 범위

# NULL이 만드는 예상치 못한 버그 — 왜 조용히 틀린 답이 나오는가

## 1. 핵심 개념

`NULL`은 값이 아닙니다. **"이 자리에 무엇이 들어갈지 모른다"는 표시**입니다.

이 한 문장이 전부입니다. 그런데 우리는 코드를 쓸 때 NULL을 "빈 값", "0", "빈 문자열" 같은 특별한 값으로 취급합니다. DB는 그렇게 취급하지 않습니다. 이 간극에서 버그가 나옵니다.

> NULL 버그가 위험한 건 **에러가 안 나기 때문**입니다. `NOT IN` 조건에 NULL이 끼면 쿼리는 성공하고, 결과는 0건입니다. 통계 API가 갑자기 0을 반환하고, 배치가 아무것도 처리하지 않고 성공 로그를 남깁니다. 예외가 터지면 그나마 다행이고, 대부분은 몇 주 뒤에 "숫자가 이상한데요"로 발견됩니다.

### 1-1. 3값 논리(Three-Valued Logic)

일반 프로그래밍 언어의 boolean은 `true`/`false` 두 개입니다. SQL은 세 개입니다.

```
TRUE  /  FALSE  /  UNKNOWN
```

`NULL`이 들어간 비교는 대부분 `UNKNOWN`이 됩니다. MySQL 공식 문서의 표현입니다.

> "In SQL, the `NULL` value is never true in comparison to any other value, even `NULL`." — [MySQL 8.4 Reference Manual, Working with NULL Values](https://dev.mysql.com/doc/refman/8.4/en/problems-with-null.html)

그리고 **`WHERE`는 `TRUE`인 행만 통과시킵니다.** `FALSE`와 `UNKNOWN`을 구분하지 않고 똑같이 버립니다. 이게 모든 NULL 버그의 뿌리입니다.

```sql
-- 셋 다 결과는 0건입니다
SELECT * FROM orders WHERE canceled_at =  NULL;
SELECT * FROM orders WHERE canceled_at <> NULL;
SELECT * FROM orders WHERE canceled_at =  canceled_at;
```

세 번째가 특히 반직관적입니다. "자기 자신과 같은가"조차 `UNKNOWN`입니다. 모르는 값과 모르는 값이 같은지 알 수 없기 때문입니다.

### 1-2. 진리표

`AND`와 `OR`가 `UNKNOWN`을 어떻게 다루는지가 실무에서 중요합니다.

| A | B | A AND B | A OR B |
|---|---|---|---|
| TRUE | UNKNOWN | UNKNOWN | **TRUE** |
| FALSE | UNKNOWN | **FALSE** | UNKNOWN |
| UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |

핵심은 두 줄입니다.

- `FALSE AND UNKNOWN` = `FALSE` — 확정적으로 거짓이면 나머지를 몰라도 거짓입니다.
- `TRUE OR UNKNOWN` = `TRUE` — 확정적으로 참이면 나머지를 몰라도 참입니다.

즉 `UNKNOWN`은 **전염되지만, 결과를 확정할 수 있으면 흡수됩니다.** `NOT IN` 함정이 왜 생기는지가 여기서 설명됩니다.

---

## 2. 함정 1 — `NOT IN` 서브쿼리가 0건을 반환한다

가장 자주 밟고, 가장 늦게 발견되는 함정입니다.

**증상**

"쿠폰을 한 번도 안 쓴 회원"을 뽑는 쿼리가 어제까지 잘 돌다가 오늘 0건을 반환합니다. 에러는 없습니다.

```sql
SELECT member_id
FROM   members
WHERE  member_id NOT IN (SELECT member_id FROM coupon_usages);
```

**원인**

`coupon_usages.member_id`에 NULL이 한 행이라도 들어간 순간입니다. `NOT IN`은 내부적으로 이렇게 펼쳐집니다.

```
member_id <> 100  AND  member_id <> 205  AND  member_id <> NULL
                                              └─ 항상 UNKNOWN
```

마지막 항이 `UNKNOWN`이므로 전체는 잘 해봐야 `UNKNOWN`입니다. 앞의 비교가 전부 `TRUE`여도 `TRUE AND UNKNOWN` = `UNKNOWN`이라 `WHERE`를 통과하지 못합니다. 결과는 **테이블 전체가 0건**입니다.

반대로 `IN`은 멀쩡히 동작합니다. `TRUE OR UNKNOWN` = `TRUE`라서 매칭되는 값이 하나만 있으면 `UNKNOWN`이 흡수되기 때문입니다. 그래서 "`IN`은 되는데 `NOT IN`만 이상하다"는 상황이 됩니다.

**해법**

`NOT EXISTS`로 바꿉니다. `EXISTS`는 값을 비교하지 않고 행의 존재 여부만 보므로 3값 논리에 걸리지 않습니다.

```sql
-- ✅ NULL이 섞여 있어도 의도대로 동작합니다
SELECT m.member_id
FROM   members m
WHERE  NOT EXISTS (
    SELECT 1 FROM coupon_usages c WHERE c.member_id = m.member_id
);
```

`NOT IN`을 꼭 써야 한다면 서브쿼리에서 NULL을 제거합니다. 다만 이건 "매번 기억해야 하는 방어"라 근본 해법이 아닙니다.

```sql
WHERE member_id NOT IN (
    SELECT member_id FROM coupon_usages WHERE member_id IS NOT NULL
);
```

**가장 좋은 해법은 애초에 `coupon_usages.member_id`를 `NOT NULL`로 선언하는 것입니다.** 외래 키 컬럼이 NULL을 허용할 이유는 거의 없습니다.

---

## 3. 함정 2 — 평균이 이상한데 합계는 맞는다

**증상**

주문 100건 중 `discount_amount`가 NULL인 행이 40건입니다. 그런데 `AVG(discount_amount)`가 기대보다 훨씬 큽니다.

**원인**

집계 함수는 NULL을 **세지 않습니다.**

> "Aggregate (group) functions such as `COUNT()`, `MIN()`, and `SUM()` ignore `NULL` values. The exception to this is `COUNT(*)`, which counts rows and not individual column values." — [MySQL 8.4 Reference Manual](https://dev.mysql.com/doc/refman/8.4/en/problems-with-null.html)

`AVG`는 `SUM / COUNT`인데, 이때 분모가 **행 수가 아니라 NULL이 아닌 값의 개수**입니다. 위 예시에서 분모는 100이 아니라 60입니다.

```sql
SELECT COUNT(*)               AS 행_수,          -- 100
       COUNT(discount_amount) AS 값이_있는_행,   --  60
       SUM(discount_amount)   AS 합계,
       AVG(discount_amount)   AS 평균            -- 합계 / 60
FROM   orders;
```

**해법**

"NULL을 0으로 볼 것인가"를 먼저 결정합니다. 이건 SQL 문제가 아니라 도메인 문제입니다.

- **할인을 안 받은 주문 = 할인액 0원**이라면 → 값을 채워서 계산합니다.
- **할인 정보가 아직 안 들어온 것**이라면 → 지금 동작이 맞습니다. 오히려 0으로 채우면 왜곡됩니다.

```sql
-- ✅ "NULL은 0으로 본다"를 명시
SELECT AVG(COALESCE(discount_amount, 0)) AS 평균 FROM orders;
```

`SUM()`이 0건을 집계하면 0이 아니라 **NULL을 반환합니다.** 이 값이 그대로 API 응답에 실려 나가면 클라이언트에서 터집니다.

```sql
-- ✅ 결과가 없을 때도 숫자를 보장
SELECT COALESCE(SUM(amount), 0) FROM orders WHERE member_id = 1;
```

---

## 4. 함정 3 — LEFT JOIN이 조용히 INNER JOIN이 된다

**증상**

"주문이 없는 회원도 포함해서" 뽑으려고 `LEFT JOIN`을 썼는데, 주문 없는 회원이 결과에 안 보입니다.

```sql
SELECT m.member_id, o.order_id
FROM   members m
LEFT JOIN orders o ON o.member_id = m.member_id
WHERE  o.status = 'PAID';   -- ❌ 여기가 문제
```

**원인**

`LEFT JOIN`은 짝이 없는 행을 오른쪽 컬럼이 전부 NULL인 채로 살려 보냅니다. 그런데 그 다음 `WHERE o.status = 'PAID'`가 평가됩니다. `NULL = 'PAID'`는 `UNKNOWN`이고, `WHERE`는 `UNKNOWN`을 버립니다.

**결과적으로 `LEFT JOIN`이 `INNER JOIN`으로 강등됩니다.** 문법은 `LEFT JOIN`인데 동작은 아닙니다. (JOIN의 단계별 동작은 `daily/day05-join-types.md`에 정리해 뒀습니다.)

**해법**

오른쪽 테이블에 대한 조건은 `WHERE`가 아니라 `ON`에 둡니다. `ON`은 짝짓기 단계에서 평가되고, 짝을 못 지은 행은 그 뒤에 NULL로 되살아납니다.

```sql
-- ✅ 조건을 ON으로
SELECT m.member_id, o.order_id
FROM   members m
LEFT JOIN orders o
       ON o.member_id = m.member_id
      AND o.status = 'PAID';
```

"짝이 없는 행만" 뽑으려는 의도라면 `IS NULL`을 명시적으로 씁니다. 이건 `WHERE`에 두는 게 맞습니다.

```sql
-- ✅ 주문이 하나도 없는 회원
SELECT m.member_id
FROM   members m
LEFT JOIN orders o ON o.member_id = m.member_id
WHERE  o.order_id IS NULL;
```

---

## 5. 함정 4 — UNIQUE 제약이 중복을 막지 못한다

**증상**

`email`에 UNIQUE 인덱스를 걸었는데 같은 회원이 여러 번 가입됩니다. 또는 "탈퇴하지 않은 회원의 로그인 ID는 유일" 같은 규칙이 안 지켜집니다.

**원인**

NULL끼리는 같은지 알 수 없으므로, **UNIQUE 제약은 여러 개의 NULL을 허용합니다.**

> "A `UNIQUE` index permits multiple `NULL` values for columns that can contain `NULL`." — [MySQL 8.4, CREATE INDEX](https://dev.mysql.com/doc/refman/8.4/en/create-index.html)

PostgreSQL도 기본 동작이 같습니다. "unique 제약을 판단할 때 null 값은 서로 같다고 보지 않는다"는 것이 기본이고, PostgreSQL 15부터 `NULLS NOT DISTINCT` 옵션으로 뒤집을 수 있습니다. ([PostgreSQL 문서 5.5 Constraints](https://www.postgresql.org/docs/current/ddl-constraints.html))

소프트 삭제(soft delete) 테이블에서 특히 자주 터집니다. `(login_id, deleted_at)`에 UNIQUE를 걸어 두고 살아 있는 행의 `deleted_at`을 NULL로 두면, 같은 `login_id`가 무한히 들어갑니다. NULL이 매번 "서로 다른 값"으로 취급되기 때문입니다.

**해법**

세 가지 중 하나를 고릅니다.

1. **부분 인덱스** (PostgreSQL) — 조건에 맞는 행만 유일성을 강제합니다.

```sql
CREATE UNIQUE INDEX ux_members_login_id_active
    ON members (login_id)
    WHERE deleted_at IS NULL;
```

2. **NULL 대신 센티널 값** (MySQL처럼 부분 인덱스가 없는 경우) — 살아 있는 행의 `deleted_at`을 `'1970-01-01 00:00:00'` 같은 고정값으로 둡니다. NULL이 사라지므로 UNIQUE가 정상 동작합니다. 대신 "이 값은 삭제 안 됨을 뜻한다"는 규칙이 코드 전체에 퍼지는 비용을 집니다.

3. **PostgreSQL 15 이상이라면** `UNIQUE NULLS NOT DISTINCT`로 NULL끼리도 중복으로 취급합니다.

---

## 6. 함정 5 — CHECK 제약을 NULL이 그냥 통과한다

**증상**

`CHECK (discount_rate BETWEEN 0 AND 100)`을 걸어 뒀는데 이상한 행이 들어옵니다.

**원인**

PostgreSQL 문서의 표현입니다.

> "A check constraint is satisfied if the check expression evaluates to true or the null value." — [PostgreSQL 문서 5.5 Constraints](https://www.postgresql.org/docs/current/ddl-constraints.html)

`NULL BETWEEN 0 AND 100`은 `UNKNOWN`이고, CHECK는 `FALSE`일 때만 막습니다. **`UNKNOWN`은 통과입니다.** 즉 CHECK 제약은 NULL을 걸러 주지 않습니다.

**해법**

값의 범위를 강제하는 것과 값의 존재를 강제하는 것은 별개의 제약입니다. 둘 다 필요하면 둘 다 씁니다.

```sql
ALTER TABLE coupons
    ALTER COLUMN discount_rate SET NOT NULL;   -- 존재 강제
-- CHECK는 범위만 담당
```

---

## 7. 함정 6 — 문자열 하나가 NULL이라 이름 전체가 사라진다

**증상**

주소 표시 필드가 통째로 비어 있습니다. 상세 주소만 입력을 안 한 회원인데 시/구까지 안 보입니다.

**원인**

`NULL`이 섞인 산술·문자열 연산은 결과 전체가 `NULL`입니다. 앞서 인용한 MySQL 문서의 "An expression that contains `NULL` always produces a `NULL` value"가 이 얘기입니다.

여기서 DB별로 갈립니다. PostgreSQL 기준으로 연산자와 함수가 다르게 동작합니다.

- `||` 연산자 — 표준 SQL 의미대로 NULL이 전파됩니다.
- `concat()` 함수 — "NULL arguments are ignored"라고 명시돼 있습니다. ([PostgreSQL 문서 9.4 String Functions](https://www.postgresql.org/docs/current/functions-string.html))

MySQL의 `CONCAT()`은 PostgreSQL의 `concat()`과 이름이 같지만 NULL 처리 규칙이 다릅니다. **이름이 같다고 동작이 같다고 가정하지 않는 게 안전합니다.**

**해법**

문자열을 이어붙일 때는 NULL 가능 컬럼을 반드시 감쌉니다.

```sql
-- ❌ detail_address가 NULL이면 전체가 NULL
SELECT city || ' ' || district || ' ' || detail_address AS full_address FROM addresses;

-- ✅
SELECT city || ' ' || district || ' ' || COALESCE(detail_address, '') AS full_address FROM addresses;
```

---

## 8. 함정 7 — 정렬 순서가 DB를 바꾸면 달라진다

**증상**

로컬(PostgreSQL)에서 만든 목록 API를 운영(MySQL)에 올렸더니 첫 페이지 내용이 다릅니다.

**원인**

NULL을 어디에 놓을지에 대한 기본값이 다릅니다. 둘 다 공식 문서에 명시돼 있습니다.

| DB | ASC | DESC |
|---|---|---|
| MySQL 8.4 | NULL 먼저 | NULL 나중 |
| PostgreSQL | NULL 나중 | NULL 먼저 |

- MySQL: "When using `ORDER BY`, `NULL` values are presented first, or last if you specify `DESC`." ([MySQL 8.4](https://dev.mysql.com/doc/refman/8.4/en/problems-with-null.html))
- PostgreSQL: null은 어떤 non-null 값보다 큰 것으로 정렬되며, 기본값은 ASC에서 `NULLS LAST`, DESC에서 `NULLS FIRST`입니다. ([PostgreSQL 문서 7.5 Sorting Rows](https://www.postgresql.org/docs/current/queries-order.html))

정확히 반대입니다.

**해법**

정렬 결과가 API 계약의 일부라면 기본값에 기대지 말고 명시합니다. PostgreSQL은 `NULLS LAST`를 직접 쓸 수 있습니다.

```sql
-- PostgreSQL
ORDER BY published_at DESC NULLS LAST;
```

MySQL 8.4에는 `NULLS LAST` 구문이 없어서 정렬 키를 하나 더 만들어 흉내 냅니다.

```sql
-- MySQL
ORDER BY (published_at IS NULL), published_at DESC;
```

`published_at IS NULL`이 0/1로 평가되므로 NULL인 행이 뒤로 갑니다.

<!-- TODO: 확인 필요 — Oracle, SQL Server의 기본 NULL 정렬 순서는 이번에 공식 문서로 확인하지 못했습니다. 해당 DB를 쓴다면 직접 확인하고 표에 추가하세요. -->

---

## 9. 함정 8 — 애플리케이션에서 NULL이 0으로 둔갑한다

DB만의 문제가 아닙니다. Java까지 넘어오면서 한 번 더 변합니다.

**증상 1 — 값이 조용히 0이 된다**

JDBC의 `getInt()`는 SQL NULL을 만나면 예외를 던지지 않습니다.

> "the column value; if the value is SQL `NULL`, the value returned is `0`" — [Java SE 21 API, ResultSet.getInt](https://docs.oracle.com/en/java/javase/21/docs/api/java.sql/java/sql/ResultSet.html#getInt(int))

즉 **"값이 없음"과 "값이 0"이 구분되지 않습니다.** 구분하려면 값을 읽은 직후 `wasNull()`을 호출해야 합니다. 실무에서 JDBC를 직접 쓰는 일은 줄었지만, 이 규칙이 하위 계층에 그대로 살아 있다는 건 알고 있어야 합니다.

```java
int point = resultSet.getInt("point");
if (resultSet.wasNull()) {
    // 실제 값은 NULL이었습니다
}
```

**증상 2 — 조회만 했는데 NPE**

JPA 엔티티에서 nullable 컬럼을 원시 타입(primitive)에 매핑한 경우입니다.

```java
// ❌ discount_amount가 NULL인 행을 읽는 순간 언박싱 NPE
@Column(name = "discount_amount")
private long discountAmount;
```

DB에서 온 `null`을 `long`에 넣으려면 언박싱이 필요하고, `null.longValue()`가 되면서 `NullPointerException`이 납니다. 스택트레이스에 SQL도 컬럼명도 안 나와서 원인을 찾기 어렵습니다.

```java
// ✅ nullable 컬럼은 래퍼 타입으로 받습니다
@Column(name = "discount_amount")
private Long discountAmount;
```

**해법의 방향**

컬럼이 NULL을 허용하는지 여부와 필드 타입이 일치해야 합니다.

- 컬럼이 `NOT NULL`이면 → 원시 타입(`long`, `int`)을 쓰고, 엔티티에도 `@Column(nullable = false)`로 의도를 남깁니다.
- 컬럼이 nullable이면 → 래퍼 타입(`Long`, `Integer`)을 씁니다. **그리고 이 필드를 다루는 코드는 전부 null을 처리해야 합니다.**

두 번째 항목의 비용이 생각보다 큽니다. 그래서 다음 절이 중요합니다.

---

## 10. 근본 해법 — NULL을 허용할지 스키마에서 결정한다

지금까지의 함정은 전부 "NULL이 이미 들어와 있다"를 전제로 한 대응입니다. 대응 코드는 매번 기억해야 하고, 한 번 빠뜨리면 다시 버그입니다.

**가장 값싼 방어는 NULL이 들어올 자리를 줄이는 것입니다.** 컬럼을 만들 때 다음을 스스로에게 묻습니다.

> "이 컬럼이 비어 있는 상태가 **도메인에서 의미가 있는가?**"

| 상황 | 판단 |
|---|---|
| 배송완료일 — 아직 배송 안 된 주문 | **NULL이 맞습니다.** "아직 없음"이 실제 상태입니다 |
| 할인금액 — 할인을 안 받은 주문 | **`NOT NULL DEFAULT 0`이 낫습니다.** 0원 할인은 값이 있는 상태입니다 |
| 회원 등급 — 가입 시 자동 부여 | **`NOT NULL`.** 등급 없는 회원이 존재할 수 없다면 NULL도 없어야 합니다 |
| 외래 키 — 소속 부서 | **관계가 선택적일 때만** nullable. 필수 관계면 `NOT NULL` |

기준은 하나입니다. **"모른다"가 진짜 상태 중 하나인 컬럼만 NULL을 허용합니다.** 그냥 값이 안 정해져서, 마이그레이션이 귀찮아서 nullable로 두는 게 대부분의 원인입니다.

기존 테이블을 고칠 때는 순서가 있습니다. 데이터가 있는 상태에서 바로 `SET NOT NULL`을 걸면 실패합니다.

```sql
-- 1) 기존 NULL을 채웁니다
UPDATE orders SET discount_amount = 0 WHERE discount_amount IS NULL;

-- 2) 기본값을 먼저 걸어 신규 INSERT를 막습니다
ALTER TABLE orders ALTER COLUMN discount_amount SET DEFAULT 0;

-- 3) 마지막에 NOT NULL
ALTER TABLE orders ALTER COLUMN discount_amount SET NOT NULL;
```

큰 테이블에서 1번 `UPDATE`는 락과 복제 지연을 유발합니다. 배치로 나눠서 돌리는 게 안전합니다.

---

## 11. NULL을 다루는 도구 정리

| 목적 | 표준 SQL / PostgreSQL | MySQL |
|---|---|---|
| NULL 판별 | `IS NULL` / `IS NOT NULL` | 동일 |
| NULL이면 대체값 | `COALESCE(a, b)` | `COALESCE(a, b)`, `IFNULL(a, b)` |
| 두 값이 같으면 NULL로 | `NULLIF(a, b)` | 동일 |
| NULL 안전 비교 | `IS NOT DISTINCT FROM` | `<=>` |

`<=>`에 대한 MySQL 문서의 설명입니다.

> "`NULL`-safe equal. This operator performs an equality comparison like the `=` operator, but returns `1` rather than `NULL` if both operands are `NULL`, and `0` rather than `NULL` if one operand is `NULL`. The `<=>` operator is equivalent to the standard SQL `IS NOT DISTINCT FROM` operator." — [MySQL 8.4, Comparison Operators](https://dev.mysql.com/doc/refman/8.4/en/comparison-operators.html)

값이 바뀌었는지 판정하는 코드에서 유용합니다. `old <> new`는 한쪽이 NULL이면 "안 바뀜"으로 판정되지만, `NOT (old <=> new)`는 정확합니다.

`NULLIF`는 0으로 나누기를 막는 데 자주 씁니다.

```sql
-- 분모가 0이면 NULL이 되어 에러 대신 NULL을 반환합니다
SELECT SUM(paid_amount) / NULLIF(COUNT(*), 0) FROM orders;
```

---

## 12. 코드 리뷰 체크리스트

NULL 버그는 리뷰에서 잡는 게 가장 쌉니다. 다음 다섯 개만 봐도 대부분 걸립니다.

```
[ ] NOT IN 서브쿼리가 있는가 → NOT EXISTS로 바꿀 수 있는가
[ ] LEFT JOIN 뒤 WHERE에 오른쪽 테이블 컬럼 조건이 있는가
[ ] AVG / SUM 결과를 그대로 응답에 싣는가 → COALESCE로 감쌌는가
[ ] 새로 만든 컬럼이 nullable인가 → "모른다"가 실제 상태인가
[ ] JPA 엔티티에서 nullable 컬럼을 원시 타입으로 받고 있는가
```

---

## 13. 참고자료

- [MySQL 8.4 Reference Manual — Working with NULL Values](https://dev.mysql.com/doc/refman/8.4/en/problems-with-null.html)
- [MySQL 8.4 Reference Manual — Comparison Functions and Operators](https://dev.mysql.com/doc/refman/8.4/en/comparison-operators.html)
- [MySQL 8.4 Reference Manual — CREATE INDEX Statement](https://dev.mysql.com/doc/refman/8.4/en/create-index.html)
- [PostgreSQL Documentation — 5.5. Constraints](https://www.postgresql.org/docs/current/ddl-constraints.html)
- [PostgreSQL Documentation — 7.5. Sorting Rows (ORDER BY)](https://www.postgresql.org/docs/current/queries-order.html)
- [PostgreSQL Documentation — 9.4. String Functions and Operators](https://www.postgresql.org/docs/current/functions-string.html)
- [Java SE 21 API — java.sql.ResultSet](https://docs.oracle.com/en/java/javase/21/docs/api/java.sql/java/sql/ResultSet.html)
- 관련 노트: `daily/day05-join-types.md` — `ON`과 `WHERE`의 차이, LEFT JOIN의 3단계 동작

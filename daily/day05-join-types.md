# INNER·LEFT·RIGHT JOIN이 실제로 하는 일

> 이 문서가 답할 질문: **JOIN은 테이블을 어떻게 합치길래, 조건을 `ON`에 쓸 때와 `WHERE`에 쓸 때 결과가 달라지는가?**
>
> 기준: MySQL 8.4 / PostgreSQL 18. 표준 SQL 동작이라 다른 DB도 같습니다.

## 1. 핵심 개념

JOIN을 "두 테이블을 옆으로 붙이는 것"으로 이해하면 절반은 맞고 절반은 틀립니다. 정확하게는 **행과 행을 짝짓고, 짝을 못 찾은 행을 어떻게 처리할지 정하는 연산**입니다.

PostgreSQL 문서는 LEFT OUTER JOIN을 이렇게 정의합니다. "먼저 inner join을 수행합니다. 그다음 T2의 어떤 행과도 조인 조건을 만족하지 못한 T1의 각 행에 대해, T2 컬럼을 NULL로 채운 조인 행을 추가합니다." ([Table Expressions](https://www.postgresql.org/docs/current/queries-table-expressions.html))

정의에 두 단계가 들어 있는 게 보입니까. **짝짓기가 먼저고, 낙오된 행을 되살리는 게 나중입니다.** 이 순서를 모르면 다음이 설명되지 않습니다.

> 회원별 결제 완료 주문을 뽑으려고 `LEFT JOIN`을 쓰고 `WHERE o.status = 'PAID'`를 붙였습니다. 주문이 하나도 없는 회원은 결과에서 사라집니다. LEFT JOIN을 썼는데 INNER JOIN이 나온 겁니다. 문법 에러도 없고, 개발 DB에서는 모든 회원에게 주문이 있어서 티도 안 납니다. 신규 가입자가 대시보드에서 통째로 누락되는 걸 며칠 뒤에 발견합니다.

또 하나. **JOIN은 행을 거르기만 하는 게 아니라 늘립니다.** `orders`에 `order_items`를 조인하면 주문 1건이 상품 개수만큼 복제됩니다. 이 상태로 `SUM(o.amount)`를 하면 금액이 상품 개수만큼 부풀어 오릅니다. 쿼리는 성공하고, 숫자는 틀립니다.

## 2. 구조 — 모든 JOIN은 3단계의 변형이다

조인 종류는 다섯 개지만 동작 원리는 하나입니다. 3단계로 쪼개면 전부 설명됩니다.

```
1단계  왼쪽 테이블 × 오른쪽 테이블  →  모든 조합 (카티션 곱)
2단계  ON 조건이 참인 조합만 남긴다  →  여기까지가 INNER JOIN
3단계  2단계에서 탈락한 "원본 행"을 NULL로 채워 되살린다  →  OUTER JOIN
```

**조인 종류는 3단계에서 누구를 되살리느냐만 다릅니다.**

| 종류 | 3단계에서 되살리는 대상 | 결과 행 수 |
|---|---|---|
| `CROSS JOIN` | 2단계 자체가 없음 | N × M |
| `INNER JOIN` | 없음 | 짝지어진 조합 수 |
| `LEFT JOIN` | 짝 못 찾은 왼쪽 행 | 최소 N |
| `RIGHT JOIN` | 짝 못 찾은 오른쪽 행 | 최소 M |
| `FULL JOIN` | 양쪽 다 | 최소 max(N, M) |

이 표에서 읽어야 할 건 오른쪽 열입니다. **INNER JOIN의 결과 행 수는 N보다 클 수도, 작을 수도 있습니다.** 짝이 없으면 줄고, 짝이 여럿이면 늡니다. "조인했더니 행이 몇 개 나올까"에 답하려면 조인 키의 카디널리티를 알아야 합니다.

옵티마이저는 실제로 카티션 곱을 만들지 않습니다. 3단계는 **결과가 무엇이어야 하는지를 정의하는 규칙**이지 실행 방법이 아닙니다. 실행 방법은 8절에서 다룹니다.

### 2-1. RIGHT JOIN을 쓰지 않는 이유

MySQL 문서는 이렇게 권합니다. "RIGHT JOIN은 LEFT JOIN과 대칭으로 동작합니다. DB 간 코드 이식성을 위해 RIGHT JOIN 대신 LEFT JOIN을 쓰기를 권장합니다." ([JOIN Clause](https://dev.mysql.com/doc/refman/8.4/en/join.html))

실무적인 이유가 하나 더 있습니다. `FROM a LEFT JOIN b LEFT JOIN c`는 위에서 아래로 읽으면 되지만, 중간에 RIGHT가 섞이면 기준 테이블이 어디인지 매번 되짚어야 합니다. 3개 이상 조인에서 특히 그렇습니다. MySQL은 hash join을 적용할 때 RIGHT JOIN을 내부적으로 LEFT JOIN으로 다시 쓰기까지 합니다 ([Hash Join Optimization](https://dev.mysql.com/doc/refman/8.4/en/hash-joins.html)).

**RIGHT JOIN이 필요하면 테이블 순서를 뒤집어서 LEFT JOIN으로 바꿉니다.** 결과는 같습니다.

### 2-2. MySQL에는 FULL OUTER JOIN이 없다

MySQL은 `FULL OUTER JOIN` 문법을 지원하지 않습니다. 필요하면 LEFT JOIN 결과와 "오른쪽에만 있는 행"을 `UNION ALL`로 붙입니다.

```sql
-- MySQL에서 FULL OUTER JOIN 흉내내기
SELECT u.id AS user_id, o.id AS order_id
  FROM users u LEFT JOIN orders o ON o.user_id = u.id
UNION ALL
SELECT u.id, o.id
  FROM users u RIGHT JOIN orders o ON o.user_id = u.id
 WHERE u.id IS NULL;   -- 왼쪽에서 이미 나온 행을 제외
```

두 번째 쿼리의 `WHERE u.id IS NULL`이 핵심입니다. 이게 없으면 짝지어진 행이 두 번 나옵니다. `UNION`(중복 제거)을 쓰면 이 조건 없이도 되지만, 정렬 비용이 붙고 원래 데이터에 있던 중복 행까지 사라집니다.

## 3. 흐름

### 3-1. 코드로 보는 구성

```sql
CREATE TABLE users (
    id   BIGINT      PRIMARY KEY,
    name VARCHAR(50) NOT NULL
);

CREATE TABLE orders (
    id      BIGINT      PRIMARY KEY,
    user_id BIGINT      NOT NULL,
    status  VARCHAR(20) NOT NULL,
    amount  INT         NOT NULL,
    KEY idx_orders_user_id (user_id)
);

INSERT INTO users VALUES (1, '김지원'), (2, '박서준'), (3, '이하늘');
INSERT INTO orders VALUES
    (100, 1, 'PAID',     10000),
    (101, 1, 'CANCELED',  5000),
    (102, 2, 'PAID',      7000);
-- 3번 회원은 주문이 없습니다. 이 행이 이 챕터의 리트머스지입니다.
```

### 3-2. 실행 흐름 — 같은 조건, 다른 위치

세 쿼리를 비교합니다. 조건은 전부 `status = 'PAID'` 하나입니다.

```sql
-- (A) INNER JOIN
SELECT u.name, o.id, o.status
  FROM users u
  JOIN orders o ON o.user_id = u.id
 WHERE o.status = 'PAID';

-- (B) LEFT JOIN + WHERE  ← 의도와 다르게 동작
SELECT u.name, o.id, o.status
  FROM users u
  LEFT JOIN orders o ON o.user_id = u.id
 WHERE o.status = 'PAID';

-- (C) LEFT JOIN + ON  ← 회원을 보존
SELECT u.name, o.id, o.status
  FROM users u
  LEFT JOIN orders o ON o.user_id = u.id
                    AND o.status = 'PAID';
```

(C)의 처리 순서를 3단계 규칙에 대입하면 이렇습니다.

```
1단계  users 3행 × orders 3행 = 9개 조합
2단계  ON (user_id 일치 AND status='PAID')  →  (김지원,100), (박서준,102)  2행
3단계  짝 못 찾은 왼쪽 행 되살리기  →  이하늘(NULL) 추가, 총 3행
```

(B)는 3단계까지 똑같이 간 뒤, **되살린 `이하늘(NULL)` 행에 `WHERE o.status = 'PAID'`를 적용합니다.** `NULL = 'PAID'`는 참이 아니므로 방금 되살린 행이 다시 탈락합니다.

| 쿼리 | 김지원/100 | 박서준/102 | 이하늘 | 행 수 |
|---|:---:|:---:|:---:|---:|
| (A) INNER | O | O | 없음 | 2 |
| (B) LEFT + WHERE | O | O | **없음** | 2 |
| (C) LEFT + ON | O | O | NULL 행 | 3 |

**(A)와 (B)는 결과가 같습니다.** PostgreSQL 문서가 짚는 지점이 이겁니다. "ON에 놓인 제약은 조인 전에, WHERE에 놓인 제약은 조인 후에 처리됩니다. inner join에서는 상관없지만 outer join에서는 크게 다릅니다."

## 4. 특징

### 4-1. 언제 무엇을 쓰는가

판단 기준은 하나입니다. **"오른쪽에 데이터가 없는 왼쪽 행이 결과에 나와야 하는가?"**

| 상황 | 선택 |
|---|---|
| 주문 목록 + 주문한 회원 정보 (`orders` 기준) | `INNER JOIN` — FK NOT NULL이면 어차피 다 있음 |
| 회원 목록 + 최근 주문 (관리자 화면) | `LEFT JOIN` — 주문 없는 회원도 보여야 함 |
| 주문 + 적용된 쿠폰 (쿠폰은 선택) | `LEFT JOIN` — 쿠폰 없는 주문이 다수 |
| 주문했는데 배송 레코드가 없는 건 찾기 | `LEFT JOIN` + `WHERE 우측.id IS NULL` |

마지막 패턴은 MySQL 문서에도 실려 있는 안티 조인(anti-join) 관용구입니다.

```sql
-- 주문은 있는데 배송 레코드가 없는 건 (= 누락 데이터 탐지)
SELECT o.id
  FROM orders o
  LEFT JOIN shipments s ON s.order_id = o.id
 WHERE s.order_id IS NULL;
```

여기서 `WHERE`에 조건을 쓰는 건 실수가 아니라 의도입니다. "3단계에서 되살아난 행만 남긴다"는 뜻이니까요. **`WHERE 우측컬럼 IS NULL`은 LEFT JOIN에서 유일하게 의미가 있는 우측 조건입니다.** 나머지 우측 조건은 전부 `ON`으로 가야 합니다.

`IS NULL`을 검사할 컬럼은 조인 키나 PK처럼 **NOT NULL이 보장된 컬럼**으로 고릅니다. 원래 NULL이 들어갈 수 있는 컬럼을 쓰면 "짝이 없어서 NULL"과 "짝은 있는데 값이 NULL"을 구분하지 못합니다.

### 4-2. 트레이드오프

**LEFT JOIN은 공짜가 아닙니다.** 옵티마이저 입장에서 INNER JOIN은 테이블 순서를 자유롭게 바꿔도 되지만, OUTER JOIN은 기준 테이블이 고정됩니다. 선택지가 줄어드니 더 나쁜 실행 계획이 나올 수 있습니다. MySQL이 조건만 맞으면 LEFT JOIN을 INNER JOIN으로 되돌리는 최적화를 하는 이유가 이겁니다 (8절).

그래서 원칙은 이렇습니다. **기본은 INNER JOIN, "없는 행도 보여야 한다"는 요구사항이 실제로 있을 때만 LEFT JOIN.** "혹시 몰라서" LEFT JOIN을 쓰는 습관은 성능과 정확성을 동시에 갉아먹습니다.

## 5. 예제 — 집계가 부풀어 오르는 쿼리

주문별로 상품 개수와 총 결제액을 뽑는 화면입니다. 주문 하나에 상품 여러 개, 쿠폰 여러 개가 붙을 수 있습니다.

### 5-1. 클린하지 않은 코드 ❌

```sql
-- 주문 100번: 상품 3개, 쿠폰 2개
SELECT o.id,
       o.amount,
       COUNT(i.id)    AS item_count,
       SUM(o.amount)  AS total_amount
  FROM orders o
  LEFT JOIN order_items   i ON i.order_id = o.id
  LEFT JOIN order_coupons c ON c.order_id = o.id
 GROUP BY o.id, o.amount;
```

`item_count`가 3이 아니라 **6**으로 나옵니다. `total_amount`도 결제액의 6배입니다.

원인은 2절의 1단계입니다. 조인 후 중간 결과는 상품 3행 × 쿠폰 2행 = **6행**이고, `orders`의 `amount` 값이 6번 복제된 뒤 합산됩니다. 이걸 팬아웃(fan-out)이라고 부릅니다. 자식 테이블이 하나뿐일 때는 정상으로 보이다가, 두 번째 자식 테이블을 조인하는 순간 조용히 틀어집니다.

### 5-2. 개선한 코드 ✔️

방법 1 — 집계를 먼저 끝내고 그 결과를 조인합니다.

```sql
SELECT o.id,
       o.amount,
       COALESCE(i.item_count, 0)     AS item_count,
       COALESCE(c.discount_sum, 0)   AS discount_sum
  FROM orders o
  LEFT JOIN (SELECT order_id, COUNT(*) AS item_count
               FROM order_items GROUP BY order_id) i ON i.order_id = o.id
  LEFT JOIN (SELECT order_id, SUM(amount) AS discount_sum
               FROM order_coupons GROUP BY order_id) c ON c.order_id = o.id;
```

각 서브쿼리가 `order_id`당 1행이므로 팬아웃이 발생하지 않습니다. `GROUP BY`도 필요 없어집니다.

방법 2 — 자식 테이블이 하나뿐이라면 `DISTINCT`로 막을 수 있습니다.

```sql
SELECT o.id, COUNT(DISTINCT i.id) AS item_count
  FROM orders o
  LEFT JOIN order_items i ON i.order_id = o.id
 GROUP BY o.id;
```

다만 `COUNT(DISTINCT ...)`는 중복 제거 비용이 붙고, **`SUM`에는 이 방법이 통하지 않습니다.** 같은 금액이 두 번 나오면 하나로 합쳐져 버리기 때문입니다. `SUM`이 필요하면 방법 1을 씁니다.

## 6. 실무에서 찾아보는 JOIN — 옵티마이저는 내 JOIN을 바꾼다

내가 쓴 조인 종류가 그대로 실행되지 않습니다. 공식 문서로 확인된 두 가지입니다.

**MySQL — LEFT JOIN을 INNER JOIN으로 되돌립니다.** `WHERE`에 우측 테이블에 대한 null-rejected 조건(NULL이 들어가면 거짓이 되는 조건)이 있으면 outer join을 inner join으로 변환합니다. 테이블 순서를 자유롭게 정하기 위해서입니다 ([Outer Join Optimization](https://dev.mysql.com/doc/refman/8.4/en/outer-join-optimization.html)).

3-2절의 (B)가 정확히 이 케이스입니다. **(B)가 (A)와 같은 결과인 건 우연이 아니라 옵티마이저가 실제로 (A)로 바꿔서 실행하기 때문입니다.** `EXPLAIN`을 떠보면 LEFT JOIN이 사라진 계획이 나옵니다.

**MySQL — 조인 알고리즘은 hash join입니다.** hash join은 8.0.18에서 inner join용으로 도입됐고, 8.0.20부터 block nested loop 알고리즘이 제거되면서 이전에 BNL이 쓰이던 자리를 전부 hash join이 차지했습니다 ([Changes in MySQL 8.0.20](https://dev.mysql.com/doc/relnotes/mysql/8.0/en/news-8-0-20.html)). `EXPLAIN` 출력에 `Using join buffer (hash join)`이 보이면 이겁니다.

**PostgreSQL — 조인 자체를 없애기도 합니다.** `enable_self_join_elimination`은 기본값이 `on`이고, "쿼리 트리를 분석해 셀프 조인을 의미가 같은 단일 스캔으로 대체하는 최적화"를 수행합니다 ([Query Planning](https://www.postgresql.org/docs/current/runtime-config-query.html)).

교훈은 하나입니다. **조인 종류는 "무엇을 원하는가"의 선언이지 "어떻게 실행하라"는 지시가 아닙니다.** 실행 방식이 궁금하면 추측하지 말고 `EXPLAIN`을 봅니다.

## 7. 관련된 개념과 비교 — JOIN vs EXISTS

"주문한 적 있는 회원"을 뽑는 두 방법입니다.

```sql
-- (a) JOIN + DISTINCT
SELECT DISTINCT u.* FROM users u JOIN orders o ON o.user_id = u.id;

-- (b) EXISTS
SELECT u.* FROM users u WHERE EXISTS (SELECT 1 FROM orders o WHERE o.user_id = u.id);
```

결과는 같지만 의미가 다릅니다. (a)는 주문 건수만큼 행을 만든 뒤 중복을 제거합니다. (b)는 **첫 번째 일치를 찾는 순간 멈춥니다.** 존재 여부만 필요하고 오른쪽 컬럼을 select하지 않는다면 (b)가 의도를 정확히 표현합니다.

**오른쪽 테이블의 컬럼이 결과에 필요하면 JOIN, 필터 조건으로만 쓰면 EXISTS.** 이 기준으로 나누면 `DISTINCT`를 붙일 일이 대부분 사라집니다. `SELECT DISTINCT`가 등장하는 조인 쿼리는 팬아웃을 뒤늦게 덮고 있는 경우가 많습니다.

## 8. 함정

**함정 1 — LEFT JOIN이 조용히 INNER JOIN이 된다**

- **증상**: LEFT JOIN을 썼는데 왼쪽 테이블의 일부 행이 결과에서 사라집니다. 주로 "데이터가 없는" 신규/비활성 레코드가 누락됩니다.
- **원인**: 우측 테이블 컬럼에 대한 조건을 `WHERE`에 뒀습니다. NULL로 되살아난 행이 `WHERE`에서 다시 탈락합니다. MySQL은 아예 INNER JOIN으로 변환해 실행합니다.
- **해법**: 우측 테이블 조건은 `ON` 절로 옮깁니다. 단 `WHERE 우측키 IS NULL`(안티 조인)은 예외입니다. 리뷰할 때는 `LEFT JOIN`과 `WHERE`가 한 쿼리에 있으면 우측 별칭이 `WHERE`에 등장하는지부터 봅니다.

**함정 2 — 집계값이 정수배로 부풀어 오른다**

- **증상**: `SUM`, `COUNT` 결과가 실제보다 2배, 3배로 나옵니다. 자식 테이블을 하나만 조인할 때는 멀쩡하다가 하나를 더 추가한 뒤부터 틀립니다.
- **원인**: 1:N 조인이 부모 행을 N번 복제합니다. 자식 테이블 두 개를 조인하면 N×M번 복제됩니다.
- **해법**: 집계 대상 자식 테이블이 둘 이상이면 각각 서브쿼리로 미리 집계한 뒤 조인합니다(5-2절 방법 1). 검증은 간단합니다. **`GROUP BY` 없이 조인만 한 상태에서 `COUNT(*)`를 세보고, 부모 테이블 행 수와 다르면 팬아웃이 있는 겁니다.**

**함정 3 — `NOT IN` 서브쿼리가 빈 결과를 낸다**

- **증상**: `WHERE id NOT IN (SELECT user_id FROM orders)`가 아무 행도 반환하지 않습니다. 눈으로 보면 해당하는 행이 분명히 있습니다.
- **원인**: 서브쿼리 결과에 NULL이 하나라도 섞이면 `NOT IN` 전체가 참이 되지 못합니다. NULL과의 비교는 참도 거짓도 아닌 unknown이기 때문입니다 ([Subquery Expressions](https://www.postgresql.org/docs/current/functions-subquery.html)).
- **해법**: 안티 조인은 `NOT EXISTS`나 `LEFT JOIN ... WHERE 우측키 IS NULL`로 씁니다. 둘 다 NULL에 영향받지 않습니다. `NOT IN`을 유지해야 한다면 서브쿼리에 `WHERE user_id IS NOT NULL`을 명시합니다.

**함정 4 — `NATURAL JOIN`은 스키마 변경에 폭발한다**

- **증상**: 잘 돌던 쿼리가 컬럼 추가 배포 직후 결과가 줄어들거나 0행이 됩니다. 쿼리는 한 글자도 안 바꿨습니다.
- **원인**: `NATURAL JOIN`은 **양쪽에 이름이 같은 모든 컬럼**으로 조인 조건을 만듭니다. 두 테이블에 `created_at`이나 `status` 같은 컬럼이 새로 생기면 그것까지 조인 조건에 들어갑니다. PostgreSQL 문서도 "NATURAL은 상당히 위험하다"고 명시합니다.
- **해법**: `NATURAL JOIN`을 쓰지 않습니다. `USING (order_id)`는 나열한 컬럼만 쓰므로 안전하고, `ON`은 가장 명시적입니다.

## 9. 참고자료

- [MySQL 8.4 — JOIN Clause](https://dev.mysql.com/doc/refman/8.4/en/join.html)
- [MySQL 8.4 — Outer Join Optimization](https://dev.mysql.com/doc/refman/8.4/en/outer-join-optimization.html)
- [MySQL 8.4 — Hash Join Optimization](https://dev.mysql.com/doc/refman/8.4/en/hash-joins.html)
- [PostgreSQL 18 — Table Expressions](https://www.postgresql.org/docs/current/queries-table-expressions.html)
- [PostgreSQL 18 — Query Planning](https://www.postgresql.org/docs/current/runtime-config-query.html)
- 실행 계획 읽는 법은 `07-database/02-explain-plan`에서 다룹니다.

# INNER, LEFT, RIGHT JOIN이 실제로 하는 일

## 1. 핵심 개념: INNER/LEFT/RIGHT JOIN이란?

- **INNER JOIN**: 두 테이블 모두에 매칭되는 행만 반환합니다.
- **LEFT JOIN**: 왼쪽 테이블의 모든 행을 반환합니다. 오른쪽에 매칭이 없으면 그 컬럼은 `NULL`로 채웁니다.
- **RIGHT JOIN**: 방향만 반대인 LEFT JOIN입니다. 오른쪽 테이블의 모든 행을 보존합니다.

> **"주문이 한 번도 없는 고객이 몇 명인지" 세는 쿼리에 INNER JOIN을 쓰면, 그 고객들이 결과에서 조용히 빠집니다.** JOIN을 "테이블 합치는 문법" 정도로만 알면 이런 실수를 코드 리뷰에서도 못 잡습니다.

## 2. 구조

- LEFT/RIGHT는 **어느 쪽 테이블의 행을 전부 보존할지**를 결정합니다. 매칭이 안 된 반대쪽 컬럼은 전부 `NULL`이 됩니다.
- INNER JOIN은 보존 대상이 없습니다. 양쪽 다 있어야만 결과에 남습니다.
- `customers`(왼쪽)와 `orders`(오른쪽)를 조인한다고 하면, LEFT JOIN은 "주문이 없는 고객도 포함", RIGHT JOIN은 "고객 정보가 없는 주문도 포함"이라는 뜻입니다.

### 2-1. 선택적 확장 지점

- 기본 동작은 옵티마이저가 테이블 통계를 보고 조인 순서를 알아서 정하는 것입니다.
- MySQL은 `STRAIGHT_JOIN`으로 `FROM`절에 적힌 순서대로 조인하도록 강제할 수 있습니다. 옵티마이저가 통계 부족 등으로 비효율적인 순서를 고를 때 선택적으로 씁니다.

## 3. 흐름

### 3-1. 예제 테이블과 쿼리

```sql
-- customers: id, name
-- orders: id, customer_id, amount

SELECT c.name, o.amount
FROM customers c
INNER JOIN orders o ON c.id = o.customer_id;
```

```sql
SELECT c.name, o.amount
FROM customers c
LEFT JOIN orders o ON c.id = o.customer_id;
```

샘플 데이터가 다음과 같다고 하면:

```
customers: (1, '김철수'), (2, '이영희'), (3, '박민수')
orders:    (100, customer_id=1, amount=5000), (101, customer_id=1, amount=3000)
```

`박민수`(3)와 `이영희`(2)는 주문이 없습니다.

### 3-2. 실행 결과

```
INNER JOIN 결과:
김철수 | 5000
김철수 | 3000
(이영희, 박민수는 없음 — 매칭되는 주문이 없어서 제외)

LEFT JOIN 결과:
김철수 | 5000
김철수 | 3000
이영희 | NULL
박민수 | NULL
(고객 전체가 보존되고, 주문 없는 고객은 amount가 NULL)
```

## 4. 특징

### 4-1. 사용 시기

- **INNER JOIN**: 두 테이블 모두에 존재해야 의미 있는 데이터를 조회할 때 (예: 실제 발생한 주문 내역)
- **LEFT JOIN**: 기준이 되는 쪽(왼쪽) 전체를 봐야 할 때 (예: 전체 고객과 각자의 주문 여부)
- **RIGHT JOIN**: 실무에서 거의 쓰지 않습니다. `FROM` 절의 테이블 순서만 바꾸면 LEFT JOIN으로 똑같이 표현되기 때문입니다.

### 4-2. 장점

- 여러 테이블의 데이터를 쿼리 한 번으로 결합할 수 있습니다. 애플리케이션 코드에서 테이블마다 따로 조회해 메모리에서 합칠 필요가 없습니다.

### 4-3. 단점 / 트레이드오프

- 조인하는 테이블이 늘어날수록 결과 행 수가 곱연산으로 늘어날 수 있습니다. 1:N 관계를 여러 번 조인하면 특히 그렇습니다. (10장 함정 참고)
- 조인 개수가 많아지면 옵티마이저가 고르는 실행계획을 예측하기 어려워집니다.

## 5. 예제: LEFT JOIN인데 결과가 INNER JOIN처럼 나온다

### 5-1. 클린하지 않은 코드 ❌

```sql
-- ❌ LEFT JOIN을 썼지만 WHERE절에서 오른쪽 테이블 컬럼으로 필터링
SELECT c.name, o.amount
FROM customers c
LEFT JOIN orders o ON c.id = o.customer_id
WHERE o.amount > 0;
```

- 주문이 없는 고객은 `o.amount`가 `NULL`입니다. `NULL > 0`은 `TRUE`도 `FALSE`도 아니라 결과에서 제외됩니다.
- 결국 LEFT JOIN을 썼는데도 INNER JOIN과 똑같은 결과가 나옵니다.

### 5-2. 조건을 ON절로 옮긴 코드 ✔️

```sql
-- ✅ 오른쪽 테이블 조건은 ON절에 둔다 — LEFT JOIN의 "전체 보존" 의미가 유지된다
SELECT c.name, o.amount
FROM customers c
LEFT JOIN orders o ON c.id = o.customer_id AND o.amount > 0;
```

- `ON`절의 조건은 조인이 일어나기 전에 적용됩니다. 조인 자체는 실패해도 왼쪽 행은 그대로 남고, 오른쪽 컬럼만 `NULL`이 됩니다.

## 6. 명시적 JOIN 문법 원칙

- SQL-92 이후 표준은 조인을 `JOIN ... ON`으로 명시하도록 정했습니다. 그 이전 방식인 콤마 조인은 조인 조건과 필터 조건이 전부 `WHERE`절에 섞입니다.

### 6-1. 원칙을 어긴 코드 ❌

```sql
-- ❌ 콤마 조인 — 조인 조건을 WHERE에 빠뜨리기 쉽다
SELECT c.name, o.amount
FROM customers c, orders o
WHERE c.id = o.customer_id;
```

- 실수로 `WHERE` 조건을 빠뜨리면 두 테이블의 모든 행 조합(카티션 곱)이 그대로 반환됩니다. 문법 오류가 아니라서 알아채기 어렵습니다.

### 6-2. 원칙을 지킨 코드 ✔️

```sql
-- ✅ 명시적 JOIN — 조인 조건과 필터 조건이 분리된다
SELECT c.name, o.amount
FROM customers c
JOIN orders o ON c.id = o.customer_id;
```

- 조인 조건(`ON`)과 필터 조건(`WHERE`)이 문법적으로 분리돼 있어서, 조인 조건을 빠뜨리면 문법 오류가 나거나 최소한 코드 리뷰에서 눈에 띕니다.

## 7. 확장 지점 응용하기 — STRAIGHT_JOIN

### 7-1. 클린하지 않은 코드 ❌

```sql
-- ❌ 옵티마이저에게 순서를 맡긴다 — 통계가 부정확하면 큰 테이블부터 스캔할 수 있다
SELECT c.name, o.amount
FROM customers c
JOIN orders o ON c.id = o.customer_id;
```

### 7-2. STRAIGHT_JOIN을 적용한 코드 ✔️

```sql
-- ✅ FROM절에 적은 순서(customers 먼저)대로 조인하도록 강제한다
SELECT STRAIGHT_JOIN c.name, o.amount
FROM customers c
JOIN orders o ON c.id = o.customer_id;
```

- 옵티마이저가 통계 부족이나 특수한 데이터 분포 때문에 비효율적인 순서를 고를 때만 씁니다. 항상 쓰면 오히려 옵티마이저의 최적화를 막습니다.

## 8. 실무에서 찾아보는 JOIN

- Spring Data JPA의 `JOIN FETCH` — 연관된 엔티티를 별도 쿼리 없이 한 번에 즉시 로딩합니다.
- QueryDSL의 `.join()`, `.leftJoin()` — SQL의 JOIN 문법을 Java 코드로 표현합니다.

## 9. 관련된 개념과 비교

### 9-1. LEFT JOIN VS RIGHT JOIN

**유사점**

- 둘 다 OUTER JOIN입니다. 매칭 안 된 쪽 컬럼은 `NULL`로 채웁니다.

**차이점**

- LEFT JOIN은 왼쪽(`FROM` 바로 뒤) 테이블 전체를 보존합니다.
- RIGHT JOIN은 오른쪽(`JOIN` 뒤) 테이블 전체를 보존합니다.
- `A RIGHT JOIN B`는 테이블 순서를 바꾼 `B LEFT JOIN A`와 결과가 같습니다. 그래서 실무에서는 가독성을 위해 LEFT JOIN 하나로 통일하고 RIGHT JOIN은 거의 쓰지 않습니다.

## 10. 함정

**FULL OUTER JOIN이 MySQL에 없다**

- **증상**: `FULL OUTER JOIN` 문법을 쓰면 `syntax error near 'FULL'`이 발생합니다.
- **원인**: MySQL 8.0은 FULL OUTER JOIN을 네이티브로 지원하지 않습니다. LEFT JOIN과 RIGHT JOIN만 지원합니다.
- **해법**: LEFT JOIN과 RIGHT JOIN 결과를 `UNION`으로 합쳐 에뮬레이션합니다.

```sql
-- MySQL에서 FULL OUTER JOIN 흉내내기
SELECT c.name, o.amount
FROM customers c
LEFT JOIN orders o ON c.id = o.customer_id
UNION
SELECT c.name, o.amount
FROM customers c
RIGHT JOIN orders o ON c.id = o.customer_id;
```

**여러 개의 LEFT JOIN이 집계 값을 부풀린다**

- **증상**: 고객별 주문 합계와 리뷰 개수를 한 쿼리로 같이 구했더니 `SUM(주문금액)`이 실제보다 훨씬 크게 나옵니다.
- **원인**: 고객 1명에 주문 2건, 리뷰 3건이 있으면 `customers LEFT JOIN orders LEFT JOIN reviews`는 2×3=6행을 만듭니다. 그 상태로 주문 금액을 `SUM`하면 같은 주문 금액이 리뷰 개수만큼 중복 합산됩니다.
- **해법**: 집계는 조인 전에 서브쿼리로 미리 끝내거나, 두 집계를 별도 쿼리로 나눠 조회한 뒤 애플리케이션에서 합칩니다.

## 11. 참고자료

- [MySQL 8.0 Reference Manual — JOIN Clause](https://dev.mysql.com/doc/refman/8.0/en/join.html)
- [MySQL 8.0 Reference Manual — Outer Join Optimization](https://dev.mysql.com/doc/refman/8.0/en/outer-join-optimization.html)
- `daily/day04-null-traps.md` — NULL이 만드는 예상치 못한 버그
- `07-database/05-index-not-used` — 조인 컬럼에 인덱스가 있는데 안 타는 경우들

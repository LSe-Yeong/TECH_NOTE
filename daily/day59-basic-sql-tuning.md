# 인덱스를 추가하기 전에 쿼리에서 먼저 고칠 것은 무엇인가

> 이 문서가 답할 질문: **느린 쿼리를 받았을 때, 인덱스를 만들기 전에 쿼리문 자체에서 고칠 수 있는 것은 무엇이고 어디서부터는 인덱스가 답인가?**
>
> 기준: MySQL 8.4 LTS / InnoDB, PostgreSQL 18 (2026년 10월 확인). `day17-why-index.md`의 인덱스 기초, `day29-explain-plan.md`의 실행계획 읽기, `day47-index-not-used.md`의 "인덱스가 있는데 안 타는 경우"를 전제로 합니다.

## 1. 핵심 개념 — 인덱스는 경로를 바꾸고, 쿼리는 작업량을 정합니다

느린 쿼리를 받으면 반사적으로 `CREATE INDEX`부터 떠오릅니다. 가끔 맞습니다. 그런데 이 둘은 서로 다른 레버입니다.

- **인덱스**는 "필요한 행에 어떻게 도달할 것인가"를 바꿉니다. 접근 경로를 바꿉니다.
- **쿼리문**은 "애초에 몇 행을 만지고, 각 행에서 몇 바이트를 꺼내고, 중간 결과를 몇 번 쌓을 것인가"를 정합니다. 작업량 자체를 정합니다.

작업량이 과한 쿼리에 인덱스를 붙이면, 과한 작업을 조금 더 빠른 경로로 할 뿐입니다. 100만 행을 임시 테이블에 쌓고 정렬한 뒤 10행을 돌려주는 쿼리는, 그 100만 행을 모으는 경로가 빨라져도 여전히 100만 행을 정렬합니다.

> 순서를 거꾸로 하면 인덱스가 쌓입니다. 인덱스는 만든 뒤 테이블과 계속 동기화해야 하므로 모든 쓰기에 비용을 더합니다. PostgreSQL 문서는 여기에 더해 인덱스가 HOT(heap-only tuple) 최적화를 막을 수 있다고 적고, "거의 또는 전혀 쓰이지 않는 인덱스는 제거해야 한다"고 못 박습니다([Introduction to Indexes](https://www.postgresql.org/docs/18/indexes-intro.html)). MySQL 8.4에서는 이 비용이 8.0보다 더 즉각적으로 드러납니다. 세컨더리 인덱스 쓰기를 모아서 처리하던 change buffering의 기본값이 `all`에서 `none`으로 바뀌었기 때문입니다([InnoDB Startup Options and System Variables](https://dev.mysql.com/doc/refman/8.4/en/innodb-parameters.html)).

이 챕터는 문제해결형입니다. 증상(느리다) → 원인(쿼리가 만드는 작업량) → 해법(쿼리 재작성) 순으로 갑니다. 인덱스 설계는 그다음입니다.

---

## 2. 고치기 전에 재는 것 — 추정이 아니라 실측

`EXPLAIN`의 `rows`는 옵티마이저의 **추정치**입니다. 통계가 낡으면 실제와 자릿수가 다릅니다. 쿼리를 고칠지 인덱스를 만들지는 실측으로 갈립니다.

### 2-1. MySQL — `EXPLAIN ANALYZE`

문서는 이 명령을 "문장을 실행하고, `EXPLAIN` 출력과 함께 타이밍 및 반복자 기반 정보를 만들어 **옵티마이저의 예상이 실제 실행과 얼마나 맞았는지** 보여준다"고 설명합니다([EXPLAIN Statement](https://dev.mysql.com/doc/refman/8.4/en/explain.html)). 8.4 기준 제약도 같은 문서에 있습니다.

- 항상 `TREE` 포맷입니다. `FORMAT=TRADITIONAL`이나 `FORMAT=JSON`은 에러입니다.
- `SELECT`, 멀티 테이블 `UPDATE`·`DELETE`, `TABLE` 문에만 쓸 수 있습니다.
- 실제로 실행되므로 길면 `KILL QUERY`로 끊습니다.

```sql
EXPLAIN ANALYZE
SELECT o.id, o.total_amount
FROM orders o
WHERE o.member_id = 10234
ORDER BY o.ordered_at DESC
LIMIT 20;
```

출력의 각 줄에서 세 쌍을 봅니다.

1. `rows=` (추정) vs `actual ... rows=` (실측) → 벌어져 있으면 통계·카디널리티 문제입니다.
2. `loops=` → 1이 아니면 그 반복자가 N번 돌았다는 뜻입니다. 조인 안쪽에서 `loops`가 크면 거기가 병목입니다.
3. `actual time=a..b` → `a`는 첫 행까지, `b`는 마지막 행까지입니다. 둘의 차이가 크면 행을 계속 뽑고 있는 구간입니다.

### 2-2. PostgreSQL — `EXPLAIN (ANALYZE)`

PostgreSQL 18부터 **`ANALYZE`를 쓰면 버퍼 정보가 자동으로 포함**됩니다. 문서는 `BUFFERS` 항목에 "Buffers information is automatically included when `ANALYZE` is used"라고 적습니다([EXPLAIN](https://www.postgresql.org/docs/18/sql-explain.html)). 17까지는 `BUFFERS`를 직접 붙여야 했습니다.

같은 문서가 경고하는 함정이 하나 있습니다. `ANALYZE`를 쓰면 문장이 **실제로 실행**됩니다. `SELECT` 결과는 버려지지만 다른 부수효과는 그대로 일어납니다. 그래서 DML에는 이렇게 씁니다.

```sql
BEGIN;
EXPLAIN ANALYZE DELETE FROM order_items WHERE order_id = 998877;
ROLLBACK;
```

### 2-3. 판정 기준

실측을 얻었으면 질문 하나로 갈립니다. **반환한 행 수에 비해 읽은 행 수가 몇 배인가?**

| 읽은 행 : 반환한 행 | 1차 의심 | 먼저 할 일 |
|---|---|---|
| 비슷한데 느리다 | 행당 비용 (컬럼 폭, 랜덤 I/O) | 쿼리 — 컬럼을 줄입니다 |
| 수십~수백 배 | 중간 결과를 만들고 버린다 | 쿼리 — 필터·중복 제거 위치를 옮깁니다 |
| 읽은 행 자체가 테이블 전체 | 필터를 못 쓰고 있다 | `day47` 확인 후 인덱스 |

---

## 3. 쿼리에서 먼저 고치는 다섯 가지

### 3-1. 필터를 `HAVING`에 둔 쿼리

`WHERE`와 `HAVING`은 쓰는 자리만 다른 게 아닙니다. 적용 시점이 다릅니다. MySQL 문서는 "`HAVING` 절은 거의 마지막에, 클라이언트로 결과를 보내기 직전에 **아무 최적화 없이** 적용된다"고 쓰고, 이어서 "`WHERE` 절에 있어야 할 항목에 `HAVING`을 쓰지 말라"고 명시합니다([SELECT Statement](https://dev.mysql.com/doc/refman/8.4/en/select.html)).

```sql
-- ❌ 2024년 주문만 필요한데, 전체 기간을 그룹핑한 뒤 버립니다
SELECT member_id, SUM(total_amount) AS amount
FROM orders
GROUP BY member_id
HAVING MIN(ordered_at) >= '2024-01-01';
```

```sql
-- ✔️ 그룹을 만들기 전에 행을 버립니다
SELECT member_id, SUM(total_amount) AS amount
FROM orders
WHERE ordered_at >= '2024-01-01'
GROUP BY member_id;
```

두 쿼리는 의미가 완전히 같지는 않습니다(앞은 "첫 주문이 2024년 이후인 회원", 뒤는 "2024년 이후 주문"). 바로 그게 핵심입니다. **`HAVING`에 조건을 쓰는 순간 "그룹 전체"가 판정 단위가 되고, 그러려면 그룹을 다 만들어야 합니다.** 집계값을 쓰지 않는 조건이 `HAVING`에 있다면 그건 거의 항상 `WHERE`로 옮길 수 있는 조건입니다.

### 3-2. `SELECT *`

`SELECT *`는 편의 문제가 아니라 실행계획 문제입니다. 세 군데에서 비용이 생깁니다.

**(1) 커버링 인덱스를 무력화합니다.** MySQL이 `Extra`에 `Using index`를 띄우는 조건은 "실제 행을 읽는 추가 탐색 없이 인덱스 트리의 정보만으로 컬럼 정보를 얻는 경우"이고, 문서는 "쿼리가 단일 인덱스에 포함된 컬럼만 사용할 때 이 전략을 쓸 수 있다"고 규정합니다([EXPLAIN Output Format](https://dev.mysql.com/doc/refman/8.4/en/explain-output.html)). 컬럼을 하나라도 더 요구하면 그 전략이 사라지고 행마다 테이블 조회가 붙습니다(`day41-covering-index.md`).

**(2) 큰 컬럼을 따라옵니다.** `TEXT`/`BLOB` 본문은 행 밖에 저장되므로, 안 쓰는 본문 컬럼 하나가 행당 추가 I/O가 됩니다.

**(3) 깨지는 시점이 숨습니다.** 컬럼이 추가되면 애플리케이션이 모르는 사이에 전송량이 늘어납니다.

```sql
-- ❌ 목록 화면에 본문이 필요 없는데 같이 끌고 옵니다
SELECT * FROM articles WHERE board_id = 7 ORDER BY created_at DESC LIMIT 20;

-- ✔️ (board_id, created_at, id, title) 인덱스가 있으면 테이블을 안 봅니다
SELECT id, title, created_at FROM articles
WHERE board_id = 7 ORDER BY created_at DESC LIMIT 20;
```

### 3-3. 중복을 만들고 지우는 쿼리 — `JOIN` + `DISTINCT`

"이 상품을 한 번이라도 주문한 회원"을 뽑을 때 가장 흔한 형태입니다.

```sql
-- ❌ 조인으로 행을 부풀린 다음 DISTINCT로 접습니다
SELECT DISTINCT m.id, m.name
FROM members m
JOIN orders o ON o.member_id = m.id
JOIN order_items oi ON oi.order_id = o.id
WHERE oi.product_id = 5512;
```

회원 한 명이 그 상품을 30번 샀으면 중간 결과에 30행이 생기고, `DISTINCT`가 그 29행을 지웁니다. 지우는 데도 비용이 듭니다. `EXPLAIN`에 `Using temporary`가 보이면 그 비용이 보이는 겁니다.

```sql
-- ✔️ 존재 여부만 묻습니다. 첫 매치에서 멈춥니다
SELECT m.id, m.name
FROM members m
WHERE EXISTS (
    SELECT 1 FROM orders o
    JOIN order_items oi ON oi.order_id = o.id
    WHERE o.member_id = m.id AND oi.product_id = 5512
);
```

**"서브쿼리는 조인보다 느리다"는 말은 지금 기준으로 틀렸습니다.** MySQL은 이런 형태를 세미조인으로 변환합니다. 문서는 세미조인을 "바깥 행이 서브쿼리에서 하나 이상 매치될 때 그 행을 최대 한 번만 반환하는 준비 단계 변환"으로 정의하고, 중복을 만들었다 지우는 낭비를 피하는 것이 목적이라고 설명합니다([Optimizing IN and EXISTS Subquery Predicates with Semijoin Transformations](https://dev.mysql.com/doc/refman/8.4/en/semijoins.html)). 같은 문서가 정리하는 조건이 실무에서 중요합니다.

- `IN`, `= ANY`, `EXISTS`가 `WHERE`/`ON`의 최상위에 있어야 합니다(`AND`의 항으로는 가능).
- 8.0.16부터 `EXISTS`는 동등한 `IN`처럼 다뤄집니다. 상관 서브쿼리도 됩니다.
- 8.0.17부터 `NOT IN`/`NOT EXISTS`는 안티조인으로 변환될 수 있습니다. 단, 비교 대상이 nullable이면 대부분 적용되지 않습니다.
- 서브쿼리에 `HAVING`, 집계 함수, `LIMIT`가 있으면 변환되지 않습니다. `UNION`도 안 됩니다.

마지막 줄이 함정입니다. 서브쿼리에 `LIMIT`나 집계를 하나 넣는 순간 세미조인이 통째로 꺼집니다. `NOT IN`에 nullable 컬럼을 쓰면 안티조인도 못 받습니다. `NOT IN`보다 `NOT EXISTS`를 쓰는 이유가 하나 더 생기는 지점입니다.

### 3-4. 파생 테이블을 머티리얼라이즈하게 만드는 구조

`FROM` 절 서브쿼리(파생 테이블), 뷰, CTE를 옵티마이저는 두 가지로 처리합니다. **바깥 쿼리에 병합(merge)하거나, 임시 테이블로 머티리얼라이즈(materialize)하거나**입니다. MySQL 문서는 병합을 선호하는 이유를 "불필요한 머티리얼라이즈를 피하고, 바깥 쿼리의 조건을 파생 테이블로 밀어 넣을 수 있게 해서 더 효율적인 계획을 만든다"로 설명합니다([Optimizing Derived Tables, View References, and Common Table Expressions](https://dev.mysql.com/doc/refman/8.4/en/derived-table-optimization.html)).

`derived_merge`는 기본으로 켜져 있지만, **서브쿼리에 다음이 있으면 병합이 막힙니다.** 같은 문서의 목록입니다.

집계·윈도우 함수 · `DISTINCT` · `GROUP BY` · `HAVING` · `LIMIT` · `UNION`/`UNION ALL` · 셀렉트 리스트의 서브쿼리 · 사용자 변수 대입

병합이 막히면 조건을 안으로 못 밀어 넣습니다. 그래서 이런 쿼리가 나옵니다.

```sql
-- ❌ 안쪽에서 전체 회원을 집계한 뒤, 바깥에서 한 명만 고릅니다
SELECT * FROM (
    SELECT member_id, COUNT(*) AS cnt
    FROM orders GROUP BY member_id
) AS s
WHERE s.member_id = 10234;
```

`GROUP BY`가 있으니 병합되지 않고, `member_id = 10234`는 전체 집계가 끝난 뒤에야 적용됩니다.

```sql
-- ✔️ 조건을 안으로 직접 넣습니다
SELECT member_id, COUNT(*) AS cnt
FROM orders
WHERE member_id = 10234
GROUP BY member_id;
```

CTE라고 다르지 않습니다. `WITH`로 쓰면 읽기는 좋아지지만, 안에 `GROUP BY`가 있으면 똑같이 머티리얼라이즈됩니다. 재귀 CTE는 문서상 **항상** 머티리얼라이즈됩니다. 가독성을 위해 CTE로 쪼갰는데 느려졌다면 거의 이 경로입니다.

### 3-5. `ORDER BY ... LIMIT`에서 정렬을 다시 하게 만드는 구조

`LIMIT`은 세다가 멈추는 기능이 아니라 실행계획을 바꾸는 요소입니다. 문서는 "`LIMIT row_count`를 `ORDER BY`와 함께 쓰면 전체를 정렬하는 대신 정렬 결과의 첫 `row_count`행을 찾는 즉시 정렬을 멈춘다. **인덱스로 정렬이 이뤄지면 이것은 매우 빠르다**"라고 쓰고, 반대 경우를 이렇게 적습니다 — "filesort를 해야 한다면, `LIMIT` 없이 쿼리에 매치되는 모든 행을 고른 뒤 대부분 또는 전부를 정렬하고 나서 첫 `row_count`행을 찾는다"([LIMIT Query Optimization](https://dev.mysql.com/doc/refman/8.4/en/limit-optimization.html)).

즉 `LIMIT 20`이 붙어 있어도 `Using filesort`가 떠 있으면 20행이 아니라 **매치된 전부**를 정렬합니다. 그래서 `ORDER BY` 컬럼 목록을 인덱스가 따라갈 수 있는 모양으로 두는 일이 인덱스 추가보다 먼저입니다(`day35-composite-index-order.md`).

같은 문서가 짚는 두 번째 함정은 정확성 쪽입니다. **`LIMIT`이 실행계획을 바꾸므로, 정렬 키가 같은 행들의 순서는 `LIMIT`이 있을 때와 없을 때 달라질 수 있습니다.** 해법은 `ORDER BY`에 유니크한 컬럼을 덧붙이는 것입니다.

```sql
-- ❌ ordered_at이 같은 주문이 여러 건이면 페이지마다 순서가 흔들립니다
SELECT id, total_amount FROM orders ORDER BY ordered_at DESC LIMIT 20;

-- ✔️ 동점을 깨는 키를 둡니다
SELECT id, total_amount FROM orders ORDER BY ordered_at DESC, id DESC LIMIT 20;
```

큰 `OFFSET`은 또 다른 문제입니다. `LIMIT 20 OFFSET 100000`은 10만 행을 읽어서 버리고 20행을 줍니다. 이건 쿼리 재작성으로 푸는 문제가 맞지만 범위가 커서 `day15-pagination-api.md`에서 따로 다룹니다.

---

## 4. 여기서부터는 인덱스가 답입니다

쿼리 재작성이 만능이라는 뜻은 아닙니다. 아래 두 경우는 쿼리를 어떻게 써도 인덱스 없이는 안 풀립니다.

**(1) 조인 조건에 쓸 인덱스가 없는 경우.** MySQL 8.4는 "가능할 때마다 기본적으로 해시 조인을 사용"하며, 특히 "각 조인에 동등 조인 조건이 있고 조인 조건에 적용할 인덱스가 없는 모든 쿼리"에 씁니다([Hash Join Optimization](https://dev.mysql.com/doc/refman/8.4/en/hash-joins.html)). 해시 조인은 중첩 루프보다 훨씬 낫지만 공짜는 아닙니다. 같은 문서가 선을 긋습니다 — "해시 조인의 메모리 사용량은 `join_buffer_size`로 제어할 수 있으며, 해시 조인은 이 양보다 많은 메모리를 쓸 수 없다." 넘으면 디스크 파일을 쓰고, 파일 수가 `open_files_limit`를 넘으면 조인이 실패할 수도 있습니다. 조인 키에 인덱스를 거는 편이 낫습니다.

**(2) 선택도가 높은 필터가 풀스캔으로 처리되는 경우.** 100만 행에서 10행을 고르는 조건인데 `type: ALL`이면 쿼리 문제가 아닙니다. 다만 그 전에 `day47-index-not-used.md`를 확인합니다. 인덱스가 **없어서** 못 타는 것과 **있는데** 안 타는 것은 해법이 다릅니다.

판단 순서를 한 줄로 쓰면 이렇습니다.

> 실측 → 반환 행 대비 읽은 행이 과한가 → (과함) 3장의 다섯 가지로 작업량을 줄인다 → (여전히 풀스캔) 인덱스를 설계한다

---

## 5. 하나로 합쳐 보기 — 느린 통계 쿼리

"2024년 이후에 VIP 등급으로 주문한 회원별 주문 금액 상위 20명" 화면이 8초 걸립니다. 쿼리는 이렇게 생겼습니다.

```sql
-- ❌ 3장의 다섯 가지가 전부 들어 있습니다
SELECT DISTINCT s.*
FROM (
    SELECT m.*, SUM(o.total_amount) AS amount
    FROM members m
    JOIN orders o ON o.member_id = m.id
    JOIN order_items oi ON oi.order_id = o.id
    GROUP BY m.id
) AS s
WHERE s.grade = 'VIP'
HAVING MIN(s.amount) > 0
ORDER BY s.amount DESC
LIMIT 20;
```

무엇이 일어나는지 순서대로 보면 이렇습니다.

1. `order_items` 조인이 주문 한 건을 상품 개수만큼 부풀립니다 → `SUM`이 부풀려집니다(정확성 버그).
2. 파생 테이블에 `GROUP BY`가 있어 병합이 막힙니다 → 전체 회원을 집계한 임시 테이블이 만들어집니다.
3. `grade = 'VIP'` 필터가 그 임시 테이블 **바깥**에 있어, 집계가 끝난 뒤에야 적용됩니다.
4. `HAVING`은 집계가 필요 없는 조건인데 마지막에, 최적화 없이 적용됩니다.
5. `s.*`가 커버링 가능성을 지우고, `DISTINCT`가 임시 테이블을 하나 더 만듭니다.
6. `LIMIT 20`이 있지만 정렬 대상은 20행이 아니라 집계된 회원 전부입니다.

인덱스를 아무리 붙여도 2·4·5·6은 그대로입니다. 쿼리를 고칩니다.

```sql
-- ✔️ 필터를 안으로, 중복을 만들지 않고, 필요한 컬럼만
SELECT m.id, m.name, s.amount
FROM (
    SELECT o.member_id, SUM(o.total_amount) AS amount
    FROM orders o
    WHERE o.ordered_at >= '2024-01-01'
      AND EXISTS (
          SELECT 1 FROM members m2
          WHERE m2.id = o.member_id AND m2.grade = 'VIP'
      )
    GROUP BY o.member_id
    ORDER BY amount DESC
    LIMIT 20
) AS s
JOIN members m ON m.id = s.member_id
ORDER BY s.amount DESC;
```

바뀐 것은 네 가지입니다.

- `order_items` 조인을 지웠습니다. 금액 합계에 필요 없는 테이블이었고, 이게 `DISTINCT`의 원인이었습니다.
- `grade` 필터와 기간 필터를 집계 **전**으로 옮겼습니다. 집계 대상 행 수가 먼저 줄어듭니다.
- 상위 20명을 먼저 확정한 뒤 `members`를 조인합니다. 회원 정보 조회가 전체가 아니라 20번으로 줄어듭니다.
- `m.*`를 실제 쓰는 컬럼으로 바꿨습니다.

안쪽 파생 테이블에 `GROUP BY`와 `LIMIT`이 있으므로 이 서브쿼리는 여전히 머티리얼라이즈됩니다. 그래도 괜찮습니다. **머티리얼라이즈 자체가 나쁜 게 아니라, 조건을 못 밀어 넣은 채 큰 중간 결과를 만드는 게 나쁜 것입니다.** 여기서 임시 테이블은 20행입니다.

여기까지 하고도 느리면 그때 인덱스입니다. 이 쿼리가 원하는 모양은 `orders(ordered_at, member_id, total_amount)` 정도입니다.

---

## 6. 함정

**① `EXPLAIN`만 보고 "인덱스 탔네"로 끝냅니다**

- **증상**: `key` 컬럼에 인덱스 이름이 찍혀 있는데 쿼리는 여전히 느립니다.
- **원인**: `key`는 "이 인덱스로 접근한다"일 뿐 몇 행을 읽는지가 아닙니다. 범위가 넓으면 인덱스를 타고도 수십만 행을 읽습니다. `rows`는 추정이라 통계가 낡으면 작게 나옵니다.
- **해법**: `EXPLAIN ANALYZE`로 `actual ... rows`와 `loops`를 봅니다. 추정과 실측이 자릿수로 벌어지면 통계부터 갱신합니다(MySQL `ANALYZE TABLE`, PostgreSQL `ANALYZE`).

**② 가독성을 위해 CTE로 쪼갰더니 느려집니다**

- **증상**: 한 덩어리 쿼리를 `WITH` 여러 개로 나눴을 뿐인데 응답 시간이 몇 배가 됩니다.
- **원인**: CTE 안의 `GROUP BY`·`DISTINCT`·`LIMIT`이 병합을 막아 머티리얼라이즈됩니다. 바깥 `WHERE`가 안으로 못 들어갑니다(3-4).
- **해법**: 실행계획에 머티리얼라이즈가 보이면 바깥 조건을 CTE 안으로 직접 복사해 넣습니다. 가독성이 필요하면 CTE는 두되 필터는 중복해서 씁니다.

**③ 서브쿼리를 전부 조인으로 바꾸다가 결과가 틀립니다**

- **증상**: "서브쿼리는 느리다"는 말에 `EXISTS`를 `JOIN`으로 바꿨더니 집계값이 부풀었습니다.
- **원인**: `EXISTS`는 존재 여부라 바깥 행이 한 번만 나오지만, `JOIN`은 매치된 수만큼 행이 늘어납니다. 뒤에 `SUM()`이 있으면 조용히 틀린 숫자가 나옵니다.
- **해법**: 존재 여부만 필요하면 `EXISTS`를 유지합니다. 옵티마이저가 세미조인으로 바꿔줍니다. 굳이 조인으로 쓸 거면 안쪽을 먼저 집계해서 1:1로 만든 다음 조인합니다.

**④ 인덱스를 만들어보고 아니면 지우면 된다고 생각합니다**

- **증상**: 테이블 하나에 인덱스가 10개 넘게 쌓이고 쓰기 지연이 올라갑니다.
- **원인**: 검증 없이 추가한 인덱스가 지워지지 않습니다. MySQL 8.4는 change buffering 기본값이 `none`이라 세컨더리 인덱스 쓰기 비용이 바로 드러나고, PostgreSQL은 인덱스가 HOT 업데이트를 막습니다(1장 출처).
- **해법**: 추가 전에 3장을 먼저 소진합니다. 추가했으면 사용량을 확인하고 안 쓰이면 지웁니다(MySQL `sys.schema_unused_indexes`, PostgreSQL `pg_stat_user_indexes`).

---

## 7. 참고자료

- [EXPLAIN Statement — MySQL 8.4](https://dev.mysql.com/doc/refman/8.4/en/explain.html)
- [EXPLAIN Output Format — MySQL 8.4](https://dev.mysql.com/doc/refman/8.4/en/explain-output.html)
- [SELECT Statement (HAVING) — MySQL 8.4](https://dev.mysql.com/doc/refman/8.4/en/select.html)
- [Optimizing IN and EXISTS Subquery Predicates with Semijoin Transformations — MySQL 8.4](https://dev.mysql.com/doc/refman/8.4/en/semijoins.html)
- [Optimizing Derived Tables, View References, and CTEs — MySQL 8.4](https://dev.mysql.com/doc/refman/8.4/en/derived-table-optimization.html)
- [LIMIT Query Optimization — MySQL 8.4](https://dev.mysql.com/doc/refman/8.4/en/limit-optimization.html)
- [Hash Join Optimization — MySQL 8.4](https://dev.mysql.com/doc/refman/8.4/en/hash-joins.html)
- [InnoDB Startup Options and System Variables — MySQL 8.4](https://dev.mysql.com/doc/refman/8.4/en/innodb-parameters.html)
- [EXPLAIN — PostgreSQL 18](https://www.postgresql.org/docs/18/sql-explain.html)
- [Introduction to Indexes — PostgreSQL 18](https://www.postgresql.org/docs/18/indexes-intro.html)
- 관련 챕터: `day17-why-index.md`, `day29-explain-plan.md`, `day35-composite-index-order.md`, `day41-covering-index.md`, `day47-index-not-used.md`, `day15-pagination-api.md`

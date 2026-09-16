# 복합 인덱스의 컬럼 순서는 무엇이 정하는가

> 이 문서가 답할 질문: **같은 컬럼 세 개로 인덱스를 만드는데, 왜 순서에 따라 결과가 달라지는가. 그리고 그 순서는 무엇을 기준으로 정하는가?**
>
> 기준: MySQL 8.4 LTS / InnoDB, 대조로 PostgreSQL 18 (2026년 9월 확인). `day23-btree-index.md`의 B+Tree 구조와 `day29-explain-plan.md`의 실행계획 읽는 법을 전제로 합니다.

## 1. 핵심 개념 — 복합 인덱스는 컬럼 여러 개가 아니라 이어붙인 키 하나입니다

`INDEX (shop_id, status, ordered_at)`을 만들면 인덱스 세 개가 생기는 게 아닙니다. **`(shop_id, status, ordered_at)`이라는 튜플 하나를 키로 쓰는 B+Tree 한 개**가 생깁니다. 리프는 이 튜플의 사전식 순서로 정렬됩니다. `shop_id`로 먼저 줄을 세우고, 같으면 `status`로, 그것도 같으면 `ordered_at`으로 줄을 세웁니다.

여기서 모든 것이 따라 나옵니다. `shop_id`를 모르면 특정 `status` 값이 인덱스 어디에 있는지 알 방법이 없습니다. `status = 'PAID'`인 레코드는 인덱스 전체에 상점 수만큼 흩어져 있기 때문입니다.

> 인덱스를 추가했고 `EXPLAIN`의 `key` 칸에 그 인덱스 이름이 찍히는데도 쿼리가 느리다면, 십중팔구 순서 문제입니다. 순서를 잘못 정하면 인덱스가 **안 쓰이는 게 아니라 덜 쓰입니다.** 안 쓰이면 풀 스캔이 찍히니 바로 보이지만, 덜 쓰이면 계획서상으로는 멀쩡해 보입니다. 이쪽이 훨씬 찾기 어렵습니다.

MySQL의 복합 인덱스는 최대 16개 컬럼까지 가능합니다([Multiple-Column Indexes](https://dev.mysql.com/doc/refman/8.4/en/multiple-column-indexes.html)). 다만 실제로 그렇게 쓰는 일은 없습니다. 이유는 8절에서 다룹니다.

## 2. 왼쪽 접두사 규칙 — 쓸 수 있는 조합은 정해져 있습니다

인덱스 `(shop_id, status, ordered_at)`에 대해 옵티마이저가 탐색 범위를 좁히는 데 쓸 수 있는 조합은 **왼쪽부터 끊기지 않고 이어지는 접두사**뿐입니다.

| 조건 | 인덱스로 좁혀지는가 |
|---|---|
| `shop_id = ?` | 예 |
| `shop_id = ? AND status = ?` | 예 |
| `shop_id = ? AND status = ? AND ordered_at = ?` | 예 |
| `status = ?` | 아니오 |
| `status = ? AND ordered_at = ?` | 아니오 |
| `shop_id = ? AND ordered_at = ?` | `shop_id`까지만 |

마지막 줄이 중요합니다. **중간 컬럼을 건너뛰면 그 앞까지만 쓰입니다.** `ordered_at` 조건은 탐색 범위를 좁히는 데 기여하지 못하고, 좁혀진 구간 안에서 걸러내는 역할만 합니다(3-2 참고).

`WHERE` 절에 쓴 순서는 아무 상관이 없습니다. `WHERE status = 'PAID' AND shop_id = 7`로 써도 옵티마이저가 알아서 맞춰 씁니다. 순서가 의미를 갖는 곳은 `WHERE` 절이 아니라 **인덱스 정의**입니다.

### 2-1. 실제로 어디까지 썼는지는 `key_len`이 알려줍니다

`EXPLAIN`의 `key` 칸은 "이 인덱스를 썼다"까지만 말합니다. **몇 번째 컬럼까지 썼는지는 `key_len`에 나옵니다.**

```sql
EXPLAIN
SELECT order_id FROM orders
WHERE shop_id = 7 AND status = 'PAID';
```

`shop_id`가 `BIGINT NOT NULL`(8바이트), `status`가 `VARCHAR(20) NOT NULL`에 `utf8mb4`(20×4 + 길이 2바이트 = 82바이트)라면 `key_len`은 90이 나와야 정상입니다. 8만 찍혔다면 `status` 조건이 인덱스 탐색에 안 쓰이고 있다는 뜻입니다. 인덱스 이름만 보고 넘어가면 놓치는 정보입니다.

## 3. 등치는 통과시키고 범위는 문을 닫습니다

접두사 규칙만으로는 순서를 정할 수 없습니다. 실무 쿼리에는 등치 조건과 범위 조건이 섞여 들어오기 때문입니다. 여기에 두 번째 규칙이 붙습니다.

MySQL 문서는 B-Tree 인덱스의 탐색 구간(interval)을 만들 때 이렇게 동작한다고 명시합니다. **`=`, `<=>`, `IS NULL`은 다음 키 파트로 넘어가지만, `>`, `<`, `>=`, `<=`, `!=`, `BETWEEN`, 선행 와일드카드 없는 `LIKE`가 나오면 거기서 멈추고 그 뒤 키 파트는 구간 구성에 쓰이지 않습니다**([Range Optimization](https://dev.mysql.com/doc/refman/8.4/en/range-optimization.html)).

문서가 드는 예를 우리 테이블로 옮기면 이렇습니다.

```sql
-- INDEX (shop_id, ordered_at, status)
WHERE shop_id = 7 AND ordered_at >= '2026-09-01' AND status = 'PAID'
```

- `shop_id = 7` → 등치. 다음으로 진행합니다.
- `ordered_at >= '2026-09-01'` → 범위. **여기서 닫힙니다.**
- `status = 'PAID'` → 구간을 만드는 데 쓰이지 않습니다.

결과 탐색 구간은 `(7, '2026-09-01', -inf)`부터 `(7, +inf, +inf)`까지입니다. 9월 이후 그 상점의 주문 전부를 인덱스에서 읽고, 그중 `PAID`만 고릅니다. 주문의 대부분이 `PAID`가 아니라면 대부분이 헛읽기입니다.

### 3-1. 닫힌 뒤의 컬럼도 완전히 무용하지는 않습니다

구간을 못 좁힐 뿐, `status` 값은 인덱스 리프 안에 들어 있습니다. 그래서 InnoDB는 클러스터형 인덱스로 행을 가지러 가기 전에 리프에서 먼저 걸러낼 수 있습니다. Index Condition Pushdown입니다(`day23-btree-index.md` 6절).

구분이 필요합니다.

- **구간을 좁힌다** = 인덱스에서 읽을 레코드 수 자체가 줄어듭니다.
- **리프에서 걸러낸다** = 읽을 레코드 수는 그대로고, 행을 가지러 가는 랜덤 접근만 줄어듭니다.

후자도 이득이지만 전자가 훨씬 큽니다. `EXPLAIN`의 `Extra`에 `Using index condition`이 보인다면 지금 후자에 기대고 있다는 신호입니다.

### 3-2. `IN()`은 등치 쪽입니까 범위 쪽입니까

실무에서 가장 자주 걸리는 애매한 경우입니다. `status IN ('PAID', 'SHIPPED')`은 뒤 컬럼으로 문을 열어줄까요.

문서가 **다음 키 파트로 진행하는 연산자**로 명시한 것은 `=`, `<=>`, `IS NULL` 셋입니다. 동시에 `IN()`은 단일 키 파트의 범위 조건을 구성하는 연산자 목록에도 들어 있습니다. 두 설명을 합치면 `IN()`은 **등치 구간 여러 개의 합집합**으로 전개되는 형태입니다. `IN ('PAID', 'SHIPPED')`이면 `status = 'PAID'`인 구간과 `status = 'SHIPPED'`인 구간 두 개가 만들어지고, 각 구간 안에서는 등치처럼 동작합니다.

그래서 목록이 짧으면 등치에 가깝고, 길어지면 구간이 그 개수만큼 늘어 비용이 달라집니다. 값 수백 개짜리 `IN`을 선행 컬럼에 두는 설계는 이 관점에서 다시 봐야 합니다. <!-- TODO: MySQL 8.4에서 IN 목록 길이에 따른 구간 전개 임계값이 존재하는지, 옵티마이저 트레이스로 확인 필요 -->

참고로 MongoDB의 ESR 문서는 같은 문제에 대해 **`$in` 요소가 201개 미만이면 등치처럼, 그 이상이면 범위처럼 다룬다**고 임계값까지 못박아 둡니다. MongoDB 한정 규칙이지만, `IN`이 어느 쪽인지가 엔진 구현에 달린 문제라는 걸 보여줍니다.

## 4. 그래서 순서 규칙은 등치 → 정렬 → 범위입니다

2절과 3절을 합치면 규칙이 하나 나옵니다.

```
1순위  등치(=) 조건으로 들어오는 컬럼
2순위  ORDER BY에 쓰는 컬럼
3순위  범위 조건으로 들어오는 컬럼
```

MongoDB 문서가 이걸 **ESR(Equality, Sort, Range) 규칙**이라는 이름으로 정리해 두었습니다([ESR Guideline](https://www.mongodb.com/docs/manual/tutorial/equality-sort-range-guideline/)). MongoDB 문서지만 근거는 B-Tree 인덱스의 성질이라 RDB에도 그대로 적용됩니다.

**등치가 맨 앞인 이유**는 3절입니다. 등치만이 다음 컬럼으로 문을 열어줍니다. 등치 컬럼끼리는 서로 순서가 중요하지 않습니다.

**정렬이 범위보다 앞인 이유**가 덜 직관적입니다. 인덱스 `(shop_id, ordered_at)`에서 `shop_id`가 등치로 고정되면, 그 구간 안의 레코드는 전부 `ordered_at` 순서로 읽힙니다. MySQL 문서가 명시하는 사례입니다 — `WHERE key_part1 = constant ORDER BY key_part2`는 정렬 없이 처리됩니다([ORDER BY Optimization](https://dev.mysql.com/doc/refman/8.4/en/order-by-optimization.html)).

그런데 정렬 컬럼 앞에 범위 컬럼이 끼면 이 성질이 깨집니다. 범위 조건은 여러 값을 훑으므로, 그 뒤 컬럼은 구간 전체로 보면 정렬돼 있지 않습니다. 정렬이 필요하면 `filesort`가 붙습니다.

**예외도 문서에 있습니다.** 범위 조건이 아주 선택적이라면(예: `order_id BETWEEN` 으로 10건만 남는 경우) 범위를 정렬보다 앞에 두는 편이 나을 수 있습니다. 10건 정렬하는 비용이 구간을 넓게 잡는 비용보다 싸기 때문입니다. **규칙보다 데이터 분포가 셉니다.**

## 5. 예제 — 순서만 바꿔서 달라지는 쿼리

상점별 주문 목록 API를 가정합니다. 최근 주문부터 20건씩 보여줍니다.

```sql
CREATE TABLE orders (
    order_id     BIGINT       NOT NULL AUTO_INCREMENT,
    shop_id      BIGINT       NOT NULL,
    status       VARCHAR(20)  NOT NULL,
    total_amount INT          NOT NULL,
    ordered_at   DATETIME(6)  NOT NULL,
    PRIMARY KEY (order_id)
) ENGINE = InnoDB;

SELECT order_id, total_amount, ordered_at
FROM orders
WHERE shop_id = 7
  AND status = 'PAID'
  AND ordered_at >= '2026-09-01 00:00:00'
ORDER BY ordered_at DESC
LIMIT 20;
```

### 5-1. 잘못 고른 순서 ❌

```sql
-- ❌ 범위·정렬에 쓰는 컬럼을 맨 앞에 뒀습니다
CREATE INDEX idx_orders_bad ON orders (ordered_at, shop_id, status);
```

"날짜로 자르는 게 제일 많이 거르니까 앞에"라는 판단입니다. 실제로는 이렇게 됩니다.

1. `ordered_at >= '2026-09-01'`이 첫 키 파트의 범위 조건 → 여기서 구간이 닫힙니다.
2. `shop_id`, `status`는 구간을 못 좁힙니다. 리프에서 걸러낼 뿐입니다.
3. 9월 이후 **전 상점의 모든 주문**을 인덱스에서 읽습니다.

`EXPLAIN`은 `type=range`, `key=idx_orders_bad`로 멀쩡해 보입니다. `rows`만 수십만입니다.

### 5-2. ESR을 적용한 순서 ✔️

```sql
-- ✔️ 등치(shop_id, status) → 정렬 겸 범위(ordered_at)
CREATE INDEX idx_orders_shop_status_time ON orders (shop_id, status, ordered_at);
```

1. `shop_id = 7 AND status = 'PAID'` 두 등치가 모두 구간을 좁힙니다.
2. 좁혀진 구간 안은 `ordered_at` 순서입니다.
3. `ordered_at >= ...`로 시작점을 잡고, 리프 연결 리스트를 역방향으로 20건 읽고 끝냅니다.

`filesort`가 사라지고 `LIMIT 20`이 실제로 20건만 읽는 형태가 됩니다. 이 쿼리에서는 정렬 컬럼과 범위 컬럼이 같은 `ordered_at`이라 ESR의 S와 R이 한 자리로 합쳐졌습니다. 흔한 형태이고, 순서 고민이 가장 쉽게 풀리는 경우입니다.

### 5-3. 정렬 컬럼과 범위 컬럼이 다르면 하나는 포기합니다

```sql
-- WHERE shop_id = ? AND ordered_at >= ?  ORDER BY total_amount DESC
```

여기서는 S(`total_amount`)와 R(`ordered_at`)이 다른 컬럼입니다. 하나만 고를 수 있습니다.

| 인덱스 | 얻는 것 | 잃는 것 |
|---|---|---|
| `(shop_id, total_amount, ordered_at)` | `filesort` 없음 | 날짜로 구간을 못 좁힘 |
| `(shop_id, ordered_at, total_amount)` | 날짜로 구간을 좁힘 | `filesort` 발생 |

기본값은 위쪽(ESR)입니다. `LIMIT`이 작으면 정렬된 순서로 읽다가 조건 맞는 20건을 채우는 즉시 끝낼 수 있기 때문입니다. 날짜 범위가 아주 좁아서 남는 행이 수십 건 수준이라면 아래쪽이 낫습니다. **둘 다 만들어 `EXPLAIN ANALYZE`로 비교하는 게 정답입니다.** 여기서부터는 규칙이 아니라 측정의 영역입니다.

## 6. 흔한 오답 — "카디널리티 높은 컬럼을 앞으로"

가장 널리 퍼진 규칙이고, 조건부로만 맞습니다.

이 규칙이 성립하는 범위는 **모든 조건이 등치이고 정렬이 없을 때**입니다. 그때는 더 잘게 나누는 컬럼이 앞에 있어야 구간이 빨리 좁혀집니다. 그런데 조건 전체가 등치이고 정렬이 없는 목록 쿼리는 실무에 거의 없습니다.

범위나 정렬이 섞이는 순간 규칙이 뒤집힙니다. 5-1이 그 예입니다. `ordered_at`은 마이크로초 단위라 카디널리티가 압도적으로 높지만, 범위 조건으로 들어오기 때문에 맨 앞에 두면 최악입니다. **카디널리티는 컬럼의 속성이고, 순서를 정하는 건 쿼리가 그 컬럼을 어떤 연산자로 쓰느냐입니다.**

카디널리티 숫자 자체도 조심해서 봐야 합니다. `SHOW INDEX`나 `information_schema.STATISTICS`의 `Cardinality`는 실측값이 아니라 **인덱스 페이지를 무작위로 뽑아 추정한 값**입니다. InnoDB는 이를 random dive라고 부르고, 표본 페이지 수를 정하는 `innodb_stats_persistent_sample_pages`의 기본값은 20입니다([Configuring Persistent Optimizer Statistics](https://dev.mysql.com/doc/refman/8.4/en/innodb-persistent-stats.html)). 수억 행 테이블을 20페이지로 추정합니다. 값이 치우친 컬럼에서는 크게 빗나갈 수 있습니다.

정확한 분포가 필요하면 직접 셉니다.

```sql
SELECT status, COUNT(*) FROM orders GROUP BY status;
```

`PAID`가 전체의 92%라면, `status`는 앞에 둬도 거의 못 거릅니다. 카디널리티(고유값 개수)가 아니라 **실제로 들어오는 값의 선택도**가 판단 기준입니다.

## 7. 엔진이 접두사 규칙을 깨주는 경우 — 스킵 스캔

접두사 규칙에는 예외가 생겼습니다. 선행 컬럼에 조건이 없어도 인덱스를 쓰는 **스킵 스캔**입니다. 원리는 단순합니다. 선행 컬럼의 고유값을 하나씩 뽑아 등치 조건을 스스로 만들어 붙이고, 그 각각에 대해 범위 스캔을 반복합니다.

MySQL은 8.0.13부터 지원합니다. 조건이 꽤 빡빡합니다([Range Optimization](https://dev.mysql.com/doc/refman/8.4/en/range-optimization.html)).

- 단일 테이블 쿼리여야 합니다. 조인에는 안 쓰입니다.
- `GROUP BY`, `DISTINCT`가 없어야 합니다.
- **쿼리가 참조하는 컬럼이 전부 그 인덱스 안에 있어야 합니다.** 사실상 커버링 인덱스 조건입니다. `SELECT *`면 탈락입니다.
- 건너뛸 선행 컬럼의 조건은 없거나 상수 등치(`IN()` 포함)여야 합니다.
- `optimizer_switch`의 `skip_scan` 플래그로 제어하고 기본값은 켜짐입니다.
- `EXPLAIN`의 `Extra`에 `Using index for skip scan`으로 찍힙니다.

PostgreSQL은 18에서 B-Tree 스킵 스캔이 들어갔습니다([PostgreSQL 18 Release Notes](https://www.postgresql.org/docs/release/18.0/)). 원래 PostgreSQL은 비선행 컬럼 조건으로도 인덱스를 쓸 수는 있었습니다. 다만 인덱스를 통째로 훑는 방식이라 문서가 "가장 비효율적"이라고 표현하던 경로였고, 스킵 스캔이 이걸 개선합니다([Multicolumn Indexes](https://www.postgresql.org/docs/18/indexes-multicolumn.html)).

**중요한 건 이득 조건입니다.** 두 엔진 모두 건너뛸 컬럼의 **고유값이 적을 때만** 이득입니다. `shop_id`처럼 값이 수만 개인 컬럼을 건너뛰면 수만 번의 서브 스캔이 됩니다. 그래서 스킵 스캔은 잘못된 컬럼 순서를 고쳐주는 기능이 아닙니다. `is_deleted`나 `region_code`처럼 값이 서너 개뿐인 선행 컬럼 때문에 인덱스를 못 쓰던 특정 형태를 구제해주는 기능입니다.

## 8. 복합 인덱스 하나 vs 단일 인덱스 둘

"`shop_id` 인덱스랑 `status` 인덱스를 따로 만들면 알아서 합쳐 쓰지 않나요?"

합쳐 쓰는 기능은 있습니다. **인덱스 머지(index merge)** 의 intersection 알고리즘입니다. 다만 적용 조건이 좁습니다. 각 조건이 **해당 인덱스의 모든 키 파트를 덮는 등치 조건**이거나, InnoDB에서 **기본 키에 대한 범위 조건**이어야 합니다([Index Merge Optimization](https://dev.mysql.com/doc/refman/8.4/en/index-merge-optimization.html)). `EXPLAIN`에 `type=index_merge`, `Extra`에 `Using intersect(...)`로 찍힙니다.

조건을 만족해도 인덱스 머지는 두 인덱스를 각각 스캔하고 결과를 교집합으로 맞춰야 합니다. 복합 인덱스 하나는 한 번의 탐색으로 끝납니다. **같이 들어오는 조건이라면 복합 인덱스 하나가 거의 항상 낫습니다.**

반대 방향의 함정도 있습니다. 컬럼을 계속 붙이고 싶어집니다. PostgreSQL 문서는 여기에 대해 분명하게 씁니다 — **멀티컬럼 인덱스는 아껴 쓰고, 컬럼 세 개를 넘는 인덱스는 용도가 아주 특수하지 않은 한 도움이 되는 경우가 드뭅니다**([Multicolumn Indexes](https://www.postgresql.org/docs/18/indexes-multicolumn.html)). 컬럼이 늘수록 키가 길어져 팬아웃이 줄고, 쓰기 비용이 늘고, 그 순서를 활용하는 쿼리는 더 좁아집니다.

## 9. 함정

### 함정 1 — `EXPLAIN`에 인덱스 이름이 찍히는데 느립니다

- **증상**: `key`에 의도한 인덱스가 찍혔고 `type`도 `range`인데 응답이 느립니다. `rows`가 수십만입니다.
- **원인**: 범위 조건이 앞쪽 키 파트에 있어서 그 뒤 등치 조건이 구간을 못 좁히고 있습니다(3절). 인덱스는 "쓰이고" 있지만 첫 컬럼까지만 쓰입니다.
- **해법**: `key_len`을 계산해서 몇 번째 컬럼까지 쓰였는지 확인합니다(2-1). 기대보다 짧으면 등치 컬럼을 앞으로 옮긴 인덱스를 새로 만들고 `EXPLAIN ANALYZE`로 `rows`와 실제 시간을 비교합니다. 옛 인덱스는 새 인덱스가 실제로 선택되는 걸 확인한 뒤 지웁니다.

### 함정 2 — `WHERE`는 인덱스를 타는데 `Using filesort`가 붙습니다

- **증상**: 조건 절은 잘 좁혀지는데 `Extra`에 `Using filesort`가 있습니다. `LIMIT 20`인데도 전체를 다 읽습니다.
- **원인**: 정렬 컬럼이 범위 컬럼 뒤에 있습니다. 범위 조건이 걸린 컬럼 이후로는 구간 전체가 정렬 상태를 유지하지 못합니다(4절).
- **해법**: 정렬 컬럼을 범위 컬럼 앞으로 옮깁니다(ESR). 정렬 방향이 섞여 있다면(`grade ASC, score DESC`) 내림차순 인덱스가 필요합니다 — `day23-btree-index.md` 5절에서 다뤘습니다. 옮긴 뒤에도 `filesort`가 남으면 정렬 컬럼 앞의 모든 컬럼이 등치로 고정돼 있는지 확인합니다. 하나라도 빠지면 정렬 순서가 성립하지 않습니다.

### 함정 3 — 인덱스가 계속 늘어나고 쓰기가 느려집니다

- **증상**: 테이블에 인덱스가 여덟 개입니다. `INSERT` 배치 시간이 꾸준히 늘고, 새 인덱스를 추가할 때마다 조금씩 더 느려집니다.
- **원인**: 요청이 들어올 때마다 그 쿼리 전용 인덱스를 만들어 온 결과입니다. 특히 `(shop_id)`와 `(shop_id, status)`가 함께 있는 형태가 흔합니다. **앞쪽 것은 뒤쪽 것의 왼쪽 접두사라 완전히 중복입니다.** 쓰기 비용만 내고 있습니다.
- **해법**: 접두사 관계인 인덱스를 찾아 짧은 쪽을 지웁니다. MySQL sys 스키마의 `schema_redundant_indexes` 뷰로 후보를 뽑을 수 있습니다. <!-- TODO: 8.4에서의 뷰 이름·컬럼 구성 확인 필요 --> 지우기 전에 `performance_schema.table_io_waits_summary_by_index_usage`로 실제 사용 여부를 봅니다. 새 인덱스를 만들기 전에 **기존 인덱스에 컬럼을 하나 더 붙여 해결되는지부터** 검토하는 습관이 근본 대책입니다.

### 함정 4 — 로컬에서는 타는데 프로덕션에서 안 탑니다

- **증상**: 같은 쿼리, 같은 스키마인데 실행계획이 다릅니다. 프로덕션에서만 풀 스캔으로 떨어집니다.
- **원인**: 두 가지가 겹칩니다. 첫째, 옵티마이저 판단의 입력인 통계가 표본 추정이고 기본 표본은 20페이지입니다(6절). 둘째, 데이터 분포가 다릅니다. 로컬에서는 `status` 값이 고르게 분포한 더미 데이터지만 프로덕션에서는 92%가 한 값에 몰려 있습니다. 후자에서는 그 컬럼으로 구간을 좁혀도 남는 행이 거의 안 줄어서 옵티마이저가 풀 스캔이 싸다고 판단합니다. 실제로 그게 맞는 판단인 경우도 많습니다.
- **해법**: 먼저 `ANALYZE TABLE`로 통계를 갱신하고 계획이 바뀌는지 봅니다. 그래도 같다면 통계 문제가 아니라 분포 문제입니다. `GROUP BY`로 실제 분포를 확인하고, 선택도가 낮은 컬럼을 선두에서 빼거나 인덱스에서 아예 뺍니다. 통계 정밀도 자체가 부족하다면 `innodb_stats_persistent_sample_pages`를 올리는 선택지가 있습니다. 다만 `ANALYZE TABLE`이 그만큼 느려지므로 문서도 정확도와 실행 시간의 맞교환으로 설명합니다. **인덱스 힌트로 강제하는 건 마지막 수단입니다.** 데이터가 더 늘면 옵티마이저 판단이 맞았던 게 되는 경우가 있습니다.

## 10. 참고자료

- [MySQL 8.4 — Multiple-Column Indexes](https://dev.mysql.com/doc/refman/8.4/en/multiple-column-indexes.html) — 왼쪽 접두사 규칙, 최대 16컬럼
- [MySQL 8.4 — Range Optimization](https://dev.mysql.com/doc/refman/8.4/en/range-optimization.html) — 3절 구간 구성 규칙, 7절 스킵 스캔 조건
- [MySQL 8.4 — ORDER BY Optimization](https://dev.mysql.com/doc/refman/8.4/en/order-by-optimization.html) — 4절 정렬에 인덱스가 쓰이는 조건
- [MySQL 8.4 — Index Merge Optimization](https://dev.mysql.com/doc/refman/8.4/en/index-merge-optimization.html) — 8절 intersection 적용 조건
- [MySQL 8.4 — Configuring Persistent Optimizer Statistics](https://dev.mysql.com/doc/refman/8.4/en/innodb-persistent-stats.html) — 6절 random dive, 표본 20페이지
- [PostgreSQL 18 — Multicolumn Indexes](https://www.postgresql.org/docs/18/indexes-multicolumn.html) — 비선행 컬럼 조건의 비용, 컬럼 수 권고
- [PostgreSQL 18 Release Notes](https://www.postgresql.org/docs/release/18.0/) — B-Tree 스킵 스캔 도입
- [MongoDB — The ESR Guideline](https://www.mongodb.com/docs/manual/tutorial/equality-sort-range-guideline/) — 4절 등치·정렬·범위 순서와 그 예외
- `day23-btree-index.md` — B+Tree 구조, Index Condition Pushdown, 내림차순 인덱스
- `day29-explain-plan.md` — `type`·`rows`·`Extra` 읽는 순서, `EXPLAIN ANALYZE` 검증
- `day17-why-index.md` — 페이지 단위 비용, 풀 스캔이 이기는 구간

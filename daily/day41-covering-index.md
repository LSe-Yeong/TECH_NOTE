# 커버링 인덱스 — 인덱스를 타고도 남는 비용을 없애는 법

> 이 문서가 답할 질문: **인덱스를 제대로 탔는데도 느린 쿼리가 있습니다. 인덱스가 행의 위치를 찾아낸 다음에 남아 있는 비용은 무엇이고, 그걸 어떻게 없애는가?**
>
> 기준: MySQL 8.4 LTS / InnoDB, PostgreSQL 18 (2026년 9월 확인). `day23-btree-index.md`의 B+Tree 구조, `day35-composite-index-order.md`의 컬럼 순서, `day29-explain-plan.md`의 실행계획 읽는 법을 전제로 합니다.

## 1. 핵심 개념 — 인덱스 탐색은 일의 절반입니다

인덱스를 탄 쿼리가 하는 일은 사실 두 단계입니다.

```
1단계  인덱스에서 조건에 맞는 항목을 찾는다        ← 인덱스가 빠르게 해주는 부분
2단계  찾은 항목이 가리키는 "진짜 행"을 읽으러 간다  ← 아무도 이야기하지 않는 부분
```

2단계가 비용입니다. InnoDB의 세컨더리 인덱스 레코드에는 행의 물리 주소가 아니라 **기본 키 값**이 들어 있고, 엔진은 그 값으로 클러스터형 인덱스를 다시 탐색해서 행을 가져옵니다([InnoDB Index Types](https://dev.mysql.com/doc/refman/8.4/en/innodb-index-types.html)). 조건에 맞는 행이 100건이면 이 재탐색이 100번 일어납니다. 게다가 인덱스 순서와 기본 키 순서는 대체로 무관하므로, 이 100번은 디스크 여기저기를 찌르는 랜덤 접근입니다.

> `EXPLAIN`의 `type`이 `ref`고 `rows`가 5만이라면, 그 5만 건 각각에 대해 테이블을 다시 읽는다는 뜻입니다. 인덱스가 아무리 정교해도 2단계가 남아 있는 한 비용은 "찾은 행 수"에 비례해서 늘어납니다. 그래서 인덱스를 잘 탔는데도 `LIMIT`이 없으면 느린 쿼리가 나옵니다.

**커버링 인덱스는 2단계를 통째로 없애는 기법입니다.** 특별한 인덱스 종류가 아닙니다. MySQL 용어집은 커버링 인덱스를 "쿼리가 가져오는 모든 컬럼을 포함하는 인덱스"라고 정의하고, 인덱스 값을 행을 찾는 포인터로 쓰는 대신 **인덱스 구조에서 값을 바로 반환한다**고 설명합니다([MySQL Glossary](https://dev.mysql.com/doc/refman/8.4/en/glossary.html)).

즉 커버링은 인덱스의 속성이 아니라 **인덱스와 쿼리의 관계**입니다. 같은 인덱스가 어떤 쿼리에는 커버링이고 어떤 쿼리에는 아닙니다. `SELECT` 목록에 컬럼 하나를 추가하는 순간 깨집니다.

## 2. InnoDB는 이미 절반쯤 커버링입니다

InnoDB 세컨더리 인덱스가 기본 키를 담고 있다는 사실에는 따라오는 이득이 있습니다. **모든 세컨더리 인덱스는 자기 컬럼 + 기본 키를 이미 커버합니다.**

```sql
CREATE TABLE orders (
    order_id     BIGINT      NOT NULL AUTO_INCREMENT,
    shop_id      BIGINT      NOT NULL,
    status       VARCHAR(20) NOT NULL,
    total_amount INT         NOT NULL,
    ordered_at   DATETIME(6) NOT NULL,
    PRIMARY KEY (order_id),
    KEY idx_shop_status (shop_id, status)
) ENGINE = InnoDB;
```

`idx_shop_status`의 리프에는 `(shop_id, status, order_id)`가 들어 있습니다. 그래서 이 쿼리는 테이블을 한 번도 안 봅니다.

```sql
SELECT order_id FROM orders WHERE shop_id = 7 AND status = 'PAID';
```

MySQL 용어집도 InnoDB가 MyISAM보다 이 최적화를 더 많은 인덱스에 적용할 수 있는 이유로 세컨더리 인덱스가 기본 키를 포함한다는 점을 듭니다. 같은 문서가 **기본 키가 길면 모든 세컨더리 인덱스가 커진다**고 경고하는 것도 같은 구조 때문입니다. UUID 문자열을 기본 키로 쓰면 인덱스 여덟 개가 전부 그 문자열을 사본으로 들고 있습니다.

## 3. 커버링인지 확인하는 법

### 3-1. MySQL — `Extra`의 `Using index`

MySQL 문서는 `Using index`를 이렇게 정의합니다. **"실제 행을 읽기 위한 추가 탐색 없이 인덱스 트리의 정보만으로 컬럼 정보를 가져온다"**([EXPLAIN Output Format](https://dev.mysql.com/doc/refman/8.4/en/explain-output.html)).

헷갈리는 값이 셋 있습니다. 구분이 필요합니다.

| `EXPLAIN` 값 | 뜻 | 테이블을 읽는가 |
|---|---|---|
| `Extra: Using index` | 커버링 인덱스 | 안 읽습니다 |
| `Extra: Using index condition` | Index Condition Pushdown | 걸러낸 뒤 읽습니다 |
| `type: index` | 인덱스 풀 스캔 | 커버링이 아니면 읽습니다 |

`type: index`가 특히 함정입니다. 이름만 보면 좋아 보이지만 **인덱스를 처음부터 끝까지 훑는다**는 뜻이라 커버링이 아니면 최악에 가깝습니다. 인덱스 전체 스캔에 행 재탐색까지 붙습니다.

예외 하나가 문서에 있습니다. InnoDB에서 `type`이 `index`이고 `key`가 `PRIMARY`이면 `Using index`가 없어도 클러스터형 인덱스만 읽습니다. 애초에 행이 거기 있기 때문입니다.

### 3-2. PostgreSQL — `Index Only Scan`과 `Heap Fetches`

PostgreSQL은 노드 이름 자체가 `Index Only Scan`으로 바뀝니다. 그런데 **이름이 그렇게 찍혀도 테이블을 읽고 있을 수 있습니다.** `EXPLAIN (ANALYZE)`의 `Heap Fetches` 줄을 봐야 합니다.

```
Index Only Scan using idx_orders_shop_status on orders
  (actual time=0.006..0.007 rows=1.00 loops=1)
  Index Cond: ((shop_id = 7) AND (status = 'PAID'))
  Heap Fetches: 0
```

`Heap Fetches: 0`이면 진짜로 테이블을 안 읽은 것입니다. 이 숫자가 왜 0이 아닐 수 있는지가 다음 절입니다.

## 4. PostgreSQL에서는 컬럼을 다 넣어도 부족합니다

PostgreSQL 인덱스에는 **행의 가시성 정보가 없습니다.** 내 트랜잭션에서 이 행이 보여야 하는지는 힙(테이블 본체)에 가야 알 수 있습니다. MVCC를 쓰는 대가입니다.

그래서 컬럼을 전부 인덱스에 넣어도 그것만으로는 테이블을 안 볼 수가 없습니다. PostgreSQL은 **가시성 맵(visibility map)** 으로 이 문제를 우회합니다. "이 힙 페이지의 행은 전부 모든 트랜잭션에 보인다"는 비트를 페이지마다 하나씩 두고, Index Only Scan은 힙에 가기 전에 이 비트를 먼저 확인합니다. 비트가 서 있으면 힙 접근을 건너뜁니다([Index-Only Scans](https://www.postgresql.org/docs/18/indexes-index-only-scans.html)).

이 비트를 세우는 것은 **VACUUM**입니다([Routine Vacuuming](https://www.postgresql.org/docs/18/routine-vacuuming.html)). 결론이 여기서 나옵니다.

- 방금 대량으로 `INSERT`하거나 `UPDATE`한 테이블은 커버링 인덱스가 있어도 Index Only Scan이 이득을 못 냅니다.
- 문서도 Index Only Scan이 **천천히 변하는 테이블**에서 주로 이득이라고 못박습니다.
- 그래서 PostgreSQL에서는 커버링 인덱스 튜닝이 vacuum 운영과 분리되지 않습니다.

MySQL/InnoDB에는 이 문제가 없습니다. 언두 정보를 참조해 인덱스만으로 판단할 수 있기 때문입니다. 다만 용어집에 제약이 하나 적혀 있습니다 — **트랜잭션이 수정 중인 테이블에 대해서는 그 트랜잭션이 끝날 때까지 이 최적화를 적용하지 않습니다.**

### 4-1. `INCLUDE` — 키가 아닌 컬럼을 매다는 문법

PostgreSQL은 11부터 커버링 전용 문법이 있습니다.

```sql
CREATE INDEX idx_orders_shop_status
    ON orders (shop_id, status) INCLUDE (total_amount);
```

`total_amount`는 인덱스에 저장되지만 **키가 아닙니다.** 탐색·정렬에 관여하지 않고 오직 커버링 용도로만 실려 있습니다. 문서가 드는 성질은 이렇습니다([Index-Only Scans](https://www.postgresql.org/docs/18/indexes-index-only-scans.html)).

- 검색 동작과 유니크 판정에 영향을 주지 않습니다.
- B-tree, GiST, SP-GiST만 지원합니다. **GIN은 값 일부만 저장하므로 Index Only Scan 자체가 불가능합니다.**
- 표현식은 `INCLUDE`에 넣을 수 없습니다.
- 비키 컬럼은 테이블 데이터를 복제하는 것이라 인덱스를 부풀립니다.

키 컬럼으로 넣는 것과의 차이가 실무에서 중요합니다. 키로 넣으면 B-tree 상위 레벨에도 그 값이 올라가 팬아웃이 줄지만, `INCLUDE`는 리프에만 실립니다. **정렬·탐색에 안 쓸 컬럼이면 `INCLUDE`가 맞습니다.**

MySQL에는 이 문법이 없습니다([CREATE INDEX](https://dev.mysql.com/doc/refman/8.4/en/create-index.html)). 커버링용 컬럼도 키 컬럼으로 뒤에 붙이는 수밖에 없습니다. 이게 6절의 트레이드오프를 MySQL 쪽에서 더 무겁게 만듭니다.

## 5. 예제 — 커버링이 깨지는 가장 흔한 방식

상점 관리자 화면의 주문 목록입니다. 화면에는 주문번호·금액·주문시각만 나옵니다.

### 5-1. 커버링이 깨진 코드 ❌

```java
// ❌ 엔티티로 조회하면 매핑된 전 컬럼을 SELECT 합니다
public interface OrderRepository extends JpaRepository<Order, Long> {

    List<Order> findByShopIdAndStatusOrderByOrderedAtDesc(
            Long shopId, OrderStatus status, Pageable pageable);
}
```

```sql
-- 실제로 나가는 SQL
SELECT order_id, shop_id, status, total_amount, ordered_at, memo, address, ...
FROM orders
WHERE shop_id = 7 AND status = 'PAID'
ORDER BY ordered_at DESC LIMIT 20;
```

`idx_orders_shop_status_time (shop_id, status, ordered_at)`이 있어도 `memo`, `address` 때문에 커버링이 깨집니다. `Extra`에 `Using index`가 사라지고 20건에 대해 클러스터형 인덱스 재탐색이 붙습니다.

**JPA에서 커버링이 잘 안 나오는 구조적 이유가 여기 있습니다.** 엔티티 조회는 "필요한 컬럼"이 아니라 "매핑된 컬럼 전부"를 가져옵니다. 컬럼 30개짜리 엔티티에서 커버링 인덱스를 만들려면 인덱스가 테이블 사본이 됩니다.

### 5-2. 필요한 컬럼만 뽑은 코드 ✔️

```java
// ✔️ 프로젝션으로 화면이 쓰는 컬럼만 가져옵니다
public interface OrderSummary {
    Long getOrderId();
    Integer getTotalAmount();
    LocalDateTime getOrderedAt();
}

public interface OrderRepository extends JpaRepository<Order, Long> {

    List<OrderSummary> findByShopIdAndStatusOrderByOrderedAtDesc(
            Long shopId, OrderStatus status, Pageable pageable);
}
```

`(shop_id, status, ordered_at)` 인덱스는 리프에 `order_id`(기본 키)를 이미 갖고 있습니다. 여기에 `total_amount`만 더하면 커버링이 완성됩니다.

```sql
-- MySQL: 커버링용 컬럼도 키 뒤에 붙입니다
CREATE INDEX idx_orders_cover
    ON orders (shop_id, status, ordered_at, total_amount);

-- PostgreSQL: 탐색에 안 쓰는 컬럼은 INCLUDE로
CREATE INDEX idx_orders_cover
    ON orders (shop_id, status, ordered_at) INCLUDE (total_amount);
```

`total_amount`를 **맨 뒤에** 둔 것이 중요합니다. `ordered_at` 앞에 끼우면 정렬 성질이 깨집니다(`day35-composite-index-order.md` 4절). 커버링용 컬럼은 항상 꼬리에 붙입니다.

### 5-3. 구간을 못 좁히는 컬럼도 커버링에는 기여합니다

`day35-composite-index-order.md` 3절에서, 범위 조건 뒤의 컬럼은 탐색 구간을 못 좁힌다고 했습니다. 그런데 **커버링은 별개 이야기입니다.**

```sql
-- INDEX (shop_id, ordered_at, status)
WHERE shop_id = 7 AND ordered_at >= '2026-09-01' AND status = 'PAID'
```

`status`는 구간을 못 좁힙니다. 하지만 리프에 값이 있으므로 (1) 리프에서 미리 걸러내고(Index Condition Pushdown), (2) `SELECT`가 이 컬럼들로만 끝나면 커버링도 성립합니다. **"구간을 좁히는 컬럼"과 "커버하는 컬럼"은 다른 집합입니다.** 인덱스 설계에서 이 둘을 따로 세는 습관이 필요합니다.

## 6. 공짜가 아닌 지점

커버링 인덱스는 읽기 비용을 쓰기 비용과 저장 공간으로 바꾸는 거래입니다.

**첫째, 인덱스가 커집니다.** 커버링용 컬럼은 테이블 데이터의 사본입니다. `VARCHAR(500)` 컬럼을 커버링하려고 넣으면 인덱스 하나가 테이블만 해집니다. 인덱스가 메모리 버퍼에 안 들어가기 시작하면 원래 없애려던 디스크 접근이 다른 곳에서 돌아옵니다.

**둘째, 그 컬럼의 `UPDATE`가 비싸집니다.** 인덱스에 걸린 컬럼을 바꾸면 인덱스도 갱신해야 합니다. 커버링 컬럼은 대개 자주 바뀌는 값(금액, 상태, 수정시각)이라 이 비용이 실질적입니다.

**셋째, PostgreSQL에서는 HOT 최적화가 깨집니다.** PostgreSQL은 `UPDATE`가 (1) 인덱스가 참조하는 컬럼을 건드리지 않고 (2) 같은 페이지에 공간이 있으면, 인덱스를 전혀 건드리지 않는 HOT 갱신을 씁니다([Heap-Only Tuples](https://www.postgresql.org/docs/18/storage-hot.html)). 커버링용으로 `total_amount`를 인덱스에 넣는 순간, 금액을 바꾸는 `UPDATE`가 HOT 대상에서 빠집니다. 읽기를 위해 넣은 컬럼이 쓰기 경로를 바꿉니다.

문서도 같은 결론을 냅니다 — **비키 컬럼은 인덱스를 키우고 검색·쓰기를 느리게 할 수 있으므로, 테이블이 충분히 천천히 변해서 Index Only Scan이 실제로 힙 접근을 피할 때만 넣으라**고 씁니다.

### 6-1. 컬럼을 다 못 넣을 때 — 지연 조인

화면에 컬럼 20개가 필요하면 커버링은 포기해야 합니다. 그런데 커버링을 **일부 구간에만** 쓰는 방법이 있습니다.

```sql
-- ✔️ 1단계는 커버링 인덱스만으로 PK 20개를 뽑고, 2단계에서 그 20건만 테이블을 봅니다
SELECT o.*
FROM orders o
JOIN (
    SELECT order_id
    FROM orders
    WHERE shop_id = 7 AND status = 'PAID'
    ORDER BY ordered_at DESC
    LIMIT 20 OFFSET 10000
) AS page ON page.order_id = o.order_id
ORDER BY o.ordered_at DESC;
```

핵심은 **버려질 행에 대해서는 테이블을 안 읽는다**는 것입니다. 서브쿼리는 인덱스만으로 끝나고(커버링), 테이블 접근은 최종 20건에만 일어납니다. `OFFSET`이 클수록 차이가 커집니다. `OFFSET` 자체의 문제는 따로 있고, 커서 기반 전환은 `day15-pagination-api.md`에서 다뤘습니다.

## 7. 함정

### 함정 1 — `SELECT` 목록에 컬럼 하나 추가했더니 느려졌습니다

- **증상**: 잘 돌던 목록 API에 "수정자 이름도 보여주세요" 요청이 들어와 컬럼 하나를 추가했더니 응답 시간이 몇 배가 됐습니다. `WHERE` 절은 그대로입니다.
- **원인**: 커버링이 깨졌습니다. 인덱스만 읽던 쿼리가 행 수만큼 클러스터형 인덱스 재탐색을 하기 시작했습니다. `Extra`에서 `Using index`가 사라진 것 말고는 실행계획이 거의 그대로라 눈치채기 어렵습니다.
- **해법**: 변경 전후 `EXPLAIN`을 비교해 `Using index`(PostgreSQL이면 `Index Only Scan` + `Heap Fetches: 0`)가 유지되는지 봅니다. 추가된 컬럼이 작고 잘 안 바뀌면 인덱스 꼬리에 붙입니다. 크거나 자주 바뀌면 붙이지 말고 6-1의 지연 조인으로 접근 건수를 줄입니다.

### 함정 2 — PostgreSQL에서 `Index Only Scan`인데 안 빨라졌습니다

- **증상**: 커버링 인덱스를 만들었고 계획에 `Index Only Scan`이 찍히는데 시간이 그대로입니다.
- **원인**: `Heap Fetches`가 0이 아닙니다. 가시성 맵 비트가 안 서 있어서 결국 힙에 가고 있습니다. 대량 적재나 잦은 갱신 직후, 또는 autovacuum이 그 테이블을 못 따라가고 있을 때 나옵니다.
- **해법**: `EXPLAIN (ANALYZE, BUFFERS)`로 `Heap Fetches`를 확인합니다. 0이 아니면 인덱스 문제가 아니라 vacuum 문제입니다. 수동 `VACUUM`으로 숫자가 떨어지는지 먼저 검증하고, 떨어진다면 그 테이블의 autovacuum 임계값을 낮춥니다. 적재만 일어나는 테이블은 `UPDATE`/`DELETE`가 없어서 기본 임계값으로는 vacuum이 늦게 도는데, 삽입 기준 임계값(`autovacuum_vacuum_insert_threshold`)이 이 경우를 위한 설정입니다. <!-- TODO: PostgreSQL 18에서 이 파라미터의 기본값 확인 필요 -->

### 함정 3 — 커버링 인덱스를 늘렸더니 쓰기가 느려졌습니다

- **증상**: 조회 쿼리별로 커버링 인덱스를 만들었더니 읽기는 빨라졌는데 배치 `INSERT`와 주문 상태 변경이 눈에 띄게 느려졌습니다.
- **원인**: 커버링용 컬럼이 인덱스마다 중복 저장되고, 그 컬럼을 바꾸는 `UPDATE`가 인덱스 개수만큼 갱신을 유발합니다. PostgreSQL이라면 HOT까지 깨져서 갱신 한 번이 모든 인덱스에 새 항목을 만듭니다.
- **해법**: 커버링 대상을 **잘 안 바뀌는 컬럼**으로 제한하는 게 1차 방어입니다. 자주 바뀌는 컬럼은 커버링에서 뺍니다. 그리고 인덱스를 새로 만들기 전에 기존 인덱스 꼬리에 컬럼을 붙여 해결되는지 먼저 봅니다. 인덱스 두 개가 앞부분을 공유하면 하나로 합칠 수 있습니다(`day35-composite-index-order.md` 함정 3).

### 함정 4 — `UNIQUE ... INCLUDE`가 유니크를 보장할 거라고 믿었습니다

- **증상**: PostgreSQL에서 `CREATE UNIQUE INDEX ... ON orders (shop_id) INCLUDE (idempotency_key)`를 만들고 중복이 막힐 거라 기대했는데 중복 행이 들어옵니다.
- **원인**: 유니크 판정은 **키 컬럼에만** 적용됩니다. `INCLUDE` 컬럼은 판정에 참여하지 않습니다. 문서에 명시된 동작입니다.
- **해법**: 유니크를 걸어야 하는 컬럼은 반드시 키 쪽(`ON`의 괄호 안)에 둡니다. `INCLUDE`는 "이 컬럼도 인덱스에서 읽고 싶다"는 뜻일 뿐, 제약과는 무관합니다. 중복 방지를 유니크 제약에 맡기는 설계는 `day21-idempotency.md`에서 다뤘습니다.

## 8. 참고자료

- [MySQL 8.4 — Glossary: covering index](https://dev.mysql.com/doc/refman/8.4/en/glossary.html) — 정의, InnoDB에서 더 잘 먹히는 이유, 트랜잭션 중 제약
- [MySQL 8.4 — Clustered and Secondary Indexes](https://dev.mysql.com/doc/refman/8.4/en/innodb-index-types.html) — 세컨더리 인덱스가 기본 키를 담는 구조, 짧은 기본 키 권고
- [MySQL 8.4 — EXPLAIN Output Format](https://dev.mysql.com/doc/refman/8.4/en/explain-output.html) — `Using index` 정의, `Using index condition`과의 차이
- [MySQL 8.4 — CREATE INDEX](https://dev.mysql.com/doc/refman/8.4/en/create-index.html) — 지원 문법(`INCLUDE` 절 없음)
- [PostgreSQL 18 — Index-Only Scans and Covering Indexes](https://www.postgresql.org/docs/18/indexes-index-only-scans.html) — 가시성 맵 조건, `INCLUDE` 성질과 제약
- [PostgreSQL 18 — Routine Vacuuming](https://www.postgresql.org/docs/18/routine-vacuuming.html) — 가시성 맵을 세우는 주체
- [PostgreSQL 18 — Heap-Only Tuples (HOT)](https://www.postgresql.org/docs/18/storage-hot.html) — HOT 갱신 성립 조건
- `day35-composite-index-order.md` — 컬럼 순서, 구간을 좁히는 컬럼과 아닌 컬럼
- `day23-btree-index.md` — B+Tree 리프 구조, Index Condition Pushdown
- `day29-explain-plan.md` — `type`·`rows`·`Extra` 읽는 순서
- `day15-pagination-api.md` — `OFFSET` 페이지네이션의 한계와 커서 전환

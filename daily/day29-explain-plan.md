# 실행계획 읽는 법 — 느린 쿼리 앞에서 무엇을 어떤 순서로 보는가

> 이 문서가 답할 질문: **`EXPLAIN`을 붙였더니 표가 하나 나왔습니다. 이 표에서 무엇을 어떤 순서로 봐야 "이래서 느리다"에 도달하는가?**
>
> 기준: MySQL 8.4 / InnoDB, 대조로 PostgreSQL 18 (2026년 9월 확인). 인덱스가 왜 필요한지는 `day17-why-index.md`, B+Tree 구조는 `day23-btree-index.md`에서 다뤘습니다. 여기서는 그 인덱스를 **옵티마이저가 실제로 쓰기로 했는지 확인하는 방법**만 봅니다.
>
> 이 문서의 `EXPLAIN` 출력은 형태를 보여주기 위한 예시입니다. 측정치가 아니고, 같은 쿼리라도 데이터 분포와 통계 상태에 따라 다르게 나옵니다.

## 1. 실행계획은 결과 보고서가 아니라 계획서입니다

`EXPLAIN`은 쿼리를 실행하지 않습니다. 옵티마이저가 **"이렇게 실행할 생각이다"** 라고 답하는 것뿐입니다. 여기 적힌 행 수는 전부 통계 기반 추정치입니다. 매뉴얼도 `rows` 컬럼을 "MySQL이 검사해야 한다고 **믿는(believes)** 행 수이며 InnoDB에서는 추정치라 항상 정확하지는 않다"고 정의합니다([EXPLAIN Output Format](https://dev.mysql.com/doc/refman/8.4/en/explain-output.html)).

> 이걸 모르면 두 가지 방향으로 틀립니다. 하나는 실행계획을 안 보고 느린 쿼리에 인덱스를 하나씩 추가해보는 것입니다. 운이 좋으면 맞고, 대개는 안 쓰이는 인덱스만 쌓여서 쓰기가 같이 느려집니다. 다른 하나는 반대로 `EXPLAIN` 결과를 사실로 믿는 것입니다. `rows=100`이라고 적혀 있는데 실제로는 40만 행을 읽고 있는 상황이 실제로 벌어집니다. 실행계획 읽기의 절반은 **추정이 어디서 어긋났는지 찾는 일**입니다.

그래서 도구를 세 개로 나눠서 기억해야 합니다.

| 문법 | 실행 | 답해주는 질문 | 버전 |
|---|---|---|---|
| `EXPLAIN` (TRADITIONAL) | 안 함 | 어떤 인덱스로, 어떤 순서로 접근할 계획인가 | 계속 |
| `EXPLAIN FORMAT=TREE` | 안 함 | 연산자가 어떻게 중첩되어 있는가 | 8.0.16+ |
| `EXPLAIN ANALYZE` | **함** | 그 계획이 실제로 맞았는가, 시간은 어디서 갔는가 | 8.0.18+ |

`FORMAT` 옵션을 안 주면 기본은 `TRADITIONAL`이고, 8.0.32부터는 `explain_format` 시스템 변수 값을 따릅니다(기본값 `TRADITIONAL`). `EXPLAIN ANALYZE`는 항상 TREE 형식으로만 나옵니다. TREE는 해시 조인 사용 여부를 보여주는 유일한 형식이기도 합니다([EXPLAIN Statement](https://dev.mysql.com/doc/refman/8.4/en/explain.html)).

## 2. 예제 — 주문 목록 20건이 느린 상황

```sql
CREATE TABLE members (
    member_id BIGINT       NOT NULL AUTO_INCREMENT,
    email     VARCHAR(120) NOT NULL,
    grade     VARCHAR(20)  NOT NULL,
    PRIMARY KEY (member_id),
    UNIQUE KEY uk_members_email (email)
) ENGINE=InnoDB;

CREATE TABLE orders (
    order_id    BIGINT      NOT NULL AUTO_INCREMENT,
    member_id   BIGINT      NOT NULL,
    status      VARCHAR(20) NOT NULL,
    ordered_at  DATETIME    NOT NULL,
    total_price INT         NOT NULL,
    PRIMARY KEY (order_id),
    KEY idx_orders_member (member_id)
) ENGINE=InnoDB;
```

관리자 화면의 "최근 결제 완료 주문 20건" 쿼리입니다. `LIMIT 20`인데 몇 초씩 걸립니다.

```sql
EXPLAIN
SELECT o.order_id, o.total_price, m.email
FROM orders o
JOIN members m ON m.member_id = o.member_id
WHERE o.status = 'PAID'
  AND o.ordered_at >= '2026-09-01'
ORDER BY o.ordered_at DESC
LIMIT 20;
```

```text
+----+-------------+---+--------+---------------+---------+---------+---------------+---------+----------+-----------------------------+
| id | select_type | t | type   | possible_keys | key     | key_len | ref           | rows    | filtered | Extra                       |
+----+-------------+---+--------+---------------+---------+---------+---------------+---------+----------+-----------------------------+
|  1 | SIMPLE      | o | ALL    | idx_orders_.. | NULL    | NULL    | NULL          | 1998000 |     1.11 | Using where; Using filesort |
|  1 | SIMPLE      | m | eq_ref | PRIMARY       | PRIMARY | 8       | o.member_id   |       1 |   100.00 | NULL                        |
+----+-------------+---+--------+---------------+---------+---------+---------------+---------+----------+-----------------------------+
```

컬럼이 12개지만 전부 볼 필요는 없습니다. **네 곳을 이 순서로** 봅니다.

### 2-1. `type` — 테이블을 여는 방식

가장 먼저 봅니다. 매뉴얼이 좋은 순서대로 나열하는데, 실무에서 외울 만한 구간은 이 정도입니다.

```
const  →  eq_ref  →  ref  →  range  →  index  →  ALL
좋음                                            나쁨
```

- `const` / `eq_ref` — 기본키·유니크 인덱스로 한 행. 더 볼 것 없습니다.
- `ref` — 일반 인덱스 동등 조건. 정상 범위입니다.
- `range` — 인덱스 범위 스캔. `BETWEEN`, `>=`, `IN()` 등이 여기 옵니다.
- `index` — **인덱스 전체 스캔.** 이름 때문에 안심하기 쉬운데 풀스캔입니다.
- `ALL` — 테이블 풀스캔.

위 출력에서 `orders`는 `ALL`입니다. `possible_keys`에 인덱스 후보는 있는데 `key`가 `NULL`이라는 건 **후보는 있었지만 옵티마이저가 안 쓰기로 했다**는 뜻입니다. `idx_orders_member`는 `member_id`로 시작하니 `status` 조건에 쓸 수가 없습니다.

### 2-2. `rows` × `filtered` — 읽는 양과 버리는 양

`rows`는 검사할 것으로 추정한 행 수, `filtered`는 그중 조건을 통과할 것으로 추정한 비율(백분율)입니다. 매뉴얼은 "`rows` × `filtered`가 다음 테이블과 조인되는 행 수"라고 정의합니다([EXPLAIN Output Format](https://dev.mysql.com/doc/refman/8.4/en/explain-output.html)).

```
1,998,000 × 1.11% ≈ 22,178행
```

**200만 행을 읽어서 2만 행만 남기고 버립니다.** 실행계획에서 봐야 할 진짜 숫자는 행 수 자체가 아니라 이 격차입니다. `filtered`가 100에 가까울수록 "읽은 걸 다 쓰고 있다"는 뜻이고, 1.11처럼 낮으면 읽기 전에 잘라낼 방법이 없었다는 뜻입니다. 인덱스가 하는 일이 정확히 이 격차를 없애는 것입니다(`day17-why-index.md`).

조인에서는 이 값이 곱해집니다. 위 계획은 22,178행 각각에 대해 `members`를 `eq_ref`로 한 번씩 찾습니다. 한 번에 1행이라 싸 보이지만, **횟수가 2만 번**입니다. 이 곱셈이 실행계획 읽기에서 가장 자주 놓치는 지점입니다.

### 2-3. `Extra` — 여기에 다 적혀 있습니다

매뉴얼도 "쿼리를 최대한 빠르게 만들고 싶다면 `Extra` 컬럼의 `Using filesort`와 `Using temporary`를 주시하라"고 못 박습니다.

| 값 | 뜻 | 신호 |
|---|---|---|
| `Using index` | 인덱스만으로 컬럼을 다 채움 (커버링) | 좋음 |
| `Using index condition` | 조건 일부를 스토리지 엔진으로 내림 (ICP) | 보통 |
| `Using where` | 읽어온 뒤 서버가 걸러냄 | 맥락에 따라 |
| `Using filesort` | 별도 정렬 패스 필요 | 나쁨 |
| `Using temporary` | 임시 테이블 생성 | 나쁨 |

`Using index`와 `Using index condition`은 이름이 비슷하지만 다릅니다. 앞은 **테이블을 안 읽는 것**이고, 뒤는 **테이블 읽기를 미루는 것**입니다.

여기서 `LIMIT 20`인데 느린 이유가 나옵니다. `Using filesort`가 있으면 **정렬은 LIMIT보다 먼저 일어납니다.** 20건만 필요해도 2만 행을 다 만들어서 정렬한 다음 앞 20개를 자릅니다. 정렬을 인덱스로 대신할 수 있으면 상위 20개를 찾는 순간 멈출 수 있고, 그럴 수 없으면 전량을 만들어야 합니다. 이 차이가 `LIMIT` 쿼리의 응답 시간을 몇 밀리초와 몇 초로 갈라놓습니다.

### 2-4. 순서 — 위에서부터가 조인 순서

`id`가 같으면 위에 있는 행이 먼저 접근됩니다. 위 계획은 `orders`가 드라이빙 테이블이고 `members`가 그 뒤를 따릅니다. **드라이빙 테이블에서 행이 많이 나오면 뒤쪽 전부가 그만큼 반복됩니다.** 그래서 튜닝은 거의 항상 맨 위 행부터 손댑니다.

## 3. 고친 계획

```sql
CREATE INDEX idx_orders_status_ordered ON orders (status, ordered_at);
```

`status`는 동등 조건, `ordered_at`은 범위 겸 정렬 기준입니다. 동등 조건을 앞에 두면 `status = 'PAID'` 구간 안에서 `ordered_at`이 이미 정렬된 상태로 늘어서 있습니다(복합 인덱스 순서 규칙은 별도 챕터 주제입니다).

```text
+----+-------------+---+-------+---------------------------+---------------------------+---------+----------+--------------------------------------+
| id | select_type | t | type  | key                       | ref                       | rows    | filtered | Extra                                |
+----+-------------+---+-------+---------------------------+---------------------------+---------+----------+--------------------------------------+
|  1 | SIMPLE      | o | range | idx_orders_status_ordered | NULL                      |   22000 |   100.00 | Using where; Backward index scan     |
|  1 | SIMPLE      | m | eq_ref| PRIMARY                   | o.member_id               |       1 |   100.00 | NULL                                 |
+----+-------------+---+-------+---------------------------+---------------------------+---------+----------+--------------------------------------+
```

바뀐 것은 세 가지입니다.

1. `ALL` → `range`. 읽기 시작점이 생겼습니다.
2. `filtered` 1.11 → 100. 읽은 행을 버리지 않습니다.
3. **`Using filesort`가 사라졌습니다.** `ORDER BY ordered_at DESC`를 인덱스를 거꾸로 훑어서 해결합니다(`Backward index scan`). 이제 20건을 채우는 순간 멈출 수 있으므로 `rows`가 22,000으로 남아 있어도 실제로 읽는 양은 훨씬 적습니다.

**`rows`가 줄지 않았는데 빨라지는 이 경우가 `EXPLAIN`만으로는 확인이 안 되는 대표적인 상황입니다.** 그래서 다음 단계가 필요합니다.

## 4. `EXPLAIN ANALYZE` — 추정과 실제를 나란히 놓기

`EXPLAIN ANALYZE`는 쿼리를 **실제로 실행하고** 각 연산자마다 추정치와 실측치를 함께 찍습니다.

```text
-> Limit: 20 row(s)  (cost=8112 rows=20) (actual time=2481..2481 rows=20 loops=1)
    -> Nested loop inner join  (cost=8112 rows=22178) (actual time=2481..2481 rows=20 loops=1)
        -> Sort: o.ordered_at DESC  (actual time=2480..2480 rows=20 loops=1)
            -> Filter: ((o.status = 'PAID') and (o.ordered_at >= TIMESTAMP'2026-09-01 00:00:00'))
               (cost=201430 rows=22178) (actual time=0.31..1902 rows=41260 loops=1)
                -> Table scan on o  (cost=201430 rows=1998000) (actual time=0.28..1204 rows=1998000 loops=1)
        -> Single-row index lookup on m using PRIMARY (member_id=o.member_id)
           (cost=0.25 rows=1) (actual time=0.011..0.011 rows=1 loops=20)
```

읽는 규칙이 셋 있습니다.

**첫째, 안쪽부터 읽습니다.** 들여쓰기가 가장 깊은 것이 가장 먼저 실행됩니다. 위에서는 `Table scan` → `Filter` → `Sort` → `Nested loop` → `Limit` 순입니다.

**둘째, `rows=` 두 개를 대조합니다.** 괄호 앞쪽 `rows=22178`은 추정, `actual` 안의 `rows=41260`은 실측입니다. 여기서 약 2배 어긋났습니다. 이 격차가 크면 **계획 자체가 틀린 통계 위에서 세워진 것**이므로, 인덱스를 고치기 전에 통계부터 봐야 합니다.

**셋째, `loops`를 곱합니다.** 매뉴얼은 시간에 대해 "루프가 여러 번이면 이 값은 **루프당 평균**"이라고 명시합니다([EXPLAIN Statement](https://dev.mysql.com/doc/refman/8.4/en/explain.html)). 행 수도 마찬가지로 루프당 평균입니다. 마지막 줄의 `0.011ms`는 한 번 조회 비용이고 `loops=20`이니 총 0.22ms입니다.

이 세 번째 규칙이 실무에서 가장 잘 먹힙니다. **N+1 형태의 병목은 한 줄짜리 큰 시간이 아니라 작은 시간 × 큰 `loops`로 나타납니다.** `0.011ms`만 보고 넘기면 못 찾습니다. `loops`가 수만인 줄을 먼저 찾고, 그 줄의 시간에 `loops`를 곱해서 전체 시간과 비교하는 습관이 필요합니다.

`actual time=0.31..1902`의 두 숫자는 첫 행까지 걸린 시간과 마지막 행까지 걸린 시간입니다. 앞 숫자가 크면 "시작을 못 하고 있다"(선행 연산이 끝나야 함), 뒤 숫자가 크면 "양이 많다"는 뜻입니다.

## 5. 추정이 틀리는 이유

`rows` 추정이 실제와 크게 다르면 옵티마이저는 잘못된 계획을 고릅니다. 원인은 대개 통계입니다.

InnoDB는 테이블 전체를 세지 않고 **인덱스에서 페이지 몇 장을 무작위로 뽑아** 카디널리티를 추정합니다. 샘플 페이지 수를 정하는 `innodb_stats_persistent_sample_pages`의 기본값은 20입니다([Configuring Persistent Optimizer Statistics Parameters](https://dev.mysql.com/doc/refman/8.4/en/innodb-persistent-stats.html)). 값이 한쪽에 몰려 있는 컬럼이라면 20장으로는 분포를 못 잡습니다.

```sql
-- 1) 통계 갱신
ANALYZE TABLE orders;

-- 2) 인덱스가 없는 컬럼의 분포를 옵티마이저에게 알려주기
ANALYZE TABLE orders UPDATE HISTOGRAM ON status WITH 16 BUCKETS;
```

히스토그램은 인덱스가 없는 컬럼에도 만들 수 있고, `filtered` 추정에 직접 반영됩니다([ANALYZE TABLE Statement](https://dev.mysql.com/doc/refman/8.4/en/analyze-table.html)). 상태값처럼 종류는 적은데 분포가 극단적으로 치우친 컬럼에서 효과가 큽니다. 다만 히스토그램은 자동 갱신되지 않으므로, 분포가 계속 변하는 컬럼이라면 갱신 시점을 누가 책임지는지까지 정해야 합니다.

## 6. PostgreSQL은 어떻게 다른가

문법과 용어만 다르고 읽는 방식은 같습니다. 차이는 두 가지입니다.

- PostgreSQL의 `EXPLAIN`은 처음부터 트리 형식이고 비용을 `cost=시작..전체`로 보여줍니다. MySQL의 `TRADITIONAL` 표가 특이한 쪽입니다.
- PostgreSQL 18부터 `EXPLAIN ANALYZE`에 **`BUFFERS` 출력이 기본 포함**됩니다([EXPLAIN](https://www.postgresql.org/docs/current/sql-explain.html)). 몇 개의 버퍼를 읽었는지가 바로 보이니 "몇 페이지를 읽었나"를 시간보다 먼저 볼 수 있습니다. MySQL에는 이에 상응하는 기본 출력이 없어서 `rows`와 `loops`로 역산해야 합니다.

## 7. 함정

### 7-1. 손으로 `EXPLAIN` 하면 인덱스를 타는데 애플리케이션에서는 안 탑니다

- **증상**: 콘솔에서 `EXPLAIN`을 돌리면 `type=ref`인데, 운영 슬로우 쿼리 로그에는 같은 쿼리가 계속 올라옵니다.
- **원인**: 실행되는 SQL이 내가 본 SQL과 다릅니다. 흔한 경우가 **타입 불일치**입니다. `VARCHAR` 컬럼에 숫자 파라미터가 바인딩되면 암묵적 형변환이 일어나 인덱스를 못 씁니다. `IN` 절 원소 개수가 요청마다 달라져서 `range`였다가 `ALL`로 뒤집히는 경우도 있습니다.
- **해법**: 손으로 재구성한 SQL이 아니라 **실제로 실행된 SQL**을 봅니다. 지금 도는 쿼리라면 `SHOW PROCESSLIST`로 커넥션 ID를 찾아 `EXPLAIN FOR CONNECTION <id>`로 그 세션의 계획을 그대로 뜹니다. 단, `EXPLAIN ANALYZE`는 `FOR CONNECTION`을 지원하지 않습니다.

### 7-2. `type: index`를 보고 안심합니다

- **증상**: `ALL`이 아니고 `key`도 채워져 있어서 튜닝이 끝난 줄 알았는데 여전히 느립니다.
- **원인**: `index`는 인덱스를 탄다는 뜻이 아니라 **인덱스를 처음부터 끝까지 훑는다**는 뜻입니다. 행 수는 테이블 전체와 같고, 테이블 대신 인덱스를 읽어서 조금 가벼울 뿐입니다.
- **해법**: `range` 이상으로 올릴 방법을 찾습니다. `Extra`에 `Using index`가 함께 있다면 커버링 인덱스 풀스캔이라 그대로 두는 게 나은 경우도 있습니다. `rows`를 테이블 전체 행 수와 비교해보면 바로 판별됩니다.

### 7-3. `possible_keys`에 있는데 `key`가 `NULL`입니다

- **증상**: 인덱스를 분명히 만들었는데 안 씁니다.
- **원인**: 옵티마이저가 "인덱스로 찾아서 다시 테이블을 뒤지는 것보다 풀스캔이 싸다"고 판단한 것입니다. 선택도가 낮은 조건(전체의 상당 부분이 조건을 만족)에서는 이 판단이 대체로 맞습니다. 통계가 낡아서 틀린 판단일 수도 있습니다.
- **해법**: `filtered` 값을 먼저 봅니다. 값이 크면 옵티마이저가 맞고, 인덱스 설계를 바꾸거나 조건 자체를 좁혀야 합니다. `ANALYZE TABLE` 후에도 그대로면 판단이 옳았다고 보는 편이 안전합니다. `FORCE INDEX`로 덮어쓰는 것은 데이터가 변하면 같이 틀어지므로 최후 수단입니다.

### 7-4. `EXPLAIN ANALYZE`를 데이터 변경 쿼리에 씁니다

- **증상**: 계획만 보려고 했는데 데이터가 바뀌어 있습니다.
- **원인**: `EXPLAIN`과 달리 `EXPLAIN ANALYZE`는 문장을 **실행합니다.** PostgreSQL 매뉴얼은 이를 명시적으로 경고하고 `BEGIN; EXPLAIN ANALYZE ...; ROLLBACK;`을 권합니다([EXPLAIN](https://www.postgresql.org/docs/current/sql-explain.html)). MySQL의 `EXPLAIN ANALYZE`도 `SELECT` 외에 다중 테이블 `UPDATE`·`DELETE`와 `TABLE` 문을 지원합니다.
- **해법**: 변경 쿼리는 트랜잭션으로 감싸고 롤백합니다. 운영 DB에서는 애초에 하지 않습니다.
- <!-- TODO: 확인 필요 — MySQL 8.4 매뉴얼은 EXPLAIN ANALYZE가 다중 테이블 UPDATE/DELETE의 변경을 실제로 적용하는지 명시하지 않습니다. 확인 전까지 "적용된다"고 가정하고 트랜잭션으로 감싸는 것이 안전합니다. -->

### 7-5. 계획만 보고 시간을 판단합니다

- **증상**: `rows`가 줄었는데 응답 시간은 그대로입니다.
- **원인**: `EXPLAIN`은 실행하지 않으므로 버퍼 풀 적중 여부, 정렬 버퍼가 디스크로 넘어갔는지, 잠금 대기가 있었는지를 전혀 알려주지 않습니다. 3절에서 본 것처럼 `rows`는 그대로인데 실제로는 훨씬 빨라지는 반대 경우도 있습니다.
- **해법**: 계획을 고쳤으면 반드시 `EXPLAIN ANALYZE`로 실측을 확인합니다. **`EXPLAIN`은 가설을 세우는 도구이고, 검증은 `EXPLAIN ANALYZE`가 합니다.**

## 8. 정리 — 읽는 순서

1. `type`과 `key` — 테이블을 어떻게 여는가. `ALL`·`index`면 여기서 멈추고 원인을 찾습니다.
2. `rows` × `filtered` — 얼마나 읽고 얼마나 버리는가. 격차가 크면 인덱스가 할 일이 남아 있습니다.
3. `Extra` — `Using filesort`·`Using temporary`가 있으면 `LIMIT`이 무력화됩니다.
4. 맨 위 행(드라이빙 테이블)부터 손댑니다. 뒤쪽은 이 행 수만큼 반복됩니다.
5. 고친 뒤 `EXPLAIN ANALYZE`로 추정과 실측을 대조하고, `loops`가 큰 줄을 곱해서 확인합니다.

## 9. 참고자료

- [MySQL 8.4 — EXPLAIN Statement](https://dev.mysql.com/doc/refman/8.4/en/explain.html)
- [MySQL 8.4 — EXPLAIN Output Format](https://dev.mysql.com/doc/refman/8.4/en/explain-output.html)
- [MySQL 8.4 — Configuring Persistent Optimizer Statistics Parameters](https://dev.mysql.com/doc/refman/8.4/en/innodb-persistent-stats.html)
- [MySQL 8.4 — ANALYZE TABLE Statement](https://dev.mysql.com/doc/refman/8.4/en/analyze-table.html)
- [PostgreSQL 18 — EXPLAIN](https://www.postgresql.org/docs/current/sql-explain.html)
- 관련 문서: `day17-why-index.md`, `day23-btree-index.md`

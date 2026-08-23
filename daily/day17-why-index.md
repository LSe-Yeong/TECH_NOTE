# 인덱스 없는 테이블은 왜 느린가

> 이 문서가 답할 질문: **인덱스가 없을 때 데이터베이스는 정확히 무슨 일을 하길래 느려지고, 인덱스는 그중 무엇을 없애주는가?**
>
> 기준: MySQL 8.4 / InnoDB (2026년 8월 확인). 일부 대조에 PostgreSQL 17을 씁니다. 이 문서는 "왜 느린가"와 "인덱스가 없애는 것"까지만 다룹니다. B+Tree 내부 동작과 복합 인덱스 설계는 뒤에 오는 `01-btree-index`, `03-composite-index-order` 챕터의 몫입니다.

## 1. 핵심 개념 — 비용의 단위는 행이 아니라 페이지

"인덱스가 없으면 전체를 다 뒤져서 느리다"는 설명은 결론만 맞고 원인이 틀렸습니다. 이 설명대로면 비용은 행 수에 비례해야 합니다. 그런데 같은 100만 행이라도 어떤 테이블은 0.05초에 끝나고 어떤 테이블은 8초가 걸립니다.

데이터베이스는 행 단위로 디스크를 읽지 않습니다. **고정 크기 페이지 단위로 읽습니다.** InnoDB의 기본 페이지 크기는 16KB입니다([InnoDB 물리 구조](https://dev.mysql.com/doc/refman/8.4/en/innodb-physical-structure.html)). 행 하나를 보려고 해도 그 행이 든 16KB를 통째로 읽습니다.

> 그래서 조회 비용을 정하는 건 행 개수가 아니라 **읽어야 하는 페이지 개수**입니다. 인덱스가 없을 때 이 값은 언제나 "테이블의 모든 페이지"로 고정됩니다. 행 하나를 찾든 100만 건을 찾든 같습니다. 인덱스가 하는 일은 행을 빨리 읽는 게 아니라, **읽지 않아도 되는 페이지를 미리 잘라내는 것**입니다.

이 관점 하나로 흔한 현상 대부분이 설명됩니다. 컬럼이 많아 행이 뚱뚱한 테이블은 페이지당 행이 적게 들어가서 같은 행 수에도 스캔이 더 느립니다. `SELECT *` 대신 필요한 컬럼만 고르는 것이 때때로 유의미한 이유도 여기 있습니다.

## 2. 인덱스 없는 조회가 실제로 하는 일

### 2-1. InnoDB에서 테이블은 이미 B+Tree입니다

먼저 정리하고 가야 할 게 있습니다. InnoDB에는 "인덱스가 하나도 없는 테이블"이 존재하지 않습니다.

InnoDB는 행 데이터를 **클러스터형 인덱스(clustered index)의 리프 페이지 안에** 저장합니다([InnoDB 인덱스 유형](https://dev.mysql.com/doc/refman/8.4/en/innodb-index-types.html)). 테이블 = 기본 키로 정렬된 B+Tree입니다. 기본 키를 만들지 않으면 InnoDB가 순서대로 찾습니다.

1. `PRIMARY KEY`가 있으면 그것으로
2. 없으면 모든 컬럼이 `NOT NULL`인 첫 번째 `UNIQUE` 인덱스로
3. 그것도 없으면 **숨겨진 6바이트 row ID**를 만들어서

3번까지 내려간 테이블이 진짜 문제입니다. 정렬 기준이 자동 증가하는 내부 값이라 개발자가 조회에 쓸 수 없습니다. 게다가 이 row ID는 인스턴스 전역에서 공유되는 카운터라, 여러 테이블이 동시에 여기 의존하면 그 자체가 경합 지점이 됩니다. **기본 키를 만드는 건 선택이 아닙니다.**

참고로 클러스터형 인덱스 레코드에는 사용자 컬럼 외에 **6바이트 트랜잭션 ID와 7바이트 롤 포인터**가 항상 붙습니다([InnoDB 행 포맷](https://dev.mysql.com/doc/refman/8.4/en/innodb-row-format.html)). MVCC를 위한 것이고, 페이지당 들어가는 행 수를 계산할 때 이 13바이트가 빠지지 않습니다.

### 2-2. 풀 테이블 스캔의 비용 세 가지

`WHERE`에 쓸 인덱스가 없으면 옵티마이저는 클러스터형 인덱스의 리프 페이지를 처음부터 끝까지 훑습니다. `EXPLAIN`의 `type` 컬럼에 `ALL`로 찍히는 그 접근 방식입니다. 여기서 지불하는 비용은 세 가지입니다.

**첫째, I/O.** 테이블 전체 페이지를 읽습니다. 버퍼 풀에 없는 페이지는 디스크에서 가져옵니다. `innodb_buffer_pool_size`의 기본값은 **134217728바이트(128MB)** 입니다([InnoDB 파라미터](https://dev.mysql.com/doc/refman/8.4/en/innodb-parameters.html)). 이 기본값을 그대로 쓰는 인스턴스에서 2GB짜리 테이블을 스캔하면 대부분이 디스크 접근입니다.

**둘째, CPU.** 읽어온 페이지에서 행을 하나씩 꺼내 `WHERE` 조건을 평가합니다. 100만 행이면 조건 평가가 100만 번입니다. 결과가 3건이어도 그렇습니다.

**셋째, 버퍼 풀 오염.** 이게 가장 늦게 발견되고 가장 넓게 퍼집니다. 스캔은 **거의 다 버릴 페이지를 버퍼 풀에 밀어 넣습니다.** 그러면 원래 잘 캐싱돼 있던 다른 테이블의 뜨거운 페이지가 밀려납니다. 증상이 이렇게 나타납니다. 통계 화면 하나를 열었을 뿐인데, 그 뒤 몇 분간 **관계없는 API들의 응답 시간이 전부 올라갑니다.** 느린 쿼리 로그에는 그 통계 쿼리만 찍히고, 정작 느려진 API들은 임계값 아래라 안 찍힙니다.

### 2-3. 스캔이 오히려 이기는 구간

인덱스가 항상 정답은 아닙니다. MySQL 문서는 옵티마이저가 풀 스캔을 고르는 상황을 이렇게 정리합니다([풀 테이블 스캔 피하기](https://dev.mysql.com/doc/refman/8.4/en/table-scan-avoidance.html)).

- 행이 10개 미만이고 행 길이가 짧은 작은 테이블
- `ON`이나 `WHERE`에 인덱스 컬럼에 대한 제약이 없는 경우
- 비교에 쓰인 상수가 테이블의 너무 큰 부분을 커버하는 경우
- **매칭되는 행이 많은, 카디널리티가 낮은 키를 쓰는 경우**

뒤의 두 가지가 핵심입니다. 순차 읽기는 페이지가 물리적으로 이어져 있어 미리 읽기가 듣습니다. 반면 인덱스로 행을 찾아가는 건 페이지를 흩어진 순서로 읽는 랜덤 접근입니다. **결과가 테이블의 상당 부분을 차지하면, 흩어진 접근을 많이 하느니 처음부터 순서대로 읽는 편이 빠릅니다.**

## 3. 인덱스가 없애는 것

### 3-1. 정렬된 사본과 그 위의 이정표

인덱스는 지정한 컬럼만 뽑아 **정렬해 둔 별도 구조**입니다. 정렬돼 있으면 이분 탐색이 되니 빠르다 — 여기까지가 절반입니다. 나머지 절반은 그 정렬된 목록 위에 **다시 색인을 얹는다**는 점입니다.

B+Tree는 이렇게 생겼습니다.

```text
             [루트 페이지]           ← 키 범위 → 자식 페이지 번호
            /      |      \
      [내부]     [내부]    [내부]     ← 같은 역할, 한 단계 아래
      /  \        /  \      /  \
  [리프]-[리프]-[리프]-[리프]-[리프]   ← 실제 키(+포인터), 정렬됨, 서로 연결됨
```

- **리프가 아닌 페이지에는 데이터가 없습니다.** "이 키 범위는 저 페이지로"라는 이정표만 들어갑니다. 그래서 한 페이지에 아주 많이 들어갑니다.
- **리프끼리 양방향으로 연결돼 있습니다.** 범위 조회(`BETWEEN`, `>`)와 `ORDER BY`가 인덱스로 처리되는 근거가 이 연결입니다.

### 3-2. 왜 깊이가 3~4단에서 멈추는가

숫자로 감을 잡아보겠습니다. **아래는 벤치마크가 아니라 16KB 페이지를 전제로 한 자릿수 추정입니다.**

내부 페이지 한 장에 `키 + 자식 페이지 번호` 항목이 대략 수백 개 들어간다고 보면(BIGINT 키 기준, 오버헤드 포함해 항목당 20바이트 안팎), 한 단계 내려갈 때마다 갈래가 수백 배로 늘어납니다.

| 깊이 | 도달 가능한 리프 페이지 수(갈래 800 가정) |
|---:|---|
| 2단 | 약 800 |
| 3단 | 약 64만 |
| 4단 | 약 5억 |

리프 페이지 하나에 행이 100개 들어간다면 3단으로 6천만 행이 커버됩니다. **테이블이 커져도 깊이는 로그로만 자랍니다.** 이게 인덱스의 전부입니다. 100만 행에서 1억 행으로 100배가 되어도 읽는 페이지는 3~4장에서 4~5장으로 바뀝니다.

여기에 하나 더 있습니다. **상단 페이지들은 거의 항상 버퍼 풀에 상주합니다.** 모든 인덱스 탐색이 루트를 지나가니까요. 그래서 실제 디스크 접근은 마지막 한두 장뿐인 경우가 많습니다.

### 3-3. 세컨더리 인덱스는 두 번 탐색합니다

기본 키가 아닌 인덱스를 세컨더리 인덱스라고 합니다. 여기 저장되는 것이 중요합니다.

**세컨더리 인덱스의 리프에는 인덱스 컬럼과 기본 키 값이 들어갑니다.** 행의 물리 주소가 아닙니다([InnoDB 인덱스 유형](https://dev.mysql.com/doc/refman/8.4/en/innodb-index-types.html)).

```text
orders 테이블: PRIMARY KEY (order_id), INDEX idx_customer (customer_id)

클러스터형 인덱스  : order_id → [order_id, customer_id, status, amount, created_at, ...]
idx_customer      : customer_id → [customer_id, order_id]
```

그래서 `WHERE customer_id = 4021` 로 주문 금액을 가져오려면 탐색이 두 번입니다.

```text
1. idx_customer 를 타고 내려가 customer_id=4021 의 order_id 들을 모은다
2. 각 order_id 로 클러스터형 인덱스를 다시 타고 내려가 나머지 컬럼을 읽는다   ← 건마다 반복
```

2번이 흔히 말하는 랜덤 접근입니다. 결과가 5건이면 무시할 만하고, 5만 건이면 5만 번입니다. **2-3에서 옵티마이저가 인덱스를 버리고 스캔을 고르는 이유가 정확히 이 2번의 누적 비용입니다.**

두 가지가 따라옵니다.

- **기본 키가 길면 모든 세컨더리 인덱스가 같이 뚱뚱해집니다.** 모든 리프에 기본 키가 복제되기 때문입니다. 문자열 자연키를 기본 키로 잡으면 인덱스 전체가 그 비용을 나눠 냅니다.
- 인덱스 안에 필요한 컬럼이 다 있으면 2번을 건너뜁니다. `EXPLAIN`의 `Extra`에 `Using index`로 찍히는 커버링 인덱스입니다([인덱스 사용 방식](https://dev.mysql.com/doc/refman/8.4/en/mysql-indexes.html)).

## 4. EXPLAIN으로 확인하기

추측하지 말고 실행 계획을 봅니다.

```sql
CREATE TABLE orders (
    order_id    BIGINT       NOT NULL AUTO_INCREMENT,
    customer_id BIGINT       NOT NULL,
    status      VARCHAR(20)  NOT NULL,
    amount      DECIMAL(12,2) NOT NULL,
    created_at  DATETIME     NOT NULL,
    PRIMARY KEY (order_id)
) ENGINE = InnoDB;

EXPLAIN SELECT order_id, amount
FROM orders
WHERE customer_id = 4021;
```

인덱스가 없을 때 봐야 할 세 칸입니다.

```text
type: ALL          ← 풀 테이블 스캔
key:  NULL         ← 쓴 인덱스 없음
rows: 982431       ← 훑을 것으로 추정한 행 수
```

`type`은 접근 방식이고, 나쁜 쪽부터 `ALL`(풀 스캔) → `index`(인덱스 전체 스캔) → `range` → `ref` → `eq_ref` → `const` 순입니다([EXPLAIN 출력](https://dev.mysql.com/doc/refman/8.4/en/explain-output.html)). 인덱스를 만들면 이렇게 바뀝니다.

```sql
CREATE INDEX idx_orders_customer ON orders (customer_id);
```

```text
type: ref
key:  idx_orders_customer
rows: 14
```

`rows`가 **추정치**라는 점이 중요합니다. 통계가 낡으면 이 숫자가 현실과 크게 어긋나고, 옵티마이저는 그 어긋난 숫자로 판단합니다. 실제 값이 필요하면 `EXPLAIN ANALYZE`를 씁니다. 쿼리를 실제로 실행하고 이터레이터마다 추정 비용·추정 행 수와 함께 **실제 소요 시간, 실제 반환 행 수, 반복 횟수**를 보여줍니다([EXPLAIN 문서](https://dev.mysql.com/doc/refman/8.4/en/explain.html), MySQL 8.4 기준). 출력 포맷은 `TREE`만 지원하며 `FORMAT=JSON`을 같이 쓰면 오류가 납니다.

```text
-- Index lookup on orders using idx_orders_customer  (cost=4.9 rows=14)
   (actual time=0.031..0.048 rows=12 loops=1)
```

`rows=14`(추정)와 `rows=12`(실제)가 붙어 나옵니다. 이 둘이 자릿수 단위로 벌어지면 통계 문제를 먼저 의심합니다.

## 5. 인덱스를 만들었는데 안 빨라지는 경우

인덱스 생성이 곧 개선은 아닙니다. 자주 마주치는 순서대로 정리합니다.

**카디널리티가 낮습니다.** `status` 컬럼에 값이 `PAID`, `CANCELED` 둘뿐인데 인덱스를 겁니다. 절반이 매칭되면 3-3의 랜덤 접근이 50만 번 발생하므로 옵티마이저는 스캔을 고릅니다. 문서가 말하는 "매칭되는 행이 많은 낮은 카디널리티 키"가 이 경우입니다. 값 분포가 극단적으로 치우쳐 있다면(예: 99%가 `PAID`) 소수 값을 찾는 쿼리에는 여전히 유효합니다. 컬럼만 보지 말고 **찾으려는 값의 빈도**를 봅니다.

**컬럼을 가공했습니다.** `WHERE DATE(created_at) = '2026-08-23'` 는 `created_at` 인덱스를 타지 못합니다. 인덱스에 저장된 건 `created_at`이지 `DATE(created_at)`이 아니기 때문입니다. 범위 조건으로 바꿔 씁니다.

```sql
-- ❌ 인덱스를 못 탑니다
WHERE DATE(created_at) = '2026-08-23'

-- ✔️ 인덱스를 탑니다
WHERE created_at >= '2026-08-23 00:00:00'
  AND created_at <  '2026-08-24 00:00:00'
```

**컬럼 순서가 안 맞습니다.** 복합 인덱스는 **가장 왼쪽 접두사(leftmost prefix)** 로만 쓰입니다. `(customer_id, status, created_at)` 인덱스는 `(customer_id)`, `(customer_id, status)`, 세 개 전부에는 쓰이지만 `(status)` 단독 조회에는 쓰이지 않습니다([인덱스 사용 방식](https://dev.mysql.com/doc/refman/8.4/en/mysql-indexes.html)).

**통계가 낡았습니다.** 대량 적재나 대량 삭제 직후에 잘 생깁니다. `ANALYZE TABLE orders;` 로 키 분포를 갱신합니다.

## 6. 공짜가 아닙니다 — 쓰기 쪽 청구서

인덱스는 읽기 성능을 사고 쓰기 성능과 저장 공간을 파는 거래입니다.

**쓰기 증폭.** `INSERT` 한 번은 인덱스 개수 + 1개의 B+Tree를 갱신합니다. 인덱스 5개면 트리 6개를 만집니다. `UPDATE`는 바뀐 컬럼이 걸린 인덱스만 건드리지만, 그 컬럼이 마침 인덱스 컬럼이면 **삭제 + 삽입**이라 더 비쌉니다. PostgreSQL 문서도 인덱스가 데이터 조작 작업에 오버헤드를 더하며 잘 안 쓰이는 인덱스는 제거해야 한다고 명시합니다([PostgreSQL 인덱스 소개](https://www.postgresql.org/docs/17/indexes-intro.html)).

**페이지 분할.** 인덱스 레코드가 순차 순서로 들어오면 페이지는 약 **15/16까지 차고**, 무작위 순서로 들어오면 **1/2에서 15/16 사이**로 찹니다([InnoDB 물리 구조](https://dev.mysql.com/doc/refman/8.4/en/innodb-physical-structure.html)). 무작위 삽입은 가득 찬 페이지 중간에 끼어들면서 페이지를 쪼갭니다. 쪼개진 페이지는 절반만 채워진 채 남아 인덱스 전체가 부풀고, 그만큼 읽을 페이지도 늘어납니다.

이것이 **기본 키에 랜덤 UUID를 쓰면 안 되는 이유**입니다. 클러스터형 인덱스가 곧 테이블이므로 삽입이 테이블 전역에 흩어지고, 게다가 그 긴 값이 모든 세컨더리 인덱스에 복제됩니다. 정렬 가능한 형태(UUIDv7 등)를 쓰거나 자동 증가 정수를 씁니다.

**저장 공간과 운영 시간.** 인덱스도 백업 대상이고 복구 시간에 반영됩니다.

**PostgreSQL 쪽 추가 비용.** 인덱스는 힙 온리 튜플(HOT) 생성을 방해합니다. 인덱스가 걸리지 않은 컬럼만 갱신할 때 쓰는 최적화라, 인덱스가 늘수록 `UPDATE`가 더 무거워집니다.

## 7. 예제 — 컬럼마다 인덱스를 거는 습관

### 7-1. 흔한 대응 ❌

느린 쿼리를 발견하고 `WHERE`에 나온 컬럼마다 인덱스를 답니다.

```sql
-- ❌ 조건에 등장한 컬럼을 하나씩
CREATE INDEX idx_orders_customer   ON orders (customer_id);
CREATE INDEX idx_orders_status     ON orders (status);
CREATE INDEX idx_orders_created    ON orders (created_at);
```

```sql
SELECT order_id, amount
FROM orders
WHERE customer_id = 4021
  AND status = 'PAID'
ORDER BY created_at DESC
LIMIT 20;
```

옵티마이저는 이 중 **가장 선택적인 인덱스 하나**를 고르는 게 보통입니다. `idx_orders_customer`로 그 고객의 주문을 전부 꺼내고, `status` 필터링과 `created_at` 정렬은 그 뒤에 따로 합니다. `Extra`에 `Using where; Using filesort`가 남습니다. **인덱스 3개 값을 쓰기 쪽에 지불하고, 읽기 쪽에서는 1개만큼 받았습니다.**

### 7-2. 개선 ✔️

쿼리의 접근 순서에 맞춰 복합 인덱스 하나로 만듭니다.

```sql
-- ✔️ 등치 조건 → 정렬 컬럼 순서
CREATE INDEX idx_orders_customer_status_created
    ON orders (customer_id, status, created_at);

DROP INDEX idx_orders_customer ON orders;   -- 왼쪽 접두사로 대체됩니다
```

- `customer_id`, `status`로 리프의 범위를 좁힙니다.
- 그 범위 안에서 `created_at`이 이미 정렬돼 있으므로 `filesort`가 사라지고, `LIMIT 20`은 리프 연결을 따라 20건만 읽고 끝냅니다.
- `idx_orders_customer`는 새 인덱스의 왼쪽 접두사에 포함되므로 중복입니다. 지웁니다.

`(customer_id, status)`만 있고 `created_at`이 없으면 정렬이 남습니다. **정렬 컬럼까지 인덱스에 넣는 것이 `ORDER BY ... LIMIT` 쿼리에서 가장 크게 먹히는 부분입니다.**

## 8. 함정

### 함정 1 — 개발 DB에선 10ms, 운영에선 8초

- **증상**: 로컬과 개발 서버에서는 빠릅니다. 운영에 올리면 같은 쿼리가 느립니다. 코드도 스키마도 같습니다.
- **원인**: 두 가지가 겹칩니다. 첫째, 데이터가 1만 건일 때는 테이블 전체가 몇 MB라 풀 스캔도 버퍼 풀 안에서 끝납니다. 둘째, 옵티마이저는 작은 테이블에서는 **의도적으로** 풀 스캔을 고릅니다(2-3). 즉 개발 환경에서는 인덱스가 없어도 빠른 게 아니라, **인덱스가 있어도 안 쓰는 게 정답인 상태**입니다. 그래서 개발 환경의 `EXPLAIN`은 운영의 계획을 예측해주지 못합니다.
- **해법**: 인덱스 판단은 운영과 비슷한 규모의 데이터에서 합니다. 운영 데이터를 복제하기 어렵다면 최소한 행 수만이라도 비슷하게 만든 뒤 `EXPLAIN`을 봅니다. 운영에서 계획만 확인하려면 `EXPLAIN`은 쿼리를 실행하지 않으므로 안전합니다. `EXPLAIN ANALYZE`는 실제로 실행하니 조회 쿼리에만 씁니다.

### 함정 2 — `SELECT COUNT(*)`가 갑자기 느려집니다

- **증상**: 목록 API에서 총 건수를 세는 쿼리만 유독 느립니다. 인덱스도 걸려 있습니다.
- **원인**: **InnoDB는 테이블의 행 수를 따로 저장하지 않습니다.** 동시에 실행 중인 트랜잭션마다 보이는 행 수가 다를 수 있기 때문입니다. 그래서 `COUNT(*)`는 현재 트랜잭션에 보이는 행을 실제로 세고, 이때 **가장 작은 세컨더리 인덱스를 훑습니다.** 세컨더리 인덱스가 없으면 클러스터형 인덱스를 스캔합니다([집계 함수](https://dev.mysql.com/doc/refman/8.4/en/aggregate-functions.html)). 인덱스 레코드가 버퍼 풀에 다 올라와 있지 않으면 그만큼 시간이 걸립니다. `WHERE` 조건이 붙으면 세는 범위가 다시 넓어집니다.
- **해법**: 정확한 총 건수가 정말 필요한지부터 되묻습니다. 페이지네이션이라면 커서 방식으로 바꿔 총건수를 없애는 쪽이 근본적입니다(`day15-pagination-api.md`). 근사치로 충분하면 `EXPLAIN`의 `rows` 추정치나 별도 집계 테이블을 씁니다. 꼭 세야 한다면 세는 범위를 커버하는 작은 인덱스를 하나 두는 것이 효과가 있습니다.

### 함정 3 — 인덱스를 지웠더니 다른 쿼리가 죽었습니다

- **증상**: 안 쓰는 것 같은 인덱스를 `DROP` 했더니 관계없어 보이던 배치나 관리자 화면이 타임아웃 납니다. 되돌리려니 수천만 행 테이블의 인덱스 재생성이라 시간이 오래 걸립니다.
- **원인**: 그 인덱스를 쓰던 쿼리가 어딘가에 있었습니다. 인덱스 사용처는 코드 검색으로는 안 잡힙니다. 옵티마이저가 고르는 것이지 코드에 이름이 적혀 있지 않기 때문입니다.
- **해법**: 지우기 전에 **INVISIBLE로 먼저 바꿉니다.** 옵티마이저는 안 쓰지만 인덱스 유지는 그대로 계속되므로, 문제가 생기면 즉시 되돌릴 수 있습니다([Invisible Indexes](https://dev.mysql.com/doc/refman/8.4/en/invisible-indexes.html)).

  ```sql
  ALTER TABLE orders ALTER INDEX idx_orders_status INVISIBLE;
  -- 며칠 관찰 후 문제 없으면
  ALTER TABLE orders DROP INDEX idx_orders_status;
  -- 문제가 생기면 즉시
  ALTER TABLE orders ALTER INDEX idx_orders_status VISIBLE;
  ```

  후보를 찾을 때는 `sys.schema_unused_indexes` 뷰를 봅니다. 다만 Performance Schema 계측이 켜져 있어야 하고, **서버가 대표적인 워크로드를 충분히 겪은 뒤**에야 의미가 있습니다([sys.schema_unused_indexes](https://dev.mysql.com/doc/refman/8.4/en/sys-schema-unused-indexes.html)). 월 1회 배치가 쓰는 인덱스는 하루 관찰로는 안 잡힙니다.

### 함정 4 — 인덱스만 계속 늘어납니다

- **증상**: 느린 쿼리가 나올 때마다 인덱스를 추가합니다. 조회는 나아지는데 어느 순간부터 `INSERT` 지연이 올라가고, 대량 적재 배치 시간이 길어집니다. 디스크 사용량도 예상보다 빨리 찹니다.
- **원인**: 6절의 쓰기 증폭입니다. 추가할 때마다 비용은 눈에 안 띄게 조금씩 늘고, 어느 인덱스 하나가 원인이 아니라 **총합이 원인**이라 범인을 지목하기 어렵습니다. 게다가 왼쪽 접두사 규칙 때문에 `(a)`와 `(a, b)`처럼 **완전히 중복된 인덱스**가 쌓이기 쉽습니다.
- **해법**: 인덱스를 추가하기 전에 기존 인덱스로 커버되는지 먼저 확인합니다. `(a)`를 새로 만들려는데 `(a, b)`가 이미 있으면 필요 없습니다. 반대로 `(a)`가 있는 상태에서 `(a, b)`를 만들면 `(a)`는 지웁니다. 중복 후보는 `sys.schema_redundant_indexes` 뷰로 찾습니다. 그리고 인덱스 추가는 되돌리기 어려운 변경이라는 걸 기억합니다. 큰 테이블에서는 만드는 것도 지우는 것도 비쌉니다.

## 9. 참고자료

- [How MySQL Uses Indexes](https://dev.mysql.com/doc/refman/8.4/en/mysql-indexes.html) — 왼쪽 접두사 규칙, 커버링 인덱스, 풀 스캔이 유리한 조건
- [Clustered and Secondary Indexes](https://dev.mysql.com/doc/refman/8.4/en/innodb-index-types.html) — 2-1, 3-3의 근거
- [InnoDB Physical Structure](https://dev.mysql.com/doc/refman/8.4/en/innodb-physical-structure.html) — 16KB 페이지, 15/16 채움 비율
- [InnoDB Row Formats](https://dev.mysql.com/doc/refman/8.4/en/innodb-row-format.html) — 숨은 6바이트 row ID, 트랜잭션 ID·롤 포인터
- [Avoiding Full Table Scans](https://dev.mysql.com/doc/refman/8.4/en/table-scan-avoidance.html) — 2-3
- [EXPLAIN Output Format](https://dev.mysql.com/doc/refman/8.4/en/explain-output.html) / [EXPLAIN Statement](https://dev.mysql.com/doc/refman/8.4/en/explain.html) — `type`, `rows`, `EXPLAIN ANALYZE`
- [Invisible Indexes](https://dev.mysql.com/doc/refman/8.4/en/invisible-indexes.html) — 함정 3
- [Aggregate Functions](https://dev.mysql.com/doc/refman/8.4/en/aggregate-functions.html) — 함정 2의 `COUNT(*)` 동작
- [PostgreSQL 17 — Introduction to Indexes](https://www.postgresql.org/docs/17/indexes-intro.html) — 인덱스 유지 비용, HOT 방해
- `day15-pagination-api.md` — 총건수를 없애는 커서 페이지네이션
- `day05-join-types.md` — 조인이 인덱스를 어떻게 쓰는지의 전제

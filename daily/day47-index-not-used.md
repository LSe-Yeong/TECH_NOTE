# 인덱스가 있는데 왜 안 타는가

> 이 문서가 답할 질문: **인덱스를 분명히 만들었는데 실행계획은 풀스캔을 가리킵니다. 원인을 어떤 순서로 좁히고, 각각을 어떻게 고치는가?**
>
> 기준: MySQL 8.4 LTS / InnoDB, PostgreSQL 18 (2026년 10월 확인). `day23-btree-index.md`의 B+Tree 구조, `day29-explain-plan.md`의 실행계획 읽는 법, `day35-composite-index-order.md`의 컬럼 순서를 전제로 합니다.

## 1. 핵심 개념 — "못 쓴다"와 "안 쓴다"는 다른 문제입니다

인덱스는 켜면 작동하는 기능이 아닙니다. **정렬된 자료구조를 탐색할 수 있는 조건이 성립할 때만** 쓸 수 있는 접근 경로입니다. 조건이 깨지면 엔진은 아무 에러도 내지 않고 조용히 테이블을 처음부터 끝까지 읽습니다.

증상은 늘 똑같습니다. `type: ALL`, 또는 PostgreSQL의 `Seq Scan`. 그런데 원인은 성격이 전혀 다른 두 갈래입니다.

```
A. 못 쓴다 (structurally impossible)
   인덱스 순서로는 그 조건을 만족하는 구간을 특정할 수 없다.
   → 옵티마이저에게 선택권이 없다. 힌트를 줘도 안 된다.
   → 쿼리나 인덱스 자체를 바꿔야 한다.

B. 안 쓴다 (cost-based decision)
   쓸 수는 있는데, 옵티마이저가 풀스캔이 더 싸다고 계산했다.
   → 선택권이 있었고 선택을 한 것이다.
   → 계산의 근거(통계)가 맞는지 먼저 따져야 한다.
```

> 이 구분을 건너뛰면 대부분 `FORCE INDEX`로 끝냅니다. B였다면 성능이 더 나빠지고, A였다면 힌트가 아예 먹지 않습니다. 둘 다 원인은 그대로 남습니다. 그래서 진단 순서가 해법보다 먼저입니다.

MySQL 문서는 B의 정당성을 명시합니다. **"쿼리가 대부분의 행에 접근해야 할 때는 인덱스를 거치는 것보다 순차적으로 읽는 게 빠릅니다"**([How MySQL Uses Indexes](https://dev.mysql.com/doc/refman/8.4/en/mysql-indexes.html)). 풀스캔은 실패가 아니라 선택지입니다.

---

## 2. A — 구조적으로 못 쓰는 경우들

공통 원리가 하나입니다. **인덱스는 컬럼의 원본 값으로 정렬되어 있습니다.** 비교하기 전에 컬럼 값을 가공해야 한다면, 가공된 값의 순서는 인덱스 순서와 무관하므로 탐색할 구간을 특정할 수 없습니다.

### 2-1. 컬럼에 함수나 연산을 씌웠습니다

```sql
-- ❌ 인덱스가 ordered_at으로 정렬돼 있어도 DATE(ordered_at)의 순서는 모릅니다
SELECT order_id FROM orders WHERE DATE(ordered_at) = '2026-10-04';

-- ❌ email 인덱스는 원본 대소문자로 정렬돼 있습니다
SELECT user_id FROM users WHERE LOWER(email) = 'kim@example.com';

-- ❌ 산술 연산도 같습니다
SELECT order_id FROM orders WHERE total_amount * 1.1 > 11000;
```

해법은 셋 중 하나입니다. 위에서부터 시도합니다.

```sql
-- ✔️ 1순위: 컬럼을 그대로 두고 조건을 범위로 바꿉니다 (sargable 변환)
SELECT order_id FROM orders
WHERE ordered_at >= '2026-10-04 00:00:00' AND ordered_at < '2026-10-05 00:00:00';

-- ✔️ 1순위: 연산을 상수 쪽으로 옮깁니다
SELECT order_id FROM orders WHERE total_amount > 11000 / 1.1;

-- ✔️ 2순위: 바꿀 수 없는 식이면 그 식 자체를 인덱싱합니다 (MySQL 8.0.13+)
ALTER TABLE users ADD INDEX idx_email_lower ((LOWER(email)));
```

함수형 인덱스(functional index)에는 함정이 붙어 있습니다. **인덱스의 식과 `WHERE`의 식이 완전히 같아야** 합니다. MySQL 문서가 직접 든 예입니다 — `(SUBSTRING(col1, 1, 10))`으로 인덱스를 만들면 `SUBSTRING(col1, 1, 9)` 조건은 인덱스를 타지 않고, 인수가 똑같은 `SUBSTRING(col1, 1, 10)`만 탑니다([CREATE INDEX](https://dev.mysql.com/doc/refman/8.4/en/create-index.html)). 문법도 괄호를 두 번 써야 합니다. `INDEX (col1 + col2)`는 에러고 `INDEX ((col1 + col2))`가 맞습니다.

### 2-2. 암묵적 타입 변환이 컬럼 쪽에서 일어납니다

이게 가장 찾기 어렵습니다. 쿼리를 봐도 이상한 데가 없기 때문입니다.

```sql
-- 전화번호를 VARCHAR로 저장한 테이블
CREATE TABLE members (
    member_id BIGINT      NOT NULL AUTO_INCREMENT,
    phone     VARCHAR(20) NOT NULL,
    PRIMARY KEY (member_id),
    KEY idx_phone (phone)
) ENGINE = InnoDB;

-- ❌ 따옴표를 안 붙였습니다. 인덱스를 못 씁니다.
SELECT member_id FROM members WHERE phone = 01012345678;
```

MySQL 문서의 설명이 명확합니다. 문자열 컬럼과 숫자를 비교하면 둘 다 부동소수점으로 변환해 비교하는데, **`1`로 변환되는 문자열이 `'1'`, `' 1'`, `'1a'`처럼 여러 개라서 인덱스로 값을 찾을 수 없습니다**([Type Conversion in Expression Evaluation](https://dev.mysql.com/doc/refman/8.4/en/type-conversion.html)).

실무에서는 SQL을 손으로 쓸 때보다 **애플리케이션이 바인딩할 때** 더 많이 터집니다. DTO 필드를 `Long phone`으로 선언해두면 JPA가 숫자로 바인딩합니다.

```java
// ❌ 파라미터 타입이 컬럼 타입과 다릅니다 — SQL은 정상, 인덱스만 안 탑니다
@Query("select m.memberId from Member m where m.phone = :phone")
List<Long> findIdsByPhone(@Param("phone") Long phone);

// ✔️ 컬럼이 VARCHAR면 파라미터도 String입니다
List<Long> findIdsByPhone(@Param("phone") String phone);
```

<!-- TODO: 확인 필요 — 반대 방향(숫자 컬럼을 문자열 상수와 비교, `WHERE int_col = '1'`)은
     상수 쪽만 변환되므로 인덱스를 탄다고 알려져 있으나 MySQL 8.4 문서가 명시한 건
     "문자열 컬럼 vs 숫자" 한 방향뿐입니다. 쓰는 환경에서 EXPLAIN으로 직접 확인하세요. -->

콜레이션 불일치도 같은 범주입니다. `utf8mb4` 컬럼과 `utf8mb3` 컬럼을 조인하면 한쪽을 변환해야 하고, 변환되는 쪽이 조회 대상 컬럼이면 그 인덱스로 `ref` 접근을 못 합니다. 테이블은 하나씩 만들어지므로 오래된 테이블과 새 테이블이 섞인 스키마에서 잘 나옵니다.

<!-- TODO: 확인 필요 — "Cannot use ref access on index ... due to type or collation conversion"
     경고를 EXPLAIN 직후 SHOW WARNINGS로 볼 수 있다는 보고가 있으나(MySQL Bug #83856),
     8.4 레퍼런스 매뉴얼에서 이 경고의 정식 설명을 확인하지 못했습니다. -->

### 2-3. LIKE가 와일드카드로 시작합니다

```sql
-- ✔️ 범위 접근 가능 — 'kim'으로 시작하는 구간은 인덱스에서 연속입니다
SELECT user_id FROM users WHERE email LIKE 'kim%';

-- ❌ 불가능 — '...@example.com'으로 끝나는 값들은 인덱스 전체에 흩어져 있습니다
SELECT user_id FROM users WHERE email LIKE '%@example.com';
```

MySQL은 범위 조건의 정의에 이걸 못 박아뒀습니다. `LIKE` 인수가 **와일드카드로 시작하지 않는 상수 문자열**일 때만 범위 조건입니다([Range Optimization](https://dev.mysql.com/doc/refman/8.4/en/range-optimization.html)).

해법은 "LIKE를 고치는" 게 아니라 **문제를 접두사 검색으로 바꾸는** 것입니다.

- 도메인만 찾는다면 도메인을 별도 컬럼으로 분리하고 그 컬럼에 인덱스를 겁니다.
- 뒤에서부터 찾아야 한다면 뒤집은 값을 함수형 인덱스로 만들고 `REVERSE()`로 접두사 검색합니다.
- 진짜 부분 문자열 검색이 필요하면 인덱스로 풀 문제가 아닙니다. 전문 검색(FULLTEXT)이나 별도 검색 엔진의 영역입니다.

### 2-4. 복합 인덱스의 선두 컬럼이 조건에 없습니다

MySQL은 복합 인덱스의 **왼쪽 접두사(leftmost prefix)만** 탐색에 쓸 수 있습니다. `(col1, col2, col3)` 인덱스는 `(col1)`, `(col1, col2)`, `(col1, col2, col3)`에만 쓰입니다([How MySQL Uses Indexes](https://dev.mysql.com/doc/refman/8.4/en/mysql-indexes.html)).

```sql
KEY idx_shop_status_date (shop_id, status, ordered_at)

-- ✔️ 탑니다
WHERE shop_id = 7 AND status = 'PAID'
-- ❌ 안 탑니다 — shop_id 없이는 status 구간을 특정할 수 없습니다
WHERE status = 'PAID' AND ordered_at >= '2026-10-01'
```

여기서 혼동이 하나 생깁니다. 실행계획에 `type: index`가 나오면 인덱스를 탄 것처럼 보이지만, 이건 **인덱스 풀스캔**입니다. 탐색을 못 해서 인덱스 전체를 훑는 것이고, 커버링이 아니면 행을 가지러 테이블까지 갑니다. 풀스캔보다 나쁠 수 있습니다. `type: ref`/`range`와 `type: index`는 다른 이야기입니다.

### 2-5. `OR`로 묶인 조건이 서로 다른 컬럼입니다

```sql
SELECT order_id FROM orders WHERE shop_id = 7 OR coupon_id = 300;
```

`shop_id`와 `coupon_id`에 각각 인덱스가 있으면 MySQL은 두 인덱스를 각각 스캔해 합치는 **Index Merge**를 시도할 수 있습니다(`Extra: Using union(...)`). 하지만 보장되지 않습니다. 중첩이 깊은 `AND`/`OR`에서는 최적 계획이 안 나오고, 문서는 이럴 때 `(x AND y) OR z → (x OR z) AND (y OR z)` 같은 항등 변환으로 조건을 분배해보라고 권합니다([Index Merge Optimization](https://dev.mysql.com/doc/refman/8.4/en/index-merge-optimization.html)).

더 확실한 해법은 `UNION`으로 쪼개서 각 쿼리가 자기 인덱스를 타게 만드는 것입니다. 중복 제거가 필요 없으면 `UNION ALL`을 씁니다.

```sql
-- ✔️ 각 분기가 독립적으로 자기 인덱스를 탑니다
SELECT order_id FROM orders WHERE shop_id = 7
UNION
SELECT order_id FROM orders WHERE coupon_id = 300;
```

---

## 3. B — 쓸 수 있는데 안 쓰는 경우들

여기서 `FORCE INDEX`를 꺼내면 안 됩니다. 옵티마이저의 계산이 맞는지 틀린지를 먼저 봐야 합니다.

### 3-1. 선택도가 낮습니다 — 옵티마이저가 맞습니다

`status` 컬럼에 인덱스가 있는데 전체 행의 70%가 `'PAID'`라면, `WHERE status = 'PAID'`는 인덱스를 타봐야 손해입니다. 세컨더리 인덱스에서 70%의 PK를 뽑아 클러스터형 인덱스를 70만 번 랜덤 접근하는 대신, 테이블을 순차로 한 번 읽는 게 빠릅니다(`day41-covering-index.md`의 2단계 비용).

**이 경우는 고치는 게 아니라 받아들입니다.** 그래도 빠르게 해야 한다면 선택도가 높은 컬럼을 앞에 둔 복합 인덱스를 만들거나, 커버링 인덱스로 2단계를 없앱니다.

### 3-2. 통계가 낡았습니다 — 옵티마이저가 틀렸습니다

대량 배치가 돌아간 직후, 또는 테이블을 새로 적재한 직후에 멀쩡했던 쿼리가 갑자기 풀스캔으로 바뀌면 거의 이쪽입니다.

InnoDB는 `innodb_stats_persistent`가 기본 ON이고, `innodb_stats_auto_recalc`도 기본 ON이라 **행의 10% 이상이 변경되면** 통계를 자동 재계산합니다. 문제는 이게 백그라운드 비동기 작업이라는 점입니다. 문서는 **"최신 통계가 즉시 필요하면 `ANALYZE TABLE`을 실행해 동기(포그라운드) 재계산을 시작하라"**고 명시합니다([Configuring Persistent Optimizer Statistics](https://dev.mysql.com/doc/refman/8.4/en/innodb-persistent-stats.html)).

```sql
-- 추정이 실제와 얼마나 벌어졌는지 확인합니다
EXPLAIN ANALYZE SELECT order_id FROM orders WHERE shop_id = 7 AND status = 'PAID';
-- rows=12 (estimated) vs actual rows=48000 처럼 자릿수가 다르면 통계 문제입니다

ANALYZE TABLE orders;
```

같은 문서는 `mysql.innodb_index_stats`의 추정 카디널리티와 `SELECT DISTINCT`로 구한 실제 카디널리티를 비교해 정확도를 점검하는 방법도 안내합니다.

### 3-3. 값의 분포가 심하게 치우쳐 있습니다

카디널리티는 평균값이라 분포를 모릅니다. `status`가 `PAID` 95%, `REFUNDED` 0.1%라면 두 값의 최적 계획은 정반대인데 평균만으로는 구분되지 않습니다. 이때 **히스토그램**을 만들어 분포를 알려줍니다.

```sql
ANALYZE TABLE orders UPDATE HISTOGRAM ON status WITH 16 BUCKETS;
```

히스토그램은 인덱스가 아니라 통계라서 DML 때마다 갱신되지 않습니다. 분포가 바뀌면 다시 만들어야 합니다.

---

## 4. 진단 순서

원인을 아무 데서나 찾지 않습니다. 비용이 싼 확인부터 합니다.

1. **`EXPLAIN`으로 `type`과 `key`를 봅니다.** `key: NULL`이면 인덱스를 아예 안 쓴 것, `type: index`면 탐색 없이 훑은 것입니다.
2. **`EXPLAIN` 직후 `SHOW WARNINGS`를 봅니다.** 타입·콜레이션 변환이 있으면 여기서 단서가 나올 수 있습니다.
3. **`WHERE`에서 컬럼 쪽이 가공되는지 봅니다.** 함수, 연산, 타입 불일치. A의 2-1, 2-2입니다.
4. **복합 인덱스 선두 컬럼이 조건에 있는지 봅니다.** A의 2-4입니다.
5. 여기까지 깨끗하면 B입니다. **`EXPLAIN ANALYZE`로 추정 행 수와 실제 행 수를 비교합니다.** 자릿수가 다르면 통계, 비슷하면 옵티마이저 판단이 맞습니다.
6. 판단이 맞다면 쿼리가 읽어야 할 데이터 자체를 줄입니다. 인덱스 문제가 아닙니다.

`FORCE INDEX`는 5번에서 통계를 고쳐도 계획이 안 바뀔 때, 임시 방편으로만 씁니다. `FORCE INDEX`는 **풀스캔을 아주 비싸다고 가정해, 지정한 인덱스로 행을 찾을 방법이 전혀 없을 때만 테이블 스캔을 쓰게** 만듭니다([Index Hints](https://dev.mysql.com/doc/refman/8.4/en/index-hints.html)). 즉 옵티마이저의 계산을 고치는 게 아니라 무시하게 만드는 것이고, 데이터가 늘어나 판단이 달라져야 할 시점에도 그대로 밀고 갑니다. 같은 문서는 `USE INDEX`/`FORCE INDEX`가 `JOIN_INDEX` 같은 최신 옵티마이저 힌트로 대체되며 폐기 예정이라고 밝히고 있습니다.

---

## 5. PostgreSQL에서 달라지는 것

원리는 같지만 두 지점이 다릅니다.

**표현식 인덱스는 처음부터 1급 기능입니다.** `CREATE INDEX test1_lower_col1_idx ON test1 (lower(col1));`을 만들면 `WHERE lower(col1) = 'value'`를 플래너가 **단순한 인덱스 컬럼 조회처럼 취급**합니다. 다만 식이 일치해야 하는 제약은 같고, 유지 비용이 따로 붙습니다 — 행을 삽입하거나 non-HOT 업데이트할 때마다 식을 계산해야 합니다([Indexes on Expressions](https://www.postgresql.org/docs/18/indexes-expressional.html)).

**`LIKE 'prefix%'`에 함정이 하나 더 있습니다.** 기본 연산자 클래스는 로케일 정렬 규칙을 따르는데, 패턴 매칭은 문자 단위 비교가 필요합니다. 그래서 DB가 표준 `C` 로케일이 아니면 패턴 매칭용으로 `text_pattern_ops` 계열 연산자 클래스로 인덱스를 따로 만들어야 합니다. 그리고 이 인덱스는 `<`, `<=`, `>`, `>=` 같은 **일반 범위 비교에는 쓸 수 없으므로** 기본 연산자 클래스 인덱스를 함께 두어야 합니다([Operator Classes and Operator Families](https://www.postgresql.org/docs/18/indexes-opclass.html)).

```sql
-- 로케일이 C가 아닌 DB에서 접두사 검색용 인덱스
CREATE INDEX idx_users_email_pattern ON users (email text_pattern_ops);
```

MySQL에는 이 구분이 없습니다. 컬럼 콜레이션이 곧 비교 규칙이라 접두사 `LIKE`가 별도 설정 없이 인덱스를 탑니다. PostgreSQL 경험을 그대로 옮기거나 반대로 옮기면 어긋나는 지점입니다.

---

## 6. 함정

**① 인덱스를 추가해서 "고쳤다"고 끝냅니다**

- **증상**: 느린 쿼리마다 인덱스를 하나씩 붙여 한 테이블에 인덱스가 열 개를 넘어갑니다. 조회는 빨라졌는데 쓰기 지연과 복제 지연이 늘어납니다.
- **원인**: 인덱스는 모든 `INSERT`/`UPDATE`/`DELETE`에서 같이 갱신됩니다. 2-1의 1순위 해법(조건을 범위로 바꾸기)은 인덱스를 늘리지 않는데, 그걸 건너뛰고 2순위로 직행한 결과입니다.
- **해법**: 쿼리 수정 → 기존 인덱스 재설계 → 새 인덱스 추가 → 힌트, 이 순서를 지킵니다. `sys.schema_unused_indexes`로 안 쓰는 인덱스를 주기적으로 걷어냅니다.

**② 개발 DB에서 EXPLAIN을 보고 판단합니다**

- **증상**: 로컬에서는 인덱스를 타는데 프로덕션에서는 풀스캔입니다. 반대도 생깁니다.
- **원인**: B는 전부 데이터 분포와 통계에 의존합니다. 행이 1000건인 테이블에서는 풀스캔이 정말로 더 싸고, 옵티마이저는 맞게 판단한 겁니다.
- **해법**: A에 해당하는 원인(함수, 타입, 선두 컬럼)은 개발 DB에서도 그대로 재현되므로 거기서 잡습니다. B는 프로덕션과 유사한 규모·분포에서만 판단합니다. 운영 DB에서 확인해야 하면 읽기 전용 복제본에 `EXPLAIN`을 돌립니다.

**③ `IN` 리스트를 수천 개로 키웁니다**

- **증상**: `IN` 항목이 적을 때는 인덱스를 타다가, 배치에서 ID를 수천 개 넣으면 풀스캔으로 바뀝니다.
- **원인**: 두 가지가 겹칩니다. 옵티마이저는 `eq_range_index_dive_limit`를 넘으면 정확한 index dive 대신 덜 정확한 인덱스 통계로 비용을 추정합니다. 또 범위 최적화에 쓰는 메모리가 `range_optimizer_max_mem_size`를 넘으면 **범위 접근을 포기하고 풀스캔 같은 다른 방법으로 넘어갑니다**([Range Optimization](https://dev.mysql.com/doc/refman/8.4/en/range-optimization.html)). 문서는 `IN()` 리터럴 하나를 `OR` 술어 하나(약 230바이트)로 센다고 설명합니다.
- **해법**: `IN` 리스트를 몇백 건 단위로 쪼개 여러 번 질의합니다. 목록이 다른 테이블에서 나온 것이면 애플리케이션으로 올리지 말고 조인이나 서브쿼리로 DB 안에서 처리합니다.

**④ 인덱스는 탔는데 여전히 느립니다**

- **증상**: `type: range`로 바뀌었는데 응답 시간이 그대로입니다.
- **원인**: 이 문서의 문제가 아닙니다. 인덱스 탐색 다음에 남는 행 접근 비용(`day41-covering-index.md`) 또는 `Using filesort`/`Using temporary` 쪽입니다.
- **해법**: `EXPLAIN`의 `Extra`를 다시 봅니다. `type`만 보고 끝내지 않습니다.

---

## 7. 참고자료

- [How MySQL Uses Indexes — MySQL 8.4 Reference Manual](https://dev.mysql.com/doc/refman/8.4/en/mysql-indexes.html)
- [Range Optimization — MySQL 8.4](https://dev.mysql.com/doc/refman/8.4/en/range-optimization.html)
- [Type Conversion in Expression Evaluation — MySQL 8.4](https://dev.mysql.com/doc/refman/8.4/en/type-conversion.html)
- [CREATE INDEX Statement (functional key parts) — MySQL 8.4](https://dev.mysql.com/doc/refman/8.4/en/create-index.html)
- [Index Merge Optimization — MySQL 8.4](https://dev.mysql.com/doc/refman/8.4/en/index-merge-optimization.html)
- [Index Hints — MySQL 8.4](https://dev.mysql.com/doc/refman/8.4/en/index-hints.html)
- [Configuring Persistent Optimizer Statistics Parameters — MySQL 8.4](https://dev.mysql.com/doc/refman/8.4/en/innodb-persistent-stats.html)
- [Indexes on Expressions — PostgreSQL 18](https://www.postgresql.org/docs/18/indexes-expressional.html)
- [Operator Classes and Operator Families — PostgreSQL 18](https://www.postgresql.org/docs/18/indexes-opclass.html)
- 관련 챕터: `day23-btree-index.md`, `day29-explain-plan.md`, `day35-composite-index-order.md`, `day41-covering-index.md`

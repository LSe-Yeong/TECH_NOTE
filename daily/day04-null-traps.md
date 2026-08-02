# NULL이 만드는 예상치 못한 버그

## 1. 핵심 개념: NULL은 "알 수 없음"이다

- `NULL`은 빈 문자열도, 0도 아닙니다. **"값이 무엇인지 모른다"**는 상태입니다.
- 그래서 SQL은 참/거짓 두 값이 아니라 `TRUE`/`FALSE`/`UNKNOWN` **3치 논리**를 씁니다.
- 비교연산(`=`, `<>`), 논리연산(`AND`/`OR`/`NOT`), 집계함수(`COUNT`/`SUM`/`AVG`)가 전부 이 3치 논리의 영향을 받습니다.

> **`NOT IN` 목록에 `NULL`이 하나만 섞여도 쿼리 전체가 0행을 반환합니다.** 문법 오류가 없어서 결과가 빈 것을 데이터가 없어서 그런 거라고 오해하기 쉽습니다.

## 2. 구조

- **비교연산**: `col = NULL`, `col <> NULL`은 항상 `UNKNOWN`입니다. `TRUE`도 `FALSE`도 아닙니다.
- **논리연산**: `TRUE AND UNKNOWN`은 `UNKNOWN`, `FALSE OR UNKNOWN`도 `UNKNOWN`입니다. `WHERE`절은 `UNKNOWN`을 `FALSE`와 똑같이 취급해 그 행을 제외합니다.
- **집계함수**: `COUNT(컬럼)`, `SUM`, `AVG`, `MAX`, `MIN`은 전부 `NULL`을 무시하고 계산합니다.

### 2-1. 선택적 확장 지점

- 기본 동작은 `NULL`을 그대로 반환하거나 계산에서 빼는 것입니다.
- `COALESCE(컬럼, 기본값)`으로 `NULL`을 원하는 값으로 바꿔서 계산에 포함시킬 수 있습니다. MySQL은 인자 2개 전용인 `IFNULL(컬럼, 기본값)`도 지원합니다.

## 3. 흐름

### 3-1. 예제 테이블과 쿼리

```sql
-- customers: id, name, phone(nullable)
-- (1, '김철수', '010-1111-2222')
-- (2, '이영희', NULL)
-- (3, '박민수', '010-3333-4444')

SELECT * FROM customers WHERE phone <> '010-1111-2222';
```

### 3-2. 비교연산이 걸러지는 과정

```
김철수: '010-1111-2222' <> '010-1111-2222' → FALSE  → 제외
이영희: NULL <> '010-1111-2222'            → UNKNOWN → 제외
박민수: '010-3333-4444' <> '010-1111-2222' → TRUE   → 포함

결과: 박민수만 반환됨
(이영희는 "전화번호가 다르다"고 판단할 근거가 없을 뿐인데, UNKNOWN이 FALSE 취급되어 결과에서 빠집니다)
```

## 4. 특징

### 4-1. 사용 시기

- **NULL 허용**: "아직 값이 없다"는 상태 자체가 의미 있는 컬럼 (예: 배송완료일 — 배송 전에는 존재하지 않음)
- **NOT NULL 제약**: 값이 없으면 안 되는 컬럼 (예: 주문 금액, 고객 이름)

### 4-2. 장점

- "값이 없다"를 0이나 빈 문자열과 구분해서 표현할 수 있습니다. 배송이 안 된 것과 배송에 0일 걸린 것은 다른 의미입니다.

### 4-3. 단점 / 트레이드오프

- NULL을 허용하는 컬럼마다 비교·집계 로직에서 예외 케이스를 신경 써야 합니다.
- 애플리케이션 코드에서도 그 컬럼을 쓸 때마다 null 체크가 따라붙습니다.

## 5. 예제: `COUNT(*)` VS `COUNT(column)`

### 5-1. 클린하지 않은 코드 ❌

```sql
-- ❌ phone이 NULL인 고객은 세지 않는다 — "전체 고객 수"가 아니다
SELECT COUNT(phone) AS customer_count FROM customers;
```

- `COUNT(컬럼)`은 그 컬럼 값이 `NULL`이 아닌 행만 셉니다. 이영희처럼 전화번호가 없는 고객은 빠집니다.

### 5-2. `COUNT(*)`를 쓴 코드 ✔️

```sql
-- ✅ 행 자체를 센다 — 컬럼 값의 NULL 여부와 무관하게 정확한 전체 행 수
SELECT COUNT(*) AS customer_count FROM customers;
```

## 6. 3치 논리 원칙 준수

- `NULL`과의 비교는 항상 `UNKNOWN`입니다. `=`이나 `<>`로는 절대 `NULL` 여부를 판단할 수 없습니다.

### 6-1. 원칙을 어긴 코드 ❌

```sql
-- ❌ 항상 UNKNOWN — phone이 NULL인 행이 있어도 결과에 안 걸림
SELECT * FROM customers WHERE phone = NULL;
```

### 6-2. 원칙을 지킨 코드 ✔️

```sql
-- ✅ NULL 여부는 전용 연산자로 확인한다
SELECT * FROM customers WHERE phone IS NULL;
```

## 7. 확장 지점 응용하기 — COALESCE

### 7-1. 클린하지 않은 코드 ❌

```sql
-- ❌ MySQL CONCAT()은 인자 중 하나라도 NULL이면 전체 결과가 NULL
SELECT CONCAT(name, ' - ', phone) AS label FROM customers;
-- 이영희 행의 결과: NULL (이름까지 통째로 사라짐)
```

### 7-2. COALESCE를 적용한 코드 ✔️

```sql
-- ✅ NULL을 먼저 기본값으로 치환한 뒤 연결한다
SELECT CONCAT(name, ' - ', COALESCE(phone, '연락처 없음')) AS label FROM customers;
-- 이영희 행의 결과: '이영희 - 연락처 없음'
```

## 8. 실무에서 찾아보는 NULL 처리

- JPA `@Column(nullable = false)` — 컬럼 제약을 엔티티 매핑에 그대로 선언합니다.
- `Optional<T>` — 서비스 계층에서 값이 없을 수 있음을 타입으로 드러냅니다. (`daily/day01-di-why.md` 7장과 같은 패턴)
- MyBatis `<if test="phone != null">` — 동적 쿼리에서 파라미터가 `null`일 때 조건을 통째로 뺍니다.

## 9. 관련된 개념과 비교

### 9-1. MySQL VS PostgreSQL — `ORDER BY`의 NULL 정렬 위치

**유사점**

- 둘 다 정렬 결과에서 NULL이 앞에 오는지 뒤에 오는지 조정할 수 있습니다.

**차이점**

- PostgreSQL은 `ORDER BY col NULLS FIRST` / `NULLS LAST` 문법을 직접 지원합니다. 기본값은 `ASC`일 때 `NULLS LAST`(NULL이 가장 큰 값 취급)입니다.
- MySQL 8.0/8.4는 이 문법 자체가 없습니다. NULL을 가장 작은 값으로 취급해 `ASC` 정렬 시 기본적으로 맨 앞에 옵니다. NULL을 뒤로 보내려면 `ORDER BY (phone IS NULL), phone` 같은 트릭이 필요합니다.

## 10. 함정

**`NOT IN`에 NULL이 섞이면 전체 결과가 0행이 된다**

- **증상**: `WHERE id NOT IN (SELECT referred_by FROM customers)` 같은 서브쿼리가 데이터가 있는데도 결과를 0행 반환합니다.
- **원인**: `NOT IN (1, 2, NULL)`은 내부적으로 `<> 1 AND <> 2 AND <> NULL`로 풀립니다. `<> NULL`이 `UNKNOWN`이라 `TRUE AND TRUE AND UNKNOWN`도 `UNKNOWN`이 되고, 결국 모든 행이 걸러집니다.
- **해법**: `NOT IN` 대신 `NOT EXISTS`를 씁니다. `NOT EXISTS`는 값 비교가 아니라 "매칭되는 행이 있는가"만 확인하므로 NULL의 영향을 받지 않습니다.

```sql
-- ❌ referred_by에 NULL이 하나라도 있으면 전체가 0행
SELECT * FROM customers
WHERE id NOT IN (SELECT referred_by FROM customers);

-- ✅ NOT EXISTS는 NULL에 영향받지 않는다
SELECT * FROM customers c
WHERE NOT EXISTS (
    SELECT 1 FROM customers r WHERE r.referred_by = c.id
);
```

**`UNIQUE` 제약을 걸었는데 NULL이 여러 행에 들어간다**

- **증상**: `phone` 컬럼에 `UNIQUE` 제약을 걸었는데, `phone`이 `NULL`인 고객이 여러 명 등록됩니다.
- **원인**: `UNIQUE` 제약은 "값이 같으면 안 된다"는 규칙입니다. `NULL`은 값이 아니라 "알 수 없음"이라서 `NULL`끼리도 같다고 판단하지 않습니다. 대부분의 DB(MySQL, PostgreSQL 포함)가 `NULL`을 유일성 검사에서 예외로 취급해 여러 행에 허용합니다.
- **해법**: "값이 없는 것도 유일해야 한다"는 요구라면 `NULL` 대신 빈 문자열 같은 대체값을 쓰거나, 애플리케이션 레벨에서 별도로 검증합니다.

## 11. 참고자료

- [MySQL 8.0 Reference Manual — Working with NULL Values](https://dev.mysql.com/doc/refman/8.0/en/working-with-null.html)
- [MySQL 8.0 Reference Manual — Problems with NULL Values](https://dev.mysql.com/doc/refman/8.0/en/problems-with-null.html)
- `daily/day04-join-types.md` — JOIN에서 NULL로 채워지는 컬럼 다루기
- `07-database/05-index-not-used` — NULL이 인덱스 사용에 미치는 영향

# `VARCHAR(255)`가 기본값이 되면 안 되는 이유

> 이 문서가 답할 질문: **컬럼 타입을 무엇을 기준으로 고르고, 전부 `VARCHAR(255)`로 두면 실제로 무엇을 잃는가?**
>
> 기준: MySQL 8.4 LTS / InnoDB (`innodb_page_size` 16KB, `ROW_FORMAT=DYNAMIC`), PostgreSQL 18, JPA 3.1 / Hibernate 6 (2026년 10월 확인). `day17-why-index.md`의 인덱스 기초와 `day35-composite-index-order.md`의 복합 인덱스를 전제로 합니다.

## 1. 핵심 개념 — 타입은 저장 공간이 아니라 "선언"입니다

컬럼 타입을 고르는 일을 "이 값이 들어갈 만한 크기를 잡는 작업"으로 생각하면 `VARCHAR(255)`가 늘 정답으로 보입니다. 넉넉하고, 안 터지고, 고민이 없습니다.

타입은 크기 할당이 아닙니다. **이 컬럼에 들어올 수 있는 값의 집합을 DB에 알려주는 선언**입니다. 선언이기 때문에 두 가지가 따라옵니다.

1. DB가 그 범위를 **강제**합니다. 범위를 벗어난 값은 애플리케이션을 거치지 않고도 거부됩니다.
2. 다음 사람이 그 선언을 **스펙으로 읽습니다**. `VARCHAR(10)`은 "휴대폰 번호 정도"를 말하고, `VARCHAR(255)`는 아무것도 말하지 않습니다.

> `VARCHAR(255)`로 통일된 테이블은 제약이 없는 테이블입니다. 우편번호 컬럼에 소설이 들어가도 DB는 받아줍니다. 그 값은 몇 달 뒤 엑셀 익스포트가 깨질 때, 또는 외부 연동 API가 `length must be <= 10`을 돌려줄 때 발견됩니다. 그때는 이미 운영 데이터에 섞여 있어서 타입을 좁히는 `ALTER TABLE`이 데이터 정제 프로젝트가 됩니다.

이 챕터는 선택형입니다. 각 타입이 무엇을 보장하고 무엇을 포기하는지 비교해서, 고르는 순서를 정하는 게 목표입니다.

---

## 2. 255는 어디서 왔는가

두 개의 서로 무관한 이유가 겹쳐서 관습이 됐습니다.

**(1) 길이 프리픽스 1바이트.** MySQL은 가변 길이 문자열을 "길이 + 데이터"로 저장합니다. 문서는 이렇게 규정합니다 — 값이 0~255바이트면 길이에 1바이트, 255바이트를 넘을 수 있으면 2바이트를 씁니다([Data Type Storage Requirements](https://dev.mysql.com/doc/refman/8.4/en/storage-requirements.html)). 그래서 `VARCHAR(255)`가 "1바이트로 끝나는 최대치"라는 말이 돌았습니다.

여기에 함정이 있습니다. **기준은 글자 수가 아니라 바이트 수입니다.** utf8mb4는 한 글자가 최대 4바이트라서 `VARCHAR(255)`의 최대 길이는 1020바이트입니다. 255바이트를 넘으므로 길이 프리픽스는 **2바이트**입니다. 공식 문서도 ucs2 예시로 같은 이야기를 합니다. utf8mb4에서 1바이트 프리픽스를 유지하는 마지막 지점은 `VARCHAR(63)`입니다(63×4=252). 즉 **utf8mb4를 쓰는 지금 255는 아무 경계도 아닙니다.**

**(2) JPA 기본값.** JPA 명세의 `@Column(length)` 기본값이 255이고, Hibernate도 같은 값을 씁니다. 길이를 안 쓰면 DDL 생성기가 `varchar(255)`를 뱉습니다.

```java
@Entity
public class Member {
    // length를 안 적었습니다 → varchar(255)
    @Column(nullable = false)
    private String zipCode;

    @Column(nullable = false)
    private String phoneNumber;
}
```

정리하면, 255는 **latin1 시절의 바이트 경계**와 **프레임워크 기본값**이 만든 숫자입니다. 어떤 도메인 요구사항도 아닙니다.

---

## 3. 255를 기본값으로 두면 실제로 잃는 것

### 3-1. 통념의 절반은 이미 옛날 이야기입니다

"`VARCHAR(255)`는 임시 테이블과 정렬 버퍼를 선언 길이만큼 잡아먹는다"는 설명을 자주 봅니다. MySQL 5.6 시절에는 맞았습니다. 지금은 두 군데가 바뀌었습니다.

- **정렬 버퍼의 부가 컬럼(addon fields)**은 5.7.3부터 꽉 채워 담습니다. 그 전에는 `VARCHAR(255)`에 3글자가 들어 있어도 255바이트를 썼습니다([Filesort optimization in 5.7.3](https://dev.mysql.com/blog-archive/filesort-optimization-in-5-7-3-pack-values-in-the-sort-buffer/)). 8.4의 실행계획 트레이스에 보이는 `<sort_key, packed_additional_fields>`가 이 모드입니다([ORDER BY Optimization](https://dev.mysql.com/doc/refman/8.4/en/order-by-optimization.html)).
- **메모리 내부 임시 테이블**도 8.0부터 기본 엔진이 TempTable로 바뀌었습니다. 문서는 TempTable이 "VARCHAR과 VARBINARY 컬럼에 효율적인 저장을 제공한다"고 쓰고, 가변 길이 값은 NULL 플래그·길이·포인터로 이뤄진 16바이트 셀로 다룬다고 설명합니다([Internal Temporary Table Use in MySQL](https://dev.mysql.com/doc/refman/8.4/en/internal-temporary-tables.html)). 옛 MEMORY 엔진의 고정 길이 행 문제가 여기엔 없습니다.

그래서 "성능 때문에 255를 쓰지 마라"는 근거는 생각보다 약합니다. **진짜 비용은 성능이 아니라, 아래 세 개의 한계선을 미리 다 써버리는 것과 검증을 포기하는 것입니다.**

### 3-2. 행 크기 상한을 소진합니다

MySQL은 스토리지 엔진과 무관하게 **행 하나당 65,535바이트** 상한이 있습니다. 가변 길이 컬럼은 길이 바이트까지 이 계산에 들어갑니다([Limits on Table Column Count and Row Size](https://dev.mysql.com/doc/refman/8.4/en/column-count-limit.html)). 여기에 InnoDB는 더 빡빡한 자기 상한을 겹쳐 둡니다 — 페이지 안에 저장되는 행 크기가 "페이지의 절반보다 약간 작아야" 하고, 16KB 페이지에서는 에러 메시지가 정확한 숫자를 알려줍니다.

```
ERROR 1118 (42000): Row size too large (> 8126).
Changing some columns to TEXT or BLOB may help.
```

utf8mb4 `VARCHAR(255)`는 컬럼 하나가 최대 1022바이트(1020+2)를 선언합니다. 이런 컬럼을 늘려가다 보면 어느 날 컬럼 하나 추가하는 `ALTER TABLE`이 1118로 막힙니다. 터지는 시점은 **그 컬럼을 추가하는 사람**이고, 원인은 **3년 전에 전부 255로 만든 결정**입니다.

### 3-3. 인덱스 키 길이 상한에 먼저 부딪힙니다

16KB 페이지 기준 InnoDB 인덱스 키의 최대 길이는 **3072바이트**입니다. 페이지 크기를 8KB로 줄이면 1536바이트, 4KB면 768바이트로 비례해 줄어듭니다([InnoDB Limits](https://dev.mysql.com/doc/refman/8.4/en/innodb-limits.html)).

utf8mb4를 쓴다고 가정하고 숫자로 보면 이렇습니다.

| 인덱스 | utf8mb4 바이트 | 3072 이내 |
|---|---:|---|
| `VARCHAR(255)` 1개 | 1020 | 통과 |
| `VARCHAR(255)` 3개 복합 | 3060 | 간신히 통과 |
| `VARCHAR(255)` 4개 복합 | 4080 | ❌ ERROR 1071 |
| `VARCHAR(50)` 4개 복합 | 800 | 통과 |

`ROW_FORMAT`이 오래된 `COMPACT`/`REDUNDANT`로 남아 있으면 상한이 767바이트라서, `VARCHAR(255)` **한 개에도** 유니크 인덱스가 안 걸립니다. 이게 레거시 스키마에서 1071이 뜨는 전형적인 경로입니다.

### 3-4. TEXT로 도망가면 정렬이 조용히 틀립니다

3-2의 에러 메시지는 "일부 컬럼을 TEXT나 BLOB으로 바꾸면 도움이 될 수 있다"고 안내합니다. TEXT는 본문이 행 밖에 저장돼서 행 크기에 9~12바이트만 기여하므로 상한 문제는 실제로 풀립니다. 그런데 대가가 있습니다.

> 정렬할 때 컬럼의 앞 `max_sort_length` 바이트만 사용됩니다. `max_sort_length`의 기본값은 1024입니다. ([The BLOB and TEXT Types](https://dev.mysql.com/doc/refman/8.4/en/blob.html))

`ORDER BY`, `GROUP BY`, `DISTINCT`가 앞 1024바이트만 보고 판단합니다. 1024바이트까지 같고 그 뒤가 다른 두 값은 **같은 값으로 취급됩니다.** 경고도 없습니다.

<!-- TODO: 확인 필요 — MySQL 8.0 이후 이 절단 동작이 PAD SPACE 콜레이션에서만 유효하다는 보고(bugs.mysql.com #105910)가 있습니다. 8.0 기본 콜레이션 utf8mb4_0900_ai_ci는 NO PAD이므로 기본 설정에서의 실제 동작은 공식 문서로 확정하지 못했습니다. 긴 문자열을 정렬 키로 쓰지 않는다는 결론은 어느 쪽이든 같습니다. -->

---

## 4. 고르는 순서

성능 계산부터 하면 거의 항상 길을 잃습니다. 이 순서가 더 빠릅니다.

1. **이 값의 정체를 한 문장으로 적습니다.** "KRW 금액", "상품 상태", "가입 시각(UTC)". 여기서 막히면 타입이 문제가 아니라 모델링이 문제입니다.
2. **도메인이 정한 한계가 있으면 그걸 씁니다.** 국내 사업자등록번호는 10자리, 전화번호 E.164는 15자리, 이메일은 RFC 5321의 경로 상한 256옥텟. 숫자에 근거가 있으면 그게 길이입니다.
3. **한계가 없으면 "현실적 상한 × 여유"로 잡습니다.** 상품명에 1만 자가 올 일이 없으면 `VARCHAR(200)`입니다. 틀려도 `VARCHAR`를 늘리는 건 쉬운 변경이고, 줄이는 건 어려운 변경입니다.
4. **정밀도가 돈·계산에 걸리면 부동소수점을 배제합니다.**
5. **인덱스를 걸 컬럼은 폭을 한 번 더 깎습니다.** 인덱스 키는 행마다 복사되고 InnoDB 보조 인덱스에는 PK까지 함께 들어갑니다.

---

## 5. 타입별 선택 기준

### 5-1. 문자열

| 상황 | 선택 | 근거 |
|---|---|---|
| 길이가 고정이고 짧다 (국가코드, 성별 플래그) | `CHAR(n)` | 길이 프리픽스가 없고 길이 자체가 검증 |
| 가변이고 상한이 분명하다 | `VARCHAR(현실적 상한)` | 기본 선택 |
| 상한을 모르는 자유 텍스트 (본문, 메모) | `TEXT` | 행 크기 상한 회피. 대신 정렬 키로 쓰지 않음 |
| 길긴 하지만 유니크 제약이 필요하다 | 해시 컬럼 + 유니크 인덱스 | 3072바이트 키 상한 회피 |

### 5-2. 숫자

```sql
-- ❌ 돈을 DOUBLE로 저장했습니다
total_amount DOUBLE NOT NULL

-- ✔️ DECIMAL은 "정확한 수치 데이터"를 저장합니다
total_amount DECIMAL(13, 2) NOT NULL
```

MySQL 문서는 `DECIMAL`을 이렇게 설명합니다 — "정확한 정밀도를 보존하는 것이 중요할 때, 예를 들어 금전 데이터에 사용합니다"([Fixed-Point Types](https://dev.mysql.com/doc/refman/8.4/en/fixed-point-types.html)). 반대로 `FLOAT`/`DOUBLE`은 근사값 타입이라 `0.1`을 정확히 담지 못합니다. 합계가 1원씩 틀어지는 정산 버그의 대부분이 여기서 나옵니다.

트레이드오프도 있습니다. `DECIMAL`은 9자리를 4바이트로 묶어 저장하는 방식이라 `DOUBLE`(8바이트 고정)보다 넓어질 수 있고, 산술 연산도 부동소수점보다 느립니다. 금액·수량·좌표 정밀도처럼 **오차가 누적되면 안 되는 값**에만 쓰고, 통계·점수처럼 근사해도 되는 값은 `DOUBLE`로 둡니다.

정수는 저장 크기가 1·2·3·4·8바이트로 또렷하게 갈립니다([Data Type Storage Requirements](https://dev.mysql.com/doc/refman/8.4/en/storage-requirements.html)).

- PK는 `BIGINT`를 기본으로 둡니다. `INT AUTO_INCREMENT`는 약 21억에서 멈추고, 그때 하는 PK 타입 변경은 전 행 재작성입니다.
- 반대로 상태 코드·카운터 같은 좁은 값에 `BIGINT`를 쓰면 보조 인덱스마다 그 8바이트가 따라다닙니다. `TINYINT`로 충분하면 `TINYINT`입니다.
- `INT(11)`의 `11`은 **표시 폭**이고 저장 범위와 무관합니다. 범위를 바꾸려면 `TINYINT`/`BIGINT`로 타입을 바꿔야 합니다.

### 5-3. 시간

```sql
-- 서버·클라이언트 타임존에 따라 값이 달라져도 되는가?
created_at TIMESTAMP   -- 4바이트, UTC로 저장되고 읽을 때 세션 타임존으로 변환
starts_at  DATETIME    -- 5바이트, 저장한 문자 그대로. 변환 없음
```

문서가 명확합니다. MySQL은 `TIMESTAMP`를 현재 타임존에서 UTC로 바꿔 저장하고 읽을 때 되돌립니다. **`DATETIME` 같은 다른 타입에는 이 변환이 일어나지 않습니다**([The DATE, DATETIME, and TIMESTAMP Types](https://dev.mysql.com/doc/refman/8.4/en/datetime.html)). 그래서 쓰고 난 뒤 타임존이 바뀌면 `TIMESTAMP`는 다른 값으로 읽힙니다.

`TIMESTAMP`의 범위는 `'1970-01-01 00:00:01'` UTC부터 `'2038-01-19 03:14:07'` UTC까지입니다. 과거 생년월일이나 장기 계약 만료일에는 못 씁니다. 범위 밖 값은 에러가 아니라 0으로 변환됩니다.

- "사건이 일어난 절대 시각"(생성·수정 로그) → `TIMESTAMP`. 타임존 변환이 이득입니다.
- "달력 위의 약속"(이벤트 시작, 정기 결제일) → `DATETIME`. 변환되면 틀립니다.
- 소수 초가 필요 없으면 `(0)`을 유지합니다. `DATETIME(6)`은 `DATETIME(0)`보다 3바이트 더 씁니다.

### 5-4. 식별자 — UUID

`CHAR(36)`은 36바이트이고, `BINARY(16)`은 16바이트입니다. `UUID_TO_BIN()`/`BIN_TO_UUID()`로 변환하고, 두 번째 인수 `swap_flag`는 시간 기반 UUID의 time-low/time-high를 바꿔 **생성 순서대로 정렬되게** 만듭니다([Miscellaneous Functions](https://dev.mysql.com/doc/refman/8.4/en/miscellaneous-functions.html)).

InnoDB PK는 클러스터 인덱스이고 보조 인덱스에 전부 복사되므로 20바이트 차이가 테이블 전체에 곱해집니다. 다만 `swap_flag`는 v1 같은 시간 기반 UUID에만 의미가 있습니다. 랜덤인 **v4에는 효과가 없습니다** — v4를 PK로 쓰면 삽입 위치가 흩어지는 문제는 그대로 남습니다.

### 5-5. 상태값 — ENUM을 고르기 전에

`ENUM`은 매력적입니다. 값 집합이 255개 이하면 1바이트고, DB가 집합을 강제해줍니다. 그런데 정렬 규칙을 알아야 합니다.

> `ENUM` 값은 인덱스 번호를 기준으로 정렬되고, 이 번호는 컬럼 정의에 멤버를 나열한 순서를 따릅니다. 예를 들어 `ENUM('b', 'a')`에서는 `'b'`가 `'a'`보다 먼저 정렬됩니다. ([The ENUM Type](https://dev.mysql.com/doc/refman/8.4/en/enum.html))

`ORDER BY status`가 알파벳순이 아니라 **DDL에 적은 순서**로 나옵니다. 문서는 숫자처럼 보이는 값을 멤버로 쓰지 말라고도 강하게 권고합니다. 내부 인덱스 번호와 섞이기 때문입니다. 그리고 멤버를 추가하려면 `ALTER TABLE`로 컬럼 정의를 바꿔야 해서, 상태가 자주 늘어나는 도메인에서는 배포 결합이 생깁니다.

**판단 기준:** 값 집합이 1년에 한 번도 안 바뀔 것 같으면 `ENUM`, 그게 아니면 `VARCHAR(20)` + 애플리케이션 enum 또는 별도 코드 테이블입니다.

---

## 6. 예제 — 주문 테이블

```sql
-- ❌ 전부 기본값. 제약도 정보도 없습니다.
CREATE TABLE orders (
    id            INT          NOT NULL AUTO_INCREMENT,  -- 21억에서 멈춤
    order_no      VARCHAR(255) NOT NULL,                 -- 실제로는 20자 고정
    zip_code      VARCHAR(255),                          -- 실제로는 5자
    country_code  VARCHAR(255),                          -- 실제로는 2자
    total_amount  DOUBLE       NOT NULL,                 -- 금액이 근사값
    status        VARCHAR(255) NOT NULL,                 -- 7개 중 하나
    memo          VARCHAR(255),                          -- 잘릴 수 있음
    starts_at     TIMESTAMP,                             -- 2038년 이후 불가
    PRIMARY KEY (id),
    UNIQUE KEY uk_order_no (order_no)                    -- 1020바이트 키
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;
```

```sql
-- ✔️ 각 컬럼이 자기가 무엇인지 말합니다.
CREATE TABLE orders (
    id            BIGINT        NOT NULL AUTO_INCREMENT,
    order_no      CHAR(20)      NOT NULL,
    zip_code      CHAR(5)       NOT NULL,
    country_code  CHAR(2)       NOT NULL,
    total_amount  DECIMAL(13,2) NOT NULL,
    status        VARCHAR(20)   NOT NULL,
    memo          TEXT,
    starts_at     DATETIME      NOT NULL,
    created_at    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_order_no (order_no),
    KEY idx_status_created (status, created_at)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;
```

바뀐 것은 크기 절약만이 아닙니다. `uk_order_no`의 인덱스 키가 1020바이트에서 80바이트로 줄었고, `idx_status_created`가 3072바이트 상한을 걱정하지 않아도 되는 폭이 됐으며, 우편번호 컬럼에 잘못된 값이 들어오면 **DB가 거부합니다.**

JPA 쪽도 같이 맞춰야 DDL과 엔티티가 갈라지지 않습니다.

```java
@Column(name = "order_no", columnDefinition = "char(20)", nullable = false, updatable = false)
private String orderNo;

@Column(name = "total_amount", precision = 13, scale = 2, nullable = false)
private BigDecimal totalAmount;

@Enumerated(EnumType.STRING)
@Column(name = "status", length = 20, nullable = false)
private OrderStatus status;
```

`@Enumerated`에 `EnumType.ORDINAL`(기본값)을 쓰면 Java enum의 선언 순서가 DB에 숫자로 박힙니다. 중간에 상수를 끼워 넣는 순간 기존 데이터의 의미가 바뀝니다. `STRING`을 씁니다.

---

## 7. PostgreSQL에서는 기준이 다릅니다

MySQL 경험을 그대로 옮기면 틀립니다. PostgreSQL 문서는 정반대를 권고합니다.

> 이 세 타입 사이에 성능 차이는 없습니다. 공백으로 채우는 타입의 저장 공간이 늘어나는 것과, 길이 제한이 있는 컬럼에 저장할 때 길이를 검사하는 약간의 CPU 비용만 있습니다. (…) 대부분의 상황에서는 `text`나 `character varying`을 쓰는 것이 좋습니다. ([Character Types](https://www.postgresql.org/docs/18/datatype-character.html))

문서는 임의로 길이 제한을 만들어 붙이기보다 길이 지정 없는 `varchar`나 `text`를 쓰라고 안내합니다. PostgreSQL에서 `varchar(n)`의 `n`은 성능 장치가 아니라 **제약 조건**입니다. 그래서 선택 기준이 이렇게 갈립니다.

- MySQL: 선언 폭이 행 크기 상한과 인덱스 키 상한을 직접 소비합니다. 폭을 좁히는 데 성능 근거가 있습니다.
- PostgreSQL: 폭은 검증 수단일 뿐입니다. 도메인 규칙이 있으면 `varchar(n)`이나 `CHECK`로 걸고, 없으면 `text`가 기본입니다.

양쪽 모두에서 변하지 않는 것은 숫자·시간 타입의 기준입니다. 금액은 `numeric`/`DECIMAL`이고, 타임존이 섞이는 시각은 `timestamptz`/`TIMESTAMP`입니다.

---

## 8. 함정

**(1) utf8mb4로 문자셋만 바꿨는데 인덱스 생성이 실패합니다**

- **증상**: `ERROR 1071 (42000): Specified key was too long`. latin1에서 잘 돌던 `UNIQUE KEY (email)`이 안 만들어집니다.
- **원인**: 인덱스 키 바이트는 `문자 수 × 문자셋 최대 바이트`로 계산됩니다. `VARCHAR(255)`가 255바이트에서 1020바이트가 됩니다. `ROW_FORMAT`이 `COMPACT`/`REDUNDANT`로 남아 있으면 상한이 767바이트라 한 컬럼만으로도 넘습니다.
- **해법**: 먼저 `ROW_FORMAT=DYNAMIC`을 확인해 3072바이트 상한을 확보합니다. 그다음 컬럼 폭을 실제 도메인 길이로 줄입니다. 줄일 수 없는 긴 값이면 접두사 인덱스(`KEY (url(100))`)나 해시 컬럼 + 유니크 인덱스로 바꿉니다. 접두사 인덱스는 유니크 보장이 안 되므로 중복 방지가 목적이면 해시 쪽입니다.

**(2) 컬럼 하나 추가하는 `ALTER TABLE`이 거부됩니다**

- **증상**: `ERROR 1118 (42000): Row size too large (> 8126)`.
- **원인**: InnoDB 16KB 페이지에서 페이지 내 행 크기 상한에 걸렸습니다. utf8mb4 `VARCHAR(255)` 컬럼이 수십 개 쌓이면 도달합니다.
- **해법**: 급하면 가장 긴 컬럼 몇 개를 `TEXT`로 옮깁니다(행 크기 기여가 9~12바이트로 줄어듭니다). 근본 해법은 폭을 실제 길이로 되돌리는 것이고, 컬럼 수 자체가 과하면 테이블을 분리합니다. `TEXT`로 옮긴 컬럼은 정렬·그룹화 키로 쓰지 않습니다(§3-4).

**(3) 정산 합계가 몇 원씩 틀립니다**

- **증상**: 주문 금액을 `SUM`한 값과 외부 PG 정산 금액이 1~2원 차이 납니다. 재현이 들쭉날쭉합니다.
- **원인**: 금액 컬럼이 `DOUBLE`입니다. 근사값 타입이라 `0.1` 같은 값이 정확히 저장되지 않고, 합산할수록 오차가 누적됩니다.
- **해법**: `DECIMAL(13,2)`로 바꾸고 Java 쪽도 `double`이 아니라 `BigDecimal`로 받습니다. 이미 운영 중이면 `ALTER TABLE` 전에 기존 값의 반올림 기준을 먼저 합의해야 합니다 — 변환 시점에 어느 쪽으로 떨어질지가 정산 내역을 바꿉니다.

**(4) 로컬에서 맞던 시각이 운영에서 9시간 밀립니다**

- **증상**: 같은 코드인데 운영 응답의 `createdAt`이 로컬과 다릅니다.
- **원인**: `TIMESTAMP` 컬럼이고 서버와 애플리케이션의 세션 타임존이 다릅니다. `TIMESTAMP`는 쓸 때 UTC로, 읽을 때 세션 타임존으로 변환됩니다.
- **해법**: 타임존 변환이 필요한 "절대 시각"이라면 `TIMESTAMP`를 유지하고 **DB 세션 타임존을 환경 간에 고정**합니다(`connectionTimeZone` 같은 커넥션 옵션 또는 서버 `time_zone` 통일). 변환이 틀린 동작이라면(달력 위의 약속) `DATETIME`으로 바꿉니다. 자세한 환경별 설정 분리는 `day52-env-separation.md`를 참고합니다.

---

## 9. 참고자료

- [MySQL 8.4 — Data Type Storage Requirements](https://dev.mysql.com/doc/refman/8.4/en/storage-requirements.html)
- [MySQL 8.4 — The CHAR and VARCHAR Types](https://dev.mysql.com/doc/refman/8.4/en/char.html)
- [MySQL 8.4 — Limits on Table Column Count and Row Size](https://dev.mysql.com/doc/refman/8.4/en/column-count-limit.html)
- [MySQL 8.4 — InnoDB Limits](https://dev.mysql.com/doc/refman/8.4/en/innodb-limits.html)
- [MySQL 8.4 — Fixed-Point (Exact-Value) Types](https://dev.mysql.com/doc/refman/8.4/en/fixed-point-types.html)
- [MySQL 8.4 — The DATE, DATETIME, and TIMESTAMP Types](https://dev.mysql.com/doc/refman/8.4/en/datetime.html)
- [MySQL 8.4 — The ENUM Type](https://dev.mysql.com/doc/refman/8.4/en/enum.html)
- [MySQL 8.4 — The BLOB and TEXT Types](https://dev.mysql.com/doc/refman/8.4/en/blob.html)
- [MySQL 8.4 — Internal Temporary Table Use in MySQL](https://dev.mysql.com/doc/refman/8.4/en/internal-temporary-tables.html)
- [PostgreSQL 18 — Character Types](https://www.postgresql.org/docs/18/datatype-character.html)
- 관련 챕터: `day17-why-index.md`, `day35-composite-index-order.md`, `day41-covering-index.md`, `day52-env-separation.md`

# `Date` 말고 `LocalDateTime`? — 시간 타입은 무엇을 기준으로 고르는가

## 1. 핵심 개념

`java.util.Date`는 이름이 거짓말을 합니다. 실체는 epoch(1970-01-01T00:00:00Z)로부터의 밀리초를 담은 `long` 하나입니다. 날짜가 아니라 **순간**입니다. 그런데 `toString()`이 시스템 기본 타임존으로 찍히기 때문에, 마치 타임존 정보를 들고 있는 것처럼 보입니다.

```java
Date d = new Date(1_763_000_000_000L);
System.out.println(d);        // 서버 TZ가 UTC면 Thu Nov 13 ... UTC
                              // 내 노트북(KST)이면 같은 객체가 9시간 뒤로 찍힙니다
System.out.println(d.getTime()); // 1763000000000 — 이 값만이 진실입니다
```

여기에 `Date`는 가변(`setTime`)이고, `Calendar`는 월이 0부터 시작하고, `SimpleDateFormat`은 내부 상태를 공유해서 스레드 안전하지 않습니다. 포매터를 `static` 필드로 하나 두고 동시 요청을 받으면 날짜가 섞입니다.

`java.time`(JSR-310, Java 8부터)은 이 문제를 **타입을 쪼개서** 풉니다. 공식 패키지 문서가 설계 목표로 든 첫 항목이 타입 안전성입니다 — 날짜, 시각, 날짜시각, 오프셋 포함, 타임존 포함을 각각 다른 클래스로 둡니다. 그리고 모든 클래스가 불변이며 스레드 안전합니다.

> `Date`를 버리는 건 쉽습니다. 어려운 건 그다음입니다. `LocalDateTime`은 대부분의 "언제 일어났는가" 값에 **틀린 타입**입니다. 타임존이 없어서가 아니라, **타임존을 모르기 때문에** 그렇습니다. 이 선택이 DB 컬럼과 API 응답에 한번 굳으면, 나중에 바로잡으려면 이미 저장된 수백만 행을 "이건 어느 타임존 기준이었나"부터 추측해야 합니다. 그 추측은 서버를 옮기거나 리전을 늘린 시점에서 끊깁니다.

---

## 2. 구조 — 시간선이 두 개입니다

`java.time`을 외우려 하면 클래스가 열 개 넘게 보입니다. 하지만 축은 두 개뿐입니다.

**기계 시간선(instant time-line)** — epoch 기준 한 점입니다. 서울에서 보든 뉴욕에서 보든 같은 값입니다. 뺄셈이 물리적으로 의미가 있습니다.

**사람 시간선(local time-line)** — 벽에 걸린 시계가 보여주는 값입니다. "2026-03-08 09:00"은 어느 순간인지 **알 수 없습니다**. 어디에서인지를 말해주지 않았으니까요.

| 타입 | 담는 것 | 전형적인 용도 |
|---|---|---|
| `Instant` | epoch 기준 한 점 | `created_at`, 로그 시각, 토큰 만료, 이벤트 발생 시각 |
| `LocalDate` | 날짜만 | 생년월일, 정산일, 계약 만료일 |
| `LocalTime` | 시각만 | 영업시간 `09:00`, 배치 실행 시각 |
| `LocalDateTime` | 날짜+시각, 오프셋 없음 | 벽시계 값 그대로여야 하는 약속 |
| `OffsetDateTime` | 로컬 + `+09:00` | 외부 시스템 경계(DB 컬럼, XML/JSON) |
| `ZonedDateTime` | 로컬 + `Asia/Seoul` | 사람에게 보여줄 때, 타임존 규칙 계산이 필요할 때 |
| `Duration` / `Period` | 시간량 / 날짜량 | 타임아웃·경과시간 / "3개월 후" |

### 2-1. `Duration`과 `Period`가 따로 있는 이유

시간량도 두 시간선으로 갈립니다. `Duration`은 초와 나노초로 저장되는 **기계 시간량**이고, `Period`는 년·월·일로 저장되는 **달력 시간량**입니다.

```java
LocalDate start = LocalDate.of(2026, 1, 31);
start.plus(Period.ofMonths(1));   // 2026-02-28 — 달의 끝으로 보정됩니다
start.plus(Duration.ofDays(31));  // Duration은 LocalDate에 쓸 수 없습니다 (UnsupportedTemporalTypeException)
```

"한 달 후"는 며칠인지 정해져 있지 않습니다. 그래서 `Period`가 필요합니다. 타임아웃·응답시간·재시도 간격처럼 물리적 경과 시간은 `Duration`입니다. 둘을 섞어 쓰면 8-2 함정으로 이어집니다.

`ZonedDateTime`만이 두 시간선을 잇습니다. `ZoneId`에 붙은 규칙(`ZoneRules`)이 "이 지역은 이 날짜부터 오프셋이 +02:00"이라는 역사 테이블을 들고 있고, 그걸 적용해서 로컬 값을 순간으로 바꿉니다.

공식 문서는 여기에 대해 분명한 권고를 합니다. 가능하면 타임존 없는 더 단순한 클래스를 쓰고, 많은 애플리케이션은 `LocalDate`·`LocalTime`·`Instant`만으로 작성할 수 있으며 타임존은 UI 계층에서 붙이면 된다는 것입니다. `ZonedDateTime`은 상당한 복잡도를 더한다고 명시합니다.

---

## 3. 타입을 고르는 질문 두 개

### 3-1. "전 세계가 같은 순간으로 동의해야 하는 값인가?"

예라면 `Instant`입니다. 주문이 들어온 시각, 결제가 승인된 시각, 로그가 찍힌 시각. 이 값들은 조회하는 사람이 어디에 있든 같은 순간을 가리켜야 합니다. 보여줄 때만 `atZone()`으로 변환합니다.

### 3-2. "타임존이 달라져도 숫자가 그대로여야 하는가?"

예라면 `LocalDate`/`LocalTime`/`LocalDateTime`입니다. 생년월일이 1998-04-11이라면 그 사람이 뉴욕으로 이사해도 1998-04-11입니다. 여기에 `Instant`를 쓰면, 저장할 때 자정을 붙이고 읽을 때 타임존이 달라지는 순간 생일이 하루 밀립니다.

### 3-3. 애매한 한 가지 — 미래의 약속

"2027-03-28 10:00, 베를린 지점 회의"는 두 질문의 사이에 있습니다. 순간으로 변환해서 저장하면 안 됩니다. IANA tzdb는 각국 정부의 서머타임 결정에 따라 수시로 갱신되고([IANA Time Zone Database](https://www.iana.org/time-zones)), 규칙이 바뀌면 **이미 저장해둔 순간이 현지 벽시계로 10:00이 아니게** 됩니다.

미래의 사람 약속은 `LocalDateTime` + `ZoneId`를 **두 칼럼으로 따로** 저장하고, 순간은 읽을 때마다 계산합니다. 반대로 이미 지나간 일은 순간으로 저장합니다 — 과거의 오프셋은 바뀌지 않습니다.

---

## 4. 흐름 — 변환은 한 방향으로만 공짜입니다

```java
Instant now = Instant.now();                               // 순간
ZonedDateTime seoul = now.atZone(ZoneId.of("Asia/Seoul")); // 순간 + 규칙 → 벽시계
LocalDateTime wall = seoul.toLocalDateTime();              // 오프셋 버림 (정보 상실)

// 되돌리려면 버린 정보를 다시 줘야 합니다
Instant back = wall.atZone(ZoneId.of("Asia/Seoul")).toInstant();
```

```
Instant  --atZone(zone)-->  ZonedDateTime  --toLocalDateTime()-->  LocalDateTime
                                                                          |
            (ZoneId를 다시 주지 않으면 돌아올 수 없습니다) <----------------+
```

`LocalDateTime`에는 `toInstant()`가 **없습니다**. 메서드가 빠진 게 아니라, 그 변환이 불가능하다는 걸 타입으로 못 박은 것입니다. `Date`에서는 이런 변환이 암묵적으로, 그리고 시스템 기본 타임존으로 조용히 일어났습니다.

---

## 5. 트레이드오프

**얻는 것** — 타입이 의도를 기록합니다. 메서드 시그니처가 `Instant expiresAt`이면 그 값이 UTC 기준인지 서버 로컬 기준인지 묻지 않아도 됩니다. 불변이라 포매터를 `static final`로 공유해도 안전하고, `null`은 생성 시점에 `NullPointerException`으로 거부됩니다.

**지불하는 것** — 경계마다 변환 코드가 생깁니다. 컨트롤러에서 `LocalDate`를 받아 서비스에서 `Instant` 범위로 바꾸고 응답에서 다시 `ZonedDateTime`으로 돌리는 코드를 직접 써야 합니다. `Date` 하나로 다 하던 시절보다 코드가 늘어납니다. 그 대가로 "어느 타임존이었지?"라는 질문이 사라집니다.

그리고 `LocalDateTime.now()`·`Instant.now()`를 코드에 직접 박으면 테스트에서 시간을 고정할 수 없습니다. `Clock`을 주입받는 습관이 사실상 필수입니다.

---

## 6. 예제 — 쿠폰 만료 판정

### 6-1. 클린하지 않은 코드 ❌

```java
@Entity
public class Coupon {
    @Id @GeneratedValue
    private Long id;
    private LocalDateTime expiresAt;   // 어느 타임존 기준인가?

    public boolean isExpired() {
        return expiresAt.isBefore(LocalDateTime.now());  // 서버 TZ에 따라 결과가 달라집니다
    }
}
```

문제가 두 겹입니다. 저장된 `expiresAt`이 어느 기준인지 컬럼만 보고는 알 수 없고, `LocalDateTime.now()`는 JVM 기본 타임존을 읽습니다. 로컬 개발 머신(KST)과 컨테이너(UTC)에서 같은 쿠폰의 만료 판정이 9시간 어긋납니다. 테스트도 "지금"에 의존해서 시간대에 따라 깨집니다.

### 6-2. 개선한 코드 ✔️

```java
@Entity
public class Coupon {
    @Id @GeneratedValue
    private Long id;
    private Instant expiresAt;   // 순간입니다. 해석의 여지가 없습니다

    public boolean isExpired(Clock clock) {
        return expiresAt.isBefore(clock.instant());
    }
}
```

```java
@Service
public class CouponService {
    private final Clock clock;   // @Bean Clock clock() { return Clock.systemUTC(); }

    public CouponService(Clock clock) {
        this.clock = clock;
    }

    public void redeem(Coupon coupon) {
        if (coupon.isExpired(clock)) {
            throw new CouponExpiredException(coupon.getId());
        }
        // ... 생략
    }
}
```

테스트에서는 `Clock.fixed(Instant.parse("2026-11-17T00:00:00Z"), ZoneOffset.UTC)`를 넣습니다. 만료 경계 1초 전후를 결정론적으로 검증할 수 있습니다.

사용자에게 보여줄 때만 타임존을 붙입니다.

```java
String label = coupon.getExpiresAt()
        .atZone(ZoneId.of("Asia/Seoul"))
        .format(DateTimeFormatter.ofPattern("uuuu-MM-dd HH:mm"));
```

### 6-3. 하루치 조회는 반열림 구간으로 ❌ → ✔️

날짜 하나를 받아 그날 데이터를 긁는 쿼리는 거의 모든 프로젝트에 있고, 거의 모든 프로젝트에서 한 번은 틀립니다.

```java
// ❌ 23:59:59 이후 1초가 통째로 빠집니다. 컬럼 정밀도가 마이크로초면 그 안의 모든 행이 사라집니다
LocalDateTime from = date.atStartOfDay();
LocalDateTime to = date.atTime(23, 59, 59);
orderRepository.findByCreatedAtBetween(from, to);
```

```java
// ✔️ 서비스 기준 타임존에서 날짜 경계를 잡고, [시작, 다음날 시작) 반열림 구간으로 넘깁니다
private static final ZoneId SERVICE_ZONE = ZoneId.of("Asia/Seoul");

public List<Order> findDailyOrders(LocalDate date) {
    Instant from = date.atStartOfDay(SERVICE_ZONE).toInstant();
    Instant to = date.plusDays(1).atStartOfDay(SERVICE_ZONE).toInstant();
    return orderRepository.findByCreatedAtGreaterThanEqualAndCreatedAtLessThan(from, to);
}
```

경계 계산을 `atStartOfDay(zone)`에 맡기는 것이 핵심입니다. 서머타임이 있는 지역에서 자정이 존재하지 않는 날에도 이 메서드가 규칙을 적용해 올바른 순간을 돌려줍니다. `date.atTime(0, 0)`을 직접 쓰면 그 처리가 빠집니다.

---

## 7. 경계를 넘을 때 — DB와 JSON

타입을 잘 골라도 경계에서 드라이버가 다시 변환합니다. 여기가 실제 사고 지점입니다.

**PostgreSQL** — `timestamptz`는 이름과 달리 타임존을 저장하지 않습니다. 입력을 UTC로 정규화해 저장하고 읽을 때 세션 타임존으로 표시합니다. 즉 순간 전용 컬럼이고, `Instant`와 짝이 맞습니다. `timestamp`(without time zone)는 `LocalDateTime`과 짝입니다. 다만 pgjdbc가 `Instant`를 어디까지 직접 지원하는지는 드라이버 버전마다 논쟁이 있어([pgjdbc discussion #3281](https://github.com/pgjdbc/pgjdbc/discussions/3281)), 쓰는 버전의 문서를 확인하는 편이 안전합니다. <!-- TODO: pgjdbc 최신 버전의 Instant 지원 범위 확인 필요 -->

**MySQL** — `DATETIME`은 넣은 값을 그대로 보관하므로 `LocalDateTime`에, `TIMESTAMP`는 UTC로 변환해 저장하므로 순간에 해당합니다. Connector/J는 `connectionTimeZone`과 `preserveInstants`로 변환 여부를 정하고, `serverTimezone`은 8.0.23부터 `connectionTimeZone`의 별칭입니다([Connector/J 문서](https://dev.mysql.com/doc/connector-j/en/connector-j-connp-props-datetime-types-processing.html)). 8.0.23 전후로 기본 동작이 달라졌으니, 드라이버만 올리고 값이 몇 시간 밀렸다면 여기를 먼저 봅니다.

**Hibernate** — `OffsetDateTime`/`ZonedDateTime` 저장 전략이 6.2에서 바뀌었습니다. 6.0~6.1은 `TimeZoneStorageType.NORMALIZE`(오프셋을 버리고 JVM 기본 타임존으로 정규화)였고, 6.2부터는 `DEFAULT`(DB가 지원하면 타임존 포함 타입 사용)입니다. 예전 동작이 필요하면 `hibernate.timezone.default_storage=NORMALIZE`로 돌립니다([6.2 마이그레이션 가이드](https://docs.hibernate.org/orm/6.2/migration-guide/)).

**JSON** — Spring Boot 3.5 기준으로 `WRITE_DATES_AS_TIMESTAMPS`와 `WRITE_DURATIONS_AS_TIMESTAMPS`를 `false`로 고정해 ISO-8601 문자열로 직렬화합니다([`JacksonAutoConfiguration`](https://github.com/spring-projects/spring-boot/blob/3.5.x/spring-boot-project/spring-boot-autoconfigure/src/main/java/org/springframework/boot/autoconfigure/jackson/JacksonAutoConfiguration.java)). 순수 Jackson 2를 직접 쓰면 숫자로 나가므로 모듈 등록과 기능 해제를 직접 해야 합니다. Jackson 3는 ISO-8601이 기본입니다([Jackson 3.0.0 GA](https://cowtowncoder.medium.com/jackson-3-0-0-ga-released-1f669cda529a)).

---

## 8. 함정

### 8-1. 서머타임 구간은 예외 없이 조용히 밀립니다

- **증상**: 특정 날짜의 02:30 예약만 03:30으로 저장됩니다. 가을에는 한 시간 분량이 두 번 처리됩니다.
- **원인**: 서머타임 시작일에는 존재하지 않는 로컬 시각이 생깁니다. `ZonedDateTime.of()`는 이때 예외를 던지지 않고, 공식 문서대로 **갭 길이만큼 뒤로 밀어** 결과를 만듭니다. 겹침(overlap) 구간에서는 이전 오프셋을 유지하고, 없으면 이른 쪽을 씁니다.
- **해법**: 사용자 입력을 변환할 때 `ZoneId.getRules().getTransition(localDateTime)`으로 갭/겹침을 먼저 판정해 입력 단계에서 거부하거나 되묻습니다. 겹침에서 어느 쪽인지 지정해야 하면 `withEarlierOffsetAtOverlap()` / `withLaterOffsetAtOverlap()`을 명시합니다.

### 8-2. `plusDays(1)`과 `plus(Duration.ofDays(1))`은 다른 연산입니다

- **증상**: 매일 09:00에 돌아야 하는 작업이 서머타임 전환 이후로 08:00 또는 10:00에 실행됩니다.
- **원인**: `ZonedDateTime`에서 날짜 단위(`plusDays`, `ChronoUnit.DAYS`)는 **로컬 시간선**에서 계산합니다 — 로컬 값에 더한 뒤 다시 존을 적용하므로 벽시계 시각이 유지됩니다. 반면 시간 단위(`ChronoUnit.HOURS` 등)는 **순간 시간선**에서 계산합니다. `Duration`은 초와 나노초로 저장되고 `addTo`가 초를 더하므로 후자에 해당하며, `Duration`의 `DAYS` 단위는 문서에 "정확히 24시간, 서머타임 효과 무시"로 못 박혀 있습니다([`Duration` 문서](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/time/Duration.html)).
- **해법**: "매일 같은 시각"은 `plusDays`/`Period`, "정확히 24시간 뒤"는 `Duration`. 둘 중 무엇을 원하는지 먼저 정합니다.

### 8-3. `YYYY`는 연도가 아닙니다

- **증상**: 12월 말~1월 초 며칠 동안만 파일명이나 리포트 연도가 1 큰 값으로 찍힙니다.
- **원인**: `DateTimeFormatter`의 `YYYY`는 주 기반 연도(week-based year)입니다. 해가 바뀌는 주는 다음 해의 1주차로 셀 수 있어서, 12월 31일이 다음 해로 찍힙니다. `SimpleDateFormat`에도 같은 함정이 있었습니다.
- **해법**: 달력 연도는 `uuuu`를 씁니다. `YYYY`는 `w`(주차)와 함께 쓸 때만 의미가 있습니다.

### 8-4. `yyyy` + `ResolverStyle.STRICT`는 파싱에 실패합니다

- **증상**: 느슨하게 돌던 포매터에 `STRICT`를 켜자 멀쩡한 `2026-11-17`에서 예외가 납니다.
- **원인**: `yyyy`는 연도가 아니라 **연호 기준 연도(year-of-era)**입니다. `STRICT`에서는 연호 정보 없이 연도를 확정할 수 없다고 판단합니다.
- **해법**: `STRICT`로 검증하려면 패턴을 `uuuu`로 바꿉니다. `STRICT` 없이 `yyyy-MM-dd`를 쓰면 2026-02-30 같은 값이 2026-02-28로 조용히 보정될 수 있습니다.

### 8-5. Java 8과 9+에서 `Instant.now()`의 정밀도가 다릅니다

- **증상**: 저장 직후 다시 읽어 `equals`로 비교하는 테스트가 JDK를 올린 뒤 깨집니다.
- **원인**: JDK 9 사이클에서 `Clock.systemUTC()`의 정밀도를 올렸습니다([JDK-8068730](https://bugs.openjdk.org/browse/JDK-8068730)). Java 8에서는 밀리초까지만 채워졌던 자리에 Linux에서는 마이크로초 자리가 들어옵니다. Windows는 이 이점을 받지 못한다는 별도 이슈가 있습니다([JDK-8180466](https://bugs.openjdk.org/browse/JDK-8180466)). DB 컬럼 정밀도(예: MySQL `DATETIME`의 기본 초 단위)가 더 낮으면 저장 과정에서 잘려서 원본과 달라집니다.
- **해법**: 저장 전에 `truncatedTo(ChronoUnit.MICROS)` 등으로 컬럼 정밀도에 맞춰 자릅니다. 비교는 `equals`보다 `isEqual`/허용 오차 기준으로 합니다.

### 8-6. `java.sql.Timestamp`를 `java.util.Date`와 비교하면 안 됩니다

- **증상**: `a.equals(b)`는 `true`인데 `b.equals(a)`는 `false`입니다. `Set`이나 `Map`에서 값이 중복되거나 사라집니다.
- **원인**: `Timestamp`는 `Date`를 상속하면서 나노초 필드를 추가하고 `equals`를 재정의했습니다. 대칭성이 깨집니다.
- **해법**: 레거시 타입이 경계에 남아 있다면 진입 지점에서 바로 `toInstant()`로 변환하고, 도메인 안에서는 `java.time` 타입만 다닙니다.

### 8-7. 컨테이너의 기본 타임존을 믿고 쓰기

- **증상**: 로컬에서 맞던 날짜 경계 집계(일별 매출 등)가 운영에서 9시간 어긋나거나, 자정 직후 주문이 전날로 집계됩니다.
- **원인**: `LocalDate.now()`·`LocalDateTime.now()`는 JVM 기본 타임존을 읽습니다. 대부분의 컨테이너 베이스 이미지는 UTC입니다.
- **해법**: 무인자 `now()`를 쓰지 않습니다. 비즈니스 날짜 경계는 `LocalDate.now(ZoneId.of("Asia/Seoul"))`처럼 존을 명시하거나, 주입한 `Clock`에 존을 고정합니다. 집계 쿼리의 범위도 서비스 기준 타임존으로 계산한 `Instant` 양끝으로 넘깁니다.

---

## 9. 참고자료

- [`java.time` 패키지 문서 (Java SE 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/time/package-summary.html)
- [`ZonedDateTime` 문서 — 갭/겹침 해소 규칙](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/time/ZonedDateTime.html)
- [MySQL Connector/J — 날짜·시간 타입 처리 속성](https://dev.mysql.com/doc/connector-j/en/connector-j-connp-props-datetime-types-processing.html)
- [Hibernate ORM 6.2 마이그레이션 가이드 — 타임존 저장 전략](https://docs.hibernate.org/orm/6.2/migration-guide/)
- [IANA Time Zone Database](https://www.iana.org/time-zones)
- 관련 문서: `daily/day61-checked-unchecked.md`(경계에서 예외 타입을 바꾸는 이야기), `daily/day74-bean-validation.md`(입력 검증을 어느 계층에서 하는가)

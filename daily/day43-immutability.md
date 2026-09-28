# 불변 객체는 동시성 문제의 어느 절반을 없애는가

> 이 문서가 답할 질문: **객체를 불변으로 만들면 동시성에서 무엇이 공짜가 되고, 무엇이 여전히 내 몫으로 남는가?**
>
> 분류: 기술이해형(왜 존재하는가). "불변이 좋다"는 결론은 이미 널리 퍼져 있으므로, 여러 출처에서 공통으로 등장하는 **"원래 어떤 문제를 풀려고 만들어진 장치인가"** 를 기준으로 조사했습니다.
>
> 기준: Java 21 LTS. 본문의 `final` 필드 의미론은 JSR-133(Java 5)에서 정해진 뒤 바뀌지 않았고, 최신 LTS인 [JDK 25(2025-09-16 GA)](https://www.oracle.com/news/announcement/oracle-releases-java-25-2025-09-16/)에서도 동일합니다. 불변 객체의 설계 이점(테스트 용이성, 캐시 키 안정성)은 `daily/day37-equals-hashcode.md`에서 이미 다뤘으므로, 여기서는 **동시성** 한 축만 봅니다.

## 1. 핵심 개념 — 불변은 "안 바뀐다"가 아니라 "완성되기 전엔 보이지 않는다"입니다

불변 객체는 생성이 끝난 뒤 상태가 관찰 가능하게 변하지 않는 객체입니다. 여기까지는 누구나 아는 정의고, 동시성에서 진짜로 중요한 건 뒷부분입니다.

```java
public class ShippingFee {
    final int baseFee;      // final
    int surcharge;          // final 아님

    public ShippingFee() {
        this.baseFee = 3000;
        this.surcharge = 500;
    }
}
```

```java
static ShippingFee shared;

static void writerThread() {
    shared = new ShippingFee();          // 동기화 없이 발행
}

static void readerThread() {
    if (shared != null) {
        int base = shared.baseFee;       // 항상 3000
        int extra = shared.surcharge;    // 0이 나올 수 있습니다
    }
}
```

> 생성자가 끝난 뒤에 대입했는데도 `surcharge`가 `0`으로 보일 수 있습니다. 이건 버그가 아니라 [JLS §17.5](https://docs.oracle.com/javase/specs/jls/se21/html/jls-17.html)가 명시적으로 허용하는 동작입니다. 같은 객체 안에서 한 필드는 제대로 보이고 옆 필드는 기본값으로 보이는 것 — **"생성이 덜 된 객체"가 다른 스레드에 노출되는 이 상황**이 불변 설계가 없애려는 문제입니다. 흔히 말하는 "객체 상태가 중간에 바뀌어서 깨진다"보다 한 단계 앞의 문제입니다.

`if (shared != null)`을 통과했으니 객체는 분명히 만들어졌습니다. 그런데도 필드가 비어 있습니다. 재현은 거의 안 되고, 재현되더라도 몇억 번에 한 번입니다. 그래서 스테이징에서는 절대 안 잡힙니다.

## 2. 구조 — `final`이 그 보장을 만들어 내는 방식

JLS는 생성자가 끝날 때 그 객체의 `final` 필드들에 **freeze action**이 일어난다고 정의합니다. 그리고 이렇게 요약합니다.

> "Set the `final` fields for an object in that object's constructor; and do not write a reference to the object being constructed in a place where another thread can see it before the object's constructor is finished." — JLS §17.5

조건이 두 개입니다.

1. `final` 필드의 값을 **생성자 안에서** 정한다.
2. 생성자가 끝나기 전에 **`this`를 밖으로 내보내지 않는다.**

이 둘을 지키면, 그 객체의 참조가 아무런 동기화 없이(= 데이터 레이스로) 다른 스레드에 전달되어도 `final` 필드는 언제나 생성자가 넣은 값으로 보입니다. JLS의 표현으로는 "a thread-safe immutable object is seen as immutable by all threads, even if a data race is used to pass references to the immutable object between threads"입니다.

여기서 실무적으로 가장 중요한 결론이 나옵니다.

**`final`을 안 붙인 필드는 이 보장을 못 받습니다.** 세터를 안 만들고 게터만 열어 둔 클래스는 "사실상 불변(effectively immutable)"일 뿐이고, 위 예제의 `surcharge`와 정확히 같은 처지입니다. 불변성은 규율이 아니라 **키워드로 선언해야 효력이 생깁니다.**

### 2-1. `this`가 새는 지점

2번 조건은 추상적으로 들리지만 실제로는 몇 가지 정해진 패턴으로만 깨집니다.

```java
// ❌ 생성자 안에서 this가 밖으로 나갑니다
public class OrderEventListener {
    private final OrderPolicy policy;

    public OrderEventListener(EventBus bus) {
        bus.register(this);      // ① 아직 policy가 안 채워졌는데 버스가 나를 봅니다
        this.policy = new OrderPolicy();
    }
}
```

- 생성자에서 자기 자신을 리스너·레지스트리·콜백으로 등록하는 경우 (①)
- 생성자에서 스레드를 만들어 바로 `start()` 하는 경우
- 생성자가 오버라이드 가능한 메서드를 호출하고, 그 구현이 자식 필드를 건드리는 경우

해법은 전부 같습니다. **생성은 생성만 하고, 등록·시작은 생성이 끝난 뒤 별도 메서드에서** 합니다. Spring이라면 `@PostConstruct`나 `SmartInitializingSingleton`이 그 자리입니다.

### 2-2. 이 보장의 가격

freeze action은 공짜가 아닙니다. 구현체는 생성자 끝에 배리어를 하나 넣어야 합니다. 다만 x86처럼 강한 메모리 모델을 가진 CPU에서는 이 배리어가 사실상 no-op에 가깝습니다.

Aleksey Shipilev의 [Safe Publication and Safe Initialization in Java](https://shipilev.net/blog/2014/safe-public-construction/)가 jcstress로 잰 결과 중 정확성 부분만 보면 이렇습니다.

| 발행 방식 | x86 (Haswell i7-4790K) | ARMv7 (Cortex-A9) |
|---|---:|---:|
| `final` 필드로 안전하게 발행 | 0 / 3.3G | 0 / 99M |
| `final` 없이 발행 (Unsafe DCL) | 43.8K / 3.7G | 809 / 134M |

왼쪽은 실패 횟수, 오른쪽은 시도 횟수입니다. **x86에서도 37억 번 중 4만 번 이상 깨집니다.** 이 문제가 "이론상 가능하다" 수준이 아니라는 근거로 이 숫자 하나면 충분합니다. 그리고 메모리 순서가 약한 ARM 계열에서는 시도 대비 실패율이 훨씬 높아집니다 — 요즘은 서버도 ARM(Graviton 등)이 흔하므로 x86에서만 안 터졌다는 경험은 근거가 되지 않습니다.

## 3. 그래서 없어지는 절반

불변으로 만들면 동시성 문제 중 이 셋이 **구조적으로** 사라집니다.

| 문제 | 가변 객체에서 필요한 것 | 불변 객체에서 |
|---|---|---|
| 가시성 — 내가 쓴 값이 남에게 보이는가 | `volatile` / 락 / `Atomic*` | freeze action이 처리 |
| 원자성 — 여러 필드를 일관된 상태로 읽는가 | 읽기에도 락 필요 | 중간 상태 자체가 없음 |
| 방어적 복사 — 넘겨준 객체를 상대가 바꾸는가 | 넘길 때마다 복사 | 복사할 이유가 없음 |

두 번째 줄이 실무에서 가장 크게 체감됩니다. 가변 객체는 **읽는 쪽도 락을 잡아야** 합니다. `from`과 `to`를 가진 기간 객체를 락 없이 읽으면 `from`은 새 값, `to`는 옛 값인 조합을 볼 수 있습니다. 어느 쪽도 실제로 존재한 적 없는 상태입니다. 불변이면 이 조합 자체가 만들어지지 않으므로 읽기 경로에서 락이 통째로 사라집니다.

세 번째 줄은 API 설계에 바로 영향을 줍니다. 불변 객체는 캐시에 넣어도, 여러 서비스가 공유해도, 로그에 찍어도 안전합니다. "이거 넘겨주면 상대가 고치나?"를 매번 생각할 필요가 없어집니다.

## 4. 남는 절반 — 불변이 절대 못 푸는 것

여기가 이 문서의 본론입니다. 불변 객체를 열심히 만들어 놓고도 동시성 버그가 그대로 남는 경우는 대부분 아래 셋 중 하나입니다.

### 4-1. 불변 객체를 담는 **자리**는 여전히 가변입니다

```java
// ❌ ExchangeRateTable이 완벽히 불변이어도 이 필드는 가변입니다
private ExchangeRateTable rates = ExchangeRateTable.empty();

public void reload(ExchangeRateTable newRates) {
    this.rates = newRates;
}
```

`rates` 필드는 `final`이 아니므로 다른 스레드가 **갱신을 영영 못 볼 수도** 있습니다. 불변 객체는 "이 참조가 가리키는 대상이 온전하다"까지만 보장하고, "이 참조 자체가 최신이다"는 보장하지 않습니다.

```java
// ✔️ 참조를 바꿀 거면 그 자리를 volatile 또는 AtomicReference로 선언합니다
private volatile ExchangeRateTable rates = ExchangeRateTable.empty();
```

### 4-2. 읽고-계산하고-쓰기(check-then-act)는 그대로 남습니다

```java
// ❌ 각 줄은 안전한데 전체는 안전하지 않습니다
ExchangeRateTable current = this.rates;          // 읽기
ExchangeRateTable updated = current.with("USD", newRate);   // 새 불변 객체 생성
this.rates = updated;                             // 쓰기
```

읽기와 쓰기 사이에 다른 스레드가 끼어들면 그 갱신이 통째로 사라집니다. **불변성은 각 시점의 값을 지켜 줄 뿐, 값과 값 사이의 전이를 지켜 주지 않습니다.**

```java
// ✔️ 전이 자체를 원자적으로 만듭니다
private final AtomicReference<ExchangeRateTable> rates =
        new AtomicReference<>(ExchangeRateTable.empty());

public void applyRate(String currency, BigDecimal rate) {
    rates.updateAndGet(current -> current.with(currency, rate));
}
```

`updateAndGet`은 CAS 실패 시 람다를 다시 실행합니다. 그래서 **람다는 부수효과가 없어야 합니다.** 불변 객체는 이 조건을 저절로 만족시키므로, CAS 루프와 불변 값 객체는 원래 짝입니다. 이게 "불변이 동시성의 절반을 없앤다"의 정확한 의미입니다 — 나머지 절반을 `AtomicReference` 한 줄로 처리할 수 있게 만들어 줍니다.

### 4-3. 불변은 얕습니다

```java
public record ProductCatalog(String tenantId, List<String> skuList) { }
```

`record`의 컴포넌트는 `final`이지만, 그게 보장하는 건 **참조가 안 바뀐다**까지입니다. 생성자에 넘어온 `ArrayList`를 그대로 들고 있으면 호출부가 나중에 원소를 추가할 수 있고, 그 순간 이 객체는 불변이 아닙니다.

```java
public record ProductCatalog(String tenantId, List<String> skuList) {
    public ProductCatalog {
        skuList = List.copyOf(skuList);   // compact 생성자에서 불변 복사
    }
}
```

여기서 `Collections.unmodifiableList`를 쓰면 안 됩니다. [공식 문서](https://docs.oracle.com/en/java/javase/21/core/creating-immutable-lists-sets-and-maps.html)가 구분하는 대로, `unmodifiableList`는 **뷰**라서 원본이 바뀌면 뷰를 통해 그대로 보입니다. `List.copyOf`는 뷰가 아니라 별도의 자료구조를 만듭니다. 다만 넘어온 컬렉션이 이미 불변이면 복사하지 않고 그 참조를 그대로 돌려줍니다 — 그래서 남발해도 비용이 크지 않습니다.

`List.of`/`List.copyOf` 계열은 **`null` 원소를 허용하지 않습니다.** 기존 코드에서 `Arrays.asList`를 바꿔 끼우면 `NullPointerException`이 새로 나올 수 있습니다.

## 5. 만드는 법 — 규칙 네 줄

[Oracle 공식 튜토리얼](https://docs.oracle.com/javase/tutorial/essential/concurrency/imstrat.html)이 정리한 규칙입니다.

1. 세터를 만들지 않습니다.
2. 모든 필드를 `private final`로 만듭니다.
3. 서브클래스가 메서드를 오버라이드하지 못하게 합니다(클래스를 `final`로).
4. 가변 객체를 참조하는 필드가 있으면 **들어올 때와 나갈 때 모두** 복사합니다.

3번이 흔히 빠집니다. 상속이 열려 있으면 자식이 게터를 오버라이드해서 매번 다른 값을 돌려줄 수 있으므로, 부모가 아무리 `final` 필드만 써도 관찰된 상태는 변합니다.

`record`는 1·2·3번을 문법이 강제합니다. 4번만 compact 생성자에서 직접 처리하면 됩니다. **값 객체라면 클래스를 직접 짤 이유가 거의 없습니다.**

## 6. 예제 — 요금 정책 캐시

배치로 주기적으로 갱신되고, 요청 스레드 수십 개가 동시에 읽는 요금 정책입니다.

### 6-1. 클린하지 않은 코드 ❌

```java
@Component
public class FeePolicyHolder {
    private BigDecimal baseRate = new BigDecimal("0.03");
    private BigDecimal maxFee = new BigDecimal("50000");
    private LocalDate appliedFrom = LocalDate.of(2026, 1, 1);

    public void reload(FeePolicyRow row) {           // 배치 스레드가 호출
        this.baseRate = row.baseRate();
        this.maxFee = row.maxFee();
        this.appliedFrom = row.appliedFrom();
    }

    public BigDecimal getBaseRate() { return baseRate; }
    public BigDecimal getMaxFee() { return maxFee; }
}
```

문제가 세 겹입니다.

- **필드가 `final`이 아니고 `volatile`도 아닙니다.** 요청 스레드가 갱신을 영영 못 볼 수 있습니다.
- **세 필드가 따로 바뀝니다.** `baseRate`는 새 정책, `maxFee`는 옛 정책인 조합으로 요금이 계산됩니다. 로그에는 아무 흔적도 안 남고, 정산 대사에서 몇 건만 안 맞는 형태로 나타납니다.
- **`reload` 중간에 읽으면 `appliedFrom`이 아직 안 바뀐 상태입니다.** 세 필드를 묶어 주는 락이 없으니 "존재한 적 없는 정책"이 실제로 적용됩니다.

`getBaseRate`에 `synchronized`를 붙이는 게 흔한 응급처치인데, 이러면 읽기가 전부 직렬화되고 두 번째 문제는 그대로입니다(게터를 두 번 부르면 그 사이에 바뀝니다).

### 6-2. 개선한 코드 ✔️

```java
public record FeePolicy(BigDecimal baseRate, BigDecimal maxFee, LocalDate appliedFrom) {
    public FeePolicy {
        Objects.requireNonNull(baseRate, "baseRate");
        Objects.requireNonNull(maxFee, "maxFee");
    }

    public BigDecimal calculate(BigDecimal amount) {
        return amount.multiply(baseRate).min(maxFee);
    }
}
```

```java
@Component
public class FeePolicyHolder {
    private final AtomicReference<FeePolicy> current =
            new AtomicReference<>(FeePolicy.defaultPolicy());

    public void reload(FeePolicyRow row) {
        current.set(new FeePolicy(row.baseRate(), row.maxFee(), row.appliedFrom()));
    }

    public FeePolicy snapshot() {                    // 읽는 쪽은 한 번만 집어갑니다
        return current.get();
    }
}
```

```java
// 호출부 — 한 요청 안에서는 정책이 절대 바뀌지 않습니다
FeePolicy policy = policyHolder.snapshot();
BigDecimal fee = policy.calculate(order.amount());
log.info("fee calculated policyFrom={} fee={}", policy.appliedFrom(), fee);
```

바뀐 것은 세 가지입니다.

- 게터 세 개가 **스냅샷 하나**로 바뀌면서, 한 요청이 보는 정책이 일관됩니다. 로그에 찍은 `appliedFrom`이 실제로 계산에 쓰인 그 정책입니다.
- 갱신이 **참조 교체 한 번**으로 줄어 중간 상태가 사라집니다.
- 읽기 경로에 락이 없습니다. `AtomicReference.get()`은 volatile 읽기 한 번입니다.

`BigDecimal`도 불변이라 필드를 그대로 들고 있어도 됩니다(4번 규칙이 면제되는 경우입니다). 대신 `Date`나 `ArrayList`였다면 compact 생성자에서 복사해야 합니다.

## 7. 실무에서 찾아보는 불변

**`String`은 불변인데 `hash` 필드는 `final`이 아닙니다.** [OpenJDK](https://github.com/openjdk/jdk/blob/master/src/java.base/share/classes/java/lang/String.java)는 계산한 해시를 `private int hash`에 캐싱합니다. 규칙 위반처럼 보이지만 의도된 예외입니다. 계산이 순수 함수라 어느 스레드가 계산해도 결과가 같고, `int` 쓰기는 찢어지지 않으므로 최악의 경우 여러 스레드가 같은 값을 중복 계산할 뿐입니다. **불변의 목적이 "값이 항상 같게 보이는 것"이라면, 이 필드는 목적을 위반하지 않습니다.** 다만 이건 JDK 수준에서 근거를 대고 쓰는 예외지, 애플리케이션 코드에서 흉내 낼 패턴은 아닙니다.

**`java.time`은 전부 불변입니다.** `LocalDateTime.plusDays()`는 자기를 바꾸지 않고 새 객체를 돌려줍니다. 그래서 `DateTimeFormatter`는 스레드 안전한데 `SimpleDateFormat`은 아닙니다. 후자가 내부에 `Calendar`를 필드로 들고 파싱 중에 그걸 고치기 때문입니다. 싱글톤 빈에 `SimpleDateFormat`을 필드로 두는 건 지금도 자주 보이는 사고입니다.

**`BigDecimal`·`Integer` 같은 박싱 타입도 불변입니다.** 그래서 `Integer`를 카운터로 쓰면 `count = count + 1`이 매번 새 객체를 만드는 비원자적 연산이 됩니다. 이 자리는 `AtomicInteger`입니다.

## 8. 함정

**① "세터 없으면 불변"이라고 생각한다**
- **증상**: 다른 스레드에서 필드가 기본값(`0`, `null`)으로 보입니다. 재현은 며칠에 한 번.
- **원인**: `final`이 없으면 freeze action이 없고, JLS의 초기화 안전성 보장을 못 받습니다.
- **해법**: 필드에 `final`을 붙입니다. 붙일 수 없는 사정이 있으면 최소한 `volatile`로 발행합니다.

**② 생성자 안에서 자기 자신을 등록한다**
- **증상**: 서버 기동 직후 몇 건만 `NullPointerException`이 나고 이후엔 정상입니다.
- **원인**: `this`가 생성자 종료 전에 새어 나가 freeze action을 우회했습니다. `final` 필드도 이 경우엔 보호되지 않습니다.
- **해법**: 등록·스레드 시작을 생성자 밖으로 뺍니다. Spring이면 `@PostConstruct`.

**③ 불변 객체를 가변 필드에 담아 놓고 안심한다**
- **증상**: 설정을 갱신했는데 일부 인스턴스·일부 스레드에만 반영됩니다.
- **원인**: 객체는 불변이지만 그 객체를 가리키는 필드가 가변입니다. 4-1의 경우입니다.
- **해법**: 참조를 담는 자리를 `volatile` 또는 `AtomicReference`로 만듭니다.

**④ `AtomicReference.updateAndGet`에 부수효과를 넣는다**
- **증상**: 로그가 중복으로 찍히거나, 갱신 한 번에 외부 호출이 여러 번 나갑니다.
- **원인**: CAS가 실패하면 람다가 재실행됩니다. 호출 횟수가 1이라는 보장이 없습니다.
- **해법**: 람다 안에는 순수 계산만 둡니다. 부수효과는 `updateAndGet`이 반환한 결과로 바깥에서 한 번 실행합니다.

**⑤ 요청 하나 안에서 게터를 여러 번 부른다**
- **증상**: 로그에 찍힌 값과 실제 계산에 쓰인 값이 다릅니다.
- **원인**: 게터를 부를 때마다 최신 참조를 읽으므로, 호출 사이에 갱신이 끼어듭니다.
- **해법**: 경계에서 한 번 `snapshot()`으로 집어 지역 변수에 담고, 그 뒤로는 그것만 씁니다.

**⑥ 복사 비용을 무서워해 불변을 포기한다**
- **증상**: 수만 건짜리 리스트를 `List.copyOf`로 감싸다 GC가 늘었습니다.
- **원인**: 불변은 공짜가 아닙니다. 상태 변경이 잦고 큰 구조라면 전체 복사가 실제 비용이 됩니다.
- **해법**: 불변으로 만들 단위를 "요청 하나가 통째로 보는 스냅샷" 크기로 잡습니다. 그보다 크고 변경이 잦으면 `ConcurrentHashMap` 같은 동시성 자료구조가 맞는 선택입니다. 불변은 기본값이지 유일한 답이 아닙니다.

## 9. 참고자료

- [JLS §17.5 final Field Semantics (Java SE 21)](https://docs.oracle.com/javase/specs/jls/se21/html/jls-17.html) — freeze action과 초기화 안전성 원문
- [A Strategy for Defining Immutable Objects (Java Tutorials)](https://docs.oracle.com/javase/tutorial/essential/concurrency/imstrat.html) — 네 줄 규칙
- [Creating Immutable Lists, Sets, and Maps (Java SE 21)](https://docs.oracle.com/en/java/javase/21/core/creating-immutable-lists-sets-and-maps.html) — unmodifiable 뷰와 불변 컬렉션의 차이
- [Safe Publication and Safe Initialization in Java — Aleksey Shipilev](https://shipilev.net/blog/2014/safe-public-construction/) — jcstress 실측치
- 관련 노트: `daily/day37-equals-hashcode.md`(해시 키가 불변이어야 하는 이유), `daily/day32-bean-lifecycle.md`(생성자와 `@PostConstruct`의 순서), `daily/day20-service-layer-design.md`(경계에서 스냅샷을 잡는다는 발상)

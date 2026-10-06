# `Optional`은 왜 반환 타입에서만 제값을 하는가

> 이 문서가 답할 질문: **`Optional`은 원래 어떤 문제를 풀려고 만들어졌고, 그 의도를 벗어나 필드·파라미터에 쓰면 무엇이 깨지는가?**
>
> 분류: 기술이해형. "쓰면 안 되는 이유"의 근거는 결국 "이 타입이 원래 무엇을 풀려고 나왔는가"에 있어서, 여러 출처가 공통으로 말하는 설계 의도를 찾는 관점으로 조사했습니다.
>
> 기준: Java 25 API 문서 · Spring Framework 6.x/7.x (2026년 10월 확인). DB의 NULL 자체가 만드는 버그는 `day11-null-traps.md`에서 다뤘습니다. 이 문서는 **Java 코드에서 "값이 없음"을 타입으로 표현하는 방법**만 다룹니다.

## 1. 핵심 개념 — `Optional`은 "없음"을 알리는 장치지, null을 없애는 장치가 아닙니다

`Optional<T>`는 값이 하나 들어 있거나 비어 있는 컨테이너입니다. 여기까지는 다 아는 내용이고, 실무에서 갈리는 건 **어디에 놓느냐**입니다.

JDK 문서가 의도를 직접 밝혀 둡니다.

> `Optional`은 주로 **"결과 없음"을 명확히 표현해야 하고 `null`을 쓰면 오류를 유발하기 쉬운 메서드 반환 타입**으로 쓰려고 만들었습니다. 그리고 타입이 `Optional`인 변수는 **그 자체가 절대 `null`이면 안 되고**, 항상 어떤 `Optional` 인스턴스를 가리켜야 합니다. ([Java 25 API — Optional](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/Optional.html))

핵심은 "반환 타입"이라는 단어가 API Note에 박혀 있다는 점입니다. 범용 null 대체재라고 쓰여 있지 않습니다.

> 이걸 "null 안전 래퍼"로 오해하고 필드와 파라미터까지 `Optional`로 바꾸면, 코드가 안전해지는 게 아니라 **상태가 하나 늘어납니다.** 원래 `String name`은 값 아니면 null, 두 가지였습니다. `Optional<String> name`은 값 있는 Optional · 빈 Optional · **필드 자체가 null인 Optional**, 세 가지가 됩니다. 세 번째 상태를 막아주는 장치는 언어에 없습니다. 그래서 NPE를 없애려고 도입한 타입이 NPE가 터질 자리를 하나 더 만듭니다. 게다가 직렬화와 ORM 매핑이 같이 깨집니다.

## 2. 구조 — `Optional`이 실제로 하는 일과, 하지 않는 일

### 2-1. 하는 일: "값이 없을 수 있음"을 호출자에게 컴파일 타임에 알립니다

`User findByEmail(String email)`의 시그니처만 보고는 null이 올 수 있는지 알 수 없습니다. 주석을 읽거나 구현을 열어봐야 합니다. `Optional<User> findByEmail(String email)`은 **시그니처가 직접 말합니다.** 호출자는 `orElseThrow()`든 `map()`이든 "없을 때"를 처리하지 않으면 값을 꺼낼 수 없습니다.

이게 `Optional`이 제공하는 가치의 거의 전부입니다. **문서화된 계약**입니다.

### 2-2. 하지 않는 일 ①: 직렬화

`Optional`의 선언은 `public final class Optional<T>`이고, 구현하는 인터페이스가 없습니다. 즉 **`Serializable`이 아닙니다.** 필드에 `Optional`을 두면 그 클래스는 자바 직렬화 대상이 될 수 없습니다. IntelliJ가 `Optional`을 필드·파라미터 타입으로 쓸 때 경고를 띄우는 이유로도 이 점을 명시합니다([JetBrains Inspectopedia — Optional used as field or parameter type](https://jetbrains.com/help/inspectopedia/OptionalUsedAsFieldOrParameterType.html)).

JSON은 사정이 조금 다릅니다. Jackson 2 계열에서는 `jackson-datatype-jdk8` 모듈이 있어야 `Optional`을 제대로 풀어서 직렬화하고, 그게 없으면 `{"present":true}` 같은 엉뚱한 모양이 나옵니다. Spring Boot 3 계열은 이 모듈이 클래스패스에 있으면 자동 등록해 줍니다([Spring Boot 3.3 — JSON](https://docs.spring.io/spring-boot/3.3/reference/features/json.html)). Spring Framework 7 / Spring Boot 4 계열은 Jackson 3로 넘어가면서 모듈 탐색 방식 자체가 서비스 로더 기반으로 바뀌었습니다([Introducing Jackson 3 support in Spring](https://spring.io/blog/2025/10/07/introducing-jackson-3-support-in-spring/)).

요약하면 **동작은 하는데 버전과 설정에 의존합니다.** 응답 DTO 필드를 `Optional`로 둘 이유로는 약합니다.

<!-- TODO: 확인 필요 — Jackson 3 databind가 Optional 지원을 코어로 흡수했는지는 Spring 블로그에 parameter-names·datatype-jsr310만 명시돼 있어 jdk8 모듈의 처리는 확정하지 못했습니다. Jackson 3 릴리스 노트로 재확인이 필요합니다. -->

### 2-3. 하지 않는 일 ②: ORM 매핑

JPA 구현체는 엔티티 필드의 타입을 보고 컬럼 타입을 정합니다. 필드 타입이 `Optional<LocalDate>`면 Hibernate는 이걸 어떤 타입으로 저장할지 알 수 없어 매핑 예외로 기동이 실패합니다. 해법은 **필드는 실제 타입으로 두고, 게터 반환 타입만 `Optional`로 감싸는 것**입니다. 필드 접근(field access) 방식에서는 Hibernate가 게터를 호출하지 않으므로 이 조합이 성립합니다([Vlad Mihalcea — The best way to map a Java 1.8 Optional entity attribute](https://vladmihalcea.com/the-best-way-to-map-a-java-1-8-optional-entity-attribute-with-jpa-and-hibernate/)).

이 해법 자체가 §1의 결론을 다시 말해 줍니다. **저장되는 자리는 원래 타입, 꺼내 주는 자리는 `Optional`.**

### 2-4. 하지 않는 일 ③: 동일성 비교와 잠금

`Optional`은 값 기반 클래스(value-based class)입니다. 문서가 두 가지를 명시적으로 경고합니다.

- `Optional.empty()`가 싱글턴이라는 보장이 없으므로 `==`·`!=`로 비었는지 판별하지 말고 `isEmpty()`·`isPresent()`를 쓸 것
- 인스턴스를 동기화 락 객체로 쓰지 말 것 — 향후 릴리스에서 동기화가 실패할 수 있음

`equals()`는 참조가 아니라 **담긴 값을 `equals()`로 비교**합니다. 둘 다 비어 있으면 같다고 봅니다. `Optional`을 `Map`의 키나 `Set`의 원소로 쓰는 코드를 만나면 이 지점을 먼저 보세요(관련: `day37-equals-hashcode.md`).

## 3. 흐름 — 어디서 감싸고 어디서 벗기는가

`Optional`은 계층을 가로지르며 끝까지 끌고 다니는 타입이 아닙니다. **생기는 자리와 사라지는 자리가 정해져 있습니다.**

```
저장소/조회 메서드  →  서비스  →  컨트롤러/응답
   Optional 생성       Optional 소비      평범한 값 또는 예외
   (없을 수 있음을        (orElseThrow /     (여기엔 Optional이
    타입으로 선언)         map / filter)       남아 있지 않음)
```

### 3-1. 코드로 보는 구성

```java
public interface OrderRepository extends JpaRepository<Order, Long> {
    // 조회 결과가 없을 수 있다 — 시그니처가 직접 말합니다
    Optional<Order> findByOrderNumber(String orderNumber);
}

@Service
@RequiredArgsConstructor
public class OrderService {

    private final OrderRepository orderRepository;

    // 서비스 경계에서 Optional을 소비하고 평범한 타입으로 되돌립니다
    public OrderDetailResponse getDetail(String orderNumber) {
        Order order = orderRepository.findByOrderNumber(orderNumber)
                .orElseThrow(() -> new OrderNotFoundException(orderNumber));
        return OrderDetailResponse.from(order);
    }

    // "없음"이 정상 흐름이라면 Optional을 그대로 반환해도 됩니다
    public Optional<String> findTrackingNumber(String orderNumber) {
        return orderRepository.findByOrderNumber(orderNumber)
                .map(Order::getTrackingNumber);   // 필드가 null이면 자동으로 빈 Optional
    }
}
```

`map(Order::getTrackingNumber)`에서 게터가 `null`을 돌려주면 결과는 빈 `Optional`입니다. 이 자동 변환이 `Optional` 체이닝의 실용적인 이점입니다.

### 3-2. 실행 흐름에서 구분해야 하는 두 가지 "없음"

같은 "조회 결과 없음"이라도 둘은 다릅니다.

| 상황 | 의미 | 처리 |
|---|---|---|
| 주문번호로 조회했는데 없음 | 클라이언트가 잘못된 번호를 보냄 | `orElseThrow()` → 404 |
| 아직 송장번호가 안 붙음 | 정상 상태. 배송 전 주문 | 빈 `Optional` 그대로 반환 |

`Optional`이 유용한 건 두 번째 줄입니다. 첫 번째 줄은 어차피 예외로 끝나므로 `Optional`을 거쳐 가기만 합니다. **"없음이 정상인가"를 먼저 판단하면 반환 타입이 정해집니다.**

## 4. 특징

### 4-1. 쓰는 자리

- 값이 없을 수 있는 **메서드 반환 타입**. 특히 조회(`findBy...`) 계열
- "없음"이 예외가 아니라 정상 분기인 경우

### 4-2. 안 쓰는 자리

- **컬렉션 반환.** `Optional<List<Order>>`는 쓰지 않습니다. 없으면 빈 리스트를 돌려주면 됩니다. 호출자가 비었는지 확인하는 방법이 두 가지가 되는 게 더 나쁩니다
- **필드.** §2-2, §2-3의 이유
- **파라미터.** §5에서 따로 봅니다
- **`boolean`·`int` 같은 원시 타입 반환.** 굳이 박싱할 이유가 없고, 필요하면 `OptionalInt` 계열이 따로 있습니다

### 4-3. 트레이드오프 — 공짜가 아닙니다

`Optional`은 **객체 하나를 더 할당합니다.** 반환할 때마다 래퍼가 생깁니다. 대부분의 코드에서는 신경 쓸 수준이 아니지만, 초당 수만 번 호출되는 내부 메서드에까지 기계적으로 붙일 이유는 없습니다. JDK가 `Optional`을 "주로 반환 타입"으로 한정한 배경에도 이런 비용 인식이 있습니다.

<!-- TODO: 확인 필요 — 할당 비용의 구체적 수치는 JIT의 escape analysis 적용 여부에 따라 달라지고, 공신력 있는 최신 벤치마크를 찾지 못해 숫자는 쓰지 않았습니다. -->

가독성도 일방향이 아닙니다. 체이닝이 두세 단계를 넘어가면 `if (x == null)`보다 읽기 어려워지는 지점이 옵니다. 단일 조회의 "있으면 쓰고 없으면 예외"는 `Optional`이 명백히 낫고, 조건이 뒤섞인 분기는 아닐 수 있습니다.

## 5. 예제

### 5-1. 필드와 파라미터에 퍼뜨린 코드 ❌

```java
@Entity
public class Member {

    @Id @GeneratedValue
    private Long id;

    private String email;

    // ❌ Hibernate가 이 필드를 어떤 컬럼 타입으로 저장할지 알 수 없습니다
    private Optional<String> phoneNumber;

    // ❌ 호출자가 of/ofNullable/empty 중 무엇을 넘길지 매번 고민합니다
    public void updateContact(Optional<String> phoneNumber, Optional<String> address) {
        this.phoneNumber = phoneNumber;   // 여기에 null이 들어와도 컴파일됩니다
        // ...
    }
}
```

호출부는 이렇게 됩니다.

```java
// 호출자가 감싸는 책임을 떠안습니다 — 한 쪽이라도 null이면 그대로 필드에 박힙니다
member.updateContact(Optional.ofNullable(form.getPhone()), Optional.empty());
```

세 가지가 동시에 깨집니다. 매핑이 안 되고, 직렬화가 막히고, `Optional` 필드 자체가 `null`일 수 있는 3상태가 생깁니다.

### 5-2. 개선한 코드 ✔️

```java
@Entity
public class Member {

    @Id @GeneratedValue
    private Long id;

    private String email;

    // ✔️ 저장되는 자리는 원래 타입 그대로
    private String phoneNumber;

    // ✔️ 꺼내 주는 자리에서만 Optional로 감쌉니다 (필드 접근이라 Hibernate는 이 게터를 쓰지 않습니다)
    public Optional<String> getPhoneNumber() {
        return Optional.ofNullable(phoneNumber);
    }

    // ✔️ 파라미터는 평범한 타입. "없음"은 오버로드로 표현합니다
    public void updatePhoneNumber(String phoneNumber) {
        this.phoneNumber = Objects.requireNonNull(phoneNumber, "phoneNumber");
    }

    public void removePhoneNumber() {
        this.phoneNumber = null;
    }
}
```

파라미터 쪽 규칙을 한 문장으로 쓰면 이렇습니다. **`Optional` 파라미터는 "이 인자를 생략할 수 있다"는 뜻인데, 자바에는 그걸 표현하는 문법이 이미 있습니다 — 오버로딩입니다.** 정적 분석 도구들이 `Optional` 파라미터를 코드 스멜로 분류하는 근거도 여기에 있습니다(Sonar `java:S3553` — "Optional" should not be used for parameters).

호출부가 어떻게 달라지는지가 결정적입니다.

```java
// ❌ 호출자가 매번 포장지를 고릅니다
member.updateContact(Optional.of(phone), Optional.empty());

// ✔️ 의도가 메서드 이름에 있습니다
member.updatePhoneNumber(phone);
member.removePhoneNumber();
```

## 6. 실무에서 찾아보는 `Optional`

이 규칙을 가장 일관되게 지키는 사례가 Spring입니다. 세 군데에서 쓰이는데, **전부 "반환 타입"이거나 프레임워크가 직접 채워 주는 자리**입니다.

**1. Spring Data 리포지토리 반환 타입**

`Optional<Order> findByOrderNumber(String)` 처럼 조회 결과가 없을 수 있는 자리에 씁니다. 가장 교과서적인 용법입니다.

**2. 선택적 의존성 주입**

```java
@Service
public class NotificationService {

    private final Optional<SlackClient> slackClient;

    // 빈이 없으면 Spring이 빈 Optional을 넣어 줍니다
    public NotificationService(Optional<SlackClient> slackClient) {
        this.slackClient = slackClient;
    }
}
```

Spring 문서는 개별 파라미터를 `java.util.Optional`로 선언해 기본 required 의미를 덮어쓸 수 있다고 설명합니다([Spring Framework — Using @Autowired](https://docs.spring.io/spring-framework/reference/core/beans/annotation-config/autowired.html)). 여기서는 필드가 `Optional`인데도 괜찮습니다. **컨테이너가 반드시 인스턴스를 넣어 주므로 "필드 자체가 null"인 3상태가 구조적으로 생기지 않기 때문입니다.** 규칙이 아니라 규칙의 근거를 보면 예외가 어디서 성립하는지 보입니다.

**3. 컨트롤러 메서드 인자**

```java
@GetMapping("/orders")
public OrderListResponse list(@RequestParam Optional<String> status) {
    return orderService.list(status.orElse("ALL"));
}
```

Spring 문서는 `java.util.Optional`이 `required` 속성을 가진 애노테이션(`@RequestParam`, `@RequestHeader` 등)과 조합해 지원되며 **`required = false`와 동등**하다고 명시합니다([Spring Framework — Method Arguments](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-controller/ann-methods/arguments.html)). §5에서 "파라미터에 쓰지 말라"고 했지만 이건 내가 호출하는 메서드가 아니라 **프레임워크가 호출하는 진입점**이고, 인자를 채우는 쪽이 `null`을 넣지 않도록 보장합니다.

## 7. 함정

### 함정 1 — `Optional` 필드가 `null`

- **증상**: `Optional`을 썼는데 `NullPointerException`이 납니다. 스택트레이스는 `order.getCoupon().isPresent()` 같은 줄을 가리킵니다.
- **원인**: `Optional<Coupon> coupon` 필드를 초기화하지 않았거나, 역직렬화·리플렉션이 필드를 `null`로 채웠습니다. 문서가 "`Optional` 타입 변수는 절대 `null`이면 안 된다"고 적어 둔 그 상황입니다. 컴파일러는 막아주지 않습니다.
- **해법**: 필드에 `Optional`을 두지 않습니다. 필드는 원래 타입으로 두고 게터에서 `Optional.ofNullable()`로 감쌉니다(§5-2).

### 함정 2 — `isPresent()` + `get()`

- **증상**: `Optional`로 바꿨는데 코드 줄 수와 모양이 `null` 체크 시절과 똑같습니다.
- **원인**: `if (opt.isPresent()) { T v = opt.get(); ... }`은 `if (v != null)`의 다른 철자일 뿐입니다. 타입만 바뀌고 제어 흐름은 그대로입니다.
- **해법**: `map`·`filter`·`orElseThrow`·`ifPresentOrElse`로 바꿉니다. JDK 문서도 `get()`에 대해 **"이 메서드의 권장 대안은 `orElseThrow()`"** 라고 API Note를 달아 두었습니다(Java 10에서 인자 없는 `orElseThrow()`가 추가됐습니다).

```java
// ❌
if (couponOpt.isPresent()) {
    price = couponOpt.get().apply(price);
}

// ✔️
price = couponOpt.map(coupon -> coupon.apply(price)).orElse(price);
```

### 함정 3 — `orElse()`가 항상 실행됩니다

- **증상**: 값이 있는데도 기본값을 만드는 코드가 실행됩니다. DB 조회나 외부 호출이 들어 있으면 쿼리가 두 배로 나갑니다.
- **원인**: `orElse(other)`의 인자는 **메서드 호출 전에 평가되는 평범한 인자**입니다. 값의 존재 여부와 무관하게 계산됩니다. `orElseGet(Supplier)`만 필요할 때 공급자를 호출합니다.
- **해법**: 기본값이 상수면 `orElse`, 계산이나 I/O가 끼면 반드시 `orElseGet`.

```java
// ❌ 캐시에 값이 있어도 loadFromDatabase()가 매번 실행됩니다
Order order = cache.find(orderId).orElse(loadFromDatabase(orderId));

// ✔️ 비었을 때만 실행됩니다
Order order = cache.find(orderId).orElseGet(() -> loadFromDatabase(orderId));
```

### 함정 4 — `Optional.of(null)`

- **증상**: 값을 감싸기만 했는데 그 줄에서 `NullPointerException`이 납니다.
- **원인**: `of()`는 `null`을 거부합니다. "절대 null이 아님"을 주장하는 메서드입니다.
- **해법**: null일 수 있으면 `ofNullable()`. 반대로 **여기서 null이면 버그라고 단정할 수 있는 자리에는 일부러 `of()`를 씁니다.** 조용히 빈 `Optional`이 되어 흘러가는 것보다 그 줄에서 터지는 편이 낫습니다.

### 함정 5 — `==`로 비었는지 확인

- **증상**: 로컬에서는 멀쩡한데 특정 환경·버전에서 분기가 반대로 탑니다.
- **원인**: `opt == Optional.empty()` 비교입니다. `Optional.empty()`가 같은 인스턴스를 돌려준다는 보장이 문서에 없습니다. 값 기반 클래스라 JVM이 인스턴스를 자유롭게 다룰 수 있습니다.
- **해법**: `isEmpty()`(Java 11 추가) 또는 `isPresent()`를 씁니다. 같은 이유로 `Optional`을 `synchronized` 락 객체로 쓰지 않습니다.

### 함정 6 — `Optional<List<T>>`

- **증상**: 호출자마다 체크 방식이 다릅니다. 누구는 `isPresent()`, 누구는 `orElse(List.of()).isEmpty()`.
- **원인**: "비어 있음"을 표현하는 방법이 두 개가 됐습니다. 빈 `Optional`과 빈 리스트가 의미상 같은데 타입이 다릅니다.
- **해법**: 컬렉션은 `Optional`로 감싸지 않고 **빈 컬렉션을 반환**합니다. `null`도 반환하지 않습니다.

## 8. 참고자료

- [Java 25 API — `java.util.Optional`](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/Optional.html) — 클래스 API Note, 값 기반 클래스 주의, `get()`의 권장 대안
- [Spring Framework — Using `@Autowired`](https://docs.spring.io/spring-framework/reference/core/beans/annotation-config/autowired.html) — 선택적 의존성과 `Optional`
- [Spring Framework — Method Arguments](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-controller/ann-methods/arguments.html) — 컨트롤러 인자에서의 `Optional`
- [Spring Boot 3.3 — JSON](https://docs.spring.io/spring-boot/3.3/reference/features/json.html) · [Introducing Jackson 3 support in Spring](https://spring.io/blog/2025/10/07/introducing-jackson-3-support-in-spring/) — 모듈 등록 방식
- [JetBrains Inspectopedia — Optional used as field or parameter type](https://jetbrains.com/help/inspectopedia/OptionalUsedAsFieldOrParameterType.html)
- [Vlad Mihalcea — The best way to map a Java 1.8 Optional entity attribute](https://vladmihalcea.com/the-best-way-to-map-a-java-1-8-optional-entity-attribute-with-jpa-and-hibernate/)
- 관련 챕터: `day11-null-traps.md` (DB의 NULL) · `day37-equals-hashcode.md` (값 비교 계약) · `day43-immutability.md` (불변 설계) · `day14-dto-vs-entity.md` (계층 간 타입 분리)

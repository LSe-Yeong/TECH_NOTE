# 의존성 주입은 무슨 문제를 푸는가

> 이 문서가 답할 질문: **의존성 주입(DI)은 `new` 한 줄을 대신해주는 편의 기능인가, 아니면 그 이상의 무엇인가?**
>
> 기준: Spring Boot 4.1.0 (2026-06-10 GA) / Spring Framework 7.0.x. 순환 참조 관련 동작은 Spring Boot 2.6부터 동일합니다.

## 1. 핵심 개념 — 바뀌는 건 "누가 결정하는가"

의존성 주입은 객체가 **자기가 쓸 협력 객체를 스스로 만들지 않고**, 생성자 인자·팩토리 메서드 인자·세터를 통해서만 받아들이는 방식입니다. 만드는 일은 컨테이너가 합니다. 제어의 흐름이 뒤집혀서 제어의 역전(IoC, Inversion of Control)이라고 부릅니다 ([Spring Framework — The IoC Container](https://docs.spring.io/spring-framework/reference/core/beans/introduction.html)).

정의만 보면 "그래서 뭐가 좋은데"가 안 나옵니다. 없을 때를 봐야 합니다.

```java
public class OrderService {

    private final PaymentClient paymentClient = new TossPaymentClient();  // 여기가 문제

    public void place(Order order) {
        paymentClient.pay(order.amount());
    }
}
```

이 코드는 잘 돕니다. 문제는 `OrderService`가 **결제 수단을 고르는 결정까지 떠안았다**는 것입니다. 결제사를 바꾸려면 주문 코드를 고쳐야 하고, 테스트에서 가짜 결제를 쓰려면 그럴 방법이 없습니다. 실제 결제 API를 때려야 주문 로직을 검증할 수 있습니다.

> `new`는 결합을 만듭니다. 그리고 그 결합은 **컴파일 시점에 굳어서** 실행 시점에 바꿀 수 없습니다. DI가 푸는 문제는 "객체 생성이 귀찮다"가 아니라 **"쓰는 쪽이 고르는 결정까지 하고 있다"**입니다. 이걸 방치하면 나중에 테스트를 짜려는 순간 벽을 만납니다. 그때는 이미 고칠 클래스가 200개입니다.

주입으로 바꾸면 이렇게 됩니다.

```java
public class OrderService {

    private final PaymentClient paymentClient;

    public OrderService(PaymentClient paymentClient) {   // 받아서 쓴다. 고르지 않는다
        this.paymentClient = paymentClient;
    }
}
```

`OrderService`는 이제 "결제할 무언가가 필요하다"고 선언만 합니다. 무엇을 줄지는 바깥이 정합니다. 프로덕션에서는 컨테이너가, 테스트에서는 테스트 코드가 정합니다.

## 2. 구조

### 2-1. 주입 지점은 세 곳입니다

| 방식 | 형태 | 컨테이너 없이 조립 | `final` 가능 |
|---|---|---|---|
| 생성자 주입 | 생성자 파라미터 | 가능 | 가능 |
| 세터 주입 | `@Autowired` setter | 가능(호출 누락 위험) | 불가 |
| 필드 주입 | 필드에 `@Autowired` | 불가(리플렉션 필요) | 불가 |

Spring 팀의 공식 권고는 명확합니다. 레퍼런스 문서는 생성자 주입을 "컴포넌트를 불변 객체로 만들 수 있고 필수 의존성이 `null`이 아님을 보장하기 때문에" 권장하고, 세터 주입은 "기본값을 줄 수 있는 선택적 의존성에만" 쓰라고 적습니다 ([Dependency Injection](https://docs.spring.io/spring-framework/reference/core/beans/dependencies/factory-collaborators.html)). Spring Boot 레퍼런스도 "생성자 주입으로 의존성을 연결할 것을 일반적으로 권장한다"고 씁니다 ([Spring Beans and Dependency Injection](https://docs.spring.io/spring-boot/reference/using/spring-beans-and-dependency-injection.html)).

생성자가 하나뿐이면 `@Autowired`를 붙일 필요가 없습니다. 문서의 표현 그대로 "대상 빈이 생성자를 하나만 정의한다면 그 생성자에 `@Autowired`는 필요하지 않습니다"입니다. **둘 이상이면 하나를 반드시 지정해야 합니다.**

### 2-2. 후보가 여러 개일 때

같은 타입의 빈이 두 개 이상이면 컨테이너는 고를 수 없어서 예외를 던집니다. 조정 수단이 세 가지입니다.

- `@Qualifier("tossPaymentClient")` — 주입받는 쪽이 이름으로 지목합니다. 가장 명시적입니다.
- `@Primary` — "후보가 여럿이면 나를 골라라". 제공하는 쪽이 기본값을 선언합니다.
- `@Fallback` — Spring Framework 6.2에서 추가됐습니다. `@Primary`의 거울상입니다. **"다른 게 하나도 없을 때만 나를 골라라"**입니다 ([@Primary or @Fallback](https://docs.spring.io/spring-framework/reference/core/beans/annotation-config/autowired-primary.html)).

`@Fallback`이 실무에서 의미 있는 지점은 라이브러리나 공통 모듈을 만들 때입니다. 기본 구현에 `@Fallback`을 달아두면, 사용하는 쪽이 자기 구현을 하나 등록하는 순간 별도 설정 없이 그쪽이 선택됩니다. `@Primary`로 같은 걸 하려면 사용하는 쪽이 자기 빈에 `@Primary`를 붙여야 합니다 — 즉 사용자에게 숙제를 넘기게 됩니다.

### 2-3. 없어도 되는 의존성

필수가 아닌 의존성을 표현하는 방법도 문서화돼 있습니다.

```java
// 1) 아예 안 들어올 수 있음
public OrderService(@Autowired(required = false) DiscountPolicy policy) { ... }

// 2) 타입으로 드러내기
public OrderService(Optional<DiscountPolicy> policy) { ... }

// 3) 지연 조회 + 0개/여러 개를 다루기
private final ObjectProvider<DiscountPolicy> policies;
```

`ObjectProvider`가 가장 유연합니다. 필요한 순간에 조회하고, `getIfAvailable()`·`orderedStream()`으로 "없으면 넘어가기"와 "있는 만큼 전부 돌기"를 모두 표현할 수 있습니다.

## 3. 흐름

### 3-1. 코드로 보는 구성

```java
public interface PaymentClient {
    PaymentResult pay(long amount);
}

@Component
public class TossPaymentClient implements PaymentClient {
    @Override
    public PaymentResult pay(long amount) {
        // 실제 PG 호출
        return PaymentResult.success();
    }
}

@Service
public class OrderService {

    private final PaymentClient paymentClient;
    private final OrderRepository orderRepository;

    // 생성자 하나 → @Autowired 불필요
    public OrderService(PaymentClient paymentClient, OrderRepository orderRepository) {
        this.paymentClient = paymentClient;
        this.orderRepository = orderRepository;
    }

    public Long place(Order order) {
        PaymentResult result = paymentClient.pay(order.amount());
        order.markPaid(result.transactionId());
        return orderRepository.save(order).getId();
    }
}
```

### 3-2. 조립 순서

컨테이너가 하는 일을 순서대로 보면 이렇습니다.

1. 컴포넌트 스캔 → `@Component`/`@Service`가 붙은 클래스를 찾아 **빈 정의**를 등록합니다. 아직 객체는 없습니다.
2. `OrderService` 생성 요청 → 생성자 파라미터 타입을 봅니다. `PaymentClient`가 필요합니다.
3. `PaymentClient` 타입 후보를 찾습니다. 하나면 확정, 여럿이면 `@Qualifier` → `@Primary` → `@Fallback` → 파라미터 이름 순으로 좁힙니다.
4. `TossPaymentClient`를 먼저 만듭니다. → 그다음 `OrderService` 생성자를 호출합니다.
5. 반환 시점에 `OrderService`는 **완전히 조립된 상태**입니다.

5번이 핵심입니다. 문서 표현으로는 "생성자 주입된 컴포넌트는 언제나 완전히 초기화된 상태로 호출 코드에 반환됩니다". 세터·필드 주입은 이 보장이 없습니다. 객체가 만들어진 **다음에** 채워지므로, 그 사이에는 필드가 `null`인 반쯤 완성된 객체가 존재합니다.

## 4. 특징

### 4-1. 생성자 주입이 실제로 주는 것

- **`final`을 쓸 수 있습니다.** 조립 이후 아무도 바꿀 수 없습니다. 싱글톤 빈이 여러 스레드에서 동시에 쓰이는 환경에서 이건 안전장치입니다.
- **컴파일러가 검사해줍니다.** 의존성을 하나 추가하면 그 클래스를 `new`로 만들던 모든 코드(주로 테스트)가 컴파일 에러를 냅니다. 필드 주입은 조용히 `null`이 되고 런타임 NPE로 나타납니다.
- **컨테이너 없이 테스트할 수 있습니다.** `new OrderService(fakePaymentClient, fakeRepository)`면 끝입니다. `@SpringBootTest`를 띄우지 않아도 됩니다.
- **의존성 개수가 눈에 보입니다.** 생성자 파라미터가 9개면 코드 리뷰에서 걸립니다. 필드 주입은 10개든 20개든 세로로 늘어날 뿐이라 아무도 안 셉니다.

마지막 항목이 과소평가됩니다. **생성자 주입은 설계가 나빠지는 걸 눈에 보이게 만드는 장치입니다.** 파라미터가 계속 늘면 그 클래스가 너무 많은 일을 한다는 신호이고, 쪼개라는 뜻입니다.

### 4-2. 대가

공짜는 아닙니다.

- **런타임까지 가야 알 수 있는 오류가 생깁니다.** `new`는 컴파일 시점에 결정되지만 DI는 컨테이너 기동 시점에 결정됩니다. 타입이 안 맞거나 후보가 둘이면 컴파일은 통과하고 **애플리케이션 시작이 실패**합니다.
- **실제로 무엇이 주입됐는지 코드만 봐서는 모릅니다.** `PaymentClient` 구현이 세 개면 어느 게 들어갔는지 설정과 조건부 빈까지 추적해야 합니다. IDE의 "Go to implementation"이 갈래를 못 좁혀줍니다.
- **기동 시간이 늘어납니다.** 스캔·프록시 생성·의존성 해석이 전부 시작 비용입니다.
- **모든 클래스가 빈일 필요는 없습니다.** 값 객체(`Order`, `Money`)나 순수 계산 유틸까지 컨테이너에 올리면 복잡도만 늘어납니다. **의존성이 바뀔 여지가 있고, 생명주기 관리가 필요한 것만** 빈으로 만듭니다.

## 5. 예제 — 필드 주입에서 생성자 주입으로

### 5-1. 클린하지 않은 코드 ❌

```java
@Service
public class SettlementService {

    @Autowired private OrderRepository orderRepository;
    @Autowired private PaymentClient paymentClient;
    @Autowired private LedgerClient ledgerClient;

    public void settle(LocalDate date) { /* ... */ }
}
```

짧아서 좋아 보입니다. 세 가지가 무너집니다.

1. `final`을 못 씁니다. 누가 나중에 `settlementService.orderRepository = ...` 로 바꿔치기해도 막을 수 없습니다.
2. 단위 테스트에서 `new SettlementService()`를 하면 필드가 전부 `null`입니다. 값을 넣으려면 리플렉션(`ReflectionTestUtils`)을 쓰거나 컨테이너를 통째로 띄워야 합니다. **테스트가 무거워지는 원인이 여기서 시작됩니다.**
3. 의존성을 하나 더 붙여도 아무 코드도 깨지지 않습니다. 그래서 계속 늘어납니다.

### 5-2. 개선한 코드 ✔️

```java
@Service
public class SettlementService {

    private final OrderRepository orderRepository;
    private final PaymentClient paymentClient;
    private final LedgerClient ledgerClient;

    public SettlementService(OrderRepository orderRepository,
                             PaymentClient paymentClient,
                             LedgerClient ledgerClient) {
        this.orderRepository = orderRepository;
        this.paymentClient = paymentClient;
        this.ledgerClient = ledgerClient;
    }

    public void settle(LocalDate date) { /* ... */ }
}
```

테스트는 이렇게 바뀝니다.

```java
@Test
void 결제_실패한_주문은_정산에서_제외한다() {
    SettlementService service = new SettlementService(
            new InMemoryOrderRepository(),
            new AlwaysFailPaymentClient(),
            new RecordingLedgerClient());

    service.settle(LocalDate.of(2026, 8, 10));
    // 스프링 컨텍스트 없음. 밀리초 단위로 끝납니다.
}
```

생성자가 길어지는 게 부담이면 Lombok `@RequiredArgsConstructor`로 줄일 수 있습니다. 단, 이 애너테이션은 **선언부에서 초기화되지 않은 `final` 필드와 `@NonNull` 필드만** 생성자에 넣습니다 ([Lombok — @RequiredArgsConstructor](https://projectlombok.org/features/constructor)). `final`을 빠뜨린 필드는 조용히 주입 대상에서 빠지고 `null`로 남습니다.

## 6. DI가 지키는 원칙 — 의존성 역전

DI라는 **기법**이 서비스하는 **원칙**은 의존성 역전 원칙(DIP, Dependency Inversion Principle)입니다. 상위 정책(주문 처리)이 하위 세부사항(특정 PG사)에 의존하지 않게 만드는 것입니다.

여기서 흔한 오해가 하나 있습니다. **생성자로 주입받기만 하면 DIP를 지킨 게 아닙니다.**

```java
// ❌ 주입은 받지만 방향은 그대로다
public OrderService(TossPaymentClient tossPaymentClient) { ... }
```

구체 클래스를 파라미터 타입으로 받으면 결합은 그대로입니다. PG를 바꾸는 순간 이 시그니처를 고쳐야 합니다. 인터페이스를 받아야 방향이 뒤집힙니다.

```java
// ✔️ OrderService가 필요로 하는 계약을 스스로 정의하고, 구현이 그것을 따라온다
public OrderService(PaymentClient paymentClient) { ... }
```

다만 **인터페이스를 무조건 뽑는 것도 낭비**입니다. 구현이 하나뿐이고 바뀔 계획이 없다면 인터페이스 하나에 구현 하나짜리 파일 두 개가 늘 뿐입니다. 판단 기준은 "구현이 바뀔 여지가 있는가"와 "테스트에서 다른 걸 끼워야 하는가", 둘 중 하나라도 예인 경우입니다.

## 7. 순환 참조는 DI가 보내는 설계 신호입니다

`OrderService`가 `PaymentService`를, `PaymentService`가 다시 `OrderService`를 생성자로 주입받으면 컨테이너는 둘 중 무엇도 먼저 만들 수 없습니다. 문서 표현대로 "해결 불가능한 순환 의존" 상황이고, `BeanCurrentlyInCreationException`이 납니다.

Spring Boot는 2.6부터 순환 참조를 **기본 금지**로 바꿨습니다 ([Spring Boot 2.6 Release Notes](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-2.6-Release-Notes)). 실패 분석기가 이런 메시지를 출력합니다.

```
The dependencies of some of the beans in the application context form a cycle:

┌─────┐
|  orderService
↑     ↓
|  paymentService
└─────┘

Action:
Relying upon circular references is discouraged and they are prohibited by
default. Update your application to remove the dependency cycle between beans.
As a last resort, it may be possible to break the cycle automatically by
setting spring.main.allow-circular-references to true.
```

메시지가 스스로 "최후의 수단"이라고 말합니다. `SpringApplication#setAllowCircularReferences`의 javadoc도 기본값이 `false`임을 명시합니다.

**순환이 생겼다는 건 두 클래스의 책임 경계가 잘못 그어졌다는 뜻입니다.** 실무에서 쓸 수 있는 선택지를 위험한 순서대로 놓으면 이렇습니다.

1. **공통 책임을 제3의 클래스로 뽑습니다.** 대부분 이게 정답입니다. 두 서비스가 서로를 부르는 이유는 보통 양쪽에 걸친 로직 하나가 어디에도 못 가고 있어서입니다.
2. **한쪽을 이벤트로 뒤집습니다.** `ApplicationEventPublisher`로 사실만 알리면 호출 방향이 한쪽으로 정리됩니다.
3. **`@Lazy`로 지연 해석 프록시를 주입합니다.** javadoc이 밝히듯 프록시는 **항상 주입되고**, 대상이 실제로 없으면 호출하는 순간에야 예외로 알게 됩니다 ([@Lazy javadoc](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/context/annotation/Lazy.html)). 기동은 성공하는데 특정 요청에서만 터지는 형태로 문제가 옮겨갑니다.
4. **`spring.main.allow-circular-references=true`.** 순환을 없애는 게 아니라 안 보이게 덮는 것입니다.

3번과 4번은 **문제를 기동 시점에서 요청 시점으로 미루는 일**입니다. 기동할 때 실패하는 편이 항상 낫습니다.

## 8. 함정

**함정 1 — 필드 주입이 테스트를 통째로 무겁게 만든다**

- **증상**: 단위 테스트가 없고 전부 `@SpringBootTest`입니다. 테스트 한 번 도는 데 몇 분씩 걸리고, 결국 아무도 로컬에서 안 돌립니다.
- **원인**: 필드 주입 클래스는 컨테이너 없이 조립할 수 없습니다. `new`로 만들면 필드가 전부 `null`이라 컨텍스트를 띄우는 것 외에 방법이 없습니다.
- **해법**: 생성자 주입으로 바꿉니다. 전부 한 번에 바꿀 필요는 없고, 테스트를 새로 짜는 클래스부터 하나씩 옮깁니다. 옮긴 클래스는 즉시 `new`로 테스트가 가능해집니다.

**함정 2 — 같은 타입 빈이 둘이 되는 순간 기동이 죽는다**

- **증상**: 잘 돌던 애플리케이션에 구현체를 하나 추가했더니 `NoUniqueBeanDefinitionException: expected single matching bean but found 2`로 시작이 안 됩니다.
- **원인**: 타입만으로 후보를 못 좁힙니다. 자기 코드가 아니라 **의존성으로 딸려 온 자동 구성 빈** 때문에 생기는 경우도 많습니다.
- **해법**: 주입받는 쪽이 확실히 알면 `@Qualifier`, 제공하는 쪽이 기본값을 정하는 게 맞으면 `@Primary`, 라이브러리의 기본 구현이면 `@Fallback`을 씁니다. 세 개는 우선순위가 다른 게 아니라 **결정 주체가 다른** 도구입니다.

**함정 3 — 싱글톤 빈에 상태를 들고 있다**

- **증상**: 부하가 없을 땐 멀쩡한데 동시 요청이 몰리면 A 사용자의 데이터가 B 응답에 섞여 나옵니다. 재현이 거의 안 됩니다.
- **원인**: 스프링 빈은 기본 스코프가 싱글톤입니다. 인스턴스 하나를 모든 요청 스레드가 공유합니다. 주입받은 협력 객체가 아니라 **처리 도중 값을 담아둔 필드**가 원인입니다.
- **해법**: 빈의 필드는 주입받은 의존성만 두고 전부 `final`로 막습니다. 요청별 데이터는 메서드 지역 변수나 파라미터로 넘깁니다. 생성자 주입 + `final`을 쓰면 이 실수를 애초에 못 하게 됩니다.

**함정 4 — 생성자를 하나 더 만들었더니 기동이 실패한다**

- **증상**: 테스트 편의용 생성자를 추가한 뒤 `No default constructor found` 또는 엉뚱한 생성자로 조립됩니다.
- **원인**: 생성자가 하나일 때만 `@Autowired` 생략이 성립합니다. 둘 이상이면 컨테이너가 어느 것을 쓸지 모릅니다.
- **해법**: 쓸 생성자에 `@Autowired`를 명시합니다. 애초에 테스트용 생성자는 만들지 않는 편이 낫습니다 — 생성자 주입이면 테스트도 정식 생성자를 그대로 쓰면 됩니다.

**함정 5 — 컨테이너에 없는 객체에서 빈을 꺼내 쓴다**

- **증상**: `new`로 직접 만든 객체 안에서 `@Autowired` 필드가 `null`입니다. 같은 클래스인데 스프링이 만든 인스턴스에서는 잘 됩니다.
- **원인**: 주입은 **컨테이너가 만든 인스턴스에만** 일어납니다. `new`로 만든 건 컨테이너가 모릅니다.
- **해법**: 그 객체도 빈으로 등록하거나, 필요한 협력 객체를 생성자 인자로 넘겨받습니다. 조건에 따라 동적으로 빈을 만들어야 한다면 Spring Framework 7에 추가된 `BeanRegistrar`로 등록 시점에 프로그래밍 방식으로 처리하는 방법도 있습니다 ([Programmatic Bean Registration](https://docs.spring.io/spring-framework/reference/core/beans/java/programmatic-bean-registration.html)). `ApplicationContext`를 주입받아 `getBean()`을 부르는 건 DI를 다시 서비스 로케이터로 되돌리는 일이라 마지막 수단입니다.

## 9. 정리

- DI가 푸는 문제는 객체 생성의 번거로움이 아니라 **"쓰는 쪽이 고르는 결정까지 하고 있다"**는 결합입니다.
- 생성자 주입이 기본입니다. `final`·컴파일 타임 검사·컨테이너 없는 테스트·의존성 개수 가시화, 넷을 한 번에 줍니다.
- 세터 주입은 기본값을 줄 수 있는 **선택적 의존성**용입니다. 필드 주입은 테스트를 인질로 잡습니다.
- 후보가 여럿일 때 `@Qualifier`·`@Primary`·`@Fallback`은 우열이 아니라 **결정 주체가 누구냐**의 차이입니다.
- 순환 참조는 버그가 아니라 **설계 신호**입니다. `allow-circular-references`나 `@Lazy`로 덮으면 기동 시점 실패가 요청 시점 실패로 바뀔 뿐입니다.
- DI의 대가는 런타임 결정입니다. 잘못된 조립은 컴파일이 아니라 **기동에서** 드러납니다. 그래서 기동 실패는 좋은 소식입니다.

## 10. 참고자료

- [Spring Framework — The IoC Container (Introduction)](https://docs.spring.io/spring-framework/reference/core/beans/introduction.html)
- [Spring Framework — Dependency Injection](https://docs.spring.io/spring-framework/reference/core/beans/dependencies/factory-collaborators.html)
- [Spring Framework — Using @Autowired](https://docs.spring.io/spring-framework/reference/core/beans/annotation-config/autowired.html)
- [Spring Framework — Fine-tuning Autowiring with @Primary or @Fallback](https://docs.spring.io/spring-framework/reference/core/beans/annotation-config/autowired-primary.html)
- [Spring Framework — Programmatic Bean Registration](https://docs.spring.io/spring-framework/reference/core/beans/java/programmatic-bean-registration.html)
- [Spring Boot — Spring Beans and Dependency Injection](https://docs.spring.io/spring-boot/reference/using/spring-beans-and-dependency-injection.html)
- [Spring Boot 2.6 Release Notes — Circular References Prohibited by Default](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-2.6-Release-Notes)
- [Spring Boot 4.1.0 available now](https://spring.io/blog/2026/06/10/spring-boot-4/)
- 요청이 컨트롤러까지 도달하는 과정과 그 사이의 빈들은 `daily/day02-spring-request-flow.md`에서 다룹니다.

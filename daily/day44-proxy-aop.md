# `@Transactional`을 붙였는데 왜 안 먹는가

> 이 문서가 답할 질문: **애노테이션은 분명히 붙어 있는데 트랜잭션이 걸리지 않는다. 프록시 기반 AOP는 무엇을 보고 무엇을 못 보길래 이런 일이 생기는가?**
>
> 분류: 문제해결형(증상 → 원인 → 해법). 여러 출처에서 공통으로 보고되는 증상은 "예외가 났는데 롤백이 안 됐다" 하나인데, 그 뒤의 원인은 전혀 다른 것이 최소 여섯 가지라 원인별로 갈라서 조사했습니다.
>
> 기준: **Spring Boot 4.1 / Spring Framework 7.0** 레퍼런스와 `spring-aop`·`spring-tx`·`spring-context` 7.0.x 소스를 확인해 썼습니다. 빈이 언제 만들어지는지는 `daily/day32-bean-lifecycle.md`, 자기 주입이 순환 참조로 이어지는 문제는 `daily/day38-circular-reference.md`에서 다뤘으므로 여기서는 참조만 합니다. 트랜잭션 전파(`REQUIRES_NEW` 등)는 범위 밖입니다.

## 1. 핵심 개념 — 내가 주입받은 건 내가 만든 객체가 아닙니다

`@Transactional`은 코드를 바꾸지 않습니다. 컴파일러도, JVM도 이 애노테이션을 모릅니다. 트랜잭션을 여는 코드는 **내 클래스를 상속하거나 내 인터페이스를 구현한 다른 객체**가 실행합니다. 그게 프록시입니다.

```java
@Service
public class OrderService {
    @Transactional
    public void place(OrderCommand command) { /* ... */ }
}
```

```java
@Autowired OrderService orderService;

// 실행 중에 찍어보면 내 클래스가 아닙니다
System.out.println(orderService.getClass());
// class com.example.order.OrderService$$SpringCGLIB$$0
```

> 애노테이션은 **선언**일 뿐이고, 실제 동작은 "누가 그 메서드를 부르느냐"가 정합니다. 프록시를 거쳐서 부르면 트랜잭션이 열리고, 거치지 않고 부르면 그냥 평범한 메서드 호출입니다. 그런데 **거치지 않고 불렀을 때 예외도 로그도 없습니다.** 코드는 정상적으로 동작하고, 커밋만 안 됩니다. 이게 이 문제가 스테이징을 통과해서 프로덕션까지 가는 이유입니다.

Spring AOP의 조인 포인트가 **메서드 실행 하나뿐**인 것도 여기서 나옵니다([레퍼런스 용어 정의](https://docs.spring.io/spring-framework/reference/core/aop/introduction-defn.html)). 프록시가 가로챌 수 있는 건 자기를 통해 들어오는 호출뿐이니까요.

## 2. 구조 — 프록시가 만들어지는 자리와 두 가지 방식

컨테이너가 빈을 초기화한 **직후**, 자동 프록시 생성기(`BeanPostProcessor`의 일종)가 그 빈을 감싼 새 객체를 만들어 컨테이너에 대신 등록합니다. 그래서 다른 빈이 주입받는 건 원본이 아니라 프록시입니다.

만드는 방식은 두 가지입니다.

| | JDK 동적 프록시 | CGLIB 프록시 |
|---|---|---|
| 만드는 법 | 인터페이스를 구현한 클래스를 런타임 생성 | 대상 클래스를 **상속**한 서브클래스를 생성 |
| 전제 조건 | 대상이 인터페이스를 하나 이상 구현 | 클래스가 `final`이 아닐 것 |
| 가로챌 수 있는 것 | 인터페이스에 선언된 `public` 메서드 | `public` · `protected` · package-private 메서드 |
| 못 가로채는 것 | 인터페이스에 없는 메서드 전부 | `final` 메서드, `private` 메서드 |

**Spring Boot는 CGLIB가 기본값입니다.** 레퍼런스가 "By default, Spring Boot's auto-configuration configures Spring AOP to use CGLib proxies. To use JDK proxies instead, set `spring.aop.proxy-target-class` to `false`"라고 명시합니다([Spring Boot Reference — AOP](https://docs.spring.io/spring-boot/reference/features/aop.html)). 인터페이스를 만들어 뒀어도 기본 설정에서는 서브클래스 프록시가 생깁니다.

Spring Framework 7.0부터는 빈 단위로 `@Proxyable(INTERFACES)` / `@Proxyable(TARGET_CLASS)`를 붙여 방식을 지정할 수 있습니다([Proxying Mechanisms](https://docs.spring.io/spring-framework/reference/core/aop/proxying.html)).

### 2-1. 메서드 가시성 규칙은 6.0에서 한 번 바뀌었습니다

Spring Framework 6.0부터 **`protected`·package-private 메서드도 클래스 기반 프록시에서는 트랜잭션이 걸립니다.** `AbstractFallbackTransactionAttributeSource`의 `allowPublicMethodsOnly()` 기본값이 `false`이기 때문입니다. 예전 동작(비공개 메서드 전부 무시)으로 되돌리려면 명시적으로 등록해야 합니다.

```java
@Bean
TransactionAttributeSource transactionAttributeSource() {
    return new AnnotationTransactionAttributeSource(true);  // publicMethodsOnly
}
```

`private`은 이 규칙과 무관하게 **영원히 안 됩니다.** 서브클래스가 오버라이드할 수 없는 메서드라 CGLIB가 손댈 자리가 없습니다.

## 3. 흐름 — 프록시를 지나는 길과 지나지 않는 길

지나는 길:

```
Controller → (프록시).place() → TransactionInterceptor
                              → 트랜잭션 시작
                              → 원본 OrderService.place() 실행
                              → 커밋 또는 롤백
```

지나지 않는 길:

```
Controller → (프록시).place() → 트랜잭션 시작
                              → 원본 OrderService.place() 실행
                                  └→ this.saveHistory()  ← 원본 객체에서 원본 객체로.
                                                            프록시가 관여할 자리가 없음
```

핵심은 마지막 줄입니다. 프록시는 **바깥 문**이지 내부 배선이 아닙니다. 일단 원본 객체 안으로 들어오면 `this`는 원본을 가리키고, 그 뒤의 호출은 전부 프록시 바깥에서 벌어집니다.

## 4. 안 먹는 여섯 가지 경우

### 4-1. `this`로 부른다 (압도적 1위)

```java
@Service
public class OrderService {
    public void place(OrderCommand command) {
        validate(command);
        saveOrder(command);   // ❌ @Transactional이 무시됩니다
    }

    @Transactional
    public void saveOrder(OrderCommand command) { /* ... */ }
}
```

레퍼런스가 직접 못 박습니다. "in proxy mode (which is the default), only external method calls coming in through the proxy are intercepted"([Annotations](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/annotations.html)).

`this.`를 생략해도 같습니다. 컴파일러가 `this.saveOrder(...)`로 바꿔 줄 뿐입니다.

### 4-2. `private` 또는 `final` 메서드다

`private`은 4-1보다 더 조용합니다. `AbstractFallbackTransactionAttributeSource`는 트랜잭션 속성을 찾아내지만, CGLIB가 그 메서드를 오버라이드하지 못해 인터셉터가 끼어들 자리가 없습니다. 로그도 없습니다.

`final`은 그나마 흔적을 남깁니다. `CglibAopProxy`가 클래스를 검증하면서 경고를 찍습니다.

```
Public final method [...] cannot get proxied via CGLIB,
consider removing the final marker or using interface-based JDK proxies.
```

다만 이 검증은 **로거가 INFO 이상일 때만** 수행됩니다(`spring-aop` 7.0.x `CglibAopProxy#validateClassIfNecessary`). 운영에서 `org.springframework.aop`를 WARN으로 올려 두면 이 경고 자체가 안 나옵니다. Kotlin 클래스가 기본 `final`이라 자주 밟히는 자리이기도 합니다.

### 4-3. 그 객체가 빈이 아니다

```java
// ❌ 직접 new 한 객체에는 프록시가 없습니다
OrderService service = new OrderService(orderRepository);
service.place(command);
```

테스트 코드에서 특히 자주 나옵니다. 단위 테스트에서 `new`로 만들어 돌리면 트랜잭션 관련 동작은 하나도 검증되지 않습니다.

### 4-4. 프록시가 붙기 전에 빈이 만들어졌다

`BeanPostProcessor`가 어떤 빈을 주입받으면, 그 빈은 자동 프록시 생성기보다 **먼저** 만들어집니다. 프록시를 붙일 순서를 놓치는 겁니다. 이때 컨테이너가 기동 로그에 WARN을 남깁니다.

```
Bean 'orderService' of type [com.example.order.OrderService]
is not eligible for getting processed by all BeanPostProcessors
(for example: not eligible for auto-proxying)
```

이 줄이 로그에 있으면 원인 찾기가 끝난 겁니다(`spring-context` 7.0.x `PostProcessorRegistrationDelegate.BeanPostProcessorChecker`). 기동 로그에서 한 번 검색해 볼 가치가 있습니다.

### 4-5. `@PostConstruct` 안에서 부른다

레퍼런스가 명시합니다. "the proxy must be fully initialized to provide the expected behavior, so you should not rely on this feature in your initialization code — for example, in a `@PostConstruct` method." 프록시는 초기화 콜백이 **끝난 뒤**에 씌워지므로, 초기화 중인 자기 자신은 아직 프록시가 아닙니다.

### 4-6. 프록시는 탔는데 롤백이 안 된다

여기부터는 프록시 문제가 아닙니다. 증상이 똑같아서 같이 다룹니다.

```java
@Transactional
public void place(OrderCommand command) {
    orderRepository.save(command.toOrder());
    throw new InsufficientStockException();  // checked exception
}
```

기본 롤백 규칙은 **`RuntimeException`과 `Error`뿐**입니다. checked exception은 커밋됩니다([Rolling Back](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/rolling-back.html)). 해법은 셋입니다.

- 예외를 `RuntimeException` 계열로 설계한다 (기본값)
- `@Transactional(rollbackFor = InsufficientStockException.class)`
- Spring Framework 6.2부터 전역 변경: `@EnableTransactionManagement(rollbackOn = ALL_EXCEPTIONS)`

세 번째는 편하지만 "checked를 던져도 커밋된다"를 전제로 짠 기존 코드를 조용히 바꿔 버립니다. 새 프로젝트가 아니면 권하지 않습니다.

반대 방향의 함정도 있습니다. 안쪽 트랜잭션에서 예외가 나 롤백 마크가 찍혔는데 바깥에서 `try-catch`로 삼키면, 커밋 시점에 이게 터집니다.

```
UnexpectedRollbackException: Transaction silently rolled back
because it has been marked as rollback-only
```

## 5. 진단 절차 — 3분 안에 원인 좁히기

증상이 하나이므로 순서를 정해 두는 게 빠릅니다.

1. **프록시가 붙긴 했나** — 문제 메서드 안에서 `getClass().getName()`을 찍습니다. `$$SpringCGLIB$$`나 `$Proxy`가 없으면 4-3 또는 4-4입니다.
2. **트랜잭션이 열렸나** — `TransactionSynchronizationManager.isActualTransactionActive()`가 `false`면 프록시를 안 탄 겁니다.
3. **호출부를 본다** — 같은 클래스 안에서 불렀으면 4-1입니다.
4. **시그니처를 본다** — `private`·`final`이면 4-2입니다.
5. **여기까지 다 통과했다면** 프록시는 탄 겁니다. 4-6, 즉 롤백 규칙 문제입니다.

1~2번은 아래 로거만 켜도 확인됩니다.

```yaml
logging:
  level:
    org.springframework.transaction.interceptor: TRACE
```

트랜잭션이 열릴 때마다 `Getting transaction for [...]` 형태로 찍힙니다. **안 찍히면 프록시를 안 탄 겁니다.** 이 한 줄이 1~4번을 전부 가릅니다.

## 6. 예제 — 주문 저장과 이력 기록

### 6-1. 클린하지 않은 코드 ❌

```java
@Service
@RequiredArgsConstructor
public class OrderService {
    private final OrderRepository orderRepository;
    private final OrderHistoryRepository historyRepository;
    private final PaymentClient paymentClient;

    public void place(OrderCommand command) {
        PaymentResult result = paymentClient.pay(command.amount());
        persist(command, result);          // ❌ 프록시를 안 거칩니다
    }

    @Transactional
    private void persist(OrderCommand command, PaymentResult result) {  // ❌ private
        Order order = orderRepository.save(command.toOrder(result));
        historyRepository.save(OrderHistory.created(order.getId()));
    }
}
```

문제가 두 겹입니다. `private`이라 애초에 프록시가 못 건드리고, 설령 `public`으로 바꿔도 `this` 호출이라 여전히 안 걸립니다. **두 개의 `save`가 각각 자기 커밋으로 나가서**, 두 번째가 실패해도 첫 번째는 남습니다. 주문은 있는데 이력이 없는 데이터가 만들어지고, 이건 며칠 뒤 대사에서 발견됩니다.

### 6-2. 개선한 코드 ✔️

```java
@Service
@RequiredArgsConstructor
public class OrderService {
    private final PaymentClient paymentClient;
    private final OrderPersistService persistService;   // 별도 빈으로 분리

    public void place(OrderCommand command) {
        PaymentResult result = paymentClient.pay(command.amount());
        persistService.persist(command, result);        // ✔️ 프록시 경유
    }
}
```

```java
@Service
@RequiredArgsConstructor
public class OrderPersistService {
    private final OrderRepository orderRepository;
    private final OrderHistoryRepository historyRepository;

    @Transactional
    public void persist(OrderCommand command, PaymentResult result) {
        Order order = orderRepository.save(command.toOrder(result));
        historyRepository.save(OrderHistory.created(order.getId()));
    }
}
```

빈을 하나 더 만드는 게 우회처럼 보이지만, 사실 **설계가 원래 그랬어야 하는 모양**입니다. `place`는 외부 결제 호출을 하고 `persist`는 DB만 만집니다. 둘을 한 트랜잭션에 넣으면 결제 응답을 기다리는 동안 커넥션을 쥐고 있게 됩니다(`daily/day20-service-layer-design.md`). **트랜잭션 경계가 클래스 경계와 어긋난다는 신호**로 읽는 게 맞습니다.

## 7. 해법 네 가지와 가격

| 해법 | 언제 | 대가 |
|---|---|---|
| 별도 빈으로 분리 | 기본값 | 클래스가 하나 늘어남 |
| 자기 자신 주입 | 분리할 만한 책임 경계가 없을 때 | 순환 참조 취급을 받음 |
| `AopContext.currentProxy()` | 위 둘이 다 막혔을 때 | 코드가 Spring AOP에 묶임 |
| AspectJ 위빙 | 프레임워크 차원의 결정 | 빌드·기동 구성 전체가 바뀜 |

**자기 주입**은 레퍼런스가 인정하는 패턴이지만 생성자 주입으로는 안 됩니다. 자기 자신이 완성되기 전에 자기를 넣어 줄 수 없으니까요.

```java
@Service
public class OrderService {
    @Autowired @Lazy
    private OrderService self;        // 프록시가 주입됩니다

    public void place(OrderCommand command) {
        self.persist(command);        // ✔️ 프록시 경유
    }

    @Transactional
    public void persist(OrderCommand command) { /* ... */ }
}
```

필드 주입에 `@Lazy`까지 붙여야 한다는 점에서 이미 냄새가 납니다. `daily/day38-circular-reference.md`에서 다룬 것과 같은 종류의 회피책입니다.

**`AopContext`**는 `exposeProxy = true`를 켜야 동작합니다. 안 켜면 `IllegalStateException`이 납니다.

```java
@EnableAspectJAutoProxy(exposeProxy = true)
```

```java
((OrderService) AopContext.currentProxy()).persist(command);
```

**AspectJ 모드**는 프록시를 아예 안 씁니다. 대상 클래스의 바이트코드를 직접 고치므로 `this` 호출도, `private` 메서드도 전부 걸립니다.

```java
@EnableTransactionManagement(mode = AdviceMode.ASPECTJ)
```

`spring-aspects.jar`와 컴파일 타임 또는 로드 타임 위빙 설정이 필요합니다. 자기 호출 하나 때문에 도입할 물건은 아닙니다.

## 8. 함정

**① 인터페이스에 `@Transactional`을 붙인다**
- **증상**: JDK 프록시에서는 되던 게 CGLIB로 바꾸거나 AspectJ를 켜면 안 됩니다.
- **원인**: 자바 애노테이션은 인터페이스에서 상속되지 않습니다. 레퍼런스도 "interface-declared annotations are still not recognized by the weaving infrastructure when using AspectJ mode"라고 적습니다.
- **해법**: 구현 클래스의 메서드에 붙입니다. Spring 팀의 공식 권고입니다.

**② 테스트에서는 되는데 운영에서 안 된다**
- **증상**: `@SpringBootTest`로 검증했는데 배포 후 롤백이 안 됩니다.
- **원인**: 테스트 클래스의 `@Transactional`이 테스트 메서드 전체를 감싸고 끝나면 롤백합니다. 프로덕션 코드에 트랜잭션이 없어도 테스트는 통과합니다.
- **해법**: 트랜잭션 경계를 검증할 때는 테스트 메서드에 `@Transactional`을 붙이지 않고, 커밋 후 별도 조회로 확인합니다.

**③ `final` 경고를 못 본다**
- **증상**: Kotlin으로 짠 서비스에서만 트랜잭션이 안 걸립니다.
- **원인**: Kotlin 클래스·메서드는 기본이 `final`입니다. CGLIB가 상속할 수 없습니다.
- **해법**: `kotlin-spring` 플러그인(`all-open`)을 적용합니다. 그리고 기동 시 `org.springframework.aop` 로거를 INFO로 두어 경고를 받습니다.

**④ 예외를 잡아서 로그만 찍는다**
- **증상**: 에러 로그는 있는데 데이터가 남아 있습니다.
- **원인**: `@Transactional` 메서드 안에서 `try-catch`로 예외를 삼키면 인터셉터까지 예외가 안 올라갑니다. 롤백할 이유가 없다고 판단하고 커밋합니다.
- **해법**: 잡아야 한다면 `TransactionAspectSupport.currentTransactionStatus().setRollbackOnly()`를 명시합니다. 그게 아니면 다시 던집니다.

**⑤ `UnexpectedRollbackException`을 예외 처리 버그로 본다**
- **증상**: 내가 잡아서 처리했는데 커밋 단계에서 처음 보는 예외가 납니다.
- **원인**: 안쪽에서 이미 롤백 마크가 찍혔습니다. 바깥에서 아무리 잡아도 물리 트랜잭션은 커밋될 수 없습니다.
- **해법**: 실패해도 전체를 되돌리면 안 되는 작업이라면 전파 속성을 `REQUIRES_NEW`로 분리합니다. 애초에 트랜잭션 경계 설계 문제입니다.

**⑥ 프록시를 걷어내려고 `spring.aop.proxy-target-class=false`를 켠다**
- **증상**: JDK 프록시로 바꿨더니 다른 곳에서 `ClassCastException`이 납니다.
- **원인**: JDK 프록시는 인터페이스 타입으로만 캐스팅됩니다. 구현 클래스로 주입받던 코드가 전부 깨집니다.
- **해법**: 전역 설정을 뒤집지 말고, 필요한 빈에만 Spring Framework 7.0의 `@Proxyable(INTERFACES)`을 씁니다.

## 9. 참고자료

- [Using `@Transactional` — Spring Framework Reference](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/annotations.html) — 자기 호출 제약, 6.0 가시성 변경, `AdviceMode.ASPECTJ`
- [Proxying Mechanisms — Spring Framework Reference](https://docs.spring.io/spring-framework/reference/core/aop/proxying.html) — JDK/CGLIB 제약, `AopContext`, 7.0 `@Proxyable`
- [Rolling Back a Declarative Transaction](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/rolling-back.html) — 기본 롤백 규칙과 `rollbackFor`
- [Aspect-Oriented Programming — Spring Boot Reference](https://docs.spring.io/spring-boot/reference/features/aop.html) — `spring.aop.proxy-target-class` 기본값
- 관련 노트: `daily/day32-bean-lifecycle.md`(프록시가 씌워지는 시점), `daily/day38-circular-reference.md`(자기 주입의 비용), `daily/day20-service-layer-design.md`(트랜잭션 경계 설계)

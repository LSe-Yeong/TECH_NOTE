# 빈은 언제 만들어지고 언제 죽나

> 이 문서가 답할 질문: **빈이 만들어지고 사라지는 순서 중 내 코드가 끼어들 수 있는 지점은 어디이고, 각 지점에서 무엇이 가능하고 무엇이 불가능한가?**
>
> 분류: 기술이해형(왜 존재하는가). 여러 출처에서 공통으로 등장하는 "생명주기 훅이 원래 어떤 문제를 풀려고 생겼는가"를 찾는 관점으로 조사했습니다.
>
> 기준: 본문의 실행 결과는 `spring-context 6.2.13` / Temurin JDK 17에서 직접 실행해 얻은 것입니다. 문서 인용은 Spring Framework 7.0 / Spring Boot 4.1 레퍼런스 기준입니다. 빈을 **어떻게 등록하는가**(`@Component` 스캔, `@Bean` 메서드)는 이 문서의 범위가 아닙니다. 여기서는 등록이 끝난 뒤의 이야기만 다룹니다.

## 1. 핵심 개념 — 생명주기는 "객체의 수명"이 아니라 "컨테이너가 책임지는 구간"입니다

빈 생명주기는 자바 객체의 수명과 다릅니다. 자바 객체는 `new` 하는 순간 태어나고 참조가 끊기면 GC가 가져갑니다. 여기에 개발자가 끼어들 자리는 없습니다.

컨테이너가 만드는 객체는 다릅니다. 컨테이너는 객체를 만든 뒤에도 **의존성을 꽂고, 후처리하고, 초기화 콜백을 부르고, 종료할 때 소멸 콜백을 부릅니다.** 이 "만든 다음, 쓰기 전" 구간과 "안 쓰게 된 다음, 버리기 전" 구간이 생명주기입니다. 생명주기 훅은 이 두 구간에 내 코드를 넣는 장치입니다.

> 이 구간을 모르면 증상이 이렇게 나옵니다. 생성자에서 주입받은 필드를 읽었더니 `null`입니다. `@PostConstruct`에 `@Transactional`을 붙였는데 트랜잭션이 안 걸립니다. `@PreDestroy`에 커넥션 정리를 넣었는데 프로토타입 빈이라 영영 호출되지 않습니다. 셋 다 "언제 불리는가"를 몰라서 생기는 일이고, 셋 다 컴파일도 되고 테스트도 통과합니다.

## 2. 구조 — 열한 단계, 네 구간

컨테이너가 싱글톤 빈 하나를 다루는 전체 순서입니다. 번호는 아래 3절에서 실제로 찍어본 출력 순서와 같습니다.

**구간 A. 생성과 조립**
1. 생성자 호출
2. 의존성 주입 (필드·세터)

**구간 B. 초기화**
3. `BeanPostProcessor.postProcessBeforeInitialization()`
4. `@PostConstruct`
5. `InitializingBean.afterPropertiesSet()`
6. `@Bean(initMethod = "...")`
7. `BeanPostProcessor.postProcessAfterInitialization()` ← **AOP 프록시가 여기서 만들어집니다**
8. `SmartInitializingSingleton.afterSingletonsInstantiated()` (모든 싱글톤이 끝난 뒤 한 번)

**구간 C. 사용** — 컨테이너가 개입하지 않습니다.

**구간 D. 소멸** (`ApplicationContext`가 닫힐 때)
9. `@PreDestroy`
10. `DisposableBean.destroy()`
11. `@Bean(destroyMethod = "...")`

4·5·6과 9·10·11의 순서는 Spring 레퍼런스가 명시한 순서입니다. 셋을 다 쓸 일은 없지만, **같은 역할의 훅이 세 개인 이유**는 알아둘 만합니다. `@PostConstruct`는 JSR-250 표준이라 스프링에 의존하지 않고, `InitializingBean`은 스프링 인터페이스라 코드가 묶이며(레퍼런스가 직접 "권하지 않는다"고 씁니다), `initMethod`는 **내가 못 고치는 서드파티 클래스**를 `@Bean`으로 등록할 때 쓰는 수단입니다. 선택 기준은 취향이 아니라 "그 클래스를 내가 소유하고 있는가"입니다.

### 2-1. 확장 지점 — 훅은 빈 하나짜리와 컨테이너 전체짜리로 나뉩니다

| 확장 지점 | 대상 | 언제 |
|---|---|---|
| `@PostConstruct` / `@PreDestroy` | 빈 하나 | 그 빈의 초기화·소멸 |
| `BeanFactoryPostProcessor` | 빈 **정의** | 인스턴스 만들기 전 (정의 자체를 고침) |
| `BeanPostProcessor` | 모든 빈 인스턴스 | 초기화 앞뒤 (프록시로 바꿔치기 가능) |
| `SmartInitializingSingleton` | 컨테이너 | 모든 싱글톤 초기화 완료 후 |
| `SmartLifecycle` | 컨테이너 | `start()`/`stop()`, phase로 순서 지정 |

`BeanPostProcessor`가 중요한 이유는 **반환값이 원본을 대체**하기 때문입니다. `@Transactional`, `@Async`, `@Cacheable`이 전부 7번 단계에서 원본 객체를 프록시로 갈아끼우는 방식으로 동작합니다. 그래서 4번(`@PostConstruct`) 시점의 `this`는 아직 프록시가 아닙니다. 이 한 줄이 아래 함정 대부분의 원인입니다.

## 3. 흐름

### 3-1. 코드로 보는 구성

훅을 전부 붙인 빈과, 순서를 관찰할 `BeanPostProcessor`입니다.

```java
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.springframework.beans.factory.DisposableBean;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.beans.factory.annotation.Autowired;

public class PaymentGateway implements InitializingBean, DisposableBean {

    private RetryPolicy retryPolicy;

    public PaymentGateway() {
        System.out.println("1. 생성자");
    }

    @Autowired
    void setRetryPolicy(RetryPolicy retryPolicy) {
        this.retryPolicy = retryPolicy;
        System.out.println("2. 의존성 주입");
    }

    @PostConstruct
    void warmUp() { System.out.println("4. @PostConstruct"); }

    @Override
    public void afterPropertiesSet() { System.out.println("5. afterPropertiesSet()"); }

    public void openConnection() { System.out.println("6. @Bean(initMethod)"); }

    @PreDestroy
    void drain() { System.out.println("9. @PreDestroy"); }

    @Override
    public void destroy() { System.out.println("10. destroy()"); }

    public void closeConnection() { System.out.println("11. @Bean(destroyMethod)"); }
}
```

```java
@Configuration
public class AppConfig {

    @Bean(initMethod = "openConnection", destroyMethod = "closeConnection")
    PaymentGateway paymentGateway() { return new PaymentGateway(); }

    @Bean
    @Scope("prototype")
    AuditLog auditLog() { return new AuditLog(); }   // @PreDestroy를 가진 프로토타입 빈

    // BeanPostProcessor는 static @Bean으로 선언합니다 (이유는 10절 함정 5)
    @Bean
    static BeanPostProcessor tracer() {
        return new BeanPostProcessor() {
            @Override public Object postProcessBeforeInitialization(Object bean, String name) {
                if (bean instanceof PaymentGateway) System.out.println("3. postProcessBeforeInitialization");
                return bean;
            }
            @Override public Object postProcessAfterInitialization(Object bean, String name) {
                if (bean instanceof PaymentGateway) System.out.println("7. postProcessAfterInitialization");
                return bean;   // 여기서 프록시를 반환하면 원본이 대체됩니다
            }
        };
    }

    @Bean
    SmartInitializingSingleton readyCheck() {
        return () -> System.out.println("8. afterSingletonsInstantiated()");
    }
}
```

### 3-2. 실행 결과

`AnnotationConfigApplicationContext`를 띄우고, 프로토타입 빈을 하나 꺼낸 뒤 `close()`를 부른 결과입니다.

```text
1. 생성자
2. 의존성 주입
3. postProcessBeforeInitialization
4. @PostConstruct
5. afterPropertiesSet()
6. @Bean(initMethod)
7. postProcessAfterInitialization
8. afterSingletonsInstantiated()
--- 프로토타입 빈 요청 ---
--- context.close() ---
9. @PreDestroy
10. destroy()
11. @Bean(destroyMethod)
```

여기서 두 가지를 확인할 수 있습니다.

**첫째, 7번이 4번보다 뒤입니다.** `@PostConstruct`가 도는 시점에 프록시는 아직 없습니다. 그래서 `@PostConstruct` 안에서의 자기 호출에는 `@Transactional`이 걸리지 않습니다.

**둘째, 프로토타입 빈의 `@PreDestroy`는 출력에 아예 없습니다.** 요청해서 인스턴스를 받았는데도 `close()`에서 호출되지 않습니다. 사라진 게 아니라 처음부터 등록되지 않았습니다.

## 4. 특징

### 4-1. 어느 훅을 쓸 것인가

| 하고 싶은 일 | 쓸 것 |
|---|---|
| 설정값 검증, 자료구조 준비 | `@PostConstruct` |
| 내가 못 고치는 클래스의 초기화 | `@Bean(initMethod = "...")` |
| 커넥션·스레드풀 정리 | `@PreDestroy` 또는 `close()` (추론됨) |
| 무거운 작업, 다른 빈 호출 | `ApplicationRunner` / `SmartInitializingSingleton` / `ContextRefreshedEvent` |
| 트래픽 받기 시작/중단 | `SmartLifecycle` |

Spring 레퍼런스는 `@PostConstruct`의 용도를 **"설정 상태 검증과 자료구조 준비"로 한정**하고, 그 이상은 하지 말라고 씁니다. 이유가 분명합니다. `@PostConstruct`는 컨테이너의 **싱글톤 생성 락 안에서** 실행되고, 이 메서드가 끝나야 그 빈이 "완성됨"으로 공개됩니다. 여기서 다른 빈을 끌어다 쓰면 초기화 데드락 위험이 생깁니다. 무거운 작업은 락 밖인 `SmartInitializingSingleton.afterSingletonsInstantiated()`나 컨텍스트 리프레시 이벤트로 미루라는 것이 공식 권고입니다.

### 4-2. 스코프가 바꾸는 것

| | 싱글톤 | 프로토타입 |
|---|---|---|
| 생성 시점 | 컨테이너 기동 시 미리 | `getBean()` 할 때마다 |
| 초기화 콜백 | 호출됨 | 호출됨 |
| **소멸 콜백** | 호출됨 | **호출 안 됨** |

레퍼런스의 표현을 그대로 옮기면, 컨테이너는 프로토타입을 만들어 조립해서 클라이언트에게 넘긴 뒤 **그 인스턴스에 대한 기록을 남기지 않습니다.** 기록이 없으니 소멸시킬 방법도 없습니다. 정리는 받아 간 쪽 책임입니다.

싱글톤이 기동 시점에 미리 만들어지는 것도 그냥 구현 디테일이 아닙니다. **설정 오류를 요청이 들어오기 전에 터뜨리는 장치**입니다. `spring.main.lazy-initialization=true`로 켤 수 있는 지연 초기화는 기동 시간을 줄여 주지만, Spring Boot 레퍼런스가 명시하듯 "문제 발견이 늦어진다"는 대가를 함께 삽니다. 로컬에서는 켤 만하고 프로덕션에서는 신중해야 하는 이유가 이것입니다.

## 5. 예제 — `@PostConstruct`에 넣으면 안 되는 것

캐시를 미리 채워 두고 싶은 서비스입니다.

### 5-1. 클린하지 않은 코드 ❌

```java
@Service
public class ProductCache {

    private final ProductRepository productRepository;
    private final Map<Long, Product> cache = new ConcurrentHashMap<>();

    public ProductCache(ProductRepository productRepository) {
        this.productRepository = productRepository;
    }

    @PostConstruct
    @Transactional(readOnly = true)   // ❌ 프록시가 아직 없어서 무시됩니다
    void preload() {
        productRepository.findAllActive()      // ❌ 싱글톤 생성 락 안에서 DB를 때립니다
                .forEach(product -> cache.put(product.getId(), product));
    }
}
```

두 가지가 동시에 잘못됐습니다. `@Transactional`은 7번 단계에서 붙는데 이 코드는 4번 단계입니다. 그리고 `findAllActive()`가 수 초 걸리면 그동안 컨테이너 기동이 통째로 멈춥니다.

### 5-2. 개선한 코드 ✔️

```java
@Service
public class ProductCache {

    private final ProductRepository productRepository;
    private final Map<Long, Product> cache = new ConcurrentHashMap<>();

    public ProductCache(ProductRepository productRepository) {
        this.productRepository = productRepository;
    }

    @PostConstruct
    void validateConfig() {
        // 여기서는 "검증"만 합니다 — 실패하면 기동 자체가 멈춰야 하는 것들
        Assert.notNull(productRepository, "productRepository must not be null");
    }

    @EventListener(ApplicationReadyEvent.class)   // 모든 빈이 완성되고 프록시도 붙은 뒤
    @Transactional(readOnly = true)               // ✔️ 이제 프록시를 경유하므로 동작합니다
    public void preload() {
        productRepository.findAllActive()
                .forEach(product -> cache.put(product.getId(), product));
    }
}
```

경계가 분명해졌습니다. **기동을 막아야 하는 검증은 `@PostConstruct`, 다른 빈을 부르는 실제 작업은 컨테이너가 다 조립된 뒤로.**

## 6. 이 생명주기가 지키는 원칙 — "완성 전에는 공개하지 않는다"

훅이 이렇게 여러 단계로 쪼개져 있는 이유는 하나입니다. **반쯤 만들어진 객체를 다른 코드가 보게 두지 않겠다**는 것입니다.

그래서 컨테이너는 "주입 완료 → 초기화 콜백 → 후처리"를 전부 끝낸 다음에야 그 빈을 공개합니다. 이 원칙을 깨는 대표적인 코드가 **생성자에서 일하는 것**입니다.

```java
// ❌ 생성자 — 아직 아무것도 보장되지 않는 시점
@Component
public class NotificationSender {
    @Autowired private SlackClient slackClient;   // 필드 주입은 생성자 뒤에 일어납니다

    public NotificationSender() {
        slackClient.ping();   // NullPointerException
    }
}
```

```java
// ✔️ 필요한 것은 생성자로 받고, 일은 초기화 콜백에서
@Component
public class NotificationSender {
    private final SlackClient slackClient;

    public NotificationSender(SlackClient slackClient) {
        this.slackClient = slackClient;   // 받기만 합니다
    }

    @PostConstruct
    void verifyChannel() {
        slackClient.ping();   // 주입이 끝난 것이 보장된 시점
    }
}
```

생성자 주입을 권하는 이유가 여기서도 한 번 더 나옵니다. 생성자 주입은 **"이 객체는 이게 없으면 존재할 수 없다"를 타입으로 못 박아서**, 위 `null` 상황 자체를 만들 수 없게 합니다. 자세한 내용은 `daily/day08-di-why.md`에 있습니다.

## 7. 실무에서 찾아보는 생명주기

**소멸 메서드 추론** — `@Bean`의 `destroyMethod` 기본값은 `"(inferred)"`입니다. 컨테이너가 `close()` 또는 `shutdown()`이라는 public 무인자 메서드를 리플렉션으로 찾아 자동으로 등록합니다. `HikariDataSource`에 아무 설정을 안 해도 종료 시 커넥션 풀이 닫히는 게 이 때문입니다. 추론이 곤란하면 `@Bean(destroyMethod = "")`로 끌 수 있지만, javadoc에 따르면 이때도 `DisposableBean`과 `Closeable`/`AutoCloseable`의 close는 계속 감지됩니다.

**웹서버 graceful shutdown** — Spring Boot의 graceful shutdown은 별도 장치가 아니라 이 생명주기의 일부입니다. 레퍼런스는 이를 "`SmartLifecycle` 빈들을 멈추는 가장 이른 페이즈에서 수행된다"고 설명합니다. 즉 **소멸 콜백(9~11번)보다 먼저** 새 요청 수신을 끊고 진행 중인 요청을 마무리합니다. 순서가 이래야만 `@PreDestroy`에서 리소스를 닫아도 처리 중인 요청이 깨지지 않습니다. 관련 내용은 `daily/day18-graceful-shutdown.md`에 있습니다.

**`SpringApplication`의 종료 훅** — Spring Boot는 매 `SpringApplication`마다 JVM 종료 훅을 자동 등록합니다. 순수 스프링(`ClassPathXmlApplicationContext` 등)에서는 `ctx.registerShutdownHook()`을 직접 불러야 소멸 콜백이 돕니다. Boot에서 `@PreDestroy`가 도는 걸 당연하게 여기다가 순수 스프링 배치 애플리케이션으로 옮겨서 안 도는 경우가 여기서 나옵니다.

## 8. 함정

**함정 1 — 프로토타입 빈의 `@PreDestroy`가 조용히 안 불립니다**
- **증상**: 프로토타입 스코프 빈에 `@PreDestroy`로 파일 핸들·커넥션 정리를 넣었는데 실행 로그에 흔적이 없습니다. 장시간 운영 후 `Too many open files`가 납니다.
- **원인**: 컨테이너가 프로토타입 인스턴스의 참조를 보관하지 않습니다. 초기화 콜백은 호출되지만 소멸 콜백은 등록조차 되지 않습니다.
- **해법**: 프로토타입 빈에 정리할 리소스를 두지 않는 것이 우선입니다. 꼭 필요하면 `AutoCloseable`로 만들어 `try-with-resources`로 쓰거나, 받아 간 쪽이 명시적으로 정리 메서드를 부릅니다.

**함정 2 — `@PostConstruct`의 `@Transactional`·`@Async`가 무시됩니다**
- **증상**: 초기화 시 여러 건을 저장하는데 롤백이 안 됩니다. `@Async`를 붙였는데 동기로 돕니다. 예외도 안 나고 로그도 안 남습니다.
- **원인**: AOP 프록시는 `postProcessAfterInitialization`(7번)에서 만들어집니다. `@PostConstruct`(4번)는 그 이전이라 아직 원본 객체이고, 프록시를 거치지 않는 호출에는 어드바이스가 적용되지 않습니다.
- **해법**: 초기화 작업을 `ApplicationReadyEvent` 리스너나 `ApplicationRunner`로 옮깁니다. 굳이 앞당겨야 한다면 `TransactionTemplate`으로 직접 트랜잭션을 엽니다.

**함정 3 — 싱글톤에 주입한 프로토타입이 하나로 굳습니다**
- **증상**: `@Scope("prototype")`을 붙였는데 매번 같은 인스턴스가 나옵니다. 그 안에 상태를 담아 두면 요청끼리 데이터가 섞입니다.
- **원인**: 의존성은 **주입 시점에 한 번** 해석됩니다. 싱글톤이 만들어질 때 프로토타입 인스턴스 하나가 생성되어 꽂히고, 그 뒤로는 싱글톤의 수명을 그대로 따릅니다.
- **해법**: 인스턴스가 아니라 공급자를 주입합니다. `ObjectProvider<AuditLog>`로 받아 필요할 때마다 `getObject()`를 부릅니다.

**함정 4 — 무거운 `@PostConstruct`가 기동 시간을 먹거나 데드락을 만듭니다**
- **증상**: 배포할 때마다 기동이 느려집니다. 최악의 경우 헬스체크 타임아웃에 걸려 롤링 배포가 계속 실패합니다. 드물게는 기동이 아예 멈춥니다.
- **원인**: `@PostConstruct`는 싱글톤 생성 락 안에서 실행되고, 그 빈은 메서드가 끝나야 공개됩니다. 여기서 외부 빈을 건드리면 초기화 데드락 위험이 생긴다고 레퍼런스가 직접 경고합니다.
- **해법**: `@PostConstruct`는 검증과 자료구조 준비까지만 합니다. 실제 작업은 `SmartInitializingSingleton.afterSingletonsInstantiated()`나 `ContextRefreshedEvent`처럼 락 밖에서 도는 지점으로 옮깁니다.

**함정 5 — `BeanPostProcessor`를 non-static `@Bean`으로 선언하면 다른 빈의 후처리가 빠집니다**
- **증상**: 기동 로그에 `Bean '...' is not eligible for getting processed by all BeanPostProcessors` 경고가 뜹니다. 그 빈에 `@Transactional`이나 AOP가 안 걸립니다.
- **원인**: `BeanPostProcessor`는 다른 빈들보다 먼저 만들어져야 하는데, non-static `@Bean` 메서드로 선언하면 그것을 담고 있는 `@Configuration` 클래스를 먼저 인스턴스화해야 합니다. 그 과정에서 일부 빈이 후처리 대상에서 빠집니다.
- **해법**: `BeanPostProcessor`와 `BeanFactoryPostProcessor`를 반환하는 `@Bean` 메서드는 `static`으로 선언합니다. 경고 메시지가 이미 이 해법을 알려줍니다.

## 9. 참고자료

- [Customizing the Nature of a Bean — Spring Framework](https://docs.spring.io/spring-framework/reference/core/beans/factory-nature.html) — 콜백 실행 순서, `@PostConstruct` 사용 범위 경고, `Lifecycle`/`SmartLifecycle`
- [Bean Scopes — Spring Framework](https://docs.spring.io/spring-framework/reference/core/beans/factory-scopes.html) — 프로토타입 소멸 콜백, 싱글톤에 프로토타입 주입 문제
- [`@Bean` javadoc](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/context/annotation/Bean.html) — `destroyMethod` 추론과 `""`의 의미
- [SpringApplication — Spring Boot](https://docs.spring.io/spring-boot/reference/features/spring-application.html) — 종료 훅 자동 등록, `ApplicationRunner` 실행 시점, 지연 초기화
- [Graceful Shutdown — Spring Boot](https://docs.spring.io/spring-boot/reference/web/graceful-shutdown.html) — `SmartLifecycle` 최초 페이즈에서의 종료
- 관련 문서: `daily/day08-di-why.md`(생성자 주입), `daily/day18-graceful-shutdown.md`(종료 순서)

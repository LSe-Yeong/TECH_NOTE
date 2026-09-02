# 로그를 `System.out.println`으로 찍으면 안 되는 이유

> 이 문서가 답할 질문: **`System.out.println` 대신 로깅 프레임워크를 쓰면 실제로 무엇을 얻는가?**
>
> 분류: 기술이해형(왜 존재하는가). 여러 출처에서 공통으로 등장하는 "원래 어떤 문제를 풀려고 만들어졌는가"를 찾는 관점으로 조사했습니다.
>
> 기준: SLF4J 2.0.18 · Logback 1.5.38 · Spring Boot 4.1 (2026년 9월 확인). 본문의 측정값은 Temurin JDK 17.0.20.1+1 / Linux x64에서 직접 재현했고 조건을 그때마다 밝힙니다. 로그 설계(무엇을 남길 것인가)와 수집 파이프라인은 이 문서의 범위가 아닙니다.

## 1. 핵심 개념 — 출력과 로그는 다른 물건입니다

`System.out.println`은 **출력**입니다. "지금 내 터미널에 이걸 보여줘"라는 뜻입니다.

로그는 **나중에 읽힐 데이터**입니다. 3주 뒤 새벽에 누군가가 "결제가 실패했다는 CS가 들어왔는데 무슨 일이 있었냐"를 물으면서 검색할 기록입니다. 쓰는 시점과 읽는 시점이 떨어져 있고, 쓰는 사람과 읽는 사람도 다릅니다.

> 장애가 났습니다. 서버에 붙어서 로그를 봅니다. `주문 저장 완료`가 3만 줄 찍혀 있습니다. **어느 요청인지, 몇 시인지, 어느 스레드인지, 어느 클래스가 찍었는지 하나도 없습니다.** 그럼 반대로 자세히 찍으면 되냐면, 이번엔 그 상세 출력이 평소에도 계속 나가면서 디스크를 채웁니다. 끄려면 코드를 고쳐서 재배포해야 합니다. `println`으로 로그를 남긴다는 건 **읽는 사람이 필요로 하는 걸 전부 빼고 남긴다**는 뜻입니다.

로깅 프레임워크는 편의 기능 모음이 아닙니다. `println`이 잃어버리는 네 가지 — **끌 수 있는가 · 누구의 로그인가 · 얼마나 비싼가 · 어디로 보낼 것인가** — 를 되돌려주는 장치입니다.

## 2. 구조 — 프레임워크가 `println` 자리에 넣는 네 개의 층

### 2-1. 파사드와 구현의 분리

애플리케이션 코드는 `org.slf4j.Logger` 인터페이스에만 의존합니다. 실제로 파일에 쓰는 건 Logback입니다. 이 둘은 컴파일 시점에 연결되지 않고, 런타임에 클래스패스에 있는 구현체가 선택됩니다.

```text
내 코드  →  slf4j-api (인터페이스)  →  런타임 바인딩  →  logback-classic (구현)
```

이 분리가 실제로 값을 하는 순간이 있습니다. Log4j 2에서 원격 코드 실행 취약점(Log4Shell, [CVE-2021-44228](https://nvd.nist.gov/vuln/detail/CVE-2021-44228))이 터졌을 때, SLF4J를 쓰던 코드는 **로깅 호출을 한 줄도 고치지 않고** 의존성만 교체할 수 있었습니다. `System.out`은 교체 지점이 아예 없습니다.

### 2-2. 레벨 — 배포 없이 켜고 끄는 스위치

`TRACE < DEBUG < INFO < WARN < ERROR` 다섯 단계입니다. 중요한 건 단계 개수가 아니라, **호출부는 그대로 두고 출력 여부를 바깥에서 바꿀 수 있다**는 점입니다.

Spring Boot는 기본이 INFO라서 `ERROR`·`WARN`·`INFO`만 나갑니다([Spring Boot Logging](https://docs.spring.io/spring-boot/reference/features/logging.html)). 문제가 생기면 `logging.level.<로거명>` 하나로 그 패키지만 DEBUG로 내립니다.

```yaml
logging:
  level:
    root: info
    com.example.order: debug          # 이 패키지만 상세히
    org.hibernate.SQL: debug
```

환경변수로도 됩니다(`LOGGING_LEVEL_COM_EXAMPLE_ORDER=DEBUG`). 환경별로 값을 다르게 주는 방법은 `day06-env-variable.md`에서 다룹니다.

### 2-3. 컨텍스트 — 로그 한 줄이 스스로 신원을 밝히게 하기

프레임워크는 메시지 앞에 시각·레벨·스레드명·로거명을 자동으로 붙입니다. 여기에 **MDC**(Mapped Diagnostic Context)를 쓰면 "이 요청에 속한 로그"라는 표시를 스레드 단위로 붙일 수 있습니다.

```text
2026-09-02T14:03:11.482+09:00  WARN 1 --- [io-8080-exec-3] c.e.order.OrderService : 재고 부족 orderId=10293
```

이 줄에는 `println`이 절대 주지 못하는 세 가지가 들어 있습니다. **언제**(정렬·상관관계 분석의 기준), **어느 스레드**(동시 요청 분리), **어느 클래스**(레벨을 조절할 단위). 셋 다 사람이 손으로 붙이면 반드시 빠뜨립니다.

### 2-4. Appender — 어디로 보낼지는 코드 밖의 결정

같은 로그 이벤트를 콘솔로도, 파일로도, JSON으로도 내보낼 수 있고 이 결정은 설정 파일에 있습니다. Spring Boot는 `logging.file.name`을 주면 파일 출력을 켜고, Logback 기준 파일당 10MB에서 롤오버하며 7일치를 보관합니다([Spring Boot Logging](https://docs.spring.io/spring-boot/reference/features/logging.html)).

Spring Boot 3.4부터는 구조화 로깅이 내장이라 `logging.structured.format.console=ecs` 한 줄로 콘솔 출력을 JSON으로 바꿉니다([Structured logging in Spring Boot 3.4](https://spring.io/blog/2024/08/23/structured-logging-in-spring-boot-3-4/)). 로그를 수집기에 넣기로 한 날, **애플리케이션 코드는 하나도 안 바뀝니다.**

## 3. 흐름

### 3-1. 코드로 보는 구성

```java
package com.example.order;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

@Service
public class OrderService {

    private static final Logger log = LoggerFactory.getLogger(OrderService.class);

    private final OrderRepository orderRepository;

    public OrderService(OrderRepository orderRepository) {
        this.orderRepository = orderRepository;
    }

    public Order place(Long buyerId, Long productId, int quantity) {
        log.debug("주문 생성 시작 buyerId={} productId={} quantity={}", buyerId, productId, quantity);

        Order order = orderRepository.save(Order.create(buyerId, productId, quantity));

        log.info("주문 생성 완료 orderId={} buyerId={}", order.getId(), buyerId);
        return order;
    }
}
```

로거는 `static final`로 클래스당 하나 둡니다. `getLogger(OrderService.class)`가 로거 이름을 클래스 전체 이름으로 잡아주고, 그 이름이 곧 `logging.level.com.example.order`로 제어되는 단위가 됩니다. Lombok을 쓰면 `@Slf4j`가 이 필드를 대신 만들어 줍니다.

### 3-2. 한 줄이 나가기까지

```text
1. log.debug(...) 호출
2. 로거의 유효 레벨 확인          → DEBUG가 꺼져 있으면 여기서 즉시 반환 (핵심)
3. LoggingEvent 생성             → 시각, 스레드명, 로거명, MDC 수집
4. {} 자리에 인자를 채워 메시지 조립  ← 2를 통과한 경우에만 수행
5. Appender로 전달               → 콘솔 / 파일 / JSON
6. 인코더가 패턴에 맞춰 문자열로 변환 후 기록
```

**2번과 4번의 순서가 이 구조의 핵심입니다.** `log.debug("결과 {}", buildReport())`처럼 인자를 미리 계산하면 이 순서가 무의미해지므로, 비싼 인자는 §8에서 다루는 방식으로 처리합니다.

## 4. `println`이 실제로 지불하는 비용

### 4-1. 끌 수 없습니다

`println`에는 레벨이 없습니다. 디버깅하다 넣은 출력이 그대로 운영에 나갑니다. 지우려면 코드 수정 → 리뷰 → 배포입니다. 반대로 장애 중에 더 자세히 보고 싶어도 방법이 없습니다. **로그의 상세도를 실행 중에 바꿀 수 없다는 것**이 가장 큰 손실입니다.

### 4-2. 매 줄이 flush입니다

`System.out`은 그냥 스트림이 아닙니다. OpenJDK의 `System.initPhase1`은 이렇게 만듭니다.

```java
// java.lang.System — newPrintStream()
return new PrintStream(new BufferedOutputStream(out, 128), true, ...);
```

버퍼가 **128바이트**, autoFlush가 **true**입니다. 즉 줄바꿈마다 하부 스트림을 flush합니다. 게다가 `PrintStream.write`는 `synchronized (this)` 블록 안에서 동작합니다. 정리하면 `System.out.println` 한 번은 **전역 락을 잡고 하는 쓰기 + flush**입니다.

얼마나 차이가 나는지 재봤습니다. `System.out`과 같은 구성(autoFlush=true, 128바이트 버퍼)의 `PrintStream`과, autoFlush=false + 8KB 버퍼의 `PrintStream`에게 **같은 파일**로 20만 줄을 쓰게 한 결과입니다(Temurin 17.0.20.1+1 / Linux x64, 3회 실행).

| 조건 | autoFlush=true | autoFlush=false |
|---|---:|---:|
| 단일 스레드 | 216~302 ms | 41~85 ms |
| 8 스레드 동시 | 261~270 ms | 63~86 ms |

같은 양을 쓰는데 **3~5배**가 듭니다. 차이는 로직이 아니라 flush 횟수에서 옵니다. 로깅 프레임워크는 버퍼를 잡고 필요할 때만 flush하며, 더 밀어붙이려면 `AsyncAppender`로 쓰기 자체를 별도 스레드에 넘깁니다.

주의할 점은 이게 **디스크 대상 상대 비교**라는 것입니다. 터미널·파이프·컨테이너 로그 드라이버로 나갈 때의 절대값은 다릅니다. 여기서 가져갈 결론은 "몇 ms"가 아니라 **`println`은 줄마다 flush하는 구성이 기본값**이라는 사실입니다.

### 4-3. 경로가 고정됩니다

`println`은 stdout에만 갑니다. 컨테이너에서 stdout은 Docker 기본 로깅 드라이버인 `json-file`이 받습니다. 그런데 이 드라이버의 `max-size` 기본값은 **-1(무제한)**이고, `max-file`은 1이며, `max-size`를 지정하지 않으면 **회전하지 않습니다**([Docker json-file driver](https://docs.docker.com/engine/logging/drivers/json-file/)). 회전 정책을 안 잡아둔 노드에서 수다스러운 컨테이너 하나가 디스크를 채우는 사고가 여기서 나옵니다.

프레임워크를 쓰면 파일 롤오버·용량 상한·JSON 포맷을 설정으로 고를 수 있습니다. 선택지가 있다는 게 차이입니다.

## 5. 예제

### 5-1. 이런 코드 ❌

```java
public Order place(Long buyerId, Long productId, int quantity) {
    System.out.println("주문 생성 시작");
    try {
        Order order = orderRepository.save(Order.create(buyerId, productId, quantity));
        System.out.println("주문 저장 완료");
        return order;
    } catch (Exception e) {
        System.out.println("에러 발생!");
        e.printStackTrace();
        throw e;
    }
}
```

동시 요청 50개가 들어오면 위 세 줄이 **순서가 섞인 채로** 150줄 찍힙니다. 어느 `주문 생성 시작`과 어느 `주문 저장 완료`가 한 쌍인지 알 방법이 없습니다. `e.printStackTrace()`는 stderr로 나가서 stdout과 다른 스트림에 섞이고, 스택트레이스 사이에 다른 요청의 출력이 끼어듭니다.

### 5-2. 이렇게 ✔️

```java
private static final Logger log = LoggerFactory.getLogger(OrderService.class);

public Order place(Long buyerId, Long productId, int quantity) {
    log.debug("주문 생성 시작 buyerId={} productId={} quantity={}", buyerId, productId, quantity);
    try {
        Order order = orderRepository.save(Order.create(buyerId, productId, quantity));
        log.info("주문 생성 완료 orderId={} buyerId={}", order.getId(), buyerId);
        return order;
    } catch (StockShortageException e) {
        log.warn("재고 부족으로 주문 거절 buyerId={} productId={}", buyerId, productId, e);
        throw e;
    }
}
```

바뀐 점 네 가지입니다.

1. `debug`와 `info`를 나눠서, 평소에는 완료 로그만 나가고 문제 시 상세를 켤 수 있습니다.
2. 값을 `{}`로 넘겨서 식별자(`orderId`, `buyerId`)가 로그에 남습니다. 나중에 `grep orderId=10293`이 됩니다.
3. 예외를 **마지막 인자로** 넘깁니다. `{}` 개수보다 인자가 하나 많으면 SLF4J가 그것을 스택트레이스로 처리합니다. 메시지와 스택트레이스가 한 이벤트로 묶입니다.
4. 잡는 예외를 구체 타입으로 좁혀서, 예상한 실패(WARN)와 예상 못 한 실패(글로벌 핸들러의 ERROR)를 구분합니다. 예외를 어디서 처리할지는 `day03-api-error-format.md`를 참고합니다.

## 6. 그래도 stdout으로 내보내는 건 맞습니다

여기서 오해가 생깁니다. "`println`이 나쁘다 = stdout이 나쁘다"가 아닙니다.

Twelve-Factor App은 오히려 **애플리케이션이 이벤트 스트림을 stdout으로 내보내고, 라우팅과 저장에는 관여하지 말라**고 합니다([12factor.net/logs](https://12factor.net/logs)). 컨테이너 환경에서는 이쪽이 표준입니다. 앱 안에서 파일 경로와 회전 주기를 관리하는 편이 오히려 이식성을 해칩니다.

두 이야기는 층이 다릅니다.

| 층 | 결정 | 답 |
|---|---|---|
| 로그를 **만드는** 쪽 | `println`인가 로거인가 | 로거 (레벨·컨텍스트·구조가 여기서 붙음) |
| 로그를 **내보내는** 쪽 | 파일인가 stdout인가 | 환경이 정함. 컨테이너면 대개 stdout |

로거를 쓰면서 ConsoleAppender로 stdout에 내보내는 구성이 이 둘을 동시에 만족합니다. 이때도 `println`과 다른 점은, **stdout으로 나가기 전에 레벨 필터와 인코더를 통과했다**는 것입니다.

## 7. 실무에서 찾아보기 — Spring Boot는 이미 이걸 다 해두고 있습니다

`spring-boot-starter-web`을 넣으면 `spring-boot-starter-logging`이 따라옵니다. 그 안에는 `logback-classic`뿐 아니라 **다리(bridge) 라이브러리**가 들어 있습니다.

- `jul-to-slf4j` — `java.util.logging`으로 찍은 로그를 SLF4J로 넘김
- `log4j-to-slf4j` — Log4j 2 API 호출을 SLF4J로 넘김

내가 쓰는 라이브러리 중 어떤 건 JUL로, 어떤 건 Log4j로 로그를 찍습니다. 다리가 없으면 이들의 출력이 **내 로그 설정을 무시하고 제각각 나갑니다.** Spring Boot는 이걸 전부 Logback 하나로 모읍니다.

그런데 이 다리에도 못 잡는 게 하나 있습니다. **`System.out`으로 직접 찍는 코드**입니다. 로깅 API를 거치지 않으니 가로챌 지점이 없습니다. `println` 한 줄은 이 정리된 파이프라인 바깥으로 새어 나가는 유일한 구멍입니다.

## 8. 함정

### 8-1. `e.printStackTrace()`가 로그에서 사라집니다

- **증상**: 예외가 났는데 로그 파일에도, 수집기에도 스택트레이스가 없습니다. 컨테이너 로그를 직접 보면 있습니다.
- **원인**: `printStackTrace()`는 `System.err`로 씁니다. 로깅 프레임워크를 거치지 않아 파일 appender·JSON 인코더·MDC 어디에도 걸리지 않습니다.
- **해법**: `log.error("메시지 id={}", id, e)`로 예외를 마지막 인자에 넘깁니다. 프레임워크가 스택트레이스를 이벤트에 포함시킵니다.

### 8-2. 문자열을 미리 만들어서 꺼진 로그에 돈을 씁니다

- **증상**: DEBUG를 껐는데도 CPU가 안 내려갑니다. 프로파일러에 `StringBuilder.append`와 `toString`이 잡힙니다.
- **원인**: `log.debug("주문 " + order)`는 레벨을 확인하기 **전에** 문자열 연결이 끝납니다. SLF4J FAQ는 로그가 꺼져 있을 때 파라미터 방식이 연결 방식보다 최소 30배 빠르다고 설명합니다([SLF4J FAQ](https://www.slf4j.org/faq.html)). 문자열 연결 비용의 구조는 `day13-string-builder.md`에서 다룹니다.
- **해법**: `log.debug("주문 {}", order)`로 바꿉니다. 인자 조립 자체가 비싼 경우(대량 컬렉션 순회 등)에만 `if (log.isDebugEnabled())`로 감쌉니다. 파라미터 방식을 쓴다면 대부분 이 가드는 불필요합니다.

### 8-3. 로그가 트랜잭션 밖에서 엔티티를 건드립니다

- **증상**: 로그 레벨을 DEBUG로 내렸더니 `LazyInitializationException`이 나거나, 쿼리 수가 갑자기 폭증합니다.
- **원인**: `log.debug("주문 {}", order)`에서 `order.toString()`이 지연 로딩 연관을 건드립니다. 로그 한 줄이 N+1을 만듭니다.
- **해법**: 엔티티를 통째로 넘기지 않고 식별자만 넘깁니다(`order.getId()`). 엔티티에 `toString()`을 둘 거면 연관 필드를 제외합니다. 같은 이유로 **비밀번호·토큰·주민번호가 담긴 객체를 통째로 로그에 넘기지 않습니다.**

### 8-4. `AsyncAppender`가 조용히 로그를 버립니다

- **증상**: 비동기 appender를 붙였더니 부하가 몰리는 구간에서 INFO 로그가 듬성듬성 빕니다. 에러 로그는 남아 있습니다.
- **원인**: Logback `AsyncAppender`의 큐 기본 크기는 256이고, `discardingThreshold`를 지정하지 않으면 큐 크기의 1/5로 잡힙니다. 남은 자리가 이 값 밑으로 떨어지면 **TRACE·DEBUG·INFO 이벤트를 버립니다**([AsyncAppenderBase](https://logback.qos.ch/apidocs/ch.qos.logback.core/ch/qos/logback/core/AsyncAppenderBase.html)). 유실을 막으려고 `discardingThreshold=0`을 주면 이번엔 큐가 찼을 때 애플리케이션 스레드가 **블로킹**됩니다(`neverBlock` 기본값이 false라 `put()`이 자리가 날 때까지 대기).
- **해법**: 공짜가 없다는 걸 먼저 인정합니다. 유실이 허용되면 기본값을 두고 `queueSize`만 올립니다. 유실이 안 되면 `discardingThreshold=0`으로 두되 큐를 넉넉히 잡고, 로그 때문에 요청이 느려질 수 있음을 받아들입니다. 응답 지연이 절대 안 되면 `neverBlock=true`로 두고 **버려지는 쪽**을 택합니다.

### 8-5. 종료 직전 로그가 남지 않습니다

- **증상**: 배포 중 종료된 인스턴스에서 마지막 몇 초의 로그가 통째로 없습니다.
- **원인**: 비동기 appender의 큐에 남은 이벤트가 플러시되기 전에 프로세스가 죽습니다. 컨테이너에 `SIGKILL`이 오면 확실하게 잃습니다.
- **해법**: Logback 설정에 종료 훅(`<shutdownHook class="ch.qos.logback.core.hook.DefaultShutdownHook"/>`)을 두고, 오케스트레이터의 종료 유예 시간을 애플리케이션 종료 시간보다 길게 잡습니다. 종료 순서 전반은 `day18-graceful-shutdown.md`에서 다룹니다.

## 9. 정리

`println`을 쓰지 말라는 규칙은 스타일 문제가 아닙니다. 로그에 대해 나중에 내려야 할 결정 — **얼마나 자세히 볼 것인가, 어디로 보낼 것인가, 어떻게 검색할 것인가** — 을 전부 코드 수정 시점으로 앞당겨 못 박아 버리기 때문입니다. 로깅 프레임워크가 하는 일은 그 결정들을 **설정 파일과 운영 시점으로 미뤄 두는 것**입니다.

## 10. 참고자료

- [Spring Boot Reference — Logging](https://docs.spring.io/spring-boot/reference/features/logging.html)
- [Structured logging in Spring Boot 3.4](https://spring.io/blog/2024/08/23/structured-logging-in-spring-boot-3-4/)
- [SLF4J FAQ](https://www.slf4j.org/faq.html)
- [Logback — AsyncAppenderBase API](https://logback.qos.ch/apidocs/ch.qos.logback.core/ch/qos/logback/core/AsyncAppenderBase.html)
- [Docker — json-file logging driver](https://docs.docker.com/engine/logging/drivers/json-file/)
- [The Twelve-Factor App — Logs](https://12factor.net/logs)
- 관련 문서: `day06-env-variable.md`, `day13-string-builder.md`, `day18-graceful-shutdown.md`, `day03-api-error-format.md`

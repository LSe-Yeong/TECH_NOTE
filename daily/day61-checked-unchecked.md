# 검사 예외와 비검사 예외는 무엇을 기준으로 고르는가

> 이 문서가 답할 질문: **새 예외를 만들 때 검사(checked)로 할지 비검사(unchecked)로 할지는 무엇을 기준으로 정하는가?**
>
> 분류: 선택형(A vs B). 둘 중 하나를 고르는 결정이고, 각각 사는 것과 파는 것이 다릅니다. 그래서 여러 출처가 공통으로 드는 비교 기준이 무엇인지를 찾는 관점으로 조사했습니다.
>
> 기준: Java 17(Temurin 17.0.20.1)에서 직접 컴파일·실행해 확인한 동작과, Spring Framework 6.2/7.1 레퍼런스 문서입니다. 예외 계층을 어떻게 설계하는지(도메인 예외 트리 모양)는 별도 주제이고, 이 문서는 **던질 예외 하나의 종류를 고르는 판단**만 다룹니다.

## 1. 핵심 개념 — 갈리는 건 "컴파일러가 호출자를 붙잡는가" 하나뿐입니다

Java의 예외는 `Throwable` 아래 세 갈래입니다.

1. `Error` — JVM 수준 실패(`OutOfMemoryError`, `StackOverflowError`). 앱이 처리할 대상이 아닙니다.
2. `Exception` 중 `RuntimeException`이 아닌 것 — **검사 예외**. `IOException`, `SQLException` 등.
3. `RuntimeException` 이하 — **비검사 예외**. `IllegalArgumentException`, `IllegalStateException` 등.

둘의 차이는 **딱 하나**입니다. 검사 예외는 컴파일러가 catch-or-specify를 강제합니다. 잡거나, `throws`에 적어서 위로 넘기거나, 둘 중 하나를 안 하면 컴파일이 안 됩니다. 비검사 예외는 아무것도 강제하지 않습니다.

런타임 동작은 완전히 같습니다. 전파 방식, 스택트레이스, `finally` 실행, 성능 모두 동일합니다. **차이는 전부 컴파일 시점에만 있습니다.**

그래서 이 선택은 성능이나 안정성 문제가 아니라 **API 설계 문제**입니다. Oracle 튜토리얼이 이걸 분명히 말합니다. 메서드가 던질 수 있는 검사 예외는 파라미터나 반환값과 똑같이 그 메서드의 공개 인터페이스라는 것입니다([Oracle Java Tutorials — Unchecked Exceptions, The Controversy](https://docs.oracle.com/javase/tutorial/essential/exceptions/runtime.html)).

> 이걸 의식하지 않으면 두 방향으로 망가집니다. 한쪽은 전부 `RuntimeException`으로 던지는 코드입니다. 컴파일은 깔끔하게 되고, 어떤 실패가 가능한지는 아무 데도 안 적혀 있어서 호출자가 장애를 겪고 나서야 알게 됩니다. 다른 쪽은 성실하게 검사 예외를 만든 코드입니다. 반년 뒤 그 `throws`가 서비스 계층 20개 메서드 시그니처에 번져 있고, 중간 계층마다 `catch (OrderException e) { throw new RuntimeException(e); }`가 붙어 있습니다. 컴파일러가 강제한 건 호출자가 **생각하는 것**이 아니라 **한 줄 적는 것**이기 때문입니다.

## 2. 교과서 기준과 그 기준이 모자란 지점

### 2-1. 공식 기준

Oracle 튜토리얼의 결론은 짧습니다. "호출자가 그 예외로부터 복구할 것을 합리적으로 기대할 수 있으면 검사 예외로, 호출자가 복구할 수 있는 게 없으면 비검사 예외로 만들라"([같은 문서](https://docs.oracle.com/javase/tutorial/essential/exceptions/runtime.html)).

같은 문서가 비검사 예외의 자리도 명시합니다. 런타임 예외는 대개 **프로그래밍 오류**를 나타냅니다. 0으로 나누기, null 역참조, 배열 범위 초과입니다. 여기에 "API를 잘못 호출한 경우"가 더해집니다. 허용되지 않는 `null` 인자를 받았을 때 `NullPointerException`을 던지는 것이 일반적인 관행이라고 적혀 있습니다.

### 2-2. "복구 가능"은 혼자서는 판정이 안 됩니다

문제는 이 기준을 실제 코드에 대보면 거의 항상 판정이 갈린다는 점입니다. "결제 게이트웨이 타임아웃"은 복구 가능한가요? 재시도할 수 있으니 가능합니다. 그런데 재시도는 누가 하나요? 호출한 서비스가 할 수도 있고, 메시지 큐 재처리가 할 수도 있고, 사용자가 다시 누르는 것일 수도 있습니다.

"복구 가능성"은 예외의 속성이 아닙니다. **호출자의 속성**입니다. 그런데 `throws`는 예외를 던지는 쪽에 적습니다. 즉 라이브러리를 쓸 모든 호출자를 대신해서 한 번에 정하는 셈입니다.

그래서 검사 예외의 가치를 부정하는 쪽도 꾸준히 있습니다. 대부분의 예외는 로그 찍고 실패하는 것 말고 할 게 없는데, 그런 예외까지 모든 호출자에게 catch 블록을 쓰게 하면 잡음만 늘어난다는 지적입니다([Checked vs Unchecked Exceptions in Java — codeahoy](https://codeahoy.com/java/2016/04/02/checked-vs-unchecked-exceptions-in-java/), [Why You Should Avoid Using Checked Exceptions — Vonage](https://developer.vonage.com/ja/blog/why-you-should-avoid-using-checked-exceptions-in-java)). 반대쪽에서는 실패할 수 있다는 사실을 숨기는 것 자체가 설계 실수라고 봅니다([Checked vs. Unchecked Exceptions: The Debate Is Not Over — yegor256](https://www.yegor256.com/2015/07/28/checked-vs-unchecked-exceptions.html)).

<!-- TODO: 확인 필요 — 위 세 링크는 모두 개인 블로그·기술 블로그입니다. 논쟁의 양쪽 논지를 보여주려고 인용했을 뿐이고, 어느 쪽도 공식 권고가 아닙니다. -->

### 2-3. 검사 예외가 제값을 하는 세 조건

판정 가능한 기준으로 바꿔 쓰면 이렇습니다. **세 개가 동시에 성립할 때만** 검사 예외가 비용을 회수합니다.

| 조건 | 안 지켜지면 |
|---|---|
| 호출자가 이 실패에 **다른 행동**을 한다 (대안 경로가 실제로 있다) | catch 블록이 로그 한 줄 또는 `throw new RuntimeException(e)`가 됩니다 |
| 그 호출자가 **바로 윗단**이다 (경계를 여러 층 넘지 않는다) | `throws`가 계층을 타고 번져서 중간 계층 전부가 재컴파일 대상이 됩니다 |
| 실패가 그 메서드의 **예상 가능한 결과 중 하나**다 | "예외적 상황"이 아니라 흐름 제어가 되고, 호출자는 try-catch로 분기문을 쓰게 됩니다 |

두 번째 조건이 실무에서 가장 자주 깨집니다. 검사 예외의 강제력은 **바로 윗 호출자 한 명에게만** 유효합니다. 그 사람이 `throws`에 적어서 넘기면, 다음 사람에게는 "내가 처리해야 할 실패"가 아니라 "컴파일을 통과하려면 적어야 하는 글자"로 보입니다.

## 3. 흐름 — 검사 예외가 계층을 넘어갈 때

### 3-1. 전파되는 모습

재고 API를 호출하는 코드입니다. 검사 예외 하나가 리포지토리에서 컨트롤러까지 올라갑니다.

```java
// 1) 인프라 계층 — 여기서 검사 예외가 생깁니다
public class InventoryApiClient {
    public int fetchStock(String sku) throws IOException {
        // HttpClient.send 가 IOException 을 던집니다
        return httpClient.send(buildRequest(sku), ofStockQuantity()).body();
    }
}

// 2) 서비스 계층 — 할 게 없어서 그대로 넘깁니다
public class OrderService {
    public void placeOrder(OrderRequest request) throws IOException {
        int stock = inventoryApiClient.fetchStock(request.sku());
        // ...
    }
}

// 3) 컨트롤러 — 여기도 할 게 없습니다
@PostMapping("/orders")
public OrderResponse create(@RequestBody OrderRequest request) throws IOException {
    orderService.placeOrder(request);
    // ...
}
```

`IOException`이 세 계층의 시그니처에 들어왔습니다. 그런데 **아무도 이 예외로 무엇을 하지 않았습니다.** 조건 1이 깨졌는데 조건 2의 비용을 치른 상태입니다.

이 상태의 실제 비용은 글자 수가 아닙니다. `OrderService.placeOrder`가 `throws IOException`을 달고 있으면, 나중에 재고 조회를 gRPC로 바꿔서 `IOException`이 안 나오게 되는 순간 **서비스 시그니처가 바뀝니다.** 인프라 구현 세부사항이 상위 계층 API 계약에 박혀 있는 것입니다.

### 3-2. 그래서 나오는 회피 패턴 세 가지

| 패턴 | 코드 | 잃는 것 |
|---|---|---|
| 삼키기 | `catch (IOException e) { log.warn("...", e); }` | 실패했는데 호출자는 성공으로 봅니다. 가장 나쁩니다 |
| 통째로 감싸기 | `catch (IOException e) { throw new RuntimeException(e); }` | 타입 정보가 사라져 상위에서 `IOException`만 따로 처리할 수 없습니다 |
| `throws Exception` | `void placeOrder() throws Exception` | 호출자가 받는 정보가 0이 됩니다. 검사 예외의 유일한 장점을 버리고 비용만 남깁니다 |

`throws Exception`이 왜 통과하는지 궁금할 수 있습니다. Java 7부터 **정밀한 재던지기(precise rethrow)** 가 들어가서, `catch (Exception e)`로 받아 그대로 `throw e`를 하면 컴파일러가 try 블록이 실제로 던질 수 있는 타입만 추론합니다. 확인해 봤습니다.

```java
// throws 에는 IOException 만 선언했는데, catch 는 Exception 으로 받습니다
static void loadAll(String path) throws IOException {
    try {
        load(path);                       // throws IOException
    } catch (Exception e) {
        log.warn("load failed: {}", path, e);
        throw e;                          // Java 7+ 에서 컴파일됩니다
    }
}
```

Java 17에서 그대로 컴파일되고 실행됩니다. 로깅 후 재던지기 같은 패턴에서 유용합니다. 다만 이 기능은 `catch`를 넓게 받는 걸 쉽게 만들어 주기 때문에, 위 세 번째 패턴으로 미끄러지기도 쉽습니다.

## 4. 특징

### 4-1. 검사 예외를 고르는 자리

세 조건이 다 맞는 경우입니다. 실무에서는 대체로 다음 모양입니다.

- 호출자가 **대안 리소스**를 갖고 있을 때. 캐시 서버 조회가 실패하면 DB로 간다 같은 경우입니다.
- **같은 모듈 안의 바로 윗 호출자**에게만 보이는 예외일 때. 파싱 실패를 받아서 기본값 레코드를 만드는 경우가 그렇습니다.
- 호출자가 **재시도 여부를 판단해야** 할 때. 단, 그 판단이 호출자 코드에 실제로 있어야 합니다.

### 4-2. 비검사 예외를 고르는 자리

- **프로그래밍 오류.** 호출 규약 위반, 잘못된 상태. Oracle 튜토리얼이 명시한 자리입니다.
- **호출자가 분기할 수 없는 실패.** DB 커넥션 획득 실패, 설정 누락 같은 것입니다.
- **계층 경계를 여러 번 넘어야 하는 실패.** 전역 예외 처리기 한 곳에서 응답으로 바꿀 거면, 중간 계층을 전부 거치게 만들 이유가 없습니다.

### 4-3. 트레이드오프 — 비검사가 기본값일 때 잃는 것

여기서 공짜가 없다는 걸 분명히 해야 합니다. 비검사를 기본값으로 두면 **"이 메서드가 어떻게 실패하는가"가 시그니처에서 사라집니다.**

사라진 정보를 다른 수단으로 메워야 합니다.

1. Javadoc `@throws`를 비검사 예외에도 적습니다. 컴파일러는 안 보지만 IDE와 사람은 봅니다.
2. 도메인 예외 타입을 만듭니다. `RuntimeException`을 그대로 던지면 호출자가 `catch (RuntimeException e)`밖에 쓸 수 없고, 그러면 의도한 실패와 버그를 구분할 수 없습니다.
3. 전역 예외 처리기를 **반드시** 둡니다. 비검사 예외는 아무도 안 잡으면 최상단까지 올라갑니다.

Oracle 튜토리얼이 경고하는 지점이 정확히 이것입니다. 메서드가 던질 예외를 선언하지 않으려는 **편의를 위해** `RuntimeException`을 던지거나 그걸 상속하지 말라고 못 박습니다.

## 5. 예제 — 결제 요청

### 5-1. 종류 선택이 설계를 망가뜨린 코드 ❌

```java
// ❌ 모두 검사 예외. 네 개를 호출자가 전부 알아야 합니다
public class PaymentService {

    public Receipt pay(PaymentCommand command)
            throws IOException, PaymentDeclinedException,
                   InsufficientBalanceException, InvalidCardException {
        // ...
    }
}

// 호출자 — catch 네 개가 전부 같은 일을 합니다
try {
    receipt = paymentService.pay(command);
} catch (IOException e) {
    throw new RuntimeException(e);                 // 타입 유실
} catch (PaymentDeclinedException e) {
    throw new RuntimeException(e);
} catch (InsufficientBalanceException e) {
    throw new RuntimeException(e.getMessage());    // ⚠️ cause 까지 유실
} catch (InvalidCardException e) {
    throw new RuntimeException(e);
}
```

두 가지가 동시에 틀렸습니다.

`InvalidCardException`은 카드번호 형식이 틀린 경우입니다. 이건 **호출 전에 검증했어야 할 입력**이지 런타임 실패가 아닙니다. 검사 예외로 만들 자리가 아닙니다.

그리고 세 번째 catch의 `new RuntimeException(e.getMessage())`는 원인 체인을 끊습니다. 확인해 봤습니다.

```java
RuntimeException lost = new RuntimeException(e.getMessage());
RuntimeException kept = new RuntimeException("failed to load", e);

System.out.println("lost cause  = " + lost.getCause());   // null
System.out.println("kept cause  = " + kept.getCause());   // java.io.IOException: empty path
```

Java 17 실행 결과입니다. `lost` 쪽은 스택트레이스에 `Caused by:`가 아예 안 찍힙니다. 어느 줄에서 터졌는지 영구히 사라집니다.

### 5-2. 종류를 나눠 고친 코드 ✔️

```java
// ✔️ 입력 검증 위반 → 비검사. 호출자가 분기 못 하는 실패 → 비검사.
//    호출자가 실제로 분기하는 실패 하나만 검사 예외로 남깁니다.
public class PaymentService {

    /**
     * @throws IllegalArgumentException 카드번호 형식이 올바르지 않은 경우
     * @throws PaymentGatewayException  게이트웨이 통신·내부 오류 (복구 불가)
     * @throws PaymentDeclinedException 승인이 거절된 경우 — 호출자가 다른 결제수단으로 분기
     */
    public Receipt pay(PaymentCommand command) throws PaymentDeclinedException {
        Card card = Card.of(command.cardNumber());   // 형식 위반 시 IllegalArgumentException

        try {
            return gateway.authorize(card, command.amount());
        } catch (IOException e) {
            throw new PaymentGatewayException("결제 게이트웨이 통신 실패", e);  // cause 보존
        }
    }
}

// 호출자 — 실제로 분기하는 것 하나만 잡습니다
try {
    return paymentService.pay(command);
} catch (PaymentDeclinedException e) {
    return paymentService.pay(command.withFallbackMethod());   // 대안 경로가 실제로 있습니다
}
// PaymentGatewayException, IllegalArgumentException 은 @ControllerAdvice 로 올라갑니다
```

검사 예외가 하나만 남았고, 그 하나는 호출자 코드에 **분기가 실제로 존재**합니다. 조건 1과 조건 2를 둘 다 만족합니다.

## 6. 세 번째 선택지 — 예외로 만들지 않기

검사냐 비검사냐를 고민하기 전에 물어볼 게 하나 더 있습니다. **이게 정말 예외인가요?**

"재고 부족"은 예외적 상황이 아닙니다. 쇼핑몰에서 하루에 수천 번 일어나는 **정상적인 결과**입니다. 예외로 만들면 호출자는 흐름 제어를 try-catch로 쓰게 됩니다. 예상된 결과를 예외로 표현하는 건 예외를 흐름 제어에 쓰는 것이라는 비판이 여기에 해당합니다([yegor256](https://www.yegor256.com/2015/07/28/checked-vs-unchecked-exceptions.html)).

```java
// ❌ 예상 가능한 결과를 예외로 — 호출자가 try-catch 로 분기합니다
public void reserve(String sku, int quantity) throws OutOfStockException { ... }

// ✔️ 결과 타입으로 — 분기가 if 문으로 돌아옵니다
public sealed interface ReserveResult {
    record Reserved(String reservationId) implements ReserveResult {}
    record OutOfStock(int available) implements ReserveResult {}
}

public ReserveResult reserve(String sku, int quantity) { ... }
```

판별 기준은 **빈도와 호출자의 반응**입니다. 늘 일어나고 호출자가 매번 분기한다면 반환 타입입니다. 드물게 일어나고 호출자가 보통 아무것도 못 한다면 예외입니다. 그 중간, 드물지만 호출자가 분기할 때가 검사 예외의 좁은 자리입니다.

## 7. 실무에서 찾아보는 선택의 흔적

이 선택이 실제 프레임워크에서 어떻게 결정됐는지 보면 기준이 선명해집니다.

**Spring의 `DataAccessException`.** JDBC의 `SQLException`은 검사 예외입니다. Spring은 이걸 자기 계층으로 번역하는데, 번역 결과는 **비검사**입니다. Javadoc이 이유를 적어 뒀습니다. 이 클래스는 런타임 예외이므로, 모든 오류를 치명적으로 볼 것이라면(보통의 경우) 사용자 코드가 잡을 필요가 없다는 것입니다([DataAccessException javadoc](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/dao/DataAccessException.html)). 레퍼런스 문서는 효과를 이렇게 설명합니다. DAO마다 성가신 catch-and-throw 블록과 예외 선언 없이 복구 불가능한 영속성 예외를 적절한 계층에서만 처리할 수 있게 된다는 것입니다([Spring Framework — DAO Support](https://docs.spring.io/spring-framework/reference/data-access/dao.html)). 조건 1과 조건 2를 둘 다 적용한 판단입니다.

**JDK의 `UncheckedIOException`.** Java 8에 추가됐고, Javadoc 설명 한 줄이 전부입니다. `IOException`을 비검사 예외로 감싼다는 것입니다([UncheckedIOException javadoc](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/io/UncheckedIOException.html)). 검사 예외를 넣을 수 없는 자리(람다·스트림)가 생겼으니 짝이 되는 비검사 타입을 표준으로 둔 것입니다. JDK가 자기 설계의 한계를 인정하고 탈출구를 만든 사례로 읽는 게 맞습니다.

**Kotlin.** 아예 없앴습니다. 공식 문서가 "Kotlin은 모든 예외를 기본적으로 비검사로 취급한다"고 적고 있고, 이유로는 예외 처리를 단순하게 만든다는 점만 듭니다. 대신 Java 쪽에서 호출할 때 알려줄 수단으로 `@Throws` 애노테이션을 둡니다([Kotlin — Exceptions](https://kotlinlang.org/docs/exceptions.html)). 강제를 버리고 **문서화 수단만 남긴** 선택입니다.

## 8. 함정

### 8-1. `@Transactional` 메서드에서 검사 예외를 던지면 롤백되지 않습니다 ⚠️

- **증상**: 서비스 메서드가 중간에 실패해 예외를 던졌는데, 그 전까지 저장한 데이터가 커밋돼 있습니다. 주문은 생성됐고 결제는 안 된 상태로 남습니다.
- **원인**: Spring의 기본 롤백 규칙이 비검사 예외 전용입니다. 트랜잭션 인프라는 `RuntimeException`의 인스턴스나 서브클래스에 대해서만 롤백 표시를 하고, `Error`도 포함됩니다. 반면 트랜잭션 메서드에서 던진 검사 예외는 기본적으로 롤백을 일으키지 않습니다([Spring Framework — Rolling Back a Declarative Transaction](https://docs.spring.io/spring-framework/reference/7.1/data-access/transaction/declarative/rolling-back.html)).
- **해법**: 둘 중 하나입니다. `@Transactional(rollbackFor = OrderFailedException.class)`로 규칙을 명시하거나, 애초에 도메인 예외를 비검사로 설계합니다. Spring이 `DataAccessException`을 비검사로 만든 것과 같은 결론이고, **두 번째가 기본값이어야 합니다.** 예외를 추가할 때마다 `rollbackFor`를 기억하는 데 기대는 설계는 결국 빠뜨립니다.

### 8-2. 람다와 스트림에 검사 예외를 넣을 수 없습니다

- **증상**: `files.stream().map(path -> Files.readString(path))`가 컴파일되지 않습니다.
- **원인**: `Function`, `Predicate`, `Consumer` 등 표준 함수형 인터페이스에 `throws` 선언이 없습니다. 검사 예외를 던지는 호출을 람다 안에 둘 수 없습니다.
- **해법**: 람다 안에서 잡아 `UncheckedIOException`으로 감싸 던지거나, 그 구간만 스트림을 쓰지 않습니다. 스트림을 쓸지 말지 자체의 판단 기준은 `daily/day55-stream-when-not.md`에 있습니다. 검사 예외가 섞인 반복은 그 문서의 "루프가 나은 경우"에 해당합니다.

### 8-3. sneaky throws는 **타입으로 잡을 수 없는** 예외를 만듭니다

- **증상**: `catch (IOException e)`를 쓰려는데 "exception IOException is never thrown in body of corresponding try statement" 컴파일 에러가 납니다. 그런데 런타임에는 그 `IOException`이 실제로 올라옵니다.
- **원인**: 제네릭 타입 소거를 이용해 검사 예외를 `throws` 선언 없이 던지는 트릭입니다. Lombok의 `@SneakyThrows`가 같은 방식입니다. 컴파일러는 그 메서드가 `IOException`을 던질 수 있다는 걸 모르기 때문에, 호출자의 `catch (IOException e)`를 도달 불가능으로 보고 거부합니다.

```java
@SuppressWarnings("unchecked")
static <E extends Throwable> void sneakyThrow(Throwable t) throws E {
    throw (E) t;
}

static void readConfig() {                       // throws 선언이 없습니다
    sneakyThrow(new IOException("config file missing"));
}
```

Java 17에서 확인한 결과입니다. `catch (Throwable t)`로 받으면 `java.io.IOException / config file missing`이 그대로 잡힙니다. 그러나 `catch (IOException e)`는 위 컴파일 에러로 거부됩니다. 즉 **던지는 쪽은 성공했지만 받는 쪽은 그 타입을 지목할 수 없습니다.**

- **해법**: 검사 예외를 피하려면 비검사 예외로 **감싸서** 던집니다. 타입 시스템을 우회하지 말고 타입을 바꿔야 합니다. `@SneakyThrows`는 인터페이스를 고칠 수 없어 선언을 못 다는 경우에만 쓰고, 그때도 호출자가 잡아야 할 예외라면 쓰지 않습니다.

### 8-4. 감쌀 때 `getMessage()`만 옮기면 스택이 사라집니다

- **증상**: 운영 로그에 `RuntimeException: timeout` 한 줄만 있고 `Caused by:`가 없습니다. 어느 코드에서 터졌는지 알 수 없습니다.
- **원인**: `new RuntimeException(e.getMessage())`는 메시지 문자열만 복사합니다. 원인 예외 객체는 버려지고, 스택트레이스는 **감싸는 예외를 만든 그 줄**에서 새로 시작합니다.
- **해법**: 항상 `new PaymentGatewayException("...", e)` 형태로 cause를 넘깁니다. 위 5-1에서 `getCause()`가 `null`로 찍힌 것이 이 상태입니다.

## 9. 참고자료

- [Oracle Java Tutorials — Unchecked Exceptions: The Controversy](https://docs.oracle.com/javase/tutorial/essential/exceptions/runtime.html) — 공식 선택 기준과 `RuntimeException` 남용 경고
- [Spring Framework — Rolling Back a Declarative Transaction (7.1)](https://docs.spring.io/spring-framework/reference/7.1/data-access/transaction/declarative/rolling-back.html) — 기본 롤백 규칙과 `rollbackFor`
- [Spring Framework — DAO Support](https://docs.spring.io/spring-framework/reference/data-access/dao.html) · [DataAccessException javadoc](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/dao/DataAccessException.html)
- [java.io.UncheckedIOException (Java 17)](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/io/UncheckedIOException.html)
- [Kotlin — Exceptions](https://kotlinlang.org/docs/exceptions.html) — 검사 예외를 없앤 언어의 설명
- 관련 문서: `daily/day55-stream-when-not.md` (람다와 검사 예외), `daily/day49-optional-misuse.md` (없음을 시그니처로 알리는 방법), `daily/day50-transaction-propagation.md` (트랜잭션 경계와 롤백)

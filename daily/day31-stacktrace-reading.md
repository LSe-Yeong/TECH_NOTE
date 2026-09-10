# 스택트레이스를 읽는 법 — 200줄 중에 봐야 할 건 세 줄입니다

> 이 문서가 답할 질문: **스택트레이스를 받았을 때 무엇을 어떤 순서로 봐야 원인 지점에 도달하는가?**
>
> 분류: 문제해결형(증상 → 원인 → 해법). 여러 출처에서 공통으로 보고되는 "스택트레이스를 잘못 읽는 방식"과 그 교정법을 찾는 관점으로 조사했습니다.
>
> 기준: 본문의 모든 출력은 Temurin JDK 17.0.20.1+1 / Linux x64에서 직접 실행해 얻은 것입니다. JVM 플래그 기본값은 `java -XX:+PrintFlagsFinal -version`으로 같은 환경에서 확인했습니다. 예외를 어떻게 설계할 것인가(checked/unchecked, 어디서 잡을 것인가)는 이 문서의 범위가 아닙니다.

## 1. 핵심 개념 — 스택트레이스는 에러 메시지가 아니라 스택의 스냅샷입니다

스택트레이스는 **예외 객체가 생성되는 순간**의 호출 스택을 복사해 둔 배열입니다. `throw`한 시점도 아니고, `catch`한 시점도 아닙니다. `new IllegalStateException(...)`이 실행되는 그 순간에 `Throwable` 생성자가 `fillInStackTrace()`를 호출해 프레임을 찍어 둡니다.

이 한 줄이 실무에서 갖는 의미는 큽니다. **예외를 만든 위치가 곧 스택트레이스의 맨 윗줄**입니다. 그래서 예외를 미리 만들어 상수로 재사용하거나, 원인을 버리고 새 예외로 갈아끼우면 스택트레이스는 사고 현장이 아니라 엉뚱한 곳을 가리킵니다.

> 장애가 났습니다. 슬랙에 스택트레이스 200줄이 붙습니다. 사람들이 맨 윗줄 `java.lang.IllegalStateException`만 읽고 "IllegalState가 왜 나지?"를 한 시간 동안 이야기합니다. **정작 원인은 47번째 줄 `Caused by:` 블록 안에, 우리 팀이 쓴 코드 한 줄에 있습니다.** 스택트레이스를 못 읽는다는 건 이미 손에 쥔 답을 못 알아본다는 뜻입니다.

## 2. 구조 — 네 개의 부품

```text
Exception in thread "main" java.lang.IllegalStateException: 주문 조회 실패 orderId=10293
	at TraceDemo$OrderService.placeOrder(TraceDemo.java:18)      ← ①헤더 ②프레임
	at TraceDemo$OrderController.createOrder(TraceDemo.java:27)
	at TraceDemo.main(TraceDemo.java:32)
Caused by: java.sql.SQLException: Connection is closed           ← ③체인
	at TraceDemo$OrderRepository.findById(TraceDemo.java:7)
	at TraceDemo$OrderService.placeOrder(TraceDemo.java:16)
	... 2 more                                                   ← ④축약
```

**① 헤더** — `예외 타입: 메시지`. 타입은 "무엇이 잘못됐는지의 분류"고, 메시지는 "이번 건의 구체적 값"입니다. 둘 중 실제로 정보량이 많은 쪽은 메시지입니다.

**② 프레임** — `at 클래스.메서드(파일:줄)`. **위가 최근, 아래가 과거**입니다. 맨 윗줄이 예외가 만들어진 곳이고, 맨 아랫줄이 진입점(스레드 시작 지점)입니다.

**③ `Caused by:`** — 예외를 감쌀 때 원인을 함께 넘기면 체인이 생깁니다. 위쪽이 나중에 감싼 예외, 아래로 갈수록 더 원본에 가깝습니다.

**④ `... N more`** — 감싼 예외와 원인 예외의 스택 아랫부분이 겹칠 때, 겹치는 프레임 N개를 생략한 표기입니다([Throwable javadoc](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/Throwable.html)). 위 예에서 `... 2 more`는 `createOrder` → `main` 두 줄입니다. 잘린 게 아니라 **바로 위 블록에 이미 적혀 있으니 안 쓴 것**입니다.

## 3. 읽는 순서 — 위에서부터 읽지 않습니다

스택트레이스를 위에서부터 읽으면 프레임워크 내부만 보다가 끝납니다. 순서는 이렇습니다.

1. **맨 아래 `Caused by:` 블록으로 먼저 간다** — 체인의 마지막이 원본 예외입니다.
2. **그 블록에서 우리 패키지가 처음 등장하는 프레임을 찾는다** — 여기가 대개 고칠 코드입니다.
3. **헤더 메시지를 다시 읽는다** — 타입보다 메시지에 값이 들어 있습니다.
4. **프레임 사이의 낙차를 본다** — "우리 코드 → 라이브러리 → 예외"에서 경계 프레임이 무엇을 넘겼는지가 원인입니다.
5. **맨 위 블록의 아래쪽으로 올라가 "누가 이 요청을 시작했나"를 확인한다** — 배치인지 HTTP 요청인지에 따라 재현 방법이 달라집니다.

### 3-1. 절차를 노이즈가 많은 트레이스에 적용해 보기

Spring의 `@Transactional`처럼 프록시와 리플렉션이 끼면 트레이스가 갑자기 길어집니다. 같은 구조를 JDK 동적 프록시로 재현한 코드입니다.

```java
interface OrderService {
    void placeOrder(long orderId);
}

class SimpleOrderService implements OrderService {
    @Override
    public void placeOrder(long orderId) {
        throw new IllegalStateException("재고 부족 orderId=" + orderId);
    }
}

class TransactionHandler implements InvocationHandler {
    private final Object target;

    TransactionHandler(Object target) {
        this.target = target;
    }

    @Override
    public Object invoke(Object proxy, Method method, Object[] args) throws Throwable {
        return method.invoke(target, args);   // 트랜잭션 시작/커밋 자리
    }
}
```

실행 결과입니다.

```text
Exception in thread "main" java.lang.reflect.UndeclaredThrowableException
	at $Proxy0.placeOrder(Unknown Source)
	at ProxyDemo.main(ProxyDemo.java:36)
Caused by: java.lang.reflect.InvocationTargetException
	at java.base/jdk.internal.reflect.NativeMethodAccessorImpl.invoke0(Native Method)
	at java.base/jdk.internal.reflect.NativeMethodAccessorImpl.invoke(NativeMethodAccessorImpl.java:77)
	at java.base/jdk.internal.reflect.DelegatingMethodAccessorImpl.invoke(DelegatingMethodAccessorImpl.java:43)
	at java.base/java.lang.reflect.Method.invoke(Method.java:569)
	at ProxyDemo$TransactionHandler.invoke(ProxyDemo.java:27)
	... 2 more
Caused by: java.lang.IllegalStateException: 재고 부족 orderId=10293
	at ProxyDemo$SimpleOrderService.placeOrder(ProxyDemo.java:14)
	... 7 more
```

맨 위 헤더 `UndeclaredThrowableException`은 **아무 정보가 없습니다.** 프록시가 선언되지 않은 예외를 만나 감싼 것뿐입니다. 절차대로 맨 아래로 가면 `IllegalStateException: 재고 부족 orderId=10293`, 우리 코드 `SimpleOrderService.placeOrder` 14번 줄. 13줄짜리 트레이스에서 실제로 읽을 값이 있는 줄은 **마지막 두 줄**입니다.

여기서 얻는 실무 감각 하나. `java.base/`로 시작하거나 `jdk.internal`, `$Proxy0`, `org.springframework` 같은 프레임은 **경계를 표시하는 이정표**로만 쓰고 내용은 건너뜁니다. 눈이 멈춰야 하는 곳은 우리 패키지 이름이 나오는 줄입니다.

## 4. 트레이스가 이상하게 보이는 경우들

### 4-1. 메시지가 친절해졌습니다 — Helpful NPE

JDK 15부터 `ShowCodeDetailsInExceptionMessages`가 기본 `true`라서, NPE 메시지가 어느 참조가 null인지 지목합니다([JEP 358](https://openjdk.org/jeps/358)). Temurin 17.0.20.1에서 플래그 기본값이 `true`인 것을 확인했습니다.

```java
record Address(String city) {}
record Member(Address address) {}
record Order(Member member) {}

Order order = new Order(new Member(null));
System.out.println(order.member().address().city().length());
```

```text
Exception in thread "main" java.lang.NullPointerException: Cannot invoke "NpeDemo$Address.city()"
    because the return value of "NpeDemo$Member.address()" is null
```

한 줄에 `.`이 네 번 찍힌 체인에서 **어느 지점이 null인지** 알려줍니다. 예전에는 줄 번호만 보고 넷 중 하나를 추측해야 했습니다. 이 메시지가 안 보인다면 JDK 14 이하이거나 누가 `-XX:-ShowCodeDetailsInExceptionMessages`를 꺼 둔 것입니다.

### 4-2. 스택트레이스가 아예 비어 있습니다 — fast throw

가장 당황스러운 경우입니다. 로그에 예외 타입 한 줄만 있고 `at`이 하나도 없습니다.

HotSpot은 같은 지점에서 같은 종류의 예외(NPE, `ArrayIndexOutOfBoundsException` 등)가 반복해서 터지면, C2가 재컴파일하면서 **미리 만들어 둔 예외 인스턴스**를 던지도록 바꿉니다. 이 인스턴스에는 스택트레이스도 메시지도 없습니다. `OmitStackTraceInFastThrow` 플래그가 기본 `true`입니다(Temurin 17.0.20.1에서 확인).

```java
static int parseQuantity(String raw) {
    return Integer.parseInt(raw.trim());   // raw가 null이면 NPE
}
```

이 메서드를 `null`로 20만 번 호출하면서 매번 잡은 예외의 프레임 수를 찍어 봤습니다.

```text
0번째:      frames=2, message=Cannot invoke "String.trim()" because "<parameter1>" is null
199999번째: frames=0, message=null

# -XX:-OmitStackTraceInFastThrow 를 주면
0번째:      frames=2, message=Cannot invoke "String.trim()" because "<parameter1>" is null
199999번째: frames=2, message=Cannot invoke "String.trim()" because "<parameter1>" is null
```

**증상의 특징이 진단 단서입니다.** 배포 직후 몇 분간은 트레이스가 정상이다가, 트래픽이 쌓인 뒤부터 같은 예외의 트레이스가 사라집니다. 이건 JVM 버그도 로깅 설정 문제도 아니고, "이 예외가 아주 자주 터지고 있다"는 신호입니다. 운영에서 원인을 봐야 하면 `-XX:-OmitStackTraceInFastThrow`를 켜고 재기동합니다. 대신 예외 생성 비용이 올라가므로 원인을 잡은 뒤에는 되돌리는 편이 낫습니다.

### 4-3. `Unknown Source` — 줄 번호가 없습니다

원인은 둘 중 하나입니다.

- **런타임에 만들어진 클래스**: `$Proxy0`처럼 소스 파일 자체가 없습니다. 정상입니다.
- **디버그 정보 없이 컴파일된 클래스**: `javac -g:none`으로 빌드하면 우리 코드도 이렇게 나옵니다.

```text
	at TraceDemo$OrderService.placeOrder(Unknown Source)
	at TraceDemo$OrderController.createOrder(Unknown Source)
```

두 번째라면 빌드 설정 문제입니다. Gradle/Maven 기본 설정은 줄 번호를 남기므로, 누군가 명시적으로 껐다는 뜻입니다. 운영 빌드에서 줄 번호를 버리면 장애 때 지불하는 비용이 훨씬 큽니다.

### 4-4. `Suppressed:` — try-with-resources가 삼킨 예외

`close()`에서도 예외가 나면 원래 예외를 덮지 않고 아래에 매달립니다.

```text
Exception in thread "main" java.lang.IllegalStateException: 디스크 공간 부족
	at SuppressedDemo$OrderExportFile.write(SuppressedDemo.java:5)
	at SuppressedDemo.main(SuppressedDemo.java:16)
	Suppressed: java.lang.IllegalStateException: 파일 핸들 반납 실패
		at SuppressedDemo$OrderExportFile.close(SuppressedDemo.java:10)
		at SuppressedDemo.main(SuppressedDemo.java:15)
```

읽는 법이 `Caused by:`와 반대입니다. **`Suppressed:`는 원인이 아니라 곁가지**입니다. 먼저 볼 것은 위쪽 본 예외입니다. 들여쓰기가 한 단계 더 들어가 있는 것으로 구분합니다.

### 4-5. 비동기 — 호출한 사람이 트레이스에 없습니다

```java
CompletableFuture<Integer> future = CompletableFuture.supplyAsync(() -> loadStock(77L));
future.join();
```

```text
Exception in thread "main" java.util.concurrent.CompletionException: java.lang.IllegalStateException: ...
	at java.base/java.util.concurrent.CompletableFuture.encodeThrowable(CompletableFuture.java:315)
	... (ForkJoinPool 프레임 6줄 생략) ...
Caused by: java.lang.IllegalStateException: 재고 서비스 응답 없음 productId=77
	at AsyncDemo.loadStock(AsyncDemo.java:6)
	at AsyncDemo.lambda$main$0(AsyncDemo.java:10)
	at java.base/java.util.concurrent.CompletableFuture$AsyncSupply.run(CompletableFuture.java:1768)
	... 6 more
```

실제 출력 전체를 봐도 **`main`이 한 번도 안 나옵니다.** `join()`을 호출한 코드가 트레이스에 없습니다. 스택은 예외를 만든 스레드(ForkJoinPool 워커)의 것이고, 그 스레드는 우리 컨트롤러를 거쳐 온 적이 없기 때문입니다. `lambda$main$0`이라는 이름만이 "`main` 안의 첫 번째 람다"라는 힌트를 줍니다.

그래서 비동기 코드의 장애 분석은 **트레이스가 아니라 로그의 상관관계 ID로** 합니다. MDC에 요청 ID를 넣는 방법은 `day25-logging-basics.md`에서 다룹니다. 스레드 경계를 넘을 때 MDC를 복사해 주지 않으면 그마저도 끊깁니다.

### 4-6. 프레임이 1024줄에서 끊깁니다

재귀가 깊거나 프레임워크 스택이 두꺼우면 트레이스가 잘립니다. `MaxJavaStackTraceDepth` 기본값이 `1024`입니다(Temurin 17.0.20.1에서 확인). `StackOverflowError`를 분석할 때 반복 구간이 안 보이면 `-XX:MaxJavaStackTraceDepth=0`(무제한)으로 재현합니다.

## 5. 스택트레이스를 파괴하는 코드

### 5-1. 클린하지 않은 코드 ❌

```java
// ❌ 1. 원인 예외를 버리고 메시지만 문자열로 붙였다
try {
    orderRepository.findById(orderId);
} catch (SQLException e) {
    throw new IllegalStateException("주문 조회 실패: " + e.getMessage());
}

// ❌ 2. 로거에 예외를 문자열로 넘겼다 — 트레이스가 통째로 사라진다
} catch (SQLException e) {
    log.error("주문 조회 실패 " + e);
}

// ❌ 3. 잡아서 찍고 다시 던졌다 — 같은 예외가 로그에 두 번 쌓인다
} catch (SQLException e) {
    log.error("주문 조회 실패", e);
    throw e;
}
```

1번은 `Caused by:` 블록이 통째로 사라집니다. 남는 건 `IllegalStateException: 주문 조회 실패: Connection is closed` 한 줄과, **감싼 위치의 스택**뿐입니다. 진짜로 터진 `findById` 7번 줄은 영영 알 수 없습니다.

2번은 문자열 연결이라 `toString()` 결과인 `java.sql.SQLException: Connection is closed`만 남습니다. `at` 줄은 없습니다.

3번은 트레이스가 살아 있지만 같은 사건이 로그에 2~3번 나옵니다. 장애 중에 "예외 3건"인지 "1건이 3번 찍힌 것"인지 구분하는 데 시간을 씁니다.

### 5-2. 개선한 코드 ✔️

```java
// ✔️ 1. 원인을 cause로 넘긴다 — Caused by 체인이 이어진다
try {
    orderRepository.findById(orderId);
} catch (SQLException e) {
    throw new OrderLookupException("주문 조회 실패 orderId=" + orderId, e);
}

// ✔️ 2. 예외는 마지막 인자로 넘긴다 — SLF4J가 트레이스를 출력한다
} catch (SQLException e) {
    log.error("주문 조회 실패 orderId={}", orderId, e);
}
```

두 규칙으로 요약됩니다. **감쌀 때는 `cause`를 넘기고, 로깅할 때는 예외 객체를 마지막 인자로 넘깁니다.** SLF4J는 마지막 인자가 `Throwable`이면 플레이스홀더에 쓰지 않고 스택트레이스로 출력합니다.

그리고 **잡거나 던지거나 하나만 합니다.** 로그는 예외가 최종적으로 처리되는 곳(대개 `@ControllerAdvice`) 한 군데서만 남깁니다. 응답으로 무엇을 내보낼지는 `day03-api-error-format.md`에서 다룹니다.

### 5-3. 감쌀 때 메시지에 무엇을 넣는가

`cause`를 넘겼다면 원인 예외의 메시지를 다시 쓸 필요가 없습니다. 감싸는 쪽 메시지에는 **원인 예외가 모르는 정보**를 넣습니다.

```java
// ❌ 원인 예외가 이미 말하는 내용을 반복
throw new OrderLookupException("SQL 에러가 났습니다", e);

// ✔️ 어떤 작업의, 어떤 대상이었는지 — 트레이스가 절대 알려주지 않는 값
throw new OrderLookupException("주문 조회 실패 orderId=" + orderId + ", storeId=" + storeId, e);
```

스택트레이스는 **어디서**를 알려주지만 **무엇을 가지고**는 알려주지 않습니다. 파라미터 값은 우리가 넣어야만 남습니다. 다만 개인정보와 비밀번호·토큰은 넣지 않습니다. 예외 메시지는 로그로 나가고, 실수로 응답 바디에도 실려 나갑니다.

## 6. 함정

**함정 1 — `... 234 more`를 "잘린 로그"로 착각합니다**

- **증상**: 트레이스 끝에 `... 234 more`가 있으니 로그 설정이 트레이스를 자른다고 판단하고, Logback 설정을 뒤집니다.
- **원인**: `... N more`는 로거가 자른 게 아니라 `Throwable.printStackTrace`의 표준 축약입니다. 겹치는 프레임은 바로 위 블록에 이미 있습니다.
- **해법**: 위 블록의 아래쪽 N줄을 그대로 이어 읽습니다. 실제로 잘린 경우는 4-6의 1024줄 상한이거나 로그 수집기의 줄 길이 제한이고, 그때는 `... N more`가 아니라 문장 중간에서 끊깁니다.

**함정 2 — 배포 직후엔 보이던 트레이스가 사라집니다**

- **증상**: 같은 예외인데 어느 순간부터 `at` 줄이 하나도 없이 타입만 로그에 남습니다.
- **원인**: fast throw 최적화(4-2). 예외가 충분히 자주 터져서 JIT가 미리 만든 인스턴스로 바꿨습니다.
- **해법**: 재현 환경에서 `-XX:-OmitStackTraceInFastThrow`로 위치를 잡습니다. 근본 해법은 플래그가 아닙니다. **예외를 흐름 제어에 쓰고 있거나, 실제로 대량 실패 중**이라는 뜻이므로 그쪽을 고칩니다.

**함정 3 — 맨 윗줄 예외 타입으로 원인을 단정합니다**

- **증상**: `UndeclaredThrowableException`, `InvocationTargetException`, `CompletionException`, `BeanCreationException`을 검색어로 넣고 헤맵니다.
- **원인**: 이 넷은 전부 **감싸개**입니다. 자기 자신은 아무 원인도 담고 있지 않습니다.
- **해법**: 검색창에 넣을 문자열은 **맨 아래 `Caused by:` 블록의 타입과 메시지**입니다. 프레임워크 예외 이름으로는 남의 사례만 나옵니다.

**함정 4 — 로그에 트레이스가 있는데 재현이 안 됩니다**

- **증상**: 트레이스로 코드 위치는 특정했는데, 같은 입력으로 로컬에서 재현되지 않습니다.
- **원인**: 스택트레이스에는 **파라미터 값·요청 주체·시각별 상태**가 없습니다. 어디서 터졌는지만 있습니다.
- **해법**: 5-3처럼 감쌀 때 식별자를 메시지에 넣고, 요청 단위 컨텍스트는 MDC로 남깁니다. 스택트레이스는 "무엇을 더 로깅해야 했는가"를 알려주는 지표이기도 합니다.

**함정 5 — 예외 인스턴스를 상수로 재사용합니다**

- **증상**: 트레이스의 맨 윗줄이 항상 같은 유틸 클래스의 static 필드 선언 줄을 가리킵니다.
- **원인**: 스택트레이스는 **생성 시점**에 찍힙니다. `static final Exception`은 클래스 로딩 때 한 번 찍히고 끝입니다.
- **해법**: 던질 때마다 `new`로 만듭니다. 생성 비용이 정말 문제인 극단적인 경우에만 `fillInStackTrace()`를 재정의하고, 그 사실을 주석으로 남깁니다.

## 7. 참고자료

- [Throwable (Java SE 25 API)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/Throwable.html) — `printStackTrace` 출력 형식, `... N more`, `Suppressed:` 정의
- [JEP 358: Helpful NullPointerExceptions](https://openjdk.org/jeps/358) — 상세 NPE 메시지의 설계와 한계
- `day25-logging-basics.md` — 예외를 로거에 넘기는 법, MDC와 요청 상관관계 ID
- `day03-api-error-format.md` — 잡은 예외를 응답으로 어떻게 내보내는가

<!-- TODO: 확인 필요 — 본문 재현 결과와 플래그 기본값은 Temurin JDK 17.0.20.1+1에서만 확인했습니다. JDK 21/25 LTS에서 fast throw 발동 시점(반복 횟수)이나 Helpful NPE 메시지 문구가 달라지는지는 별도 검증이 필요합니다. -->

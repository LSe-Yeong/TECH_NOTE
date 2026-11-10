# 람다와 함수형 인터페이스는 무엇을 풀기 위해 들어왔는가

> 이 문서가 답할 질문: **람다는 익명 클래스를 짧게 쓰는 문법인가? 아니라면 어떤 문제를 풀려고 들어왔고, 그 설계 결정이 지금 내 코드에 어떤 제약을 남겼는가?**
>
> 분류: 기술이해형(왜 존재하는가). "문법이 짧아졌다"는 설명은 어디에나 있지만 그게 동기였다면 Java 8이 디폴트 메서드까지 같이 넣을 이유가 없습니다. 그래서 설계 문서들이 공통으로 드는 "원래 풀려던 문제"가 무엇인지를 찾는 관점으로 조사했습니다.
>
> 기준: 동작은 Java 17(Temurin 17.0.21)에서 직접 컴파일·실행해 확인했고, 버전 간 차이가 있는 항목은 Java 8·21·25에서 다시 확인해 본문에 버전을 적었습니다. 설계 의도는 [State of the Lambda (Brian Goetz, 4th edition)](https://cr.openjdk.org/~briangoetz/lambda/lambda-state-final.html), 규격은 [JLS Java SE 21](https://docs.oracle.com/javase/specs/jls/se21/html/jls-15.html)과 [`LambdaMetafactory` Javadoc](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/lang/invoke/LambdaMetafactory.html)을 인용합니다.

## 1. 핵심 개념 — 짧아진 건 결과이고, 동기는 라이브러리였습니다

**함수형 인터페이스**는 추상 메서드가 딱 하나인 인터페이스입니다. **람다**는 그 인터페이스의 인스턴스를 만드는 식입니다. 여기까지는 익명 클래스와 같은 자리를 차지합니다.

차이는 "왜 이게 필요했는가"에서 갈립니다. 설계 문서는 익명 클래스의 문제를 다섯 가지로 적어 두는데, 그중 문법이 길다는 것(이른바 "vertical problem" — `ActionListener` 하나에 다섯 줄)은 첫 번째일 뿐입니다. 나머지는 이름과 `this`의 의미가 헷갈린다, 클래스 로딩·인스턴스 생성 방식이 고정되어 있다, final이 아닌 지역변수를 캡처할 수 없다, 그리고 **제어 흐름을 추상화할 수 없다**입니다. 람다가 직접 푼 것은 앞의 둘, 간접적으로 푼 것이 셋째입니다.

> 마지막 항목이 진짜 동기입니다. 람다가 없으면 컬렉션 순회는 영원히 `for` 문, 즉 **외부 반복**입니다. 외부 반복에서는 "어떻게 돌 것인가"를 호출하는 쪽이 쥡니다. 그러면 라이브러리는 순서를 바꾸거나, 중간에 끊거나, 쪼개서 여러 코어에 뿌릴 권한이 없습니다. 멀티코어 머신에서 `for (Order o : orders)`를 병렬로 바꾸는 방법은 개발자가 직접 `ExecutorService`를 쓰는 것밖에 없고, 그건 대부분 틀리게 작성됩니다. 그래서 순회 권한을 라이브러리로 넘겨야 했고(**내부 반복**), 넘기려면 "무엇을 할지"를 값처럼 전달할 수단이 필요했습니다. 그 수단이 람다입니다. 즉 람다는 스트림을 위해 들어왔고, 문법이 짧아진 건 부산물입니다.

이 순서를 기억해야 뒤에 나오는 제약들이 "왜 하필 이렇게 생겼는가"로 이해됩니다. 람다는 쓰기 편하라고 만든 게 아니라 **라이브러리가 동작을 받아 갈 수 있게** 만든 장치입니다.

## 2. 설계 결정 — 왜 "함수 타입"을 새로 만들지 않았는가

가장 자연스러운 선택지는 언어에 함수 타입을 추가하는 것이었습니다. `(String, Object) -> int` 같은 화살표 타입을 타입 시스템에 넣는 안을 검토했고, **기각했습니다.** 기각 이유로 적힌 것은 타입 시스템 복잡도 증가, 라이브러리 스타일이 둘로 쪼개짐, 검사 예외까지 표기하면 문법이 감당 불가, 그리고 런타임 표현이 없어서 소거의 한계가 그대로 노출된다는 점입니다.

대신 택한 방향이 "use what you know"입니다. **이미 있는 단일 추상 메서드 인터페이스를 그대로 람다의 타입으로 씁니다.** 그래서 `Runnable`, `Comparator`, `Callable`처럼 Java 1.1 시절에 만들어진 타입들이 재컴파일 없이 람다를 받게 됐습니다. 이게 람다 도입에서 가장 큰 실용적 이득입니다.

공짜는 아닙니다. 대가가 두 개 남았고, 둘 다 지금 코드에서 매일 만집니다.

### 2-1. 대가 ①: 명목 타이핑 — 모양이 같아도 다른 타입입니다

함수 타입이 아니라 인터페이스이므로, 이름이 다르면 다른 타입입니다. 받는 것도 돌려주는 것도 똑같은데 대입이 안 됩니다.

```java
Function<String, Integer> length = String::length;
ToIntFunction<String> sameShape = length;   // 구조는 완전히 같다
```

Java 17에서 컴파일하면 이렇게 거절합니다.

```
error: incompatible types: Function<String,Integer> cannot be converted to ToIntFunction<String>
```

그래서 "함수를 받는 메서드"를 설계할 때 어떤 인터페이스로 받을지가 API 계약이 됩니다. 나중에 `Function`에서 `ToIntFunction`으로 바꾸면 호출하는 쪽 코드가 깨집니다. 람다 리터럴로 넘기던 호출부는 멀쩡하고, 변수에 담아 재사용하던 호출부만 깨지는 식으로 지저분하게 깨집니다.

### 2-2. 대가 ②: 소거 — 그래서 인터페이스가 43개입니다

제네릭은 타입 소거로 구현되어 있어서 `Function<Integer, Integer>`의 타입 인자는 참조 타입만 올 수 있습니다. `int`를 흘려보내면 박싱이 끼어듭니다. 얼마나 끼는지 바이트코드로 보면 명확합니다.

```java
static int viaGeneric(Function<Integer, Integer> f, int v) { return f.apply(v); }
static int viaPrimitive(IntUnaryOperator f, int v) { return f.applyAsInt(v); }
```

Java 17 `javac`가 만든 코드입니다.

```
static int viaGeneric(Function, int);
   2: invokestatic  Integer.valueOf:(I)Ljava/lang/Integer;   // ① 넣을 때 박싱
   5: invokeinterface Function.apply:(Ljava/lang/Object;)Ljava/lang/Object;
  10: checkcast     java/lang/Integer
  13: invokevirtual Integer.intValue:()I                     // ② 받을 때 언박싱

static int viaPrimitive(IntUnaryOperator, int);
   2: invokeinterface IntUnaryOperator.applyAsInt:(I)I       // 그대로 int
```

호출 지점만 이렇고 끝이 아닙니다. 람다 본문도 같이 박싱됩니다. `n -> n * 2`를 `Function`으로 받으면 람다 본문이 변환된 메서드가 이렇게 나옵니다.

```
private static java.lang.Integer lambda$main$0(java.lang.Integer);
   1: invokevirtual Integer.intValue:()I        // 언박싱해서 계산
   5: imul
   6: invokestatic  Integer.valueOf:(I)Ljava/lang/Integer;   // 다시 박싱
```

한 번 호출에 박싱/언박싱이 네 번입니다. `IntUnaryOperator`로 받으면 `lambda$main$1`은 `int → int` 그대로이고 0번입니다. 루프 안에서 수천만 번 돌면 이 차이가 전부 할당입니다.

이걸 피하려고 `java.util.function`에 원시 타입 특화 인터페이스를 따로 뒀습니다. 패키지의 타입 개수를 직접 세어 보면 **Java 8, 17, 21, 25 모두 43개**입니다(각 JDK의 `java.base`에서 `java/util/function/*.class`를 센 결과입니다). `Function`·`Predicate`·`Consumer`·`Supplier` 네 개면 될 일이 43개로 불어난 이유가 전부 소거입니다. `IntFunction`, `ToIntFunction`, `IntUnaryOperator`가 왜 다 따로 있는지도 여기서 설명됩니다 — 받는 쪽이 `int`인지, 주는 쪽이 `int`인지, 양쪽 다인지가 다른 타입이어야 하니까요.

## 3. 람다는 익명 클래스의 문법 설탕이 아닙니다

여기가 가장 흔한 오해입니다. "컴파일러가 익명 클래스로 바꿔준다"는 설명은 틀렸고, 틀린 방향으로 틀렸습니다.

### 3-1. 컴파일 결과가 다릅니다

익명 클래스 하나와 람다 셋이 들어 있는 파일을 컴파일하면 나오는 `.class` 파일은 이것뿐입니다.

```
Probe$1.class          ← 익명 클래스
Probe$Discount.class   ← 인터페이스
Probe.class
```

**람다는 클래스 파일을 만들지 않습니다.** 대신 호출 지점에 `invokedynamic` 하나가 박힙니다.

```
static Probe$Discount anonDiscount();
   0: new           Probe$1              // 컴파일 시점에 정해진 클래스를 그냥 생성
   4: invokespecial Probe$1."<init>":()V

static Probe$Discount lambdaNoCapture();
   0: invokedynamic #10,  0              // InvokeDynamic #0:applyTo:()LProbe$Discount;
```

그 `invokedynamic`의 부트스트랩 메서드로 `LambdaMetafactory.metafactory`가 지정되고, 람다 본문은 그냥 private static 메서드(`lambda$lambdaNoCapture$0`)로 남습니다. 즉 **구현 클래스를 만드는 일이 컴파일 시점에서 런타임으로 미뤄집니다.** 실제로 런타임에 받은 객체의 클래스를 찍어 보면 이렇습니다.

| | Java 17 | Java 21 / 25 |
|---|---|---|
| 익명 클래스 | `Probe$1` | `Probe$1` |
| 람다 | `Probe$$Lambda$1/0x00007f9c1c002800` | `Probe$$Lambda/0x00007f59f4002800` |

`isHidden()`이 `true`입니다. 히든 클래스라서 이름으로 찾을 수도, 리플렉션으로 로드할 수도 없습니다. Java 21부터는 이름에서 순번(`$1`)이 빠졌습니다. 이름 형식에 의존하는 로깅·필터·프록시 코드가 Java 21 업그레이드에서 조용히 깨지는 지점입니다.

이 설계가 의도한 것은 "원하면 전략을 바꿀 수 있게" 두는 것입니다. 클래스를 스핀하지 않고 기존 인스턴스를 돌려주는 선택이 가능해지고, 실제로 그렇게 동작합니다.

### 3-2. 그래서 인스턴스 동일성이 다릅니다

같은 메서드를 두 번 호출해 두 객체를 받아 `==`로 비교했습니다. Java 17·21·25 모두 결과가 같습니다.

| 만드는 방식 | 두 번 호출한 결과가 같은 객체인가 |
|---|---|
| 익명 클래스 | `false` — 항상 새로 할당 |
| 캡처가 없는 람다 (`price -> price - 10`) | **`true`** — 같은 객체가 돌아옵니다 |
| 캡처가 있는 람다 (`price -> price - amount`) | `false` |

캡처가 없으면 상태가 없으니 하나를 재사용해도 됩니다. 호출 지점마다 객체를 새로 만들던 익명 클래스에서는 불가능했던 최적화이고, 이게 람다를 `invokedynamic`으로 번역한 실익입니다. 스트림 파이프라인처럼 람다가 호출 경로마다 들어가는 코드에서 할당이 사라집니다.

**다만 이건 보장이 아닙니다.** Javadoc은 이렇게 적어 뒀습니다.

> "Capture may involve allocation of a new function object, or may return a suitable existing function object."
>
> "The identity of a function object produced by capture is unpredictable, and therefore identity-sensitive operations (such as reference equality, object locking, and `System.identityHashCode()`) may produce different results in different implementations, or even upon different invocations in the same implementation."

같은 구현에서 호출마다 달라져도 규격 위반이 아닙니다. 위 표의 `true`는 OpenJDK가 그렇게 하기로 한 것일 뿐이므로, **동일성에 기대는 코드를 쓰면 안 됩니다.** §6-③ 함정이 정확히 이것입니다.

### 3-3. `this`의 의미가 다릅니다

람다는 새 스코프를 만들지 않습니다. 규격이 못 박아 뒀습니다.

> JLS §15.8.3: "The value denoted by `this` in a lambda body is the same as the value denoted by `this` in the surrounding context."

```java
public class ThisProbe {
    private final String name = "OrderService";

    void report() {
        Task anon = new Task() {
            @Override public void run() {
                System.out.println("anon   this -> " + this.getClass().getName());
            }
        };
        Task lam = () -> System.out.println("lambda this -> " + this.getClass().getName());
        anon.run();   // anon   this -> ThisProbe$1
        lam.run();    // lambda this -> ThisProbe
    }
}
```

익명 클래스의 `this`는 자기 자신이고, 람다의 `this`는 바깥 인스턴스입니다. 익명 클래스를 람다로 "그냥 줄이는" 리팩터링이 안전하지 않은 이유가 여기 있습니다. 바디에 `this`나 숨은 필드 접근이 하나라도 있으면 의미가 바뀝니다.

## 4. 디폴트 메서드는 람다가 끌고 들어온 것입니다

Java 8 릴리스 노트를 보면 람다와 디폴트 메서드가 같이 들어왔습니다. 우연이 아닙니다.

1. 병렬화를 라이브러리에 맡기려면 내부 반복이 필요합니다.
2. 내부 반복을 주려면 `Collection`에 `stream()`을 추가해야 합니다.
3. 인터페이스에 추상 메서드를 추가하면 **세상의 모든 구현체가 깨집니다.**
4. 그래서 "구현이 딸린 인터페이스 메서드"가 필요해집니다 → 디폴트 메서드.

즉 람다 → 스트림 → 인터페이스 진화 문제 → 디폴트 메서드 순서입니다. 설계 문서도 "인터페이스는 한 번 공개하면 바꾸기 어렵다"는 문제를 디폴트 메서드의 동기로 명시합니다. 충돌 규칙은 "Class method declarations are preferred to interface defaults"이고, 디폴트끼리 충돌하면 컴파일 에러로 개발자에게 넘깁니다.

이 연쇄를 알면 `Predicate.and()`, `Comparator.thenComparing()` 같은 메서드들이 왜 디폴트 메서드인지도 설명됩니다. 함수형 인터페이스를 조합 가능하게 만들려면 메서드가 필요한데, 그걸 추상 메서드로 넣으면 더 이상 함수형 인터페이스가 아니게 됩니다(추상 메서드가 둘이 되니까요). 디폴트 메서드만이 SAM 조건을 유지하면서 조합 기능을 붙일 수 있는 자리입니다.

## 5. 예제 — 동작 파라미터화

람다를 "짧은 익명 클래스"로 보면 아래 ❌ 코드가 왜 나쁜지 설명이 안 됩니다. "동작을 값으로 넘긴다"로 보면 바로 보입니다.

### 5-1. 조건이 늘어날 때마다 메서드가 늘어나는 코드 ❌

```java
class OrderFinderBad {
    private final List<Order> orders;
    OrderFinderBad(List<Order> orders) { this.orders = orders; }

    List<Order> findPaid() {
        List<Order> result = new ArrayList<>();
        for (Order o : orders) if (o.paid()) result.add(o);
        return result;
    }
    List<Order> findByRegion(String region) {
        List<Order> result = new ArrayList<>();
        for (Order o : orders) if (o.region().equals(region)) result.add(o);
        return result;
    }
    // 조건 조합이 하나 늘 때마다 메서드가 하나 늘고, 순회 코드가 복사됩니다
    List<Order> findPaidOverAmount(String region, long min) {
        List<Order> result = new ArrayList<>();
        for (Order o : orders)
            if (o.paid() && o.region().equals(region) && o.amount() >= min) result.add(o);
        return result;
    }
}
```

변하는 건 `if` 안쪽 한 줄인데 변하지 않는 순회 코드가 메서드마다 복사됩니다. `boolean` 플래그 파라미터를 추가하는 방향으로 가면 더 나빠집니다.

### 5-2. 조건을 파라미터로 받는 코드 ✔️

```java
record Order(String id, String region, long amount, boolean paid) {}

class OrderFinder {
    private final List<Order> orders;
    OrderFinder(List<Order> orders) { this.orders = orders; }

    List<Order> find(Predicate<Order> condition) {
        return orders.stream().filter(condition).collect(Collectors.toList());
    }
}
```

```java
OrderFinder finder = new OrderFinder(orders);
Predicate<Order> paid = Order::paid;
Predicate<Order> highValue = o -> o.amount() >= 100_000;

finder.find(paid.and(highValue));   // [ORD-1, ORD-3]
finder.find(paid.negate());         // [ORD-2]
```

메서드가 하나로 줄어든 게 핵심이 아닙니다. **조건이 이름 붙은 값(`paid`, `highValue`)이 되어 조합·재사용·테스트가 된다**는 게 핵심이고, 순회 방식을 `OrderFinder`가 쥐게 되었다는 게 그다음입니다. 나중에 `parallelStream()`으로 바꿔도 호출하는 쪽 코드는 한 글자도 안 바뀝니다. §1에서 말한 "순회 권한을 라이브러리로 넘긴다"가 내 코드 안에서 벌어진 모습입니다.

## 6. 함정

### ① 람다 안에서 검사 예외를 던질 수 없습니다

**증상** — 평범한 I/O 코드를 스트림으로 바꾸면 컴파일이 안 됩니다.

```java
List<String> bodies = paths.stream()
        .map(p -> Files.readString(Path.of(p)))   // error
        .collect(Collectors.toList());
```

```
error: unreported exception IOException; must be caught or declared to be thrown
```

**원인** — `Function.apply`에 `throws`가 선언되어 있지 않습니다. §2에서 함수 타입을 기각한 이유 중 하나가 "검사 예외까지 표기하면 문법이 감당 불가"였고, 그 결정의 청구서가 여기로 옵니다. 43개 인터페이스 중 `throws`를 선언한 것은 `Callable` 계열뿐입니다.

**해법** — 람다 안에서 `try`로 감싸 비검사 예외로 바꾸거나(`throw new UncheckedIOException(e)`), 애초에 이 구간은 스트림으로 쓰지 않습니다. `ThrowingFunction` 같은 래퍼 인터페이스를 직접 만드는 방법도 있지만, 예외가 `RuntimeException`으로 바뀌어 전파되는 건 똑같으니 얻는 게 모양뿐입니다. 스트림이 오히려 손해인 경우는 `daily/day55-stream-when-not.md`에 따로 있습니다.

### ② 캡처는 필드가 아니라 객체 전체를 잡습니다 ⚠️

**증상** — 람다 하나를 리스너로 등록했는데 서비스 객체가 GC되지 않고 힙에 남습니다.

**원인** — 인스턴스 필드를 참조하는 람다는 그 필드가 아니라 **바깥 인스턴스 전체**를 캡처합니다. 런타임 객체의 필드를 리플렉션으로 열어 보면 그대로 나옵니다.

```java
static class OrderService {
    private final String region = "ap-northeast-2";
    Runnable task() { return () -> System.out.println(region); }   // String만 쓰는데
}
```

```
class = Captured$OrderService$$Lambda$1/0x00007f700c000c20
  field: Captured$OrderService arg$1      ← 서비스 인스턴스 전체를 들고 있습니다
```

`String` 하나만 쓰는 람다가 `OrderService`를, 따라서 그 서비스가 참조하는 모든 것을 살려 둡니다. `this::handleEvent` 같은 메서드 참조도 똑같습니다. 내부 클래스에서 익숙한 문제가 람다라고 사라지지 않습니다.

**해법** — 오래 살아남는 곳(정적 컬렉션, 이벤트 버스, 캐시)에 등록하는 람다는 캡처를 지역변수로 끊습니다. `String region = this.region;`을 먼저 만들고 그 변수를 참조하면 캡처되는 것은 `String` 하나입니다. 캡처가 아예 없으면 `arg$` 필드도 없습니다.

### ③ 등록한 람다는 지울 수 없습니다

**증상** — 핸들러를 등록하고, 똑같은 코드로 `remove`를 호출했는데 지워지지 않습니다.

```java
static void register()   { handlers.add(event -> System.out.println("audit: " + event)); }
static void unregister() { handlers.remove((Consumer<String>) event -> System.out.println("audit: " + event)); }
```

```
등록 후 = 1
해제 후 = 1      ← 안 지워졌습니다
```

**원인** — 소스가 글자 단위로 같아도 `invokedynamic` 호출 지점이 다르면 다른 객체입니다. 확인해 보면 `==`도 `false`, `equals()`도 `false`입니다. 생성된 히든 클래스는 `equals`를 재정의하지 않으므로 동일성 비교가 그대로 쓰이고, §3-2에서 본 "identity is unpredictable"이 이 상황을 규격 수준에서 허용합니다.

**해법** — 해제할 일이 있는 핸들러는 람다를 **변수나 필드에 담아 그 참조를 보관**하고, 등록·해제에 같은 참조를 씁니다. 등록 시점에 토큰(ID)을 돌려주는 API로 설계하는 편이 더 안전합니다. 반대로 `Set`이나 `Map` 키에 람다를 넣는 설계는 하지 않습니다.

### ④ 람다 모양이 오버로드 선택을 바꾸고, 예외가 사라집니다

**증상** — `ExecutorService`에 넘긴 작업이 예외를 던졌는데 로그에 아무것도 안 남습니다.

```java
Future<?> f = pool.submit(() -> { throw new IllegalStateException("결제 실패"); });
```

**원인** — 이 람다는 값을 반환하지 않지만, 본문이 항상 예외로 끝나므로 `Runnable`과 `Callable` 양쪽에 다 맞습니다. Java 17 `javac`가 고른 쪽을 바이트코드로 확인하면 이렇습니다.

```
invokeinterface ExecutorService.submit:(Ljava/util/concurrent/Callable;)Ljava/util/concurrent/Future;
private static java.lang.Object lambda$main$0() throws java.lang.Exception;
```

`Callable`로 해석됐습니다. `submit(Callable)`은 예외를 `Future`에 담아 두고 스레드 풀의 예외 핸들러를 거치지 않으므로, **`Future.get()`을 호출하지 않으면 예외는 영원히 보이지 않습니다.** 괄호 안 모양이 똑같아서 코드만 봐서는 어느 오버로드인지 알 수 없습니다.

**해법** — 결과가 필요 없는 작업은 `pool.execute(...)`를 씁니다(`Runnable`만 받으므로 모호성이 없고, 예외가 `UncaughtExceptionHandler`로 갑니다). `submit`을 써야 한다면 `Future`를 받아서 `get()`을 호출하거나, 람다 본문 안에서 직접 `try`/`catch`로 로그를 남깁니다. 더 일반적으로는, 오버로드가 있는 메서드에 람다를 넘길 때 어느 쪽으로 해석되는지 확인하는 습관이 필요합니다.

### ⑤ 람다는 자기 자신을 부를 수 없습니다

**증상** — 재귀를 람다로 쓰면 컴파일이 안 됩니다.

```java
IntUnaryOperator factorial = n -> n <= 1 ? 1 : n * factorial.applyAsInt(n - 1);
```

```
error: variable factorial might not have been initialized
```

**원인** — 람다는 새 스코프를 만들지 않으므로(§3-3) 본문에서 보는 `factorial`은 아직 초기화되지 않은 바로 그 지역변수입니다. 익명 클래스는 자기 타입 안에서 `this.method()`로 재귀할 수 있으니 여기서는 익명 클래스가 더 강합니다.

**해법** — 인스턴스 필드나 정적 필드로 선언하면(기본값 `null`로 초기화되므로) 통과하지만, 그렇게까지 할 일이면 그냥 이름 있는 메서드로 쓰는 게 맞습니다.

### ⑥ 스택트레이스에 의미 있는 이름이 없습니다

**증상** — 예외 로그에 `lambda$main$2` 같은 이름만 보입니다.

```
at Probe.lambda$main$2(Probe.java:30)
at Probe.main(Probe.java:31)
```

**원인** — 람다 본문은 `lambda$<감싼 메서드>$<순번>` 형태의 합성 메서드로 변환됩니다. 순번은 컴파일 순서라서, 같은 메서드 안의 람다 순서를 바꾸면 번호가 바뀝니다. 스트림 파이프라인을 거치면 프레임도 깊어집니다.

**해법** — 줄 번호가 있으니 추적은 됩니다. 다만 한 메서드에 람다를 여러 개 넣으면 어느 것인지 가려내기 어려우므로, 서로 구분해야 하는 로직은 이름 있는 메서드로 빼고 메서드 참조로 넘깁니다. 로그에도 이름이 남고 단위 테스트도 가능해집니다. 스택트레이스를 읽는 절차 자체는 `daily/day31-stacktrace-reading.md`에 있습니다.

## 7. 그래서 언제 익명 클래스를 쓰는가

람다가 익명 클래스를 완전히 대체하지 않습니다. 아래 셋 중 하나라도 걸리면 익명 클래스입니다.

| 상황 | 이유 |
|---|---|
| 추상 메서드가 둘 이상 | 함수형 인터페이스가 아니므로 람다 불가 |
| 상태를 들고 있어야 함 | 람다에는 필드를 선언할 수 없음 |
| 자기 자신을 참조·재귀해야 함 | 람다의 `this`는 바깥 인스턴스 (§3-3, §6-⑤) |
| 등록 후 동일성으로 해제해야 함 | 익명 클래스는 인스턴스가 예측 가능 (§6-③) |

반대로 람다를 쓸 자리는 "동작 하나를 값으로 넘기는" 자리입니다. 그게 람다가 들어온 이유이기도 합니다.

## 8. 참고자료

- [State of the Lambda (Brian Goetz, 4th edition)](https://cr.openjdk.org/~briangoetz/lambda/lambda-state-final.html) — 익명 클래스의 다섯 가지 한계, 화살표 타입을 기각한 이유, 디폴트 메서드의 동기
- [JEP 126: Lambda Expressions & Virtual Extension Methods](https://openjdk.org/jeps/126) — Java 8에 들어간 람다·디폴트 메서드 JEP
- [`LambdaMetafactory` Javadoc (Java SE 21)](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/lang/invoke/LambdaMetafactory.html) — 캡처 단계의 인스턴스 생성·동일성이 보장되지 않는다는 규정
- [JLS Java SE 21 §15.8.3](https://docs.oracle.com/javase/specs/jls/se21/html/jls-15.html#jls-15.8.3) — 람다 본문의 `this`
- [`java.util.function` 패키지 (Java SE 21)](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/function/package-summary.html) — 43개 인터페이스 목록

<!-- TODO: 확인 필요 — §3-1의 "원하면 전략을 바꿀 수 있게 두는 것이 invokedynamic 번역의 의도"는 설계 문서의 서술과 실제 OpenJDK 동작(캡처 없는 람다 재사용)에서 역으로 읽은 것입니다. "번역 전략을 교체 가능하게 남긴다"는 표현 자체를 규격 문서에서 직접 확인하지는 못했습니다. -->
<!-- TODO: 확인 필요 — §3-1의 Java 21부터 람다 히든 클래스 이름에서 순번이 빠진 변경은 Temurin 17.0.21 / 21 / 25에서 직접 출력해 확인한 것입니다. 이 변경을 다룬 JDK 이슈 번호는 특정하지 못했으므로, 이름 형식에 의존하는 코드가 있다면 해당 JDK에서 직접 확인하시기 바랍니다. -->

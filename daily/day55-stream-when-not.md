# 스트림이 오히려 나쁜 경우는 어디인가

> 이 문서가 답할 질문: **어떤 조건에서 스트림이 루프보다 나쁜 선택이 되고, 그 조건을 무엇으로 판별하는가?**
>
> 분류: 선택형(스트림 vs 루프). "스트림이 나쁜 경우"는 결국 두 반복 방식의 트레이드오프를 묻는 질문이라, 여러 출처가 공통으로 드는 비교 기준을 찾는 관점으로 조사했습니다.
>
> 기준: Java 25 API 문서. 동작 확인은 OpenJDK 17(Temurin 17.0.20.1)에서 직접 실행한 결과입니다. 람다·함수형 인터페이스 자체의 도입 배경은 별도 주제이고, 이 문서는 **이미 스트림을 쓸 수 있는 사람이 쓰지 말아야 할 자리를 알아보는 법**만 다룹니다.

## 1. 핵심 개념 — 스트림은 루프의 새 문법이 아니라 파이프라인 선언입니다

`for`는 "이 순서로 이만큼 돌아라"라는 명령입니다. 스트림은 "원소마다 이 함수를 적용해서 이 모양으로 접어라"라는 **선언**입니다. 반복의 주도권이 내 코드에서 라이브러리로 넘어갑니다(내부 반복).

이 차이가 그냥 취향 문제로 보이는 이유는, CRUD 수준에서는 둘이 정말 바꿔 쓸 수 있기 때문입니다. 차이는 요구사항이 조금 복잡해지는 순간 드러납니다.

JDK 문서는 파이프라인에 넘기는 함수(동작 파라미터)에 조건을 걸어둡니다. **상태가 없어야 하고, 부수효과를 내지 말아야 하고, 소스를 건드리지 말아야 합니다.** 문서는 "동작 파라미터에 상태를 두는 것을 아예 피하는 게 최선"이라고 못 박습니다([java.util.stream 패키지 문서](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/stream/package-summary.html)).

> 문제는 이 조건을 어겨도 컴파일이 된다는 점입니다. 루프는 "변수 두 개 누적하면서 중간에 빠져나가기"를 그냥 해냅니다. 스트림은 같은 걸 시키면 `int[] total = {0}` 같은 배열 트릭으로 상태를 밀어 넣게 되고, 그 코드는 순차 실행에서는 돌아갑니다. 그래서 틀린 줄 모르고 넘어갑니다. 나중에 누가 `.parallel()` 한 줄을 붙이는 순간, 합계가 호출마다 달라지는 버그가 됩니다. 재현도 안 됩니다.

스트림이 나쁜 경우를 아는 건 문체 취향이 아니라, **라이브러리에 반복을 넘겨도 되는 작업인지 판별하는 능력**입니다.

## 2. 구조 — 루프와 갈리는 세 지점

### 2-1. 반복을 내가 제어하지 못합니다

루프는 `break`, `continue`, 인덱스, 직전 원소 참조가 전부 공짜입니다. 스트림에는 인덱스가 없고, 중간 탈출은 `findFirst`·`anyMatch`·`takeWhile` 같은 **정해진 모양**일 때만 됩니다. "조건을 만족하면 거기까지의 누적값을 들고 멈춘다"는 요구는 스트림 어휘에 없습니다.

### 2-2. 동작 파라미터는 검사 예외를 던질 수 없습니다

`Function`, `Predicate`, `Consumer` 모두 `throws` 선언이 없습니다. 람다 안에서 `IOException`을 던지는 메서드를 호출하면 컴파일 에러가 나고, 결국 try-catch로 감싸 `RuntimeException`으로 바꿔 던지게 됩니다. 루프에서는 메서드에 `throws`를 한 번 붙이면 끝나는 일입니다.

### 2-3. 결과를 하나만 낼 때 가장 깔끔합니다

파이프라인은 입력 한 줄기를 받아 출력 하나로 접는 구조입니다. 한 번 순회하면서 합계·건수·목록 셋을 동시에 만들어야 하면, 스트림은 세 번 돌거나(`stream()` 세 번) 복합 수집기를 조립해야 합니다. 루프는 변수 세 개를 선언하면 끝납니다.

## 3. 흐름 — 디버깅할 때 실제로 보이는 것

### 3-1. 같은 NPE, 다른 스택트레이스

주문 합계를 구하는 코드를 스트림과 루프로 각각 쓰고, `unitPrice`가 `null`인 행을 넣어 터뜨려 봤습니다.

```java
static int totalByStream(List<OrderLine> lines) {
    return lines.stream()
            .filter(line -> line.quantity() > 0)
            .mapToInt(line -> line.quantity() * line.unitPrice())
            .sum();
}

static int totalByLoop(List<OrderLine> lines) {
    int total = 0;
    for (OrderLine line : lines) {
        if (line.quantity() <= 0) continue;
        total += line.quantity() * line.unitPrice();
    }
    return total;
}
```

스트림 쪽 스택트레이스입니다. 실제 실행 결과에서 JDK 내부 프레임만 옮겼습니다.

```text
at Trace.lambda$totalByStream$1(Trace.java:10)      ← 내 코드
at java.util.stream.ReferencePipeline$4$1.accept
at java.util.stream.ReferencePipeline$2$1.accept
at java.util.AbstractList$RandomAccessSpliterator.forEachRemaining
at java.util.stream.AbstractPipeline.copyInto
at java.util.stream.AbstractPipeline.wrapAndCopyInto
at java.util.stream.ReduceOps$ReduceOp.evaluateSequential
at java.util.stream.AbstractPipeline.evaluate
at java.util.stream.IntPipeline.reduce
at java.util.stream.IntPipeline.sum
at Trace.totalByStream(Trace.java:11)               ← 내 코드
```

루프 쪽은 두 줄입니다.

```text
at Trace.totalByLoop(Trace.java:18)
at Trace.main(Trace.java:28)
```

내 코드 두 프레임 사이에 JDK 내부 프레임 9개가 끼어 있습니다. 더 불편한 건 **터진 자리가 `lambda$totalByStream$1`로 찍힌다**는 점입니다. 람다는 이름이 없으니 컴파일러가 붙인 합성 이름이 나오고, 파이프라인에 람다가 여러 개면 몇 번째 것인지는 줄 번호로 역추적해야 합니다. 스택트레이스 읽는 요령은 `day27-stacktrace-reading.md`와 같지만, 읽을 양이 늘어납니다.

### 3-2. 중단점을 걸 자리가 다릅니다

루프는 `total +=` 줄에 중단점 하나 걸고 변수 창에서 `total`의 변화를 봅니다. 스트림은 파이프라인 전체가 한 문장이라 그 "중간"에 서려면 람다 본문에 걸어야 하고, 매 원소마다 멈춥니다. `peek`로 찍어보는 방법이 있지만 이건 함정이 하나 더 있습니다(§7-2).

## 4. 특징 — 판단 기준

### 4-1. 루프를 고르는 신호

아래 중 하나라도 해당하면 루프가 맞습니다.

1. 람다 밖의 변수를 바꾸려고 `int[]`·`AtomicInteger`·`final` 배열을 꺼내게 됨
2. 인덱스나 직전 원소가 필요함 (i와 i+1 비교, 순번 매기기)
3. 조건을 만족하면 거기까지의 누적 상태를 들고 멈춰야 함
4. 루프 몸통에서 검사 예외를 던지는 API를 호출함
5. 한 번 순회하면서 결과를 두 개 이상 만들어야 함
6. 원소마다 DB·HTTP 호출이 들어감 (I/O는 §5를 보세요)

### 4-2. 스트림을 고르는 신호

- "걸러서 → 바꿔서 → 모은다"가 그대로 코드가 됨. 중간 변수가 필요 없습니다.
- 결과가 하나입니다. 합계, 목록, 그룹별 맵.
- 수집 로직을 이름 붙여 재사용하고 싶습니다. `Collector`는 조립됩니다.
- 원소마다의 계산이 서로 독립이고 비싸서, 나중에 병렬화를 검토할 여지를 남기고 싶습니다.

### 4-3. 트레이드오프 — 공짜가 아닌 것

| 항목 | 스트림 | 루프 |
|---|---|---|
| 의도 표현 | 무엇을 하는지 보임 | 어떻게 하는지 보임 |
| 상태 누적 | 구조적으로 막혀 있음 | 자유롭게 가능 |
| 스택트레이스 | 내부 프레임이 끼어듦 | 내 프레임만 |
| 검사 예외 | 감싸서 던져야 함 | `throws`로 전파 |
| 박싱 | `Stream<Integer>`는 원소마다 박싱 | 원시 타입 그대로 |
| 병렬화 | `parallel()` 한 줄 | 직접 구현 |

박싱 항목은 실무에서 자주 놓칩니다. `list.stream().map(Order::getAmount).reduce(0, Integer::sum)`은 중간마다 `Integer`를 만듭니다. `mapToInt(...).sum()`을 쓰면 원시 타입 경로(`IntStream`)로 내려가 박싱이 사라집니다. 숫자를 다루는 파이프라인에서는 `mapToInt`·`mapToLong`을 먼저 떠올리는 게 맞습니다.

## 5. `parallel()`은 왜 기본값이 아닌가

`.parallel()`은 한 글자 추가로 멀티코어를 쓰는 것처럼 보이지만, 비용 구조가 전혀 다른 실행 방식으로 갈아타는 일입니다.

### 5-1. 작업량이 충분해야 본전입니다

스트림 병렬화 설계자인 Doug Lea가 제시한 기준이 N × Q 모델입니다. N은 원소 수, Q는 원소당 계산 비용입니다. **N × Q가 최소 10,000은 되어야 병렬화가 값을 합니다.** 병렬 실행의 고정 오버헤드가 대략 100마이크로초 수준이라는 측정에서 나온 숫자이고, `x -> x + 1` 수준의 가벼운 함수라면 원소 1만 개쯤에서 손익분기가 잡힙니다. 원소 100개 미만 컬렉션은 병렬이 **훨씬 느릴 수 있다**고 같은 글이 명시합니다([Doug Lea, When to use parallel streams](https://gee.cs.oswego.edu/dl/html/StreamParallelGuidance.html)).

실무 코드에서 `List<OrderLine>`은 보통 수십 개입니다. 거기 붙은 `.parallel()`은 이득이 아니라 순손실입니다.

### 5-2. 풀을 혼자 쓰는 게 아닙니다

병렬 스트림은 어느 스레드에서 도는지 확인해 봤습니다.

```java
Set<String> threads = ConcurrentHashMap.newKeySet();
IntStream.range(0, 1000).parallel()
        .forEach(i -> threads.add(Thread.currentThread().getName()));
System.out.println(threads);
```

4코어 환경에서의 출력입니다.

```text
[ForkJoinPool.commonPool-worker-1, ForkJoinPool.commonPool-worker-2, main]
```

호출한 스레드(`main`)까지 작업에 동원되고, 나머지는 **JVM 전체가 공유하는 공용 풀**의 워커입니다. 같은 실행에서 `ForkJoinPool.getCommonPoolParallelism()`은 `3`, `Runtime.availableProcessors()`는 `4`였습니다.

여기서 두 가지가 따라옵니다. 첫째, 공용 풀은 작습니다. 둘째, 그걸 애플리케이션의 모든 병렬 스트림이 나눠 씁니다. 그래서 원소마다 HTTP를 호출하는 병렬 스트림 하나가 워커를 전부 붙잡고 있으면, 무관한 요청의 병렬 스트림까지 같이 멈춥니다. ForkJoin 풀은 블로킹된 워커를 자동으로 보충해주지 않습니다 — JDK 문서도 "블로킹 I/O나 관리되지 않는 동기화 앞에서는 그런 조정이 보장되지 않는다"고 적어둡니다([ForkJoinPool](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/concurrent/ForkJoinPool.html)).

**결론: I/O가 섞인 반복에 `parallel()`을 붙이지 않습니다.** 병렬로 외부를 호출해야 하면 전용 `ExecutorService`와 `CompletableFuture`를 쓰는 쪽이 맞습니다. 풀을 지정할 수 있고, 타임아웃도 걸 수 있습니다.

<!-- TODO: 확인 필요 — 공용 풀 기본 병렬도가 "프로세서 수 - 1"이라는 규칙은 Java 25 javadoc에 명시돼 있지 않습니다. 위 수치는 4코어 환경 1회 실행값이므로, 다른 코어 수에서의 일반화는 확정하지 않았습니다. 코드에서 단정하지 말고 getCommonPoolParallelism()으로 확인하는 편이 안전합니다. -->

## 6. 예제

### 6-1. 배열 트릭이 나온 코드 ❌

출고 검토용으로 합계·부족 건수·부족 SKU를 한 번에 구하는 코드입니다.

```java
public ShipmentReport buildReport(List<OrderLine> lines) {
    int[] totalAmount = {0};
    int[] shortageCount = {0};
    List<String> shortageSkus = new ArrayList<>();

    lines.forEach(line -> {
        totalAmount[0] += line.quantity() * line.unitPrice();
        if (line.quantity() > line.stock()) {
            shortageCount[0]++;
            shortageSkus.add(line.sku());
        }
    });

    return new ShipmentReport(totalAmount[0], shortageCount[0], shortageSkus);
}
```

돌아갑니다. 하지만 `int[] {0}`은 컴파일러를 속이려고 만든 상자입니다. 람다는 지역 변수를 다시 대입할 수 없으니, 참조는 그대로 두고 내용만 바꿀 통을 만든 겁니다.

`forEach`를 `parallelStream().forEach`로 바꾸면 세 값 전부 깨집니다. `totalAmount[0] +=`는 읽고 더하고 쓰는 세 단계라 원자적이지 않고, `shortageSkus`는 스레드 안전하지 않은 `ArrayList`입니다. 원소 2만 개로 10회 돌려본 결과 **10회 전부 합계가 틀렸습니다**(OpenJDK 17, 4코어). 문법은 그대로인데 결과만 틀리고, 틀린 값이 매번 달라서 테스트로도 안 잡힙니다(§7-1).

### 6-2. 루프로 되돌린 코드 ✔️

```java
public ShipmentReport buildReport(List<OrderLine> lines) {
    int totalAmount = 0;
    int shortageCount = 0;
    List<String> shortageSkus = new ArrayList<>();

    for (OrderLine line : lines) {
        totalAmount += line.quantity() * line.unitPrice();
        if (line.quantity() > line.stock()) {
            shortageCount++;
            shortageSkus.add(line.sku());
        }
    }

    return new ShipmentReport(totalAmount, shortageCount, shortageSkus);
}
```

짧아지고, 상자가 사라지고, 중단점 걸 자리가 생겼습니다. **결과가 세 개이므로 애초에 파이프라인이 아니었습니다.**

### 6-3. 스트림이 맞는 자리 ✔️

같은 데이터에서 결과를 하나만 뽑는다면 스트림이 더 낫습니다.

```java
int totalAmount = lines.stream()
        .mapToInt(line -> line.quantity() * line.unitPrice())
        .sum();

Map<String, List<OrderLine>> byWarehouse = lines.stream()
        .collect(Collectors.groupingBy(OrderLine::warehouseCode));
```

판단 기준은 문체가 아니라 **출력 개수와 상태 유무**입니다.

## 7. 함정

### 7-1. 공유 컬렉션에 병렬로 모으면 원소가 없어집니다

- **증상**: `parallel().forEach(list::add)`로 2만 개를 넣었는데 `list.size()`가 2만이 아닙니다. 값이 실행마다 다르고, `ArrayIndexOutOfBoundsException`이나 `null` 원소가 섞이기도 합니다.
- **원인**: `ArrayList`는 스레드 안전하지 않습니다. 여러 워커가 같은 내부 배열과 `size` 필드를 동시에 건드립니다. 실제로 2만 개를 20회 반복해 넣어본 결과 **20회 전부 크기가 틀렸습니다**(OpenJDK 17, 4코어).
- **해법**: 수집은 직접 하지 말고 `collect`에 맡깁니다. `collect(Collectors.toList())`와 `toList()`는 스레드마다 별도 컨테이너에 모은 뒤 합치도록 설계돼 있습니다. 동기화로 막는 건 해법이 아닙니다 — 문서가 "경쟁이 병렬화 이득을 깎아먹는다"고 지적하는 경우가 정확히 이것입니다.

### 7-2. `peek`에 찍은 로그가 안 나옵니다

- **증상**: 파이프라인 중간에 `peek(System.out::println)`을 넣었는데 아무것도 출력되지 않습니다.
- **원인**: 터미널 연산이 소스 크기만으로 답을 낼 수 있으면 JDK는 파이프라인 실행을 생략합니다. `names.stream().peek(...).count()`를 돌려보면 `count`는 `3`을 반환하면서 `peek` 출력은 한 줄도 나오지 않습니다. 문서도 "짧은 회로 연산이나 `count()`처럼 원소 생산을 최적화로 없앨 수 있는 경우 동작이 호출되지 않는다"고 명시합니다.
- **해법**: `peek`은 디버깅 보조로만 봅니다. 반드시 실행돼야 하는 동작은 `forEach`나 `forEachOrdered`에 둡니다 — 문서가 생략 대상에서 예외로 지정한 둘입니다.

### 7-3. 파이프라인 안에서 소스를 고치면 예외보다 나쁜 일이 생깁니다

- **증상**: `ConcurrentModificationException`이 나거나, 더 나쁘게는 **엉뚱한 `NullPointerException`**이 납니다.
- **원인**: `Spliterator`가 소스 배열을 직접 훑는 도중 크기가 바뀝니다. 3원소 `ArrayList`에서 `stream().forEach(n -> list.remove(n))` 형태로 원소를 지우면, OpenJDK 17에서는 CME가 아니라 `"<parameter2>" is null` 같은 NPE가 났습니다. 반대로 파이프라인 안에서 `add`하면 CME가 났습니다. **같은 규칙 위반인데 증상이 갈립니다.**
- **해법**: 소스를 바꿔야 하면 `removeIf`를 쓰거나, 새 리스트를 만들어 교체합니다. 참고로 구식 `for (String n : list)`에서 끝에서 두 번째 원소를 지우면 예외도 없이 조용히 루프가 끝납니다. 어느 쪽이든 **순회 중 수정은 하지 않는다**가 답입니다.

### 7-4. `Collectors.toMap`은 `HashMap`보다 까다롭습니다

- **증상**: `HashMap.put`으로 멀쩡히 돌던 코드를 `toMap`으로 바꾸자 `NullPointerException` 또는 `IllegalStateException`이 납니다.
- **원인**: 값이 `null`이면 NPE, 키가 겹치면 ISE입니다. OpenJDK 17에서 값 `null` → `java.lang.NullPointerException`, 키 중복 → `java.lang.IllegalStateException`을 확인했습니다. 키 중복은 javadoc에 명시돼 있고, 중복 가능성이 있으면 병합 함수 받는 오버로드를 쓰라고 안내합니다.
- **해법**: 키 중복 가능성이 있으면 `toMap(keyMapper, valueMapper, (a, b) -> b)`처럼 병합 규칙을 명시합니다. 값이 `null`일 수 있으면 `toMap`을 쓰지 않거나, 앞단에서 걸러냅니다. 값 `null` 동작은 javadoc이 아니라 구현에서 나오는 결과이므로 더 믿을 게 없습니다.

### 7-5. `toList()`와 `Collectors.toList()`는 다른 물건입니다

- **증상**: 반환받은 리스트에 `add`하자 `UnsupportedOperationException`이 납니다.
- **원인**: `Stream.toList()`가 돌려주는 리스트는 **수정 불가**입니다. javadoc이 "변경 메서드 호출은 항상 `UnsupportedOperationException`을 던진다"고 적어둡니다. 반면 `Collectors.toList()`는 타입·가변성·직렬화 가능성에 **아무 보장이 없습니다**. 현재 구현에서는 `ArrayList`가 나와 `add`가 됩니다. 확인해 보면 `toList()`는 UOE, `Collectors.toList()`는 정상 추가였습니다.
- **해법**: 반환값은 `toList()`를 기본으로 씁니다. 받는 쪽이 고쳐야 한다면 가변성을 기대하지 말고 `collect(Collectors.toCollection(ArrayList::new))`로 **의도를 코드에 적습니다.** "지금 `ArrayList`가 나오니까 괜찮다"는 보장 없는 구현에 기대는 것입니다.

## 8. 참고자료

- [java.util.stream 패키지 문서 (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/stream/package-summary.html) — 부수효과·상태 있는 람다·간섭·병렬화 규칙의 1차 출처
- [Stream (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/stream/Stream.html) — `peek`의 생략 조건, `toList()`의 불변 보장
- [Collectors (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/stream/Collectors.html) — `toMap` 키 중복, `toList()`의 무보장 조항
- [ForkJoinPool (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/concurrent/ForkJoinPool.html) — 공용 풀, `ManagedBlocker`
- [Doug Lea, When to use parallel streams](https://gee.cs.oswego.edu/dl/html/StreamParallelGuidance.html) — N × Q ≥ 10,000 기준
- 관련: `day27-stacktrace-reading.md`(스택트레이스 읽기), `day49-optional-misuse.md`(타입을 의도대로 쓰기), `day43-immutability.md`(불변과 동시성)

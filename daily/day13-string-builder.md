# String 더하기가 루프 안에서 느린 이유

> 이 문서가 답할 질문: **`+`로 문자열을 이어붙이는 코드는 언제 문제가 되고, 무엇으로 바꿔야 하는가?**
>
> 분류: 문제해결형(증상 → 원인 → 해법). "느리다"는 증상에서 시작해 불변성이라는 원인까지 내려갑니다.
>
> 기준: Java 25(LTS, 2025-09-16 GA, [JDK 25](https://openjdk.org/projects/jdk/25/)) 기준으로 서술합니다. 본문의 측정값은 Temurin JDK 17.0.20+8 / Linux x64에서 직접 재현한 것이며, 조건을 그때마다 밝힙니다.

## 1. 핵심 개념 — String은 고칠 수 없습니다

`String`은 불변(immutable) 객체입니다. 한 번 만들어진 문자열의 내용은 절대 바뀌지 않습니다. 그래서 `a + b`는 `a`를 늘리는 연산이 아니라 **`a`와 `b`를 담을 새 String을 만드는 연산**입니다.

`StringBuilder`는 반대입니다. 내부에 가변 배열을 들고 있고, `append()`는 그 배열에 이어 쓰기만 합니다. 배열이 모자랄 때만 더 큰 배열로 옮깁니다.

> CSV를 만드는 배치가 로컬에서는 잘 돌았는데 운영에서 10만 행을 처리하자 30분이 지나도 안 끝납니다. CPU는 한 코어만 100%, GC 로그는 조용합니다. 프로파일러를 붙이면 `String.concat`이 아니라 `Arrays.copyOfRange`가 시간을 다 먹고 있습니다. **불변 객체를 반복문에서 누적하면 데이터가 2배가 될 때 시간은 4배가 됩니다.** 부하가 낮을 때는 절대 안 보이고, 데이터가 커지는 순간 절벽처럼 나타납니다.

## 2. 구조

### 2-1. String 내부

Java 9부터 String은 `char[]`가 아니라 `byte[]` + `coder` 필드로 문자열을 담습니다(JEP 254, [Compact Strings](https://openjdk.org/jeps/254)). Latin-1로 표현 가능한 문자만 있으면 문자당 1바이트, 아니면 UTF-16으로 2바이트를 씁니다. 대부분의 문자열이 ASCII라는 관측에서 나온 최적화입니다.

여기서 실무적으로 중요한 건 두 가지입니다.

- 한글이 하나라도 섞이면 그 문자열 전체가 UTF-16 모드가 됩니다. ASCII 문자도 2바이트를 씁니다.
- **어느 쪽이든 배열입니다.** 이어붙이려면 새 배열을 할당하고 양쪽을 복사하는 수밖에 없습니다.

### 2-2. StringBuilder 내부

`StringBuilder`는 같은 `byte[]` + `coder` 구조를 쓰되 배열을 재사용합니다. 핵심은 **용량(capacity)과 길이(length)가 다르다**는 점입니다.

| 생성 방법 | 초기 용량 |
|---|---:|
| `new StringBuilder()` | 16 |
| `new StringBuilder("hello")` | 21 (문자열 길이 + 16) |
| `new StringBuilder(4096)` | 4096 |

용량이 모자라면 새 배열로 확장합니다. 확장 크기는 "요청된 최소 용량"과 "기존 용량의 2배 + 2" 중 큰 쪽입니다([StringBuilder.ensureCapacity](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/StringBuilder.html)). 2배씩 늘어나므로 n개를 붙일 때 확장 횟수는 log n에 그칩니다. 이게 `+` 누적과 갈리는 지점입니다.

```java
// 직접 확인한 값 (Temurin 17.0.20)
new StringBuilder().capacity()          // 16
new StringBuilder("hello").capacity()   // 21
```

## 3. 흐름

### 3-1. 컴파일러가 실제로 만드는 코드

`+`가 무엇으로 바뀌는지는 컴파일 시점에 결정됩니다. 그리고 **JDK 9에서 그 방식이 바뀌었습니다**(JEP 280, [Indify String Concatenation](https://openjdk.org/jeps/280)). JDK 8까지 javac는 `StringBuilder.append()` 호출 체인을 바이트코드에 직접 박아 넣었습니다. JDK 9부터는 `invokedynamic` 한 줄만 남기고, 실제 구현은 런타임의 `java.lang.invoke.StringConcatFactory`가 결정합니다.

이렇게 바꾼 이유는 **바이트코드를 재컴파일하지 않고도 연결 전략을 갈아끼우기 위해서**입니다. append 체인이 박혀 있으면 JDK가 더 좋은 방법을 알아내도 이미 배포된 클래스 파일에는 적용할 수 없습니다.

아래 코드를 JDK 17에서 컴파일해 `javap -c`로 뜯어본 결과입니다.

```java
static String inLoop(String[] tags) {
    String result = "";
    for (String tag : tags) {
        result = result + "," + tag;
    }
    return result;
}
```

```text
  14: if_icmpge     38          ← 루프 조건
  ...
  26: invokedynamic #9,  0      // makeConcatWithConstants:(String;String;)String;
  31: astore_1
  35: goto          11          ← 루프 back edge
```

`invokedynamic`이 **루프 안에** 있습니다. 반복마다 새 String이 하나씩 만들어진다는 뜻입니다.

`-XDstringConcat=inline` 옵션을 주면 JDK 8 시절 바이트코드를 볼 수 있습니다.

```text
  23: new           #9   // class java/lang/StringBuilder   ← 루프 안에서 매번 생성
  27: invokespecial      // StringBuilder.<init>:()V
  31: invokevirtual      // StringBuilder.append
  36: invokevirtual      // StringBuilder.append
  44: invokevirtual      // StringBuilder.toString:()String;
  51: goto          11
```

여기서 흔한 오해가 깨집니다. **"컴파일러가 알아서 StringBuilder로 바꿔주니까 괜찮다"는 말은 반쪽만 맞습니다.** 바꿔주긴 하는데, 반복마다 **새 StringBuilder를 만들고 `toString()`으로 다시 String을 뽑습니다.** 누적된 내용이 매번 통째로 복사됩니다.

### 3-2. 왜 데이터가 2배면 시간이 4배인가

`result`의 길이가 L일 때 `result + ","+ tag` 한 번이 하는 일입니다.

```
1. 결과 길이 계산                  L + 1 + tag.length()
2. 그 크기의 새 byte[] 할당
3. 기존 result 전체를 복사          ← L 바이트
4. "," 와 tag 복사
5. 새 String 객체 생성
```

3번이 문제입니다. 매 반복마다 **그때까지 쌓인 전부**를 복사합니다. n번 반복하면 복사량은 대략 `1 + 2 + 3 + ... + n`, 즉 **n²/2**에 비례합니다.

```
+= 누적    : 1 → 2 → 3 → ... → n   총 복사량 ≈ n²/2
StringBuilder: 배열에 이어쓰기, 용량 초과 시에만 복사   총 복사량 ≈ 2n
```

JIT 컴파일러가 이걸 고쳐줄 수는 없습니다. 매 반복이 만드는 **중간 String이 실제로 관측 가능한 객체**라서, 복사를 건너뛰는 건 최적화가 아니라 의미 변경입니다.

## 4. 실제로 재현한 수치

n개의 숫자와 쉼표를 이어붙이는 코드를 두 방식으로 돌렸습니다. 워밍업 5회 후 측정, Temurin JDK 17.0.20+8 / Linux x64, JMH가 아닌 단순 `System.nanoTime()` 측정이라 절대값보다 **증가 추세**를 봐 주세요.

| n | `result = result + i + ","` | `sb.append(i).append(',')` |
|---:|---:|---:|
| 10,000 | 67.8 ms | 0.63 ms |
| 20,000 | 125.1 ms | 1.17 ms |
| 40,000 | 546.5 ms | 2.21 ms |
| 80,000 | 1795.5 ms | 2.29 ms |

n이 40,000 → 80,000으로 2배가 될 때 `+=`는 3.3배가 됐습니다. 이론값 4배에 가깝습니다. StringBuilder 쪽은 8만 개를 붙여도 2ms대에 머뭅니다. **80,000건에서 이미 780배 차이입니다.**

무서운 건 표의 왼쪽 위입니다. 1만 건에서 68ms면 개발할 때는 아무도 눈치채지 못합니다.

## 5. 그런데 `+`가 더 빠른 경우도 있습니다

여기서 많이들 반대 방향으로 틀립니다. **개수가 정해진 연결에서는 `+`가 손으로 짠 StringBuilder보다 빠릅니다.**

```java
// A: 그냥 +
return "order=" + orderId + " status=" + status + " qty=" + qty + " price=" + price;

// B: 손으로 짠 StringBuilder
return new StringBuilder()
        .append("order=").append(orderId)
        .append(" status=").append(status)
        .append(" qty=").append(qty)
        .append(" price=").append(price)
        .toString();
```

같은 환경에서 각 300만 회 반복한 결과입니다.

| 회차 | A (`+`) | B (수동 StringBuilder) |
|---:|---:|---:|
| 1 | 133.9 ms | 191.3 ms |
| 2 | 139.7 ms | 192.0 ms |
| 3 | 112.1 ms | 190.9 ms |

이유는 JEP 280이 만든 런타임 전략에 있습니다. `StringConcatFactory`는 인자 개수와 타입을 **링크 시점에 알고 있으므로**, 최종 길이를 먼저 계산해서 **정확한 크기의 배열을 한 번만 할당**할 수 있습니다([StringConcatFactory javadoc](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/invoke/StringConcatFactory.html)). 손으로 짠 StringBuilder는 용량 16에서 시작해 확장을 겪고, 마지막에 `toString()`으로 한 번 더 복사합니다.

**정리하면 기준은 "StringBuilder가 좋다"가 아닙니다.**

```
연결 횟수가 컴파일 시점에 고정  →  +  를 쓴다 (가독성도, 성능도)
연결 횟수가 런타임에 정해진다   →  StringBuilder 하나를 루프 밖에서 만든다
```

## 6. 예제

### 6-1. 클린하지 않은 코드 ❌

```java
public String toCsv(List<Order> orders) {
    String csv = "id,status,amount\n";
    for (Order order : orders) {
        csv += order.getId() + "," + order.getStatus() + "," + order.getAmount() + "\n";
    }
    return csv;
}
```

`csv +=`가 O(n²)입니다. 주문이 10만 건이면 사실상 끝나지 않습니다.

### 6-2. 개선한 코드 ✔️

```java
public String toCsv(List<Order> orders) {
    StringBuilder csv = new StringBuilder(orders.size() * 48);   // 행당 대략 48바이트로 예상
    csv.append("id,status,amount\n");
    for (Order order : orders) {
        csv.append(order.getId()).append(',')
           .append(order.getStatus()).append(',')
           .append(order.getAmount()).append('\n');
    }
    return csv.toString();
}
```

두 가지를 바꿨습니다.

1. StringBuilder를 **루프 밖에서** 하나만 만듭니다.
2. 초기 용량을 대략이라도 잡아 배열 확장을 줄입니다. 예상이 빗나가도 자동 확장되므로 손해는 없습니다.

### 6-3. 애초에 문자열로 안 만드는 선택 ✔️✔️

10만 행 CSV를 String으로 만들면 그 자체가 힙에 수 MB짜리 객체로 앉습니다. Old 영역까지 올라가면 GC 압박이 됩니다([day07-jvm-memory.md](day07-jvm-memory.md)).

```java
public void writeCsv(List<Order> orders, Writer out) throws IOException {
    out.write("id,status,amount\n");
    for (Order order : orders) {
        out.write(order.getId() + "," + order.getStatus() + "," + order.getAmount() + "\n");
    }
}
```

여기서 루프 안의 `+`는 **누적이 아니라 한 행짜리 고정 개수 연결**이므로 문제가 없습니다(§5). `BufferedWriter`로 감싸면 I/O도 묶입니다. **최선은 큰 문자열을 안 만드는 것입니다.**

## 7. 실무에서 찾아보는 문자열 연결

표준 라이브러리는 "구분자로 잇기"를 이미 제공합니다. StringBuilder를 직접 돌리기 전에 이쪽부터 봅니다.

```java
String tags = String.join(", ", tagList);                       // Java 8+

String ids = orders.stream()
        .map(Order::getId)
        .collect(Collectors.joining(", ", "[", "]"));            // 접두/접미까지

StringJoiner joiner = new StringJoiner(" AND ", "WHERE ", "");   // 조건이 없으면 빈 문자열
joiner.setEmptyValue("");
```

셋 다 내부적으로는 StringBuilder를 씁니다. 직접 쓰는 것보다 나은 이유는 성능이 아니라 **마지막 쉼표 처리 버그가 원천적으로 없다**는 점입니다.

`String.format`은 다른 물건입니다. 매번 포맷 문자열을 파싱하므로 루프 안에서 쓰기에는 비쌉니다. 사람이 읽을 메시지를 조립할 때만 씁니다.

## 8. 관련된 개념과 비교

| | 가변성 | 동기화 | 언제 |
|---|---|---|---|
| `String` + `+` | 불변 | — | 개수가 고정된 연결 |
| `StringBuilder` | 가변 | 없음 | 루프 누적. **기본 선택** |
| `StringBuffer` | 가변 | 모든 메서드 `synchronized` | 거의 없음 |
| `StringJoiner` / `String.join` | — | — | 구분자로 잇기 |

`StringBuffer`를 아직 쓰는 코드를 종종 봅니다. javadoc도 "가능하면 `StringBuilder`를 쓰라"고 명시합니다([StringBuilder javadoc](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/StringBuilder.html)). 그리고 **StringBuffer로 바꿔도 동시성 문제는 안 풀립니다.** `append` 한 번은 원자적이지만 "읽고 판단하고 쓰는" 여러 줄은 여전히 깨집니다.

참고로 문자열 조립을 언어 차원에서 개선하려던 String Templates는 JDK 21·22에서 프리뷰로 나왔다가 **JDK 23에서 제거됐습니다**([Inside Java Newscast #71](https://inside.java/2024/06/20/newscast-71/)). Java 26(2026-03-17 GA) 기준으로도 대체 문법은 없습니다. 당분간 `+`와 StringBuilder가 전부입니다.

## 9. 함정

### 9-1. StringBuilder를 루프 안에서 만듭니다

- **증상**: StringBuilder로 바꿨는데 빨라지지 않습니다.
- **원인**: 아래처럼 쓰면 §3-1의 `-XDstringConcat=inline` 바이트코드와 완전히 같습니다. 이름만 StringBuilder입니다.

```java
String result = "";
for (Order order : orders) {
    result = new StringBuilder(result).append(order.getId()).toString();   // ❌
}
```

- **해법**: 선언을 루프 밖으로 뺍니다. **"한 번 만들어 계속 append"가 되어야 의미가 있습니다.**

### 9-2. 로그 문자열은 레벨과 무관하게 만들어집니다

- **증상**: 운영 로그 레벨이 INFO인데 DEBUG 로그가 CPU를 먹습니다.
- **원인**: `log.debug("order=" + order + " items=" + items)`는 **인자를 넘기기 전에** 연결이 끝납니다. `toString()`까지 다 호출됩니다. DEBUG가 꺼져 있어도 비용은 이미 지불됐습니다.
- **해법**: 플레이스홀더를 씁니다. SLF4J는 레벨이 꺼져 있으면 포맷팅 자체를 건너뜁니다([SLF4J FAQ](https://www.slf4j.org/faq.html)).

```java
log.debug("order={} items={}", orderId, items.size());   // ✔️
```

### 9-3. `append(char)`인 줄 알았는데 `append(int)`입니다

- **증상**: 구분자 자리에 이상한 숫자가 찍힙니다.
- **원인**: `'A' + 1`은 Java에서 `int` 66입니다. `append(int)` 오버로드가 선택됩니다. 실제로 확인한 결과 `sb.append('A' + 1)`은 `"66"`, `sb.append((char) ('A' + 1))`은 `"B"`입니다.
- **해법**: 문자를 붙일 때는 계산식을 넣지 말고 문자 리터럴을 그대로 씁니다. `append(',')`가 `append(",")`보다 낫습니다. 길이 계산과 복사를 한 문자로 끝냅니다.

### 9-4. `sb.append(a + b)`

- **증상**: StringBuilder를 썼는데 임시 String이 계속 생깁니다.
- **원인**: 괄호 안이 먼저 평가돼 String 하나를 만들고, 그걸 다시 append합니다. 할당이 두 번입니다.
- **해법**: `sb.append(a).append(b)`로 쪼갭니다.

### 9-5. `null`이 `"null"`이 됩니다

- **증상**: DB에 `"null"`이라는 네 글자 문자열이 저장됩니다.
- **원인**: `+`와 `append(String)` 모두 null 참조를 `"null"` 네 글자로 변환합니다. 확인 결과 `new StringBuilder().append((String) null).length()`는 4입니다. NPE가 안 나므로 **조용히 데이터가 오염됩니다.**
- **해법**: null 가능성이 있는 값은 `Objects.requireNonNullElse(name, "")`처럼 명시적으로 처리하고 넘깁니다.

### 9-6. StringBuilder를 필드나 싱글톤 빈에 둡니다

- **증상**: 응답에 다른 사용자의 데이터 조각이 섞입니다. 재현이 안 됩니다.
- **원인**: `StringBuilder`는 스레드 안전하지 않습니다. 싱글톤 빈의 필드로 두면 모든 요청이 같은 배열에 씁니다.
- **해법**: **메서드 지역 변수로 만듭니다.** StringBuilder는 짧게 쓰고 버리는 객체입니다.

## 10. 참고자료

- [JEP 280: Indify String Concatenation](https://openjdk.org/jeps/280) — `+`가 `invokedynamic`으로 바뀐 이유
- [JEP 254: Compact Strings](https://openjdk.org/jeps/254) — String이 `byte[]`가 된 배경
- [StringBuilder (Java SE 25 API)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/StringBuilder.html)
- [StringConcatFactory (Java SE 25 API)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/invoke/StringConcatFactory.html)
- [SLF4J FAQ](https://www.slf4j.org/faq.html) — 파라미터화된 로깅
- 관련 문서: [day07-jvm-memory.md](day07-jvm-memory.md) — 큰 문자열이 힙 어디에 앉는가

<!-- TODO: 확인 필요 — OpenJDK JDK-8336856("hidden class 기반 string concat 전략 통합")이 정확히 어느 릴리스에 포함됐는지 확인하지 못했습니다(bugs.openjdk.org 접근 실패). 본문에서는 이 항목에 의존하는 서술을 넣지 않았고, §3~§5의 결론은 전략과 무관하게 성립합니다. -->

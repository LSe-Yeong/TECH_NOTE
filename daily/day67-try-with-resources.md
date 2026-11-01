# try-with-resources를 썼는데도 리소스가 새는 지점은 어디인가

> 이 문서가 답할 질문: **try-with-resources를 제대로 썼다고 생각하는데도 `Too many open files`나 커넥션 풀 고갈이 나는 지점은 어디이고, 왜 그런가?**
>
> 분류: 문제해결형(증상 → 원인 → 해법). 컴파일은 통과하고 코드도 교과서 모양인데 부하가 걸릴 때만 터지는 종류의 문제라, 여러 출처가 공통으로 보고하는 증상과 그 원인이 무엇인지를 찾는 관점으로 조사했습니다.
>
> 기준: Java 17(Temurin 17.0.21)에서 직접 컴파일·실행해 확인한 동작, 일부는 Java 21(Temurin 21.0.13)에서 확인했고 그 경우 본문에 명시합니다. 규격은 [JLS Java SE 21 §14.20.3](https://docs.oracle.com/javase/specs/jls/se21/html/jls-14.html#jls-14.20.3)을 인용합니다.

## 1. 핵심 개념 — 문법이 아니라 번역 규칙입니다

try-with-resources를 "`finally`를 안 써도 되는 문법"으로 알고 넘어가면 이 문서의 함정 전부를 밟습니다. 규격은 이걸 문법이 아니라 **번역(translation)** 으로 정의합니다. JLS §14.20.3.1이 자원 하나짜리 기본형을 이렇게 번역한다고 적어 뒀습니다.

```java
{
    final R Identifier = Expression;          // 자원 초기화
    Throwable #primaryExc = null;

    try {
        Block                                  // 내가 쓴 try 블록
    } catch (Throwable #t) {
        #primaryExc = #t;
        throw #t;
    } finally {
        if (Identifier != null) {              // ① null이면 close 안 함
            if (#primaryExc != null) {
                try {
                    Identifier.close();
                } catch (Throwable #suppressedExc) {
                    #primaryExc.addSuppressed(#suppressedExc);   // ② 덮어쓰지 않고 붙임
                }
            } else {
                Identifier.close();            // ③ 여기서 던진 예외는 그대로 전파
            }
        }
    }
}
```

**자원이 몇 개든, 이 블록이 자원 개수만큼 중첩됩니다.** 뒤에 나오는 모든 동작이 이 코드에서 그대로 유도됩니다. 바꿔 말하면, 이 번역 바깥에 있는 것은 아무것도 보호받지 못합니다. 리소스가 새는 지점은 전부 "내가 만든 자원이 `Identifier`에 들어오지 못한 경우"입니다.

> 이걸 손으로 쓰면 어떻게 망가지는지 보면 번역이 뭘 해주는지가 보입니다. 사람이 쓰는 `finally { reader.close(); }`에는 ②가 없습니다. try 블록에서 `IOException("parse failed")`가 올라오는 중에 `close()`가 또 던지면, **나중에 던진 close 예외가 원래 예외를 교체합니다.** 실패 원인은 `parse failed`인데 로그에는 `close failed`만 남습니다. 원인 추적이 영구히 불가능해집니다. try-with-resources가 사는 가장 큰 값은 닫아주는 것보다 이쪽입니다.

## 2. 번역에서 바로 나오는 네 가지 동작

자원 셋을 선언하고 가운데 것만 `close()`에서 던지게 만들어 Java 17에서 확인했습니다. 확인에 쓴 자원은 이것입니다.

```java
static class Tracked implements AutoCloseable {
    static final List<String> closed = new ArrayList<>();
    private final String name;
    private final boolean failOnClose;

    Tracked(String name, boolean failOnClose) {
        this.name = name;
        this.failOnClose = failOnClose;
    }

    @Override public void close() {
        closed.add(name);
        if (failOnClose) throw new IllegalStateException("close failed: " + name);
    }
}
```

```java
try (Tracked a = new Tracked("A", false);
     Tracked b = new Tracked("B", true);     // close()가 던짐
     Tracked c = new Tracked("C", false)) {
    System.out.println("body ran");
}
```

```
body ran
thrown      = close failed: B
close order = [C, B, A]
```

| 동작 | 규격 문장 | 확인 결과 |
|---|---|---|
| 역순으로 닫음 | "Resources are closed in the reverse order from that in which they were initialized." | `[C, B, A]` |
| 하나가 닫기에 실패해도 나머지를 닫음 | "An exception from the closing of one resource does not prevent the closing of other resources." | B가 던진 뒤에도 A가 닫혔습니다 |
| 초기화가 실패하면 그때까지 열린 것을 닫음 | "If a resource fails to initialize ... then all resources initialized so far ... are closed." | B 초기화 실패 시 `closed = [A]` |
| `null`은 닫지 않음 | "A resource is closed only if it initialized to a non-null value." | `try (Tracked a = null)` 에서 NPE 없음 |

세 번째가 중요합니다. **자원을 세미콜론으로 나란히 선언하는 것과, 생성자를 한 줄에 중첩하는 것은 안전성이 다릅니다.** 나란히 선언하면 각각이 번역 대상이 되고, 중첩하면 안쪽은 번역 대상이 아닙니다. 4-1이 그 얘기입니다.

Java 9부터는 이미 있는 변수를 자원으로 쓸 수도 있습니다([JEP 213](https://openjdk.org/jeps/213)). `final` 또는 사실상 final이어야 한다는 제약이 붙습니다.

```java
// Java 9+ — 새 변수를 선언하지 않고 기존 변수를 자원으로 지정합니다
Connection connection = dataSource.getConnection();   // 재할당하지 않으므로 사실상 final
try (connection) {
    connection.setAutoCommit(false);
    // ...
}
```

편해 보이지만 소유권이 흐려집니다. 남이 만들어 넘겨준 자원을 내가 닫아 버리는 코드가 이 문법으로 가장 쉽게 나옵니다. 받은 자원은 준 쪽이 닫습니다.

## 3. 예외 — 주 예외와 억제된 예외

try 블록과 `close()`가 둘 다 던지면 어느 쪽이 올라오는지가 정해져 있습니다.

```java
try (Tracked a = new Tracked("A", true)) {   // close()가 던짐
    throw new IOException("body failed");
}
```

```
primary         = java.io.IOException: body failed
suppressed      = [java.lang.IllegalStateException: close failed: A]
getMessage only -> body failed
```

규격은 억제 조건을 이렇게 적습니다. "Such an exception is suppressed if an exception was thrown previously by an initializer, the `try` block, or the closing of a resource." 즉 **먼저 던져진 쪽이 주 예외**이고, 나머지는 `addSuppressed`로 붙습니다.

반대로 try 블록이 정상 종료하면 `close()`의 예외가 **그대로 주 예외로 올라옵니다.** 위 번역의 ③입니다. 그래서 자원 선언 쪽에서 던진 예외도 같은 문장의 `catch`로 잡힙니다. 확장형(catch나 finally가 붙은 형태)은 전체를 한 번 더 감싸는 번역이라, "catch 절이 자원의 자동 초기화나 닫기에서 생긴 예외를 잡을 수 있게" 되어 있습니다.

```java
try (Tracked a = new Tracked("A", true)) {
    System.out.println("body ok");
} catch (IllegalStateException e) {
    System.out.println("caught in same statement: " + e.getMessage());
}
// body ok
// caught in same statement: close failed: A
```

마지막 줄의 `getMessage only -> body failed`가 운영에서 사람을 잡습니다. 억제된 예외는 `e.getMessage()`에도, `e.getCause()`에도 없습니다. `printStackTrace` 계열은 `Suppressed:` 줄을 찍어 주지만, 로그에 메시지만 조립해 넣는 코드에서는 통째로 사라집니다.

## 4. 리소스가 실제로 새는 네 지점

### 4-1. 생성자를 중첩한 자리 ⚠️

가장 흔하고, 가장 교과서처럼 생긴 누수입니다.

```java
// ❌ 자원이 하나로 보이지만 실제로는 둘입니다
try (GZIPInputStream in = new GZIPInputStream(new FileInputStream(file))) {
    // ...
}
```

`FileInputStream`은 이미 열렸는데, `GZIPInputStream` 생성자가 던지면 그 참조를 가진 변수가 아무 데도 없습니다. 번역의 `Identifier`에 대입되기 **전**이라 `finally`가 닫을 대상이 없습니다. 그리고 `GZIPInputStream` 생성자는 실제로 던집니다. 입력이 gzip이 아니면 헤더를 읽다가 `IOException`을 냅니다. gzip인 줄 알았던 업로드 파일이 평문이었다 같은 상황이 정확히 여기입니다.

평문 CSV를 50번 넘겨 본 결과입니다. `/proc/self/fd` 개수로 셌습니다.

```
ctor threw: leaked fds over 50 attempts = 50
```

50번 시도해서 50개가 그대로 남았습니다. `catch (IOException e)`로 로그까지 찍고 있어도 결과는 같습니다.

```java
// ✔️ 자원마다 변수를 하나씩 — 각각이 번역 대상이 됩니다
try (FileInputStream raw = new FileInputStream(file);
     GZIPInputStream in = new GZIPInputStream(raw)) {
    // ...
}
```

```
leaked fds over 50 attempts = 0
```

정상 경로에서는 `raw`가 두 번 닫힙니다. `GZIPInputStream.close()`가 안쪽을 닫고, 번역이 한 번 더 닫습니다. `Closeable`은 `close()`가 멱등일 것을 요구하므로 `java.io` 계열에서는 문제가 없습니다. 다만 `AutoCloseable`은 다릅니다. 이건 4-4의 함정으로 이어집니다.

### 4-2. 닫을 책임이 `Stream`으로 옮겨간 자리

`Files.lines`는 열린 파일을 쥔 스트림을 돌려줍니다. javadoc이 못 박아 뒀습니다. "The returned stream contains a reference to an open file. The file is closed by closing the stream." 그리고 API Note에 "This method **must** be used within a try-with-resources statement or similar control structure"라고 적혀 있습니다. `Files.list`, `Files.walk`, `Files.find`도 같은 문구를 달고 있습니다.

```java
// ❌ 스트림을 닫는 사람이 없습니다. 컴파일도, 테스트도 통과합니다
long paid = Files.lines(path).filter(line -> line.endsWith("PAID")).count();
```

```
leaked fds over 50 unclosed Files.lines = 50
```

이 누수가 특히 질이 나쁜 이유는 **간헐적**이라는 점입니다. `System.gc()`를 호출하면 누적된 fd가 회수됩니다. Cleaner가 뒤늦게 닫아 주기 때문입니다. 그래서 테스트와 한가한 시간대에는 증상이 없습니다.

fd 상한을 1024로 낮추고 같은 코드를 반복하면 이렇게 끝납니다.

```
baseline fds = 9
iteration 1452 -> java.nio.file.FileSystemException: /tmp/.../orders.csv: Too many open files
```

1024번이 아니라 1452번에서 터졌습니다. 중간에 GC가 일부를 회수했기 때문입니다. **GC 타이밍과 트래픽이 경합하는 구조**라, 재현이 안 되고 부하 테스트에서만 잡힙니다.

```java
// ✔️
try (Stream<String> lines = Files.lines(path)) {
    return lines.filter(line -> line.endsWith("PAID")).count();
}
```

### 4-3. 리소스를 try 블록 밖으로 내보낸 자리

누수의 거울상입니다. 안 닫혀서 새는 게 아니라, 닫힌 걸 쓰게 됩니다.

```java
// ❌ return 값을 만든 뒤 close가 실행됩니다
static Stream<String> readLines(Path path) throws IOException {
    try (Stream<String> lines = Files.lines(path)) {
        return lines;
    }
}
```

```
java.lang.IllegalStateException: stream has already been operated upon or closed
```

터지는 자리는 `readLines`가 아니라 **호출한 쪽의 터미널 연산**입니다. 스택트레이스에는 파일을 연 코드가 없습니다. `ResultSet`을 서비스 계층으로 반환하거나, 커넥션을 담은 람다를 비동기 실행기에 넘기는 코드가 같은 모양입니다.

해법은 두 가지뿐입니다. 자원 수명 안에서 **값으로 변환해서** 반환하거나(`.toList()`), 자원 자체를 반환하고 **닫을 책임까지 호출자에게 넘긴다고 명시**하는 것입니다. 후자를 고르면 그 메서드는 `try (var lines = readLines(path))`로만 쓰여야 합니다.

### 4-4. `close()`가 종료가 아니라 반납인 자리

풀에서 꺼낸 `Connection`의 `close()`는 커넥션을 끊지 않습니다. `javax.sql.PooledConnection` javadoc이 설명합니다. 애플리케이션이 `close()`를 호출하면 풀 매니저가 핸들을 비활성화하고 `PooledConnection`을 풀로 되돌리며, "the underlying physical connection is recycled rather than being closed"입니다.

그래서 **증상이 다르게 나타납니다.** fd는 늘지 않습니다. 커넥션을 반납하지 않으면 `getConnection()`이 `connectionTimeout`까지 기다리다 실패합니다. 장애 모양은 "파일 핸들 부족"이 아니라 "특정 API만 30초 뒤 500"입니다.

HikariCP의 `leakDetectionThreshold`는 이 상황을 **알려줄 뿐**입니다. 공식 README는 "a connection can be out of the pool before a message is logged indicating a possible connection leak"이라고 적습니다. 기본값은 `0`(비활성)이고, 켤 수 있는 최솟값은 `2000`(2초)입니다. 로그를 남기는 기능이지 회수하는 기능이 아닙니다.

## 5. `close()`가 성공해야 데이터가 저장됩니다

try-with-resources가 `close()`를 호출해 준 것과 데이터가 기록된 것은 다른 얘기입니다. 버퍼를 쓰는 writer는 `write()` 시점에 아무것도 안 보낼 수 있습니다. 실제로 내보내는 시점이 `close()` 안의 flush입니다.

디스크가 꽉 찬 상황을 재현해 확인했습니다. `FailingWriter`는 `write(char[], int, int)`에서 `IOException("No space left on device")`을 던지는 `Writer` 구현입니다.

```java
try (Writer w = new BufferedWriter(new FailingWriter())) {   // write에서 IOException
    w.write("1001,PAID");
    System.out.println("write() returned with no exception");
} catch (IOException e) {
    System.out.println("close() threw: " + e.getMessage());
}
```

```
write() returned with no exception
close() threw: No space left on device
chars actually delivered = 0
```

`write()`는 성공했다고 돌아왔고, 한 글자도 나가지 않았습니다. 실패는 `close()`에서만 보고됩니다. **쓰기 작업에서 `catch`가 close 예외를 삼키면 "성공했다고 응답했는데 파일이 비어 있는" 상태가 만들어집니다.** 읽기 전용 자원의 close 실패는 무시해도 되지만, 쓰기 자원의 close 실패는 작업 실패로 취급해야 합니다.

## 6. 함정

### 6-1. 억제된 예외가 로그에서 사라집니다

- **증상**: 로그에 `IOException: parse failed` 한 줄만 있습니다. 실제로는 그 뒤에 디스크 오류까지 있었는데 흔적이 없습니다.
- **원인**: `close()` 예외는 주 예외에 `addSuppressed`로 붙습니다. `e.getMessage()`, `e.getCause()`로는 절대 보이지 않습니다.
- **해법**: 로거에 예외 객체를 그대로 넘깁니다(`log.error("...", e)`). 문자열만 조립해 넣지 않습니다. 조사할 때는 `e.getSuppressed()`를 직접 확인합니다.

### 6-2. `ExecutorService`를 try-with-resources에 넣으면 블록 끝에서 멈춥니다 ⚠️

- **증상**: 비동기로 던지고 바로 응답하려던 코드가 작업이 끝날 때까지 블로킹됩니다.
- **원인**: `ExecutorService`가 `AutoCloseable`을 구현한 것은 **Java 19부터**입니다. `close()`는 "waits until all tasks have completed execution and the executor has terminated"이고 타임아웃이 없습니다. Java 21에서 1.5초짜리 작업 하나를 넣고 확인했더니 `close()`가 1544ms 뒤에 돌아왔습니다. Java 17에서는 아예 컴파일되지 않습니다(`ExecutorService cannot be converted to AutoCloseable`).
- **해법**: 요청 단위로 쓰고 버리는 실행기에만 씁니다. 공유 풀이라면 try-with-resources에 넣지 말고 빈 소멸 시점에 `shutdown()` + `awaitTermination(timeout, unit)`으로 상한을 둡니다. 인터럽트되면 `shutdownNow()`처럼 동작하지만 **실행 중인 작업이 끝날 때까지는 계속 기다립니다.**

### 6-3. `close()`는 멱등이 보장되지 않습니다

- **증상**: 4-1의 "자원마다 변수 하나" 패턴을 커스텀 자원에 적용했더니 close 로직이 두 번 돌아 카운터가 두 번 감소하거나 예외가 납니다.
- **원인**: `AutoCloseable` javadoc이 명시합니다. "unlike the `close` method of `Closeable`, this `close` method is **not** required to be idempotent." 멱등이 요구되는 쪽은 `Closeable`입니다.
- **해법**: `AutoCloseable`을 직접 구현할 때는 `closed` 플래그로 멱등하게 만듭니다. javadoc도 "strongly encouraged to make their `close` methods idempotent"라고 권고합니다.

### 6-4. `close()`에서 `InterruptedException`을 던지면 인터럽트가 사라집니다

- **증상**: 종료 신호를 보냈는데 스레드가 반응하지 않습니다.
- **원인**: close 예외는 주 예외가 있으면 억제됩니다. 억제된 `InterruptedException`은 아무도 보지 않고, 인터럽트 상태는 이미 지워진 상태입니다. `AutoCloseable` javadoc이 직접 경고합니다. "strongly advised to not have the `close` method throw `InterruptedException`."
- **해법**: 자원 `close()` 안에서 `InterruptedException`을 잡아 `Thread.currentThread().interrupt()`로 상태를 복원하고, 예외는 밖으로 던지지 않습니다.

### 6-5. `Statement`와 `ResultSet`을 커넥션이 닫아줄 거라고 믿습니다

- **증상**: 커넥션은 반납되는데 DB 쪽 커서나 서버 측 리소스가 오래 남습니다.
- **원인**: `Statement.close()` javadoc은 "It is generally good practice to release resources as soon as you are finished with them to avoid tying up database resources"라고만 합니다. 커넥션이 풀로 **반납**되는 구조에서는 물리 커넥션이 닫히지 않으므로, 그에 기대어 정리되기를 바랄 근거가 없습니다.
- **해법**: `Connection` → `Statement` → `ResultSet`을 한 try-with-resources에 세미콜론으로 나란히 선언합니다. 역순으로 닫히므로 순서가 맞습니다. `Statement`를 닫으면 그 시점의 `ResultSet`도 함께 닫힙니다("When a `Statement` object is closed, its current `ResultSet` object, if one exists, is also closed").

<!-- TODO: 확인 필요 — 6-5의 "커서가 서버에 남는 기간"은 DB 제품과 드라이버 구현에 따라 다릅니다. 구체적인 수치나 제품별 동작은 확인하지 못해 적지 않았습니다. -->

## 7. 참고자료

- [JLS Java SE 21 §14.20.3 try-with-resources](https://docs.oracle.com/javase/specs/jls/se21/html/jls-14.html#jls-14.20.3) — 번역 규칙, 닫는 순서, 억제 규칙의 출처
- [JEP 213: Milling Project Coin](https://openjdk.org/jeps/213) — Java 9의 사실상 final 변수 자원 지정
- [AutoCloseable javadoc (Java 21)](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/lang/AutoCloseable.html) — 멱등성과 `InterruptedException` 권고
- [Files javadoc (Java 21)](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/nio/file/Files.html) — `lines`·`list`·`walk`·`find`의 닫기 책임
- [ExecutorService javadoc (Java 21)](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/concurrent/ExecutorService.html) · [javax.sql.PooledConnection](https://docs.oracle.com/en/java/javase/21/docs/api/java.sql/javax/sql/PooledConnection.html) · [Statement](https://docs.oracle.com/en/java/javase/21/docs/api/java.sql/java/sql/Statement.html)
- [HikariCP README — leakDetectionThreshold](https://github.com/brettwooldridge/HikariCP) · [CodeQL java/input-resource-leak](https://codeql.github.com/codeql-query-help/java/java-input-resource-leak) — 중첩 생성자 누수를 잡는 정적 분석 규칙
- 관련 문서: `daily/day61-checked-unchecked.md` (예외를 감쌀 때 cause 보존), `daily/day55-stream-when-not.md` (스트림을 쓸지 말지), `daily/day31-stacktrace-reading.md` (억제된 예외가 찍히는 자리)

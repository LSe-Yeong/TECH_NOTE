# String 더하기가 루프 안에서 느린 이유

## 1. 핵심 개념: String, StringBuilder, StringBuffer란?

- `String`은 **불변(immutable)** 객체입니다. `+` 연산마다 기존 값을 바꾸지 않고 새 객체를 만듭니다.
- `StringBuilder`, `StringBuffer`는 **가변(mutable)** 객체입니다. 내부 버퍼에 직접 추가합니다.
- 셋 다 문자열을 다루지만, 불변이냐 가변이냐가 루프 안에서의 성능을 결정합니다.

> **"코드가 단순해 보여서 문제를 의심하지 않는 게 더 큰 문제입니다."** CSV 1000줄을 String `+`로 조립하면 수백 밀리초, 10000줄이면 수 초가 걸립니다.

## 2. 구조

- **String**: 불변. `result += item`은 기존 문자열을 수정하지 않고, 두 문자열을 복사한 새 String 객체를 만들고 `result`가 그걸 가리키게 합니다.
- **StringBuilder**: 가변, 동기화 없음. 내부 버퍼가 꽉 찰 때만 확장하고 `toString()` 호출 시 한 번만 String을 만듭니다.
- **StringBuffer**: 가변, 모든 메서드에 `synchronized`. `StringBuilder`의 스레드 안전 버전입니다.

### 2-1. 선택적 확장 지점

- `StringBuilder`/`StringBuffer`는 버퍼가 부족하면 자동으로 확장합니다. 이게 기본 동작입니다.
- `ensureCapacity(int minimumCapacity)`를 먼저 호출하면, 예상 크기만큼 버퍼를 미리 늘려서 확장 횟수를 줄일 수 있습니다. 필수는 아니고 선택적으로 튜닝하는 지점입니다.

```java
// 대량의 문자열을 조립할 걸 미리 안다면
StringBuilder sb = new StringBuilder();
sb.ensureCapacity(10_000);  // 이후 append에서 재할당 횟수를 줄임
```

## 3. 요청(루프) 처리 흐름

### 3-1. 클래스 구성

```java
// ❌ String — items 1000개면 새 객체 1000개
String result = "";
for (String item : items) {
    result += item + ", ";
}
```

```java
// ✅ StringBuilder — 같은 버퍼에 계속 추가
StringBuilder sb = new StringBuilder();
for (String item : items) {
    sb.append(item).append(", ");
}
String result = sb.toString();
```

### 3-2. 복사량 흐름

```
1회차: 0자 + item₁ = n₁자 복사
2회차: n₁자 + item₂ = n₁+n₂자 복사
3회차: n₁+n₂자 + item₃ = n₁+n₂+n₃자 복사
...
총 복사량(String +)   ≈ O(n²)
총 복사량(StringBuilder) ≈ O(n)
```

## 4. 특징

### 4-1. 사용 시기

- **String**: 값이 바뀌지 않는 문자열, 혹은 단순 연결 몇 개를 만들 때
- **StringBuilder**: 루프 안에서 문자열을 반복 조립할 때, 단일 스레드 환경
- **StringBuffer**: 여러 스레드가 같은 버퍼를 동시에 조립해야 할 때

### 4-2. 장점

- `StringBuilder`를 쓰면 총 복사량이 O(n)으로 줄어, 데이터가 커질수록 이득이 커집니다.
- 코드 형태(`append` 체이닝)가 조립 과정을 명확히 드러냅니다.

### 4-3. 단점 / 트레이드오프

- `StringBuilder`는 최종적으로 `toString()`을 한 번 더 호출해야 해서, 아주 짧은 연결(2~3개)에는 코드가 오히려 장황해집니다.
- `StringBuffer`는 항상 동기화 비용을 치릅니다. 단일 스레드에서는 낭비입니다.

## 5. 예제: 루프 안 문자열 조립

### 5-1. 클린하지 않은 코드 ❌

```java
// ❌ items 1000개면 1000개의 새 String이 만들어진다
String result = "";
for (String item : items) {
    result += item + ", ";
}
```

- 데이터가 늘어날수록 Young GC가 폭발하고, 원인을 찾다가 메모리 문제인 줄 알기 쉽습니다.

### 5-2. StringBuilder를 적용한 코드 ✔️

```java
StringBuilder sb = new StringBuilder();
for (String item : items) {
    sb.append(item).append(", ");
}
String result = sb.toString();
```

```java
// 스트림이라면 joining()이 더 자연스럽습니다
String result = items.stream()
        .collect(Collectors.joining(", "));
```

## 6. 불변 설계 원칙 준수

- `String`이 불변으로 설계된 이유는 **여러 곳에서 안전하게 공유**하기 위해서입니다. 값이 바뀌지 않는다는 게 보장되면 동기화 없이도 여러 스레드가 같은 `String`을 나눠 쓸 수 있습니다.
- `StringBuilder`/`StringBuffer`가 가변인 이유는 반대로 **누적 조립**이 목적이기 때문입니다. 조립이 끝나면 `toString()`으로 불변 `String`으로 바꿔서 그 다음부터는 다시 안전하게 공유합니다.

### 6-1. 원칙에 어긋나는 상상 ❌

```java
// String이 만약 가변이었다면 — 실제로는 불가능한 코드입니다
String shared = "hello";
someMethod(shared);
// someMethod 내부에서 shared의 내용을 직접 바꿔버렸다면?
// shared를 참조하던 다른 코드도 전부 영향을 받습니다
```

- 문자열이 가변이라면, 어딘가에 넘긴 문자열이 내가 모르는 사이 바뀔 수 있습니다. 공유가 곧 위험이 됩니다.

### 6-2. 실제 불변이라 안전한 코드 ✔️

```java
String shared = "hello";
someMethod(shared);
// String은 불변이므로 someMethod가 shared의 "내용"을 바꿀 방법이 없다
// shared는 항상 "hello"로 남아있음이 보장된다
```

- 조립이 필요한 구간만 `StringBuilder`로 가변 처리하고, 결과는 다시 불변 `String`으로 돌려받는 것이 Java의 설계 의도입니다.

## 7. 확장 지점(hook) 응용하기

### 7-1. 클린하지 않은 코드 ❌

```java
// ❌ 기본 용량(16자)으로 시작 — 10만 자를 append하면 내부적으로 여러 번 재할당된다
StringBuilder sb = new StringBuilder();
for (int i = 0; i < 100_000; i++) {
    sb.append(data.get(i));
}
```

### 7-2. `ensureCapacity()`를 적용한 코드 ✔️

```java
// ✅ 예상 크기를 미리 반영해서 재할당 횟수를 줄인다
StringBuilder sb = new StringBuilder();
sb.ensureCapacity(100_000);
for (int i = 0; i < 100_000; i++) {
    sb.append(data.get(i));
}
```

- 최종 크기를 대략 예측할 수 있다면 `ensureCapacity()`로 미리 힌트를 줘서 내부 배열 재할당 횟수를 줄일 수 있습니다.

## 8. 실무에서 찾아보는 String / StringBuilder

### 8-1. Java 표준

- `String.join(delimiter, elements)` — 구분자로 문자열들을 이어 붙이는 정적 메서드
- `StringJoiner` — 구분자, 접두사, 접미사를 지정해 문자열을 조립하는 클래스
- `Collectors.joining()` — 스트림 결과를 하나의 문자열로 모을 때

## 9. 관련된 개념과 비교

### 9-1. StringBuilder VS StringBuffer

**유사점**

- 둘 다 가변 버퍼를 유지하고, `append()`로 내용을 누적합니다. API가 거의 동일합니다.

**차이점**

- `StringBuffer`의 모든 메서드에는 `synchronized`가 붙어 있습니다. `StringBuilder`는 없습니다.
- 문자열 조립은 대부분 단일 스레드에서 이루어지므로 `StringBuffer`의 동기화 비용은 대개 낭비입니다.
- 멀티스레드 환경에서 문자열 버퍼를 공유해야 하는 경우가 아니라면 `StringBuilder`를 씁니다.

## 10. 함정

**"컴파일러가 자동으로 최적화해주니 괜찮다"**

- **증상**: 루프 안 `+=`를 써도 작은 데이터에서는 차이가 안 나서 문제를 모르고 지나갑니다.
- **원인**: 단순 표현식(`"a" + "b" + "c"`)은 컴파일러가 최적화하지만, 루프 축적 패턴은 하지 않습니다.
- **해법**: 문자열을 반복 누적하는 패턴이면 무조건 `StringBuilder` 또는 `joining()`을 씁니다.

**`StringBuffer`를 쓰는 레거시 코드**

- `StringBuffer`는 모든 메서드에 `synchronized`가 붙어 있습니다.
- 멀티스레드 환경에서 문자열을 공유해야 하는 경우가 아니라면 `StringBuilder`를 씁니다.

## 11. 참고자료

- [StringBuilder (Java 21 API)](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/lang/StringBuilder.html)
- `05-java/12-immutability.md` — 불변 객체가 동시성 문제의 절반을 없애는 원리

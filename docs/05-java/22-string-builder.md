---
title: String 더하기가 루프 안에서 느린 이유
category: java
level: beginner
tags: [java, string, stringbuilder, performance, immutable]
prereq: []
updated: 2026-07-19
verified: true
versions:
  java: "21"
sources:
  - https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/lang/StringBuilder.html
---

# String 더하기가 루프 안에서 느린 이유

> String은 불변입니다. `+` 연산마다 새 객체가 만들어지고, 루프 안에서는 그 비용이 O(n²)으로 쌓입니다.

## 이게 없으면 무슨 일이 벌어지는가

CSV 1000줄을 String `+`로 조립하면 수백 밀리초가 걸립니다. 10000줄이면 수 초입니다. GC 로그에 Young GC가 폭발하고, 원인을 찾다가 메모리 문제인 줄 압니다.

코드가 단순해 보여서 문제를 의심하지 않는 게 더 큰 문제입니다.

```java
// ❌ items 1000개면 1000개의 새 String이 만들어진다
String result = "";
for (String item : items) {
    result += item + ", ";
}
```

## 어떻게 동작하는가

`String`은 불변(immutable)입니다. `result += item`은 기존 문자열을 수정하지 않습니다. 두 문자열의 내용을 복사한 **새 String 객체**를 만들고 `result`가 그걸 가리키도록 합니다.

루프가 돌수록 복사해야 할 문자가 늘어납니다.

- 1회차: 0자 + item₁ = 복사 n₁자
- 2회차: n₁자 + item₂ = 복사 n₁+n₂자
- 3회차: n₁+n₂자 + item₃ = 복사 n₁+n₂+n₃자
- ...

총 복사량은 O(n²)입니다. 원소가 10배 늘면 시간이 100배 늘어납니다.

**컴파일러가 최적화해주지 않는가?**

단순 연결 표현식은 최적화합니다.

```java
// ✅ 이건 컴파일러가 하나의 효율적인 연산으로 처리합니다
String s = "Hello" + ", " + name + "!";
```

그러나 **루프 안 축적 패턴은 최적화하지 않습니다.** 컴파일러는 루프를 몇 번 돌지 모르고, 각 반복이 이전 결과에 누적된다는 걸 정적으로 분석하지 않습니다. 루프 안의 `+=`는 매 반복마다 새 String을 만듭니다.

## 실무에서는

**루프 안에서 문자열을 조립할 때는 `StringBuilder`를 씁니다.**

```java
// ✅ 내부 버퍼에 추가하고, 끝에 한 번만 String으로 변환
StringBuilder sb = new StringBuilder();
for (String item : items) {
    sb.append(item).append(", ");
}
String result = sb.toString();
```

`StringBuilder`는 내부에 가변 버퍼를 유지합니다. `append()`는 버퍼가 꽉 찰 때만 확장하고, `toString()`을 호출할 때 한 번만 String 객체를 만듭니다. 총 복사량이 O(n)입니다.

스트림으로 처리한다면 `Collectors.joining()`이 더 자연스럽습니다.

```java
// ✅ 스트림에서는 joining() 사용
String result = items.stream()
        .collect(Collectors.joining(", "));
```

## 함정

**"컴파일러가 자동으로 최적화해주니 괜찮다"**

- **증상**: 루프 안 `+=`를 써도 작은 데이터에서는 차이가 안 나서 문제를 모르고 지나갑니다.
- **원인**: 단순 표현식(`"a" + "b" + "c"`)은 컴파일러가 최적화하지만, 루프 축적 패턴은 하지 않습니다. 데이터가 수천 건이 되는 순간 차이가 드러납니다.
- **해법**: 문자열을 반복 누적하는 패턴이면 무조건 `StringBuilder` 또는 `joining()`을 씁니다.

**`StringBuffer`를 쓰는 레거시 코드**

- `StringBuffer`는 `StringBuilder`의 스레드 안전 버전입니다. 모든 메서드에 `synchronized`가 붙어 있습니다.
- 문자열 조립은 대부분 단일 스레드에서 이루어지므로 `StringBuffer`의 동기화 비용은 낭비입니다.
- 멀티스레드 환경에서 문자열을 공유해야 하는 경우가 아니라면 `StringBuilder`를 씁니다.

## 이것만은

1. `String +`는 루프 안에서 O(n²)입니다. 컴파일러는 루프 축적 패턴을 최적화하지 않습니다.
2. 루프 안에서 문자열을 모은다면 `StringBuilder.append()`, 스트림이라면 `Collectors.joining()`을 씁니다.
3. `StringBuffer`는 멀티스레드 공유 목적이 아니면 쓸 이유가 없습니다.

## 더 읽기

- [StringBuilder (Java 21 API)](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/lang/StringBuilder.html)
- `05-java/12-immutability.md` — 불변 객체가 동시성 문제의 절반을 없애는 원리

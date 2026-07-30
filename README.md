# 실무 백엔드 기술 노트

> 실무에서 마주치는 두 가지 질문에 답하는 문서 모음.
>
> - **문제 해결** — 이 문제가 나왔을 때 원인과 해법은 무엇인가
> - **기술 이해** — 이 기술은 어떤 문제를 풀기 위해 존재하고, 언제 쓰는가
>
> 대상 독자: 신입 개발자 (0~1년차)

---

## 05. Java

| 문서 | 한 줄 요약 |
|---|---|
| [JVM 위에서 실행된다는 것](docs/05-java/00-jvm-why.md) | 워밍업·GC·Stop-the-World가 왜 존재하는가 |
| [JVM 메모리: 힙, 스택, 메타스페이스](docs/05-java/01-jvm-memory.md) | OOM 에러 메시지로 어느 영역 문제인지 즉시 파악하기 |
| [String 더하기가 루프 안에서 느린 이유](docs/05-java/22-string-builder.md) | `+` 연산이 O(n²)이 되는 구조와 StringBuilder를 써야 하는 시점 |
| [List, Set, Map — 언제 무엇을 쓰는가](docs/05-java/23-collections-choice.md) | 자료구조 선택이 성능을 결정하는 이유와 구현체별 선택 기준 |

## 06. Spring

| 문서 | 한 줄 요약 |
|---|---|
| [HTTP 요청 한 개가 내 코드에 닿기까지](docs/06-spring/00-spring-request-flow.md) | Filter · Interceptor · AOP 중 어디에 로직을 두어야 하는가 |
| [의존성 주입은 무슨 문제를 푸는가](docs/06-spring/01-di-why.md) | `new`로 직접 만들 때 생기는 문제와 생성자 주입을 써야 하는 이유 |

---

## 라이선스

- 문서: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- 코드: MIT

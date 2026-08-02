# 실무 백엔드 기술 노트

> 실무에서 마주치는 두 가지 질문에 답하는 문서 모음.
>
> - **문제 해결** — 이 문제가 나왔을 때 원인과 해법은 무엇인가
> - **기술 이해** — 이 기술은 어떤 문제를 풀기 위해 존재하고, 언제 쓰는가
>
> 대상 독자: 신입 개발자 (0~1년차)

---

## Daily

| 일차 | 문서 | 한 줄 요약 |
|---:|---|---|
| 1 | [HTTP 요청 한 개가 내 코드에 닿기까지](daily/day01-spring-request-flow.md) | Filter · Interceptor · AOP 중 어디에 로직을 두어야 하는가 |
| 1 | [의존성 주입은 무슨 문제를 푸는가](daily/day01-di-why.md) | `new`로 직접 만들 때 생기는 문제와 생성자 주입을 써야 하는 이유 |
| 2 | [JVM 위에서 실행된다는 것](daily/day02-jvm-why.md) | 워밍업·GC·Stop-the-World가 왜 존재하는가 |
| 2 | [JVM 메모리: 힙, 스택, 메타스페이스](daily/day02-jvm-memory.md) | OOM 에러 메시지로 어느 영역 문제인지 즉시 파악하기 |
| 3 | [String 더하기가 루프 안에서 느린 이유](daily/day03-string-builder.md) | `+` 연산이 O(n²)이 되는 구조와 StringBuilder를 써야 하는 시점 |
| 3 | [List, Set, Map — 언제 무엇을 쓰는가](daily/day03-collections-choice.md) | 자료구조 선택이 성능을 결정하는 이유와 구현체별 선택 기준 |
| 4 | [INNER, LEFT, RIGHT JOIN이 실제로 하는 일](daily/day04-join-types.md) | 같은 두 테이블인데 JOIN 종류에 따라 결과 집합이 달라지는 이유 |
| 4 | [NULL이 만드는 예상치 못한 버그](daily/day04-null-traps.md) | `NOT IN`이 조용히 0행을 반환하는 이유와 3치 논리 |
| 5 | [인덱스 없는 테이블은 왜 느린가](daily/day05-why-index.md) | 풀 테이블 스캔과 인덱스 스캔의 비용 차이, 그리고 인덱스가 오히려 손해인 경우 |
| 5 | [인덱스는 어떻게 빠른가](daily/day05-btree-index.md) | B+Tree 구조와 세컨더리 인덱스가 두 번 순회하는 이유 |
| 6 | [DTO와 Entity를 분리해야 하는 이유](daily/day06-dto-vs-entity.md) | Entity를 API에 그대로 노출하면 생기는 Mass Assignment, 무한 재귀, LazyInitializationException |
| 6 | [서비스 계층의 책임은 어디까지인가](daily/day06-service-layer-design.md) | Controller와 Repository 사이에서 Service가 조율만 하고 판단은 도메인에 맡겨야 하는 이유 |

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
| 1 | [JVM 위에서 실행된다는 게 개발자에게 주는 것](daily/day01-jvm-why.md) | 런타임 최적화·GC·관측성을 얻는 대신 워밍업과 메모리 오버헤드를 지불한다 |
| 2 | [HTTP 요청 한 개가 컨트롤러까지 오는 과정](daily/day02-spring-request-flow.md) | 필터 → DispatcherServlet → HandlerMapping → 컨트롤러. 이 경계가 예외 처리 범위를 결정한다 |
| 3 | [에러 응답 포맷을 통일해야 하는 이유](daily/day03-api-error-format.md) | RFC 9457로 봉투를 맞춰도 설계는 남는다. 클라이언트가 분기할 안정적인 식별자를 주는 게 본질 |
| 4 | [네트워크를 왜 나누는가](daily/day04-vpc-subnet.md) | 퍼블릭/프라이빗은 서브넷의 속성이 아니라 라우팅의 결과. 라우팅·AZ·역할 세 축으로 나눈다 |
| 5 | [INNER·LEFT·RIGHT JOIN이 실제로 하는 일](daily/day05-join-types.md) | 짝짓고 → 낙오된 행을 되살리는 3단계 연산. ON과 WHERE의 차이, 그리고 집계를 부풀리는 팬아웃 |
| 6 | [환경변수로 설정을 관리하는 법](daily/day06-env-variable.md) | 저장소엔 구조, 배포엔 값. 필수 설정에 기본값을 주지 않는 게 가장 값싼 방어. 시크릿은 경계 밖 |
| 7 | [힙, 스택, 메타스페이스 — JVM 메모리는 왜 나뉘어 있는가](daily/day07-jvm-memory.md) | 나눈 기준은 공유 범위와 수명. `-Xmx`는 힙만 제한하고, OOM 메시지 뒷부분이 어느 영역인지 알려준다 |
| 8 | [의존성 주입은 무슨 문제를 푸는가](daily/day08-di-why.md) | `new`를 줄이는 기능이 아니라 "고르는 결정"을 바깥으로 옮기는 것. 생성자 주입이 기본이고, 순환 참조는 설계 신호 |
| 9 | [실무 REST의 현실 — 무엇을 지키고 무엇을 버리는가](daily/day09-rest-api-design.md) | 순수성 논쟁 대신 재시도 안전성·오류 판별 가능성·변경 내성으로 설계한다. 멱등성은 인프라가 실제로 따르는 계약 |
| 10 | [public/private 서브넷의 실체는 라우팅 테이블입니다](daily/day10-route-table.md) | 퍼블릭이라는 리소스 타입은 없다. IGW 라우트 한 줄이 실체이고, 우선순위는 최장 프리픽스 → 정적 → 프리픽스 리스트 → 전파 순 |
| 11 | [NULL이 만드는 예상치 못한 버그](daily/day11-null-traps.md) | NULL은 값이 아니라 "모름"이고, WHERE는 UNKNOWN을 버린다. NOT IN·LEFT JOIN·UNIQUE·CHECK가 조용히 무력화되는 지점 |
| 12 | [API 문서 자동화하기](daily/day12-swagger-api-docs.md) | 자동 생성은 "형태"만 보증하고 "의미"는 사람 몫. 목표는 Swagger UI가 아니라 CI에 넣는 OpenAPI 스펙 파일 |
| 13 | [String 더하기가 루프 안에서 느린 이유](daily/day13-string-builder.md) | 불변 객체를 누적하면 O(n²). 반대로 개수가 고정된 연결은 `+`가 수동 StringBuilder보다 빠르다 |
| 14 | [DTO와 Entity를 분리해야 하는 이유](daily/day14-dto-vs-entity.md) | 분리 근거는 계층이 아니라 변경 이유. 엔티티를 경계에 두면 스키마 변경이 곧 API 계약 변경이 되고, 요청 쪽에선 대량 할당이 열린다 |
| 15 | [커서 기반 페이지네이션이 필요한 순간](daily/day15-pagination-api.md) | 위치를 개수로 쓰느냐 값으로 쓰느냐의 차이. 커서는 성능과 정합성을 사는 대신 페이지 번호·총건수·정렬 변경을 판다 |
| 16 | [들어오는 문과 나가는 문은 다릅니다 — IGW와 NAT Gateway](daily/day16-igw-natgw.md) | IGW는 방향을 못 나누고 NAT는 나눈다. 무료인 IGW 대신 돈 내고 NAT를 쓰는 이유가 그것. 55,000 연결 한도와 350초 타임아웃이 대가 |

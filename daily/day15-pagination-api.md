# 커서 기반 페이지네이션이 필요한 순간

> 이 문서가 답할 질문: **`page`/`offset` 방식은 정확히 어디서 무너지고, 커서 기반은 그걸 무엇과 맞바꿔서 푸는가?**
>
> 분류: 선택형(A vs B). 두 방식이 각각 무엇을 보장하고 무엇을 포기하는지가 핵심입니다.
>
> 기준: MySQL 8.4 · Spring Data 3.1 이후(Scroll API) 기준으로 서술합니다.

## 1. 핵심 개념 — "위치"를 무엇으로 지정하는가

두 방식의 차이는 페이지를 어떻게 세는가가 아니라, **다음 페이지의 시작점을 무엇으로 표현하는가**입니다.

- **오프셋 방식**: "앞에서부터 100개 건너뛴 자리". 위치를 **개수**로 표현합니다.
- **커서 방식**: "정렬 키가 이 값인 행 다음 자리". 위치를 **값**으로 표현합니다.

개수는 상대적이고 값은 절대적입니다. 이 한 줄에서 나머지가 전부 파생됩니다.

> 게시판에 `?page=2&size=20`을 붙였습니다. 잘 돕니다. 그런데 사용자가 1페이지를 보는 사이에 새 글이 3개 올라옵니다. 2페이지를 누르면 방금 1페이지에서 본 글 3개가 **또** 보입니다. 반대로 글이 지워졌다면 그 자리에 있던 글은 **아무도 못 보고 넘어갑니다.** 버그 리포트는 "가끔 글이 중복돼요"로 들어오고, 재현이 안 됩니다. 여기에 더해 `page=5000`을 요청하는 크롤러가 붙는 순간 DB CPU가 튀는데, 슬로우 쿼리 로그에는 인덱스를 잘 타는 평범한 쿼리로 찍힙니다. **오프셋 페이지네이션이 깨지는 방식은 대부분 조용합니다.**

## 2. 구조 — 왜 그렇게 되는가

### 2-1. OFFSET은 건너뛰는 게 아니라 읽고 버립니다

`LIMIT 20 OFFSET 100000`을 DB가 "10만 번째로 점프"로 처리하지 않습니다. 앞의 10만 행을 **실제로 읽어서 정렬 순서대로 세운 다음 버립니다**([Use The Index, Luke — No Offset](https://use-the-index-luke.com/no-offset)).

그래서 비용이 페이지 깊이에 비례해 늘어납니다. 1페이지는 20행, 5000페이지는 100,020행을 만집니다. 같은 엔드포인트인데 뒷페이지만 느립니다.

커서 방식은 `WHERE created_at < ?` 같은 **범위 조건**이라 인덱스에서 시작 위치를 곧바로 찾습니다. 몇 번째 페이지든 읽는 행 수가 `LIMIT`만큼으로 일정합니다.

### 2-2. 성능보다 먼저 봐야 할 건 정합성입니다

오프셋 방식의 진짜 문제는 느린 게 아닙니다. **틀린 결과를 주는 것**입니다.

목록이 최신순이고 페이지 요청 사이에 새 글 1개가 들어오면, 모든 행이 한 칸씩 밀립니다. `OFFSET 20`은 밀리기 전 기준의 20번째가 아니라 밀린 후 기준의 20번째를 가리킵니다. 결과는 **중복**입니다. 삭제가 일어나면 반대로 **누락**입니다.

| | 페이지 사이에 삽입 | 페이지 사이에 삭제 |
|---|---|---|
| 오프셋 | 이미 본 행이 다시 나옴 | 안 본 행이 건너뛰어짐 |
| 커서 | 영향 없음(커서보다 최신이면 애초에 범위 밖) | 영향 없음 |

무한 스크롤 UI에서 이건 치명적입니다. 같은 카드가 두 번 그려지고, React에서는 key 중복 경고까지 같이 납니다. **쓰기가 활발한 목록일수록 오프셋은 성능이 아니라 정확성 때문에 못 씁니다.**

### 2-3. 커서에는 반드시 유일성이 있어야 합니다

`created_at` 하나만으로 커서를 만들면 같은 초에 만들어진 행들에서 다시 중복·누락이 생깁니다. 정렬 키가 유일하지 않으면 "이 값 다음"이라는 표현이 애매해지기 때문입니다.

해법은 **정렬 키 뒤에 유일한 컬럼(보통 PK)을 붙여 tie-breaker로 쓰는 것**입니다. 정렬도 `ORDER BY created_at DESC, id DESC`로 같이 바꿉니다. 커서는 이 두 값을 함께 담습니다.

## 3. 흐름

### 3-1. 코드로 보는 구성

```sql
-- ❌ 오프셋: 앞의 100,000행을 읽고 버립니다
SELECT id, title, created_at
FROM article
WHERE board_id = 10
ORDER BY created_at DESC, id DESC
LIMIT 20 OFFSET 100000;
```

```sql
-- ✅ 커서: (created_at, id)가 커서보다 "뒤"인 지점부터 20행
SELECT id, title, created_at
FROM article
WHERE board_id = 10
  AND (created_at < ?          -- 커서의 created_at
       OR (created_at = ? AND id < ?))   -- 동률이면 id로 가릅니다
ORDER BY created_at DESC, id DESC
LIMIT 20;
```

인덱스는 `(board_id, created_at, id)`로 둡니다. 필터 컬럼이 앞, 정렬 컬럼이 뒤입니다. 이 순서가 아니면 커서 방식이어도 정렬 때문에 파일소트가 걸립니다.

`WHERE (created_at, id) < (?, ?)` 처럼 행 생성자(row constructor)로 짧게 쓸 수도 있습니다. 다만 MySQL에서는 **다른 조건과 `AND`로 섞이면 인덱스를 덜 쓰는 경우가 있습니다**. MySQL 매뉴얼도 `c1 = 1 AND (c2, c3) > (1, 1)` 형태에서 인덱스가 `c1`까지만 쓰이는 예를 들며, 위처럼 `OR`로 풀어쓴 형태를 권합니다([MySQL 8.4 — Row Constructor Expression Optimization](https://dev.mysql.com/doc/refman/8.4/en/row-constructor-optimization.html)). 짧은 쪽을 쓰고 싶다면 `EXPLAIN`의 `key_len`을 반드시 확인합니다.

### 3-2. 실행 흐름

```
[오프셋] 클라이언트 → page=5000
        → 인덱스 스캔 시작 → 100,000행 읽음 → 전부 버림 → 20행 반환
        → 다음 페이지는 100,020행부터 다시 (앞부분을 매번 다시 읽음)

[커서]   클라이언트 → after=eyJ0IjoiMjAyNi0wOC0xOVQxMDoxMjozMCIsImkiOjkxNDJ9
        → 커서 디코드 → 인덱스에서 해당 지점 탐색 → 20행 읽음 → 반환
        → 응답에 다음 커서 동봉 (읽는 행 수는 항상 20)
```

### 3-3. "다음 페이지가 있는가"를 아는 법

커서 방식은 전체 개수를 모릅니다. 그래서 `hasNext`를 따로 계산해야 하는데, `COUNT(*)`를 도로 날리면 오프셋을 버린 의미가 없습니다.

**`limit + 1`개를 요청합니다.** 21개가 오면 다음 페이지가 있다는 뜻이고, 20개만 잘라서 응답합니다.

```java
List<Article> rows = articleRepository.findSlice(boardId, cursor, PageRequest.ofSize(21));
boolean hasNext = rows.size() > 20;
List<Article> content = hasNext ? rows.subList(0, 20) : rows;
```

Spring Data의 `Slice`가 내부적으로 쓰는 방식도 이것입니다. `Page`와 달리 `Slice`는 count 쿼리를 날리지 않습니다.

## 4. 특징

### 4-1. 커서가 포기하는 것

여기가 선택의 핵심입니다. 커서는 공짜가 아니라 **기능을 팔아서 성능과 정합성을 삽니다.**

- **페이지 번호가 없습니다.** "7페이지로 이동"이 불가능합니다. 앞/뒤 이동만 됩니다.
- **전체 개수를 안 줍니다.** "총 1,234건"을 표시하려면 별도 카운트가 필요하고, 그 카운트는 결국 무겁습니다.
- **정렬 기준을 바꾸면 커서가 무효입니다.** 커서는 특정 정렬 순서 위의 좌표이기 때문입니다. 정렬을 바꾸면 처음부터 다시 시작해야 합니다.
- **임의 필터 조합과 함께 쓰기 까다롭습니다.** 필터가 바뀌면 같은 커서가 다른 위치를 의미합니다.

### 4-2. 그래서 언제 무엇을 쓰는가

| 상황 | 선택 |
|---|---|
| 무한 스크롤, 피드, 알림 목록 | 커서 |
| 데이터 전량 동기화(배치, ETL) | 커서 |
| 외부 공개 API의 목록 조회 | 커서 |
| 관리자 화면 — 페이지 번호와 총건수가 요구사항 | 오프셋 |
| 전체가 수천 건 이하이고 쓰기가 드묾 | 오프셋 (문제 자체가 안 생깁니다) |

**요구사항에 "총 1,234건 중 3페이지"가 있으면 커서는 애초에 후보가 아닙니다.** 기술로 못 이기는 요구사항입니다. 반대로 요구사항이 "더 보기" 버튼 하나면 오프셋을 쓸 이유가 없습니다.

## 5. 예제

### 5-1. 클린하지 않은 코드 ❌

```java
@GetMapping("/boards/{boardId}/articles")
public Page<ArticleResponse> list(
        @PathVariable Long boardId,
        @PageableDefault(size = 20) Pageable pageable) {
    return articleRepository.findByBoardId(boardId, pageable)
            .map(ArticleResponse::from);
}
```

돌아가지만 세 가지가 열려 있습니다.

- `Page`는 매 요청마다 `COUNT(*)` 쿼리를 함께 날립니다. 목록보다 카운트가 더 느린 경우가 흔합니다.
- `size`에 상한이 없습니다. `?size=100000` 한 방으로 힙을 밀 수 있습니다.
- `page`에 상한이 없습니다. 깊은 페이지 요청이 그대로 DB로 갑니다.

### 5-2. 개선한 코드 ✔️

```java
public record CursorPage<T>(List<T> content, String nextCursor, boolean hasNext) {
    public static <T> CursorPage<T> of(List<T> rows, int size, Function<T, String> cursorOf) {
        boolean hasNext = rows.size() > size;
        List<T> content = hasNext ? rows.subList(0, size) : rows;
        String nextCursor = hasNext ? cursorOf.apply(content.get(content.size() - 1)) : null;
        return new CursorPage<>(content, nextCursor, hasNext);
    }
}
```

```java
@GetMapping("/boards/{boardId}/articles")
public CursorPage<ArticleResponse> list(
        @PathVariable Long boardId,
        @RequestParam(required = false) String cursor,
        @RequestParam(defaultValue = "20") int size) {

    int limit = Math.min(size, 100);   // 상한을 서버가 정합니다
    ArticleCursor decoded = ArticleCursor.decode(cursor);   // null이면 첫 페이지

    List<Article> rows = articleRepository.findNextSlice(boardId, decoded, limit + 1);

    return CursorPage.of(
            rows.stream().map(ArticleResponse::from).toList(),
            limit,
            response -> ArticleCursor.encode(response.createdAt(), response.id()));
}
```

`size`를 서버가 잘라내는 부분이 중요합니다. Stripe도 `limit`을 1~100으로 제한하고 기본값을 10으로 둡니다([Stripe API — Pagination](https://docs.stripe.com/api/pagination)). **클라이언트가 보낸 페이지 크기를 그대로 믿는 API는 DoS 입구입니다.**

### 5-3. Spring Data Scroll API로 쓰기

직접 SQL을 쓰지 않아도 됩니다. Spring Data 3.1부터 `Window`와 `ScrollPosition`이 있습니다.

```java
public interface ArticleRepository extends Repository<Article, Long> {
    Window<Article> findFirst20ByBoardIdOrderByCreatedAtDescIdDesc(
            Long boardId, ScrollPosition position);
}
```

```java
Window<Article> window = articleRepository
        .findFirst20ByBoardIdOrderByCreatedAtDescIdDesc(boardId, ScrollPosition.keyset());

while (window.hasNext()) {
    window = articleRepository.findFirst20ByBoardIdOrderByCreatedAtDescIdDesc(
            boardId, window.positionAt(window.size() - 1));
}
```

`ScrollPosition.offset()`으로 바꾸면 같은 메서드가 오프셋 방식으로 동작합니다. 구현을 갈아끼울 수 있다는 게 이 API의 장점입니다.

제약이 있습니다. **키셋 필터링에 쓰이는 정렬 속성은 `null`이 아니어야 하고**, 정렬 속성이 조회 결과에 포함돼 있어야 합니다. 프로젝션을 쓸 때 정렬 컬럼을 빼면 키셋 추출이 실패합니다([Spring Data — Scrolling](https://docs.spring.io/spring-data/jpa/reference/data-commons/repositories/scrolling.html)). 정렬 순서에는 프레임워크가 기본 키를 자동으로 덧붙여 유일성을 맞춥니다.

HTTP 커서로 내보내려면 `KeysetScrollPosition.getKeys()`로 `Map<String, Object>`를 꺼내 인코딩하고, 돌아온 값은 `ScrollPosition.forward(Map)`으로 복원합니다.

## 6. 커서는 왜 불투명해야 하는가

커서를 `?after=2026-08-19T10:12:30_9142`처럼 읽히는 형태로 내보내면, 클라이언트가 **그 형식을 파싱하고 직접 조립하기 시작합니다.** 그 순간 커서 포맷이 API 계약이 되어 정렬 키를 바꿀 수 없게 됩니다.

그래서 공개 API는 커서를 Base64 같은 불투명한 문자열로 감쌉니다. Google API 설계 가이드는 페이지 토큰이 **URL-safe하면서 사용자가 파싱할 수 없어야 한다**고 규정하고, 토큰에 만료를 둘 수 있다고 명시합니다([Google AIP-158 Pagination](https://google.aip.dev/158)). Slack도 커서에 만료가 있으니 오래 보관하지 말라고 안내합니다([Slack — Pagination](https://docs.slack.dev/apis/web-api/pagination/)).

Base64는 암호화가 아닙니다. 감추는 게 목적이 아니라 **"이걸 열어보지 말라"는 신호**가 목적입니다. 커서에 다른 사용자의 데이터로 넘어갈 수 있는 값이 들어간다면 서명이나 서버 측 저장이 별도로 필요합니다.

응답에서 마지막 페이지를 알리는 방법도 규약으로 정합니다. Slack 문서는 **결과 개수가 `limit`보다 적다고 마지막 페이지로 판단하지 말고 `next_cursor`가 비었는지로 판단하라**고 못 박습니다. 서버는 필터링 때문에 요청보다 적은 개수를 돌려줄 수 있기 때문입니다.

## 7. 오프셋을 꼭 써야 한다면

페이지 번호가 요구사항이면 오프셋을 버릴 수 없습니다. 그럴 때 쓰는 완충 장치가 둘 있습니다.

**첫째, 깊이에 상한을 둡니다.** Elasticsearch는 `index.max_result_window`로 `from + size`를 기본 10,000으로 제한하고, 이 값을 올리는 대신 `search_after`를 쓰라고 안내합니다([Elasticsearch — Index modules](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules)). GitHub 검색 API도 검색당 최대 1,000건까지만 돌려줍니다([GitHub REST — Search](https://docs.github.com/en/rest/search/search)). **상한을 두는 건 기능 축소가 아니라 정상적인 설계 선택입니다.** 실제로 500페이지를 넘겨보는 사람은 크롤러뿐입니다.

**둘째, 지연 조인(deferred join)입니다.** 인덱스만으로 PK 목록을 먼저 뽑고, 그 PK로만 본문을 가져옵니다.

```sql
SELECT a.*
FROM article a
JOIN (
    SELECT id
    FROM article
    WHERE board_id = 10
    ORDER BY created_at DESC, id DESC
    LIMIT 20 OFFSET 100000
) AS page USING (id)
ORDER BY a.created_at DESC, a.id DESC;
```

버려질 10만 행에 대해 **본문 컬럼을 읽지 않는 것**이 이득의 원천입니다. 커버링 인덱스가 받쳐줄 때 효과가 큽니다. 한 사례에서는 실행 시간 1,283ms에 검사 행 500,010행이던 쿼리가 419ms에 10행으로 줄었습니다([hackmysql — Deferred Join: A Deep Dive](https://hackmysql.com/deferred-join-deep-dive/)).

다만 만능이 아닙니다. 같은 글은 **서브쿼리가 바깥 쿼리의 행 접근을 줄여주지 못하면 오히려 손해**라고 명시합니다. 오프셋에 비례하는 비용 구조 자체는 그대로 남습니다. 상수를 줄일 뿐 기울기를 없애지는 못합니다.

## 8. 함정

### 8-1. 정렬 키에 tie-breaker가 없습니다

- **증상**: 커서로 바꿨는데도 스크롤할 때 가끔 항목이 중복되거나 빠집니다.
- **원인**: `ORDER BY created_at DESC`만 있고 유일 키가 없습니다. 같은 `created_at` 값을 가진 행들 사이의 순서가 실행마다 달라집니다.
- **해법**: `ORDER BY created_at DESC, id DESC`로 바꾸고 커서에 두 값을 모두 담습니다. 인덱스도 `(created_at, id)`로 맞춥니다.

### 8-2. 커서에 `null`이 들어갑니다

- **증상**: 특정 지점부터 목록이 갑자기 비거나 처음으로 되돌아갑니다.
- **원인**: 정렬 컬럼이 nullable입니다. `null`은 비교 연산에서 `UNKNOWN`이라 `WHERE created_at < NULL`이 아무것도 통과시키지 않습니다. Spring Data도 키셋 속성이 non-null이어야 한다고 문서에 못 박았습니다.
- **해법**: 정렬 키는 `NOT NULL` 컬럼만 씁니다. 불가능하면 `COALESCE`로 정규화한 값을 별도 컬럼에 두고 그걸 정렬 키로 삼습니다. `NULLS LAST` 같은 옵션만으로는 커서 조건식이 해결되지 않습니다.

### 8-3. 정렬을 바꿀 수 있게 열어두고 커서는 그대로 받습니다

- **증상**: 정렬을 "인기순"으로 바꾼 뒤 더 보기를 누르면 엉뚱한 데이터가 나옵니다.
- **원인**: 커서는 특정 정렬 순서 위의 좌표입니다. 정렬이 바뀌면 좌표계가 바뀝니다.
- **해법**: 커서 안에 정렬 조건·필터 조건을 함께 인코딩하고, 요청 파라미터와 다르면 400으로 거절합니다. AIP-158도 페이지 토큰과 함께 온 나머지 파라미터가 토큰을 발급한 요청과 다르면 거절하라고 규정합니다.

### 8-4. `Page`를 반환하면서 count가 느린 걸 모릅니다

- **증상**: 목록 API의 p99가 튀는데 목록 쿼리 자체는 빠릅니다.
- **원인**: `Page<T>`는 항상 count 쿼리를 추가로 실행합니다. 조인이 많은 목록이면 count가 본 쿼리보다 무겁습니다.
- **해법**: 총건수가 화면에 안 나온다면 `Slice<T>`나 `Window<T>`로 바꿉니다. 총건수가 필요하면 카운트를 별도 엔드포인트로 분리하거나 캐시합니다. 사용자에게 "1,000+"처럼 근사치를 보여주는 것도 유효한 선택입니다.

### 8-5. `limit + 1` 트릭에서 잘라내는 걸 잊습니다

- **증상**: 페이지 크기를 20으로 요청했는데 21개가 옵니다. 마지막 항목이 다음 페이지 첫 항목과 겹칩니다.
- **원인**: `hasNext` 판정에만 쓰고 리스트를 자르지 않았습니다.
- **해법**: 판정과 절단을 한 함수 안에 묶습니다. 위 `CursorPage.of()`처럼 호출부가 실수할 여지를 없앱니다.

## 9. 참고자료

- [Use The Index, Luke — No Offset](https://use-the-index-luke.com/no-offset) — OFFSET의 중복 문제와 seek 방식
- [Google AIP-158 — Pagination](https://google.aip.dev/158) — 페이지 토큰 불투명성·만료·파라미터 일치 규정
- [Stripe API — Pagination](https://docs.stripe.com/api/pagination) — `starting_after`/`ending_before`/`has_more` 규약
- [Slack — Pagination](https://docs.slack.dev/apis/web-api/pagination/) — `next_cursor`로 종료를 판단하는 이유
- [Spring Data — Scrolling](https://docs.spring.io/spring-data/jpa/reference/data-commons/repositories/scrolling.html) — `Window`, `ScrollPosition`, 키셋 제약
- [MySQL 8.4 — Row Constructor Expression Optimization](https://dev.mysql.com/doc/refman/8.4/en/row-constructor-optimization.html) — 행 생성자와 인덱스 사용
- [hackmysql — Deferred Join: A Deep Dive](https://hackmysql.com/deferred-join-deep-dive/) — 지연 조인의 효과와 한계
- [Elasticsearch — Index modules](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules) — `index.max_result_window`
- 관련 문서: [day09-rest-api-design.md](day09-rest-api-design.md) — 목록 API의 계약 설계
- 관련 문서: [day14-dto-vs-entity.md](day14-dto-vs-entity.md) — 응답 DTO를 트랜잭션 안에서 만드는 이유
- 관련 문서: [day11-null-traps.md](day11-null-traps.md) — `NULL` 비교가 `UNKNOWN`이 되는 지점

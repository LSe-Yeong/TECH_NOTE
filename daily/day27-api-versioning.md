# 깨지는 변경을 다루는 법 — API 버저닝은 마지막 수단입니다

> 이 문서가 답할 질문: **클라이언트를 깨뜨리지 않고 API를 바꿔야 할 때, 버전을 새로 파야 하는가 아니면 호환되게 확장해야 하는가?**
>
> 분류: 선택형(A vs B). 여러 출처가 공통으로 드는 비교 기준과 트레이드오프를 찾는 관점으로 조사했습니다.
>
> 기준: Spring Boot 4.1 · Spring Framework 7.0 (2026년 9월 확인). 응답 포맷 자체의 설계는 `day26-response-design.md`, 에러 표현은 `day03-api-error-format.md`에서 다뤘으므로 여기서는 **이미 나가 있는 계약을 바꾸는 문제**만 봅니다.

## 1. 핵심 개념 — "깨지는 변경"의 정의는 딱 하나입니다

기준은 문법이 아니라 결과입니다.

> **클라이언트가 코드를 한 줄도 고치지 않고 계속 동작하면 호환되는 변경이고, 한 줄이라도 고쳐야 하면 깨지는 변경입니다.**

이 정의가 왜 중요한지는 반대편에서 보면 압니다. 주문 조회 응답에서 `status` 값을 `PAID`에서 `PAYMENT_COMPLETED`로 "더 명확하게" 바꿨다고 합시다. 서버 테스트는 전부 통과합니다. 스펙 문서도 갱신했습니다. 그런데 안드로이드 앱은 이미 심사를 통과해 사용자 폰에 깔려 있고, `switch (status)`의 `default` 분기로 떨어져 결제 완료 화면을 못 그립니다. **서버는 배포 롤백이 5분이지만 앱은 스토어 심사 + 강제 업데이트라 최소 며칠입니다.** 배포 주기를 내가 통제하지 못하는 클라이언트가 하나라도 있으면, 계약을 바꾸는 비용은 내 저장소 밖에서 발생합니다.

그래서 이 문서의 선택지는 두 개입니다.

- **A안 — 호환 확장**: 버전을 만들지 않고, 기존 계약을 유지한 채 새 필드·새 엔드포인트를 더합니다.
- **B안 — 버전 분리**: `v2`를 만들고 두 벌을 동시에 운영하다가 `v1`을 끕니다.

먼저 알아야 할 건 **B안의 진짜 가격**입니다. 버전을 하나 늘리는 비용은 URL의 `v1`을 `v2`로 바꾸는 게 아닙니다. 컨트롤러 두 벌, 응답 모델 두 벌, 테스트 두 벌, 그리고 "v1은 언제 끄나"라는 질문에 아무도 답하지 못한 채 남는 코드입니다. GitHub는 새 버전을 낸 뒤 **이전 버전을 최소 24개월 지원**한다고 명시합니다([GitHub REST API versions](https://docs.github.com/en/rest/about-the-rest-api/api-versions)). 2년치 유지보수를 살 각오가 없으면 B안은 선택지가 아닙니다.

Zalando의 API 가이드라인이 `SHOULD avoid versioning`을 규칙으로 못 박은 이유도 같습니다([Rule 113](https://opensource.zalando.com/restful-api-guidelines/#113)). 버저닝은 기본 전략이 아니라, 호환 확장으로 못 푸는 경우에만 꺼내는 도구입니다.

## 2. 무엇이 깨지고 무엇이 안 깨지는가

먼저 이 표를 팀 안에서 합의해야 논쟁이 끝납니다. GitHub가 자사 API 정책에서 분류하는 기준을 정리하면 다음과 같습니다([GitHub REST API versions](https://docs.github.com/en/rest/about-the-rest-api/api-versions)).

| 변경 | 판정 | 이유 |
|---|---|---|
| 응답에 필드 추가 | 호환 | 모르는 필드를 무시하는 클라이언트라면 영향 없음 |
| 선택 파라미터·헤더 추가 | 호환 | 안 보내면 기존 동작 |
| 새 엔드포인트 추가 | 호환 | 기존 경로 그대로 |
| enum 값 추가 | 조건부 | 클라이언트가 미지의 값을 견디게 짜여 있어야 함 |
| 응답 필드 제거·이름 변경 | **깨짐** | 매핑 실패 또는 `null` |
| 필드 타입 변경 (`Long` → `String`) | **깨짐** | 역직렬화 예외 |
| 필수 파라미터 추가 | **깨짐** | 기존 요청이 400 |
| 검증 규칙 강화 | **깨짐** | 어제 통과하던 요청이 오늘 거부됨 |
| 기본 정렬·기본 페이지 크기 변경 | **깨짐** | 값은 유효한데 화면이 달라짐 |

마지막 두 줄이 실무에서 가장 자주 사고를 냅니다. 스펙 문서상으로는 아무것도 안 바뀌었기 때문에 리뷰에서 아무도 안 잡습니다.

### 2-1. enum이 조건부인 이유 — 계약은 양쪽이 지킵니다

서버가 값을 추가하는 것 자체는 호환입니다. 깨지는 건 클라이언트가 "이 필드는 세 값 중 하나"라고 닫아 뒀을 때입니다. 그래서 Zalando는 값이 늘어날 수 있는 필드에 `enum`을 닫아 쓰지 말고 예시로 문서화하라고 권고합니다([Rule 112](https://opensource.zalando.com/restful-api-guidelines/#112)).

서버 쪽에서 통제할 수 있는 건 두 가지입니다.

1. **값이 늘어날 필드는 스펙에서 닫지 않습니다.** 결제 수단, 주문 상태처럼 비즈니스가 자라면 늘어나는 것들입니다.
2. **미지의 값을 만났을 때 어떻게 하라고 문서에 씁니다.** "모르는 `status`는 `UNKNOWN`으로 취급하고 상세 조회로 확인" 같은 규칙이 있어야 클라이언트가 방어할 수 있습니다.

반대로 국가 코드처럼 정해진 집합은 닫아도 됩니다. 기준은 "값이 늘어날 수 있는가"입니다.

### 2-2. 관대한 읽기 — 내가 남의 API를 부를 때

같은 원리가 내 서버가 클라이언트일 때도 적용됩니다. 결제사 API 응답에 필드가 하나 늘었다고 우리 서버가 500을 내면, 남의 호환 변경이 우리 장애가 됩니다.

Spring Boot는 자동 구성한 Jackson 매퍼에서 `FAIL_ON_UNKNOWN_PROPERTIES`를 꺼둡니다([Spring Boot 1.2 릴리스 노트](https://github.com/spring-projects/spring-boot/wiki/spring-Boot-1.2-Release-Notes)에서 도입된 기본값). 그런데 팀에서 "엄격하게 가자"며 `spring.jackson.deserialization.fail-on-unknown-properties=true`로 되돌리는 경우가 있습니다. 그 순간 우리 서비스는 외부 API의 모든 필드 추가에 대해 깨집니다.

> ⚠️ **엄격한 역직렬화는 내가 만든 요청 DTO에만 씁니다.** 남이 주는 응답을 읽을 때는 관대해야 합니다. 이 둘을 같은 매퍼 설정으로 묶어 두면 한쪽을 위한 선택이 다른 쪽을 망가뜨립니다.

### 2-3. 그래도 확장으로 못 피하는 것들

호환 확장에도 한계가 있습니다. 아래는 버전 없이는 안 되는 경우입니다.

- 필드의 **의미**가 바뀌는 경우. `amount`가 부가세 포함에서 별도로 바뀌면, 필드 이름도 타입도 그대로라 클라이언트는 알아챌 방법이 없습니다. 이게 가장 위험합니다.
- 자원 모델이 근본적으로 쪼개지는 경우. 주문 하나에 배송지 하나였다가 여러 개가 되는 변경.
- 인증 방식 변경, 필수 파라미터 추가처럼 요청 쪽 계약이 바뀌는 경우.

`amount` 같은 의미 변경은 **새 필드를 만들어서 피하는 게 정석**입니다. `amount`는 그대로 두고 `amountExcludingTax`를 추가한 뒤, 문서에서 `amount`를 폐기 예정으로 표시합니다. 필드 하나 늘어나는 지저분함이 버전 두 벌보다 훨씬 쌉니다.

## 3. 버전을 나눠야 한다면 — 어디에 싣고, 무엇에 매기는가

### 3-1. 버전을 싣는 위치

| 방식 | 예 | 장점 | 대가 |
|---|---|---|---|
| URI 경로 | `/v2/orders` | 브라우저·curl로 바로 보임, 라우팅·캐시 분리가 쉬움 | 같은 자원에 URI가 둘이 됨. 링크·북마크가 버전에 묶임 |
| 요청 헤더 | `X-API-Version: 2` | URI가 자원 하나를 계속 가리킴 | 눈에 안 보임. 캐시가 `Vary` 설정을 안 하면 버전이 섞임 |
| 쿼리 파라미터 | `?api-version=2` | 붙이기 쉬움 | 자원 식별자에 버전이 섞임. 로그·캐시 키가 지저분해짐 |
| 미디어 타입 파라미터 | `Accept: application/json;v=2` | 콘텐츠 협상이라는 HTTP 의미에 가장 맞음 | 클라이언트 쪽 설정이 번거로움 |

Zalando는 URI 버저닝을 금지하고 미디어 타입 버저닝을 요구합니다([Rule 114·115](https://opensource.zalando.com/restful-api-guidelines/#114)). 반대로 GitHub와 Stripe는 헤더를 씁니다(`X-GitHub-Api-Version`, `Stripe-Version`).

**어느 쪽이 옳다기보다, 팀에서 하나를 고르고 전 엔드포인트에 같은 방식을 쓰는 게 훨씬 중요합니다.** 엔드포인트마다 방식이 다른 API가 최악입니다.

한 가지는 확실합니다. **헤더나 쿼리로 버저닝하면서 `Vary`를 빠뜨리면 안 됩니다.** 같은 URI에 두 응답이 나가는데 캐시가 그걸 모르면, v1 클라이언트가 v2 응답을 받습니다.

### 3-2. 엔드포인트 단위인가, API 전체인가

더 중요한 갈림길입니다.

**엔드포인트 단위**는 바뀐 엔드포인트만 버전이 올라갑니다. 코드는 단순하지만 클라이언트 입장에서는 "`/orders`는 v2인데 `/payments`는 v1"이라는 상태를 관리해야 합니다.

**API 전체 단위**는 Stripe의 방식입니다. Stripe는 날짜 기반 버전(`2026-08-26.dahlia` 형식)을 쓰고, 계정이 처음 요청한 시점의 버전에 **고정(pin)**됩니다. 메이저 릴리스에만 비호환 변경이 들어가고, 그 사이의 월간 릴리스에는 호환 변경만 들어갑니다([Stripe — Versioning](https://docs.stripe.com/api/versioning)). 개별 요청은 `Stripe-Version` 헤더로 덮어쓸 수 있습니다.

핀 방식의 핵심은 **아무것도 안 한 클라이언트가 절대 안 깨진다**는 것입니다. 대가는 서버가 과거 버전 전부를 동시에 표현할 수 있어야 한다는 점입니다. 이걸 컨트롤러 분기로 감당하면 무너집니다 — 다음 절이 그 이야기입니다.

## 4. Spring Framework 7의 내장 버저닝

Spring Framework 7.0(및 Spring Boot 4.0) 이전에는 버전 라우팅을 직접 짜야 했습니다. 7.0부터 `@RequestMapping`에 `version` 속성이 생겼습니다([API Versioning in Spring](https://spring.io/blog/2025/09/16/api-versioning-in-spring/)).

### 4-1. 설정

```java
// org.springframework.web.servlet.config.annotation.{ApiVersionConfigurer, WebMvcConfigurer}
@Configuration
public class ApiVersionConfig implements WebMvcConfigurer {

    @Override
    public void configureApiVersioning(ApiVersionConfigurer configurer) {
        configurer.useRequestHeader("X-API-Version")
                .setDefaultVersion("1.0")     // 헤더가 없으면 1.0으로 취급
                .setVersionRequired(false);
    }
}
```

`useRequestHeader` 외에 `useQueryParam(String)`, `usePathSegment(int)`, `useMediaTypeParameter(MediaType, String)`가 있습니다([`ApiVersionConfigurer` Javadoc](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/web/servlet/config/annotation/ApiVersionConfigurer.html)). Spring Boot 4에서는 간단한 경우 프로퍼티로도 됩니다.

```yaml
spring:
  mvc:
    apiversion:
      default: 1.0
      use:
        header: X-API-Version
```

기본 파서는 `SemanticApiVersionParser`라 `1.0`, `1.2.3` 형태를 파싱하고 비교합니다. 날짜 기반(Stripe 스타일)을 쓰려면 `setVersionParser`로 직접 넣습니다.

지원 버전은 기본적으로 **매핑에 선언된 값들에서 자동 감지**됩니다. 선언한 것만 허용하려면 `detectSupportedVersions(false)` + `addSupportedVersions(...)`를 씁니다. 지원하지 않는 버전이 오면 `InvalidApiVersionException`이 발생하고 **400**으로 응답합니다.

### 4-2. 고정 버전과 베이스라인 버전

여기가 Spring 구현에서 가장 실용적인 부분입니다.

```java
@RestController
@RequestMapping("/orders")
class OrderController {

    private final OrderQueryService orderQueryService;

    OrderController(OrderQueryService orderQueryService) {
        this.orderQueryService = orderQueryService;
    }

    // 1.0 이상이면 계속 이 메서드가 처리합니다.
    @GetMapping(path = "/{orderId}", version = "1.0+")
    OrderV1Response getOrder(@PathVariable Long orderId) {
        return OrderV1Response.from(orderQueryService.findById(orderId));
    }

    // 2.0부터 배송지가 여러 개가 됐습니다. 2.0 이상은 이쪽이 우선합니다.
    @GetMapping(path = "/{orderId}", version = "2.0+")
    OrderV2Response getOrderV2(@PathVariable Long orderId) {
        return OrderV2Response.from(orderQueryService.findById(orderId));
    }
}
```

`"2.0"`은 정확히 2.0에만 매칭되고, `"2.0+"`는 2.0 이상 전부에 매칭됩니다. 매칭되는 후보 중 **가장 높은 버전이 이깁니다**([`@RequestMapping` Javadoc](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/web/bind/annotation/RequestMapping.html)).

`+`가 왜 중요한지가 핵심입니다. 고정 버전만 쓰면 3.0을 내는 날 **바뀌지 않은 엔드포인트까지 전부 3.0 메서드를 복사해서 만들어야** 합니다. 베이스라인으로 선언해 두면 바뀐 엔드포인트만 새 메서드를 추가하면 됩니다. API 전체 단위 버저닝(3-2)을 Spring에서 감당 가능하게 만드는 게 이 문법입니다.

### 4-3. 요청 흐름

```
요청 도착
  → ApiVersionResolver가 헤더에서 원시 문자열을 꺼냄 (없으면 defaultVersion)
  → ApiVersionParser가 파싱 (SemanticApiVersionParser → 1.2 == 1.2.0)
  → 지원 목록에 없으면 InvalidApiVersionException → 400
  → 매핑 후보 중 조건을 만족하는 가장 높은 version의 핸들러 선택
  → ApiVersionDeprecationHandler가 응답 헤더 추가 (해당되면)
  → 핸들러 실행
```

파싱된 버전은 `HandlerMapping.API_VERSION_ATTRIBUTE` 요청 속성으로도 꺼낼 수 있습니다(Spring Framework 7.0에 추가).

## 5. 컨트롤러를 두 벌 만들지 않는 법

버전이 둘일 때는 메서드 두 개로 충분합니다. 문제는 넷, 다섯이 될 때입니다.

### 5-1. 클린하지 않은 코드 ❌

```java
@GetMapping(path = "/{orderId}", version = "1.0+")
OrderResponse getOrder(@PathVariable Long orderId,
                       @RequestHeader(name = "X-API-Version", defaultValue = "1.0") String version) {

    Order order = orderQueryService.findById(orderId);
    OrderResponse response = OrderResponse.from(order);

    // 버전 분기가 컨트롤러에 쌓입니다.
    if (version.startsWith("1.")) {
        response.setCustomerName(order.getCustomer().fullName());
        response.setFirstName(null);
        response.setLastName(null);
    }
    if (version.compareTo("3.0") < 0) {
        response.setShippingAddresses(null);
        response.setShippingAddress(order.getPrimaryShippingAddress());
    }
    return response;
}
```

증상은 코드가 길어지는 게 아닙니다. **이 `if`가 서비스 계층으로 번지기 시작합니다.** "v1은 취소 정책이 달랐는데"가 나오는 순간 도메인 로직이 버전을 알게 되고, 그때부터는 어떤 버전 조합이 실제로 동작하는지 아무도 모릅니다.

### 5-2. 개선한 코드 ✔️

Stripe가 쓰는 방식의 축소판입니다. **도메인과 서비스는 항상 최신 모델 하나만 압니다.** 오래된 버전은 경계에서 응답을 되돌립니다.

```java
/** 특정 버전에서 들어온 비호환 변경을, 그 이전 버전 클라이언트를 위해 되돌립니다. */
public interface OrderViewDowngrader {

    /** 이 비호환 변경이 도입된 버전. 요청 버전이 이보다 낮으면 적용합니다. */
    String introducedIn();

    void downgrade(ObjectNode order);
}
```

```java
/** 2.0에서 customer.name을 firstName/lastName으로 쪼갰습니다. */
@Component
class SplitCustomerNameDowngrader implements OrderViewDowngrader {

    @Override
    public String introducedIn() {
        return "2.0";
    }

    @Override
    public void downgrade(ObjectNode order) {
        JsonNode customer = order.path("customer");
        if (!customer.isObject()) {
            return;
        }
        ObjectNode node = (ObjectNode) customer;
        String name = (node.path("firstName").asText("") + " " + node.path("lastName").asText("")).trim();
        node.put("name", name);
        node.remove("firstName");
        node.remove("lastName");
    }
}
```

```java
// org.springframework.web.accept.SemanticApiVersionParser
@Component
public class OrderViewRenderer {

    private final ObjectMapper objectMapper;
    private final SemanticApiVersionParser parser = new SemanticApiVersionParser();
    private final List<OrderViewDowngrader> downgraders;

    public OrderViewRenderer(ObjectMapper objectMapper, List<OrderViewDowngrader> downgraders) {
        this.objectMapper = objectMapper;
        // 최신 변경부터 되돌려야 하므로 도입 버전 내림차순으로 정렬합니다.
        this.downgraders = downgraders.stream()
                .sorted(Comparator.comparing((OrderViewDowngrader d) -> parser.parseVersion(d.introducedIn()))
                        .reversed())
                .toList();
    }

    public ObjectNode render(OrderLatestResponse latest, String requestVersion) {
        ObjectNode node = objectMapper.valueToTree(latest);
        SemanticApiVersionParser.Version version = parser.parseVersion(requestVersion);
        for (OrderViewDowngrader downgrader : downgraders) {
            if (version.compareTo(parser.parseVersion(downgrader.introducedIn())) < 0) {
                downgrader.downgrade(node);
            }
        }
        return node;
    }
}
```

<!-- TODO: 확인 필요 — `parseVersion(String)`은 7.0.9 Javadoc으로 확인했지만,
     반환 타입 `Version`의 `Comparable` 타입 인자(`Comparable<Version>` 여부)는 확인하지 못했습니다.
     컴파일이 안 되면 `Comparator`를 직접 넘기는 형태로 바꿔 주세요. -->

이 구조의 이득은 두 가지입니다.

- **새 비호환 변경 하나 = 클래스 하나 추가.** 컨트롤러도 서비스도 안 건드립니다.
- **버전을 끌 때도 클래스 하나 삭제.** v1을 끄면 `SplitCustomerNameDowngrader`를 지우면 끝입니다. 컨트롤러 두 벌 방식에서는 "이 메서드 지워도 되나"를 아무도 확신하지 못합니다.

대가도 분명합니다. 응답이 `ObjectNode`를 거치므로 **타입 안전성을 잃고**, 필드 이름 오타가 컴파일 시점에 안 잡힙니다. 그래서 다운그레이더마다 "v1 요청 → 기대 JSON" 테스트가 필수입니다. 버전이 두세 개뿐이면 컨트롤러 메서드 두 벌이 더 낫습니다. **이 구조는 버전이 계속 늘어난다는 게 확실해진 뒤에 도입합니다.**

## 6. 버전을 끄는 법 — 폐기는 절차입니다

버저닝의 어려운 부분은 만드는 게 아니라 없애는 겁니다. 순서는 정해져 있습니다.

1. **계측이 먼저입니다.** 버전별 요청 수를 클라이언트 식별자(API 키, `User-Agent`)와 함께 셉니다. 누가 쓰는지 모르면 영원히 못 끕니다.
2. **응답 헤더로 알립니다.** `Deprecation`(RFC 9745)과 `Sunset`(RFC 8594), 그리고 마이그레이션 문서를 가리키는 `Link`입니다. `Sunset`은 `Deprecation`보다 이를 수 없습니다.
3. **문서와 스펙에 반영합니다.** 헤더만 보내면 아무도 안 봅니다.
4. **트래픽이 0에 수렴한 뒤 끕니다.** 끈 뒤에는 404가 아니라 **410 Gone**을 줍니다. GitHub도 지원 종료된 버전에 410을 반환합니다([GitHub REST API versions](https://docs.github.com/en/rest/about-the-rest-api/api-versions)).

Spring Framework 7은 2번을 내장 지원합니다.

```java
@Override
public void configureApiVersioning(ApiVersionConfigurer configurer) {
    StandardApiVersionDeprecationHandler handler = new StandardApiVersionDeprecationHandler();
    handler.configureVersion("1.0")
            .setDeprecationDate(ZonedDateTime.parse("2026-09-01T00:00:00+09:00"))
            .setSunsetDate(ZonedDateTime.parse("2027-03-01T00:00:00+09:00"))
            .setDeprecationLink(URI.create("https://example.com/docs/api/migration-v2"));

    configurer.useRequestHeader("X-API-Version")
            .setDefaultVersion("1.0")
            .setDeprecationHandler(handler);
}
```

`StandardApiVersionDeprecationHandler`는 RFC 9745·8594에 맞춰 `Deprecation`, `Sunset`, `Link` 헤더를 응답에 붙입니다.

> 반대 방향도 챙기세요. **우리가 남의 API를 부를 때 `Deprecation`·`Sunset` 헤더가 오면 로그를 남기고 알림을 겁니다.** 이 헤더는 클라이언트가 안 읽으면 존재 의미가 없습니다.

## 7. 함정

**1) 헤더 버저닝 + `Vary` 누락**

- **증상**: 대부분 정상인데 특정 시간대에만 v1 클라이언트가 v2 응답을 받습니다. 재현이 안 됩니다.
- **원인**: CDN·리버스 프록시가 URI만으로 캐시 키를 만듭니다. 버전 헤더는 키에 안 들어갑니다.
- **해법**: 버전 헤더를 `Vary`에 넣습니다(`Vary: X-API-Version`). 또는 URI 경로 버저닝으로 갑니다. **캐시 앞단에 두는 API를 헤더로 버저닝할 때 이건 선택이 아니라 필수입니다.**

**2) 기본 버전을 "최신"으로 두기**

- **증상**: 버전 헤더를 안 보내던 오래된 클라이언트가, 우리가 v2를 배포한 날 한꺼번에 깨집니다.
- **원인**: `setDefaultVersion`을 최신 버전으로 걸어 뒀습니다. 버전을 안 보내는 클라이언트는 대개 가장 오래된 클라이언트입니다.
- **해법**: 기본값은 **가장 오래된 지원 버전**으로 고정합니다. GitHub도 헤더가 없으면 최신이 아니라 `2022-11-28`로 취급합니다([GitHub REST API versions](https://docs.github.com/en/rest/about-the-rest-api/api-versions)).

**3) 웹훅과 비동기 이벤트를 버저닝에서 빼먹기**

- **증상**: 동기 API는 멀쩡한데, 우리가 보내는 웹훅 페이로드를 바꾼 날 파트너사 연동이 조용히 깨집니다.
- **원인**: 버전 협상은 요청이 있어야 됩니다. 우리가 먼저 보내는 이벤트에는 협상할 요청이 없습니다.
- **해법**: 구독 등록 시점에 버전을 함께 저장하고, 발송할 때 그 버전으로 렌더링합니다. Stripe도 웹훅 엔드포인트 생성 시 API 버전을 지정하게 합니다([Stripe — Versioning](https://docs.stripe.com/api/versioning)).

**4) v2를 새 서비스로 분리하기**

- **증상**: v1과 v2가 같은 DB를 읽는데 결과가 다릅니다.
- **원인**: "깨끗하게 다시 짜자"며 v2를 별도 애플리케이션으로 만들어 비즈니스 규칙이 두 벌이 됐습니다. 버전은 표현 계층 문제인데 도메인까지 복제한 겁니다.
- **해법**: 도메인은 하나로 두고 표현만 나눕니다(5-2). 정말 별도 서비스가 필요하다면 그건 버저닝이 아니라 서비스 분리 문제입니다.

**5) 버전을 올려 놓고 뒤에서 계속 고치기**

- **증상**: v2를 쓰는 클라이언트가 "지난주엔 됐는데"라고 합니다.
- **원인**: v2는 아직 클라이언트가 적다는 이유로 비호환 변경을 계속 넣습니다.
- **해법**: **버전은 공개하는 순간 얼립니다.** 아직 안 굳은 API라면 이름부터 미리보기로 내고("호환 보장 없음"을 명시), 굳은 뒤에 정식 버전을 붙입니다.

## 8. 정리

- 기본 전략은 **A안(호환 확장)**입니다. **B안(버전 분리)**은 요청 계약이 바뀌거나 자원 모델이 쪼개질 때만 씁니다. 가격은 최소 1~2년의 이중 운영입니다.
- 버전을 싣는 위치는 팀에서 하나로 통일하고, 헤더·쿼리로 간다면 `Vary`를 반드시 설정합니다.
- 버전이 셋 이상으로 늘어날 게 확실해지면 컨트롤러 분기 대신 **최신 모델 하나 + 응답 다운그레이더 체인**으로 옮깁니다.
- 계측 없이는 못 끕니다. `Deprecation`·`Sunset` 헤더는 폐기의 시작이지 끝이 아닙니다.

## 9. 참고자료

- [API Versioning in Spring — Spring Blog](https://spring.io/blog/2025/09/16/api-versioning-in-spring/)
- [`ApiVersionConfigurer` Javadoc (Spring Framework 7.0)](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/web/servlet/config/annotation/ApiVersionConfigurer.html)
- [`@RequestMapping` Javadoc — `version` 속성](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/web/bind/annotation/RequestMapping.html)
- [GitHub REST API versions](https://docs.github.com/en/rest/about-the-rest-api/api-versions)
- [Stripe — Versioning](https://docs.stripe.com/api/versioning)
- [Zalando RESTful API Guidelines — Compatibility](https://opensource.zalando.com/restful-api-guidelines/#compatibility)
- [RFC 9745 — The Deprecation HTTP Response Header Field](https://www.rfc-editor.org/rfc/rfc9745.txt)
- [RFC 8594 — The Sunset HTTP Header Field](https://www.rfc-editor.org/rfc/rfc8594.html)
- 관련 문서: `day26-response-design.md`, `day03-api-error-format.md`, `day09-rest-api-design.md`

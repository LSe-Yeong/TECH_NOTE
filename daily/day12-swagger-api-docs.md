# API 문서 자동화하기 — 무엇이 자동화되고 무엇은 끝까지 사람 몫인가

> 이 문서가 답할 질문: **"코드에서 API 문서를 자동 생성한다"는 게 실제로 무엇을 자동화하고, 무엇은 여전히 사람이 해야 하는가?**
>
> 기준: Spring Boot 4.1 / springdoc-openapi 3.1.0 / OpenAPI 3.1 / Spring REST Docs 4.0.

## 1. 핵심 개념 — 셋은 다른 물건입니다

"Swagger 붙이자"는 말 안에 서로 다른 세 가지가 섞여 있습니다. 이걸 분리하지 않으면 대화가 계속 어긋납니다.

| 이름 | 정체 | 역할 |
|---|---|---|
| **OpenAPI** | 명세(스펙) 자체. JSON/YAML 문서 | API의 구조를 기계가 읽을 수 있게 기술 |
| **Swagger UI** | 그 JSON을 읽어 그리는 웹 페이지 | 사람이 보고 눌러보는 화면 |
| **springdoc-openapi** | Spring 애플리케이션을 스캔해 OpenAPI JSON을 만들어주는 라이브러리 | 코드 → 스펙 변환기 |

Swagger는 원래 명세의 이름이었지만, 2015년 명세가 OpenAPI Initiative로 넘어가면서 **명세는 OpenAPI, 도구는 Swagger**로 갈라졌습니다. 지금 `springdoc.api-docs.version`의 기본값은 `openapi_3_1`입니다 ([springdoc — Properties](https://springdoc.org/properties.html)).

> 문서 자동화가 없으면 어떻게 되는지는 다들 압니다. Notion이나 Confluence에 API 표를 만듭니다. 처음 2주는 잘 맞습니다. 그다음 필드 하나가 nullable이 되고, 상태 코드가 400에서 409로 바뀌고, 쿼리 파라미터 이름이 `page`에서 `pageNumber`로 바뀝니다. 아무도 문서를 안 고칩니다. **틀린 문서는 없는 문서보다 나쁩니다.** 없으면 물어보기라도 하는데, 있으면 믿고 그대로 짜다가 통합 단계에서 터집니다. 이 현상에 이름이 붙어 있습니다 — **문서 드리프트(documentation drift)**. 자동화가 푸는 문제는 "문서 쓰기 귀찮음"이 아니라 **"문서와 코드가 갈라지는 것"** 입니다.

## 2. 구조 — 스펙이 중심이지 UI가 중심이 아닙니다

많은 팀이 Swagger UI를 목적으로 착각합니다. 실제 파이프라인에서 UI는 소비자 중 하나일 뿐입니다.

```
컨트롤러 · DTO · 애노테이션
        ↓  (springdoc이 런타임에 스캔)
   OpenAPI 3.1 문서 (JSON/YAML)   ← 이게 진짜 산출물
        ↓
   ├─ Swagger UI / Scalar UI  → 사람이 본다
   ├─ 클라이언트 SDK 생성      → 프론트·안드로이드가 타입을 받는다
   ├─ 목 서버(Mock)            → 백엔드 완성 전에 프론트가 개발한다
   ├─ 계약 테스트 / 스키마 검증 → CI가 깨진 변경을 잡는다
   └─ Git에 커밋된 스펙 파일    → 변경이 diff로 보인다
```

**"스펙을 산출물로 본다"가 이 챕터의 핵심입니다.** UI만 띄우면 얻는 건 사내 조회 화면 하나지만, 스펙을 파일로 뽑아내면 뒤의 네 가지가 전부 따라옵니다. 6절에서 다시 다룹니다.

## 3. 흐름

### 3-1. 코드로 보는 구성

```gradle
dependencies {
    implementation 'org.springdoc:springdoc-openapi-starter-webmvc-ui:3.1.0'
}

tasks.withType(JavaCompile) {
    options.compilerArgs << '-parameters'   // 파라미터 이름 보존 — 3-3 참고
}
```

WebFlux면 `webmvc`를 `webflux`로 바꿉니다. UI가 필요 없고 스펙만 필요하면 `-ui` 대신 `-api` 아티팩트를 씁니다 ([springdoc](https://springdoc.org/)).

```java
@RestController
@RequestMapping("/orders")
class OrderController {

    private final OrderService orderService;

    OrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    @Operation(summary = "주문 단건 조회")
    @ApiResponse(responseCode = "404", description = "주문이 존재하지 않음")
    @GetMapping("/{orderId}")
    OrderResponse getOrder(@PathVariable Long orderId) {
        return orderService.findById(orderId);
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    OrderResponse create(@Valid @RequestBody OrderCreateRequest request) {
        return orderService.create(request);
    }
}
```

```java
public record OrderCreateRequest(
        @NotBlank @Size(max = 50) String productCode,
        @Positive int quantity,
        @Schema(description = "요청 중복 방지 키", example = "9f2c1a3e")
        String idempotencyKey) {
}
```

애노테이션이 거의 없다는 점이 중요합니다. **경로·메서드·상태 코드·필드 타입·필수 여부는 이미 코드에 다 적혀 있습니다.** springdoc은 그걸 읽습니다.

### 3-2. 확인 지점

기동 후 두 곳이 열립니다 ([springdoc](https://springdoc.org/)).

| 대상 | 기본 경로 |
|---|---|
| OpenAPI JSON | `/v3/api-docs` |
| OpenAPI YAML | `/v3/api-docs.yaml` |
| Swagger UI | `/swagger-ui.html` |

문제가 생기면 **UI가 아니라 `/v3/api-docs`를 먼저 봅니다.** UI가 이상한 건 대부분 스펙이 이미 이상하기 때문입니다. UI는 스펙을 그대로 그릴 뿐이라 여기서 원인이 갈립니다.

### 3-3. 스캔이 실제로 읽는 것

springdoc이 정보를 얻는 출처는 세 갈래입니다. 우선순위는 아래로 갈수록 높습니다.

1. **Spring MVC 애노테이션** — `@GetMapping`, `@PathVariable`, `@RequestBody`, `@ResponseStatus`
2. **Bean Validation 애노테이션** — `@NotBlank` → `required`, `@Size(max=50)` → `maxLength`, `@Positive` → `minimum`
3. **`@Operation` / `@Schema` 등 명시적 애노테이션** — 위 둘로 표현 못 하는 설명·예시

2번이 실무에서 가장 이득이 큽니다. 검증 규칙을 이미 쓰고 있다면 문서에 제약조건이 공짜로 들어옵니다. **검증과 문서가 같은 소스를 쓰므로 둘이 어긋날 수 없습니다.**

`-parameters` 컴파일 옵션은 3-1에 넣어둔 이유가 있습니다. 이게 없으면 파라미터 이름이 `arg0`으로 나옵니다. Spring Boot 3.2부터 이 옵션을 명시적으로 요구합니다 ([springdoc — FAQ](https://springdoc.org/faq.html)).

## 4. 특징

### 4-1. 자동화되는 것

- 엔드포인트 목록, HTTP 메서드, 경로 변수·쿼리 파라미터
- 요청/응답 바디의 **구조** — 필드 이름, 타입, 중첩, 배열 여부
- 필수/선택, 길이·범위 제약 (Bean Validation에서)
- 리팩터링 반영 — 필드 이름을 바꾸면 문서도 바뀝니다

### 4-2. 자동화되지 않는 것 ⚠️

여기가 이 챕터의 본론입니다. 자동 생성기는 **코드에 적혀 있지 않은 것을 만들어낼 수 없습니다.**

- **의미.** `status`가 `String`이라는 건 압니다. 그 값이 `PENDING|PAID|CANCELED` 중 하나라는 건 모릅니다. (enum으로 만들면 압니다 — 5절)
- **왜 실패하는가.** 400이 난다는 건 압니다. "재고가 모자라면 409"는 코드 어디에도 구조로 남아 있지 않습니다.
- **호출 순서와 상태 전이.** "결제 확정 전에는 취소 API가 409를 준다" 같은 규칙.
- **성능·제한.** 페이지 크기 상한, 레이트 리밋, 타임아웃.
- **응답 예시의 현실성.** 자동 생성 예시는 `"string"`, `0`입니다.

**요약하면 자동 생성은 "형태"를 보증하고, "의미"는 사람이 채웁니다.** 그래서 `@Operation(summary=...)`이나 `@Schema(description=...)`은 게으름이 아니라 자동화가 원리적으로 채울 수 없는 칸입니다.

### 4-3. 트레이드오프

**런타임에 붙는 물건입니다.** springdoc은 애플리케이션 컨텍스트를 스캔해서 문서를 만듭니다. 기동 시간이 늘고, 프로덕션 프로세스가 문서용 엔드포인트를 하나 더 들고 있게 됩니다. 컨트롤러가 많으면 첫 `/v3/api-docs` 호출이 눈에 띄게 느립니다.

**노출 면적이 늘어납니다.** `/swagger-ui.html`이 인증 없이 열려 있으면 내부 API 목록이 그대로 공개됩니다. 함정 1에서 다룹니다.

**"돌아가면 문서가 맞다"가 아닙니다.** springdoc이 보증하는 건 **선언된 시그니처**입니다. 컨트롤러가 실제로 어떤 JSON을 뱉는지는 검증하지 않습니다. 반환 타입이 `Object`거나 `ResponseEntity<?>`면 문서는 빈 껍데기가 됩니다. 이 지점이 REST Docs와 갈리는 곳입니다(7절).

## 5. 예제 — 애노테이션을 붙이는 대신 타입으로 말하기

### 5-1. 클린하지 않은 코드 ❌

```java
@Operation(summary = "주문 조회")
@ApiResponse(responseCode = "200", description = "성공")
@GetMapping("/{orderId}")
public ResponseEntity<?> getOrder(
        @Parameter(description = "주문 ID") @PathVariable Long orderId,
        @Parameter(description = "상태", example = "PENDING")
        @RequestParam(required = false) String status) {

    Map<String, Object> body = new HashMap<>();
    body.put("orderId", orderId);
    body.put("status", "PENDING");
    return ResponseEntity.ok(body);
}
```

애노테이션은 많은데 문서는 쓸모가 없습니다. 반환 타입이 `ResponseEntity<?>`라 **응답 스키마 칸이 비어 있습니다.** `status`가 어떤 값을 받는지도 `example` 한 줄이 전부라, 클라이언트는 `"PENDING"` 하나만 보고 나머지를 추측합니다. 게다가 이 애노테이션들은 **코드와 함께 썩습니다.** 응답에 필드를 하나 추가해도 `@Operation`은 그대로입니다. 아무도 안 고칩니다.

### 5-2. 개선한 코드 ✔️

```java
public enum OrderStatus { PENDING, PAID, CANCELED }

public record OrderResponse(
        Long orderId,
        OrderStatus status,
        @Schema(description = "결제 확정 시각. 미결제면 null")
        Instant paidAt) {
}
```

```java
@Operation(summary = "주문 단건 조회",
           description = "취소된 주문도 조회됩니다. 존재하지 않으면 404입니다.")
@GetMapping("/{orderId}")
public OrderResponse getOrder(
        @PathVariable Long orderId,
        @RequestParam(required = false) OrderStatus status) {

    return orderService.findById(orderId, status);
}
```

바뀐 건 애노테이션이 아니라 **타입**입니다.

- `OrderStatus` enum → 스펙에 `enum: [PENDING, PAID, CANCELED]`가 자동으로 들어갑니다. 값이 늘면 문서도 늘어납니다.
- `OrderResponse` 구체 타입 → 응답 스키마가 채워집니다. 필드를 추가하면 문서에 나타납니다.
- `@Operation`에는 **코드가 표현할 수 없는 것만** 남겼습니다 (4-2).

**애노테이션으로 설명하고 싶어지면, 그 정보를 타입으로 옮길 수 있는지부터 봅니다.** 타입으로 옮긴 정보는 리팩터링을 따라오지만, 애노테이션에 적은 문장은 따라오지 않습니다. DTO를 분리해야 하는 이유가 하나 더 늘어난 셈입니다(`daily/day09-rest-api-design.md`와 같은 맥락).

## 6. UI를 띄우는 데서 멈추지 않기 — 스펙을 CI에 넣습니다

여기서부터가 "자동화"라는 말에 값하는 부분입니다.

**첫째, 스펙을 빌드 산출물로 뽑습니다.** springdoc은 Maven·Gradle 플러그인을 제공합니다. 통합 테스트로 애플리케이션을 띄우고 `/v3/api-docs`를 호출해 JSON/YAML로 저장하는 방식입니다 ([springdoc — FAQ](https://springdoc.org/faq.html)). 직접 짜도 몇 줄입니다.

```java
@SpringBootTest(webEnvironment = RANDOM_PORT)
class OpenApiSpecExportTest {

    @Autowired TestRestTemplate restTemplate;

    @Test
    void exportSpec() throws IOException {
        String spec = restTemplate.getForObject("/v3/api-docs", String.class);
        Files.writeString(Path.of("build/openapi.json"), spec);
    }
}
```

**둘째, 뽑은 스펙을 Git에 커밋합니다.** 그러면 API 변경이 **PR diff에 보입니다.** 리뷰어가 "이 필드 지우면 앱이 깨지지 않나요?"를 코드가 아니라 스펙 diff에서 묻게 됩니다. 이게 자동화의 진짜 수확입니다.

**셋째, 파괴적 변경을 CI가 막게 합니다.** 커밋된 스펙과 새로 생성한 스펙을 비교해 필드 삭제·타입 변경·필수 필드 추가를 잡아냅니다. 사람이 리뷰에서 놓쳐도 파이프라인이 잡습니다.

**넷째, 스펙 순서를 안정화합니다.** 생성 순서가 매번 달라지면 diff가 무의미해집니다. `springdoc.writer-with-order-by-keys`의 기본값은 `false`인데, 스펙을 커밋할 거라면 `true`로 켜서 키를 정렬합니다 ([springdoc — Properties](https://springdoc.org/properties.html)).

```yaml
springdoc:
  writer-with-order-by-keys: true
  api-docs:
    enabled: true          # 스펙은 만들되
  swagger-ui:
    enabled: false         # 운영에서 UI는 닫는다 (함정 1)
```

## 7. 관련된 개념과 비교 — springdoc과 Spring REST Docs

둘 다 "문서 드리프트"를 풀지만 **무엇을 진실의 근거로 삼는지**가 다릅니다.

| | springdoc-openapi | Spring REST Docs |
|---|---|---|
| 근거 | 애플리케이션의 선언(애노테이션·타입) | **실제로 실행된 테스트의 요청/응답** |
| 산출물 | OpenAPI 3.1 문서 + UI | Asciidoctor 스니펫 → HTML |
| 문서가 틀리면 | 조용히 틀린 채로 나갑니다 | **테스트가 실패합니다** |
| 도입 비용 | 의존성 한 줄 | 엔드포인트마다 문서화 테스트 |
| 생태계 | SDK 생성·목 서버·스키마 검증 도구 다수 | 읽기 좋은 HTML |

REST Docs의 강제력이 핵심입니다. 기본 동작이 엄격해서 **문서화되지 않은 필드가 페이로드에 있으면 테스트가 깨지고, 문서화했는데 페이로드에 없어도 깨집니다**(optional로 표시하지 않은 경우). 느슨하게 하려면 `relaxedResponseFields` 같은 메서드를 따로 써야 합니다 ([Spring REST Docs Reference](https://docs.spring.io/spring-restdocs/docs/current/reference/htmlsingle/)). 즉 필드를 추가하고 문서를 안 고치면 **빌드가 빨간불이 됩니다.** springdoc은 이걸 못 잡습니다.

대신 REST Docs는 OpenAPI 문서를 만들지 않습니다. 클라이언트 SDK 자동 생성이나 목 서버가 필요하면 별도 변환이 필요합니다.

**선택 기준:**

- **내부 팀 간 API, 빠르게 시작해야 함, 프론트가 SDK를 뽑아 쓴다** → springdoc
- **외부 공개 API, 문서 정확성이 계약 수준, 틀리면 안 됨** → REST Docs (또는 둘 다)

REST Docs 4.0은 2025년 11월 19일 릴리스됐고 Spring Framework 7·Jackson 3 기반입니다 ([Spring REST Docs 4.0.0](https://spring.io/blog/2025/11/19/spring-restdocs-4/)). Spring Boot 4를 쓴다면 이 라인을 맞춰야 합니다.

## 8. 함정

**함정 1 — Swagger UI가 운영에 열려 있다**

- **증상**: 외부에서 `https://api.example.com/swagger-ui.html`이 열립니다. 내부 관리자 API 목록까지 전부 보입니다.
- **원인**: `springdoc.swagger-ui.enabled`와 `springdoc.api-docs.enabled`의 기본값이 둘 다 `true`입니다. 의존성만 넣으면 켜집니다. 스테이징에서 편하게 쓰던 설정이 그대로 운영으로 갑니다.
- **해법**: 운영 프로필에서 `springdoc.swagger-ui.enabled=false`로 UI를 끕니다. 스펙 자체도 필요 없으면 `springdoc.api-docs.enabled=false`로 전부 끕니다 ([springdoc — FAQ](https://springdoc.org/faq.html)). UI가 운영에서도 필요하다면 인증 뒤로 넣거나, `springdoc.use-management-port=true`(기본 `false`)로 관리 포트로 옮겨 외부 노출에서 분리합니다. `springdoc.swagger-ui.tryItOutEnabled`의 기본값은 `false`인데, 이걸 켜두면 문서 화면에서 실제 API가 호출됩니다. 운영 데이터가 걸린 곳이면 켜지 않습니다.

**함정 2 — 응답 스키마가 텅 비어 있다**

- **증상**: Swagger UI의 Response 칸이 `{}`거나 `string`으로만 나옵니다. 에러는 없습니다.
- **원인**: 반환 타입이 `ResponseEntity<?>`, `Object`, `Map<String, Object>`입니다. 제네릭 정보가 없으니 스캐너가 읽을 게 없습니다. 컨트롤러가 `ModelAndView`를 반환하는 경우도 마찬가지인데, `springdoc.model-and-view-allowed`의 기본값은 `false`라 아예 무시됩니다 ([springdoc — Properties](https://springdoc.org/properties.html)).
- **해법**: 구체 타입을 반환합니다(5-2). 상태 코드 제어가 필요하면 `ResponseEntity<OrderResponse>`처럼 **제네릭을 채웁니다.** 공통 래퍼를 쓴다면 `ApiResponse<OrderResponse>` 형태로 타입 파라미터를 살립니다.

**함정 3 — 파라미터 이름이 `arg0`으로 나온다**

- **증상**: 문서의 쿼리 파라미터 이름이 `arg0`, `arg1`입니다. 로컬 IDE 실행에서는 멀쩡했는데 CI 빌드 산출물에서만 그렇습니다.
- **원인**: 컴파일 시 `-parameters` 옵션이 없으면 파라미터 이름이 클래스 파일에 남지 않습니다. Spring Boot 3.2부터 이 옵션이 필요합니다 ([springdoc — FAQ](https://springdoc.org/faq.html)). IDE는 자체 컴파일 설정을 써서 안 드러날 수 있습니다.
- **해법**: 빌드 스크립트에 `-parameters`를 추가합니다(3-1). 급하면 `@RequestParam("status")`처럼 이름을 명시하는 것도 방법이지만, 근본 해결은 컴파일 옵션입니다.

**함정 4 — Spring Security를 붙이자 문서가 404가 된다**

- **증상**: 잘 되던 `/swagger-ui.html`이 인증 리다이렉트로 튕기거나, `/v3/api-docs`가 401을 반환합니다.
- **원인**: Swagger UI는 정적 리소스 하나가 아닙니다. `/swagger-ui/**` 하위 리소스와 `/v3/api-docs/**`를 함께 받아야 화면이 그려집니다. `/swagger-ui.html` 하나만 permitAll 하면 페이지 껍데기만 열리고 내용이 비어 보입니다.
- **해법**: 세 경로를 함께 엽니다. 그리고 **운영에서는 여는 게 아니라 닫는 쪽이 기본**입니다(함정 1).

```java
http.authorizeHttpRequests(auth -> auth
        .requestMatchers("/swagger-ui.html", "/swagger-ui/**", "/v3/api-docs/**").permitAll()
        .anyRequest().authenticated());
```

**함정 5 — API 버전 설정을 켜니 문서 엔드포인트가 400을 뱉는다**

- **증상**: Spring Boot 4의 내장 API 버저닝을 켠 뒤 `/v3/api-docs`와 `/swagger-ui.html`이 HTTP 400을 반환합니다. 기동 로그에는 아무 에러가 없습니다.
- **원인**: Spring Framework 7이 `@RequestMapping`에 `version` 속성을 도입하면서, 버전 필수·경로 세그먼트 방식을 전역으로 설정하면 **버전이 없는 요청 자체가 거부됩니다.** springdoc의 문서 엔드포인트는 버전이 붙지 않은 평범한 핸들러라 여기에 걸립니다. 라이브러리 버그로 보고됐지만 `invalid`로 닫혔습니다 — 설정 범위의 문제라는 뜻입니다 ([springdoc#3163](https://github.com/springdoc/springdoc-openapi/issues/3163)).
- **해법**: 버저닝 적용 경로를 API 경로로 한정해 문서 엔드포인트가 버전 매칭 대상에 들어가지 않게 합니다. 경로 세그먼트 방식으로 그룹을 나눌 계획이라면 도입 전에 `/v3/api-docs`부터 호출해보고 넘어갑니다. <!-- TODO: 확인 필요 — 버저닝 설정 조합별 정확한 회피 방법은 공식 문서에 정리된 항목이 없어, 프로젝트 설정에서 직접 재현 후 확정할 것 -->

## 9. 정리

- 자동 생성기가 보증하는 건 **형태**입니다. **의미**는 사람이 씁니다. 그래서 설명 애노테이션은 사라지지 않습니다.
- 설명을 애노테이션에 적기 전에 **타입으로 옮길 수 있는지** 봅니다. enum과 구체 DTO가 문장 열 줄보다 오래갑니다.
- 목표는 Swagger UI가 아니라 **OpenAPI 스펙 파일**입니다. 커밋하면 API 변경이 diff로 보이고, CI가 파괴적 변경을 막습니다.
- 문서가 틀리면 빌드를 깨고 싶다면 springdoc으로는 부족합니다. REST Docs가 그 강제력을 갖습니다.
- 의존성을 넣는 순간 문서 엔드포인트가 열립니다. **운영에서 닫는 것을 기본값으로 둡니다.**

## 10. 참고자료

- [springdoc-openapi 공식 문서](https://springdoc.org/)
- [springdoc-openapi — Properties](https://springdoc.org/properties.html)
- [springdoc-openapi — F.A.Q](https://springdoc.org/faq.html)
- [Spring REST Docs Reference Documentation](https://docs.spring.io/spring-restdocs/docs/current/reference/htmlsingle/)
- [Spring REST Docs 4.0.0 릴리스](https://spring.io/blog/2025/11/19/spring-restdocs-4/)
- [springdoc-openapi issue #3163 — Boot 4 버저닝과 문서 엔드포인트](https://github.com/springdoc/springdoc-openapi/issues/3163)
- 에러 응답을 어떤 포맷으로 문서화할지는 `daily/day03-api-error-format.md`, 엔드포인트 설계 자체는 `daily/day09-rest-api-design.md`에서 다룹니다.

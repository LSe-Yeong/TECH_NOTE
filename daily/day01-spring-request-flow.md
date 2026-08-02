# HTTP 요청 한 개가 내 코드에 닿기까지

## 1. 핵심 개념: Filter, Interceptor, AOP란?

- 요청을 가로챌 수 있는 지점은 세 곳입니다: Filter, Interceptor, AOP.
- 셋 다 "본 로직 앞뒤에 공통 처리를 끼워 넣는다"는 목적은 같지만, **끼어드는 layer가 다릅니다.**
- Filter는 Servlet Container, Interceptor는 Spring MVC, AOP는 Bean 메서드 — 이 layer 차이가 "어디에 무엇을 둘지"를 결정합니다.

> **"인증 로직을 어디에 두어야 하지?"에 확신이 없으면 아무 데나 넣게 됩니다.** 그 결과 Filter에서 `@Autowired` 빈을 주입하려다 null이 나오거나, AOP로 HTTP 헤더를 읽으려다 `HttpServletRequest`를 어떻게 꺼내는지 한참 검색하게 됩니다.

## 2. 구조

- **Filter Chain**: `jakarta.servlet.Filter`를 구현합니다. Tomcat이 직접 실행하며 DispatcherServlet보다 앞에 있습니다. Spring Context가 뜨기 전에도 동작합니다.
- **DispatcherServlet**: Spring MVC의 프론트 컨트롤러입니다. 모든 요청을 받아 `HandlerMapping`에게 "이 URL은 누가 처리하는가" 물어봅니다.
- **HandlerInterceptor**: Spring MVC 레벨입니다. `preHandle()`은 컨트롤러 실행 전, `postHandle()`은 정상 응답 후, `afterCompletion()`은 예외 여부와 무관하게 응답이 나간 뒤 항상 실행됩니다.
- **HandlerAdapter**: 컨트롤러 메서드를 실제로 호출하는 객체입니다. `@RequestBody` 역직렬화, `@PathVariable` 바인딩이 여기서 일어납니다.

### 2-1. 선택적 확장 지점

- `OncePerRequestFilter`에는 `shouldNotFilter(request)`라는 메서드가 있습니다. 기본은 항상 `false`(모든 요청 필터링)지만, 오버라이드하면 특정 요청을 필터링 대상에서 뺄 수 있습니다.
- `HandlerInterceptor`의 `postHandle()`, `afterCompletion()`도 구현하지 않으면 아무 일도 하지 않는 기본 메서드입니다. 필요한 것만 골라서 오버라이드합니다.
- 필수 처리(`preHandle`)와 선택적 처리(`shouldNotFilter`, `postHandle`)를 나눠두면, 일반 케이스는 손대지 않고 예외 케이스만 추가로 손볼 수 있습니다.

## 3. 요청 처리 흐름

### 3-1. 클래스 구성

```java
// Filter 예시
@Component
public class RequestLoggingFilter extends OncePerRequestFilter {
    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws IOException, ServletException {
        log.info("요청: {} {}", request.getMethod(), request.getRequestURI());
        chain.doFilter(request, response);
        log.info("응답: {}", response.getStatus());
    }
}
```

```java
// Interceptor 예시 — WebMvcConfigurer에 addInterceptors()로 등록해야 합니다
@Component
public class AuthInterceptor implements HandlerInterceptor {
    private final TokenService tokenService;

    @Override
    public boolean preHandle(HttpServletRequest request,
                             HttpServletResponse response,
                             Object handler) throws Exception {
        String token = request.getHeader("Authorization");
        if (!tokenService.isValid(token)) {
            response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
            return false; // false 반환 시 컨트롤러를 호출하지 않습니다
        }
        return true;
    }
}
```

### 3-2. 실행 흐름

```
Client --(HTTP)--> Filter Chain
Filter Chain --> DispatcherServlet
DispatcherServlet --> HandlerMapping (컨트롤러 탐색)
HandlerMapping --> Interceptor.preHandle
Interceptor.preHandle --> @Controller
@Controller --> Interceptor.postHandle / afterCompletion
Interceptor.postHandle / afterCompletion --> Filter Chain
```

```
요청 로그: GET /orders
Interceptor.preHandle 통과
Controller 실행
Interceptor.postHandle 실행
응답 로그: 200
```

## 4. 특징

### 4-1. 사용 시기

- **Filter**: 요청/응답 바이트를 직접 다뤄야 하거나, Spring이 뜨기 전에 처리해야 할 때 (CORS, gzip, JWT 문자열 추출, 요청 본문 로깅)
- **Interceptor**: Spring Bean이 필요하면서 HTTP 요청/응답 수준의 전후처리가 필요할 때 (토큰 검증 후 `SecurityContextHolder` 세팅, API 응답 시간 측정)
- **AOP**: HTTP와 무관한 비즈니스 메서드 전후처리가 필요할 때 (`@Transactional`, `@Cacheable`)

### 4-2. 장점

- 인증, 로깅, CORS 같은 횡단 관심사를 컨트롤러 코드에서 완전히 분리할 수 있습니다.
- 계층(Filter/Interceptor/AOP)이 분명해서, 새로 합류한 개발자도 "이 로직이 왜 여기 있는지" 위치만 보고 유추할 수 있습니다.

### 4-3. 단점 / 트레이드오프

- 계층이 세 개라 처음엔 어디에 뭘 둬야 할지 헷갈립니다. 학습 비용이 듭니다.
- 로직이 Filter/Interceptor/AOP로 흩어지면, 요청 하나를 디버깅할 때 여러 파일을 오가며 추적해야 합니다.

## 5. 예제: 인증 로직을 어디에 둘 것인가

### 5-1. 클린하지 않은 코드 ❌

```java
@RestController
@RequiredArgsConstructor
public class OrderController {
    private final TokenService tokenService;
    private final OrderService orderService;

    @GetMapping("/orders")
    public List<Order> getOrders(HttpServletRequest request) {
        String token = request.getHeader("Authorization");
        if (!tokenService.isValid(token)) {
            throw new UnauthorizedException();
        }
        return orderService.findAll();
    }

    @PostMapping("/orders")
    public Order createOrder(HttpServletRequest request, @RequestBody OrderRequest req) {
        String token = request.getHeader("Authorization");
        if (!tokenService.isValid(token)) {  // 메서드마다 반복
            throw new UnauthorizedException();
        }
        return orderService.create(req);
    }
}
```

- 컨트롤러 메서드마다 같은 인증 체크가 반복됩니다.
- 새 엔드포인트를 추가할 때 인증 체크를 빼먹기 쉽습니다.

### 5-2. Interceptor를 적용한 코드 ✔️

```java
@Configuration
@RequiredArgsConstructor
public class WebConfig implements WebMvcConfigurer {
    private final AuthInterceptor authInterceptor;

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(authInterceptor)
                .addPathPatterns("/orders/**");
    }
}
```

```java
@RestController
@RequiredArgsConstructor
public class OrderController {
    private final OrderService orderService;

    @GetMapping("/orders")
    public List<Order> getOrders() {
        return orderService.findAll();  // 인증 체크는 Interceptor가 이미 끝냄
    }

    @PostMapping("/orders")
    public Order createOrder(@RequestBody OrderRequest req) {
        return orderService.create(req);
    }
}
```

- 인증 체크가 한 곳(`AuthInterceptor`)에만 있습니다. `addPathPatterns()`에 경로만 추가하면 새 엔드포인트도 자동으로 보호됩니다.

## 6. "컨테이너가 호출한다" 원칙

- Filter의 `doFilterInternal()`, Interceptor의 `preHandle()`을 개발자가 직접 호출하는 코드는 어디에도 없습니다.
- `chain.doFilter()`를 호출하는 건 Tomcat이고, `preHandle()`을 호출하는 건 `DispatcherServlet`입니다. 개발자는 등록만 해둘 뿐입니다.
- **"Don't call us, we'll call you" — 헐리우드 원칙**이 여기서도 그대로 적용됩니다. Bean으로 등록하고 `addInterceptors()`로 경로만 지정하면, 실제 호출 시점과 순서는 프레임워크가 결정합니다.
- 이 원칙 덕분에, 인증 체크 순서를 바꾸고 싶으면 `InterceptorRegistry`의 등록 순서만 바꾸면 됩니다. 호출하는 쪽 코드를 하나하나 찾아 고칠 필요가 없습니다.

## 7. 확장 지점(hook) 응용하기

### 7-1. 클린하지 않은 코드 ❌

```java
@Component
public class RequestLoggingFilter extends OncePerRequestFilter {
    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws IOException, ServletException {
        // 정적 리소스(css, js, images) 요청까지 전부 로깅됩니다
        log.info("요청: {} {}", request.getMethod(), request.getRequestURI());
        chain.doFilter(request, response);
        log.info("응답: {}", response.getStatus());
    }
}
```

- `/css/style.css`, `/js/app.js` 같은 정적 리소스 요청까지 매번 로그가 찍혀 로그가 금방 지저분해집니다.

### 7-2. `shouldNotFilter()` 적용 코드 ✔️

```java
@Component
public class RequestLoggingFilter extends OncePerRequestFilter {

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String path = request.getRequestURI();
        return path.startsWith("/css") || path.startsWith("/js") || path.startsWith("/images");
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws IOException, ServletException {
        log.info("요청: {} {}", request.getMethod(), request.getRequestURI());
        chain.doFilter(request, response);
        log.info("응답: {}", response.getStatus());
    }
}
```

- `shouldNotFilter()`가 `true`를 반환하면 `doFilterInternal()` 자체가 호출되지 않습니다. 정적 리소스는 로깅 대상에서 완전히 빠집니다.

## 8. 실무에서 찾아보는 Filter / Interceptor / AOP

### 8-1. Java 표준

- `jakarta.servlet.Filter`, `FilterChain` — Servlet 스펙 자체가 Filter Chain 구조입니다.

### 8-2. Spring Framework

- `OncePerRequestFilter` — 요청당 한 번만 실행되는 Filter의 표준 베이스 클래스
- `CommonsRequestLoggingFilter` — Spring이 기본 제공하는 요청 로깅 Filter
- `HandlerInterceptor` — Spring MVC의 Interceptor 인터페이스
- `@Around` AOP — 메서드 호출 자체를 감싸는 가장 강력한 Advice

## 9. 관련된 개념과 비교

### 9-1. Interceptor VS AOP

**유사점**

- 둘 다 실제 로직 앞뒤에 공통 처리를 끼워 넣습니다.
- 둘 다 "핵심 로직 코드를 건드리지 않고" 부가 기능을 추가합니다.

**차이점**

- Interceptor는 `HttpServletRequest`/`HttpServletResponse`에 접근할 수 있습니다. AOP는 메서드 파라미터와 리턴값에만 접근합니다.
- Interceptor는 HTTP 요청에만 적용됩니다. AOP는 HTTP와 무관하게 임의의 Bean 메서드에 적용할 수 있습니다.
- Interceptor는 Spring MVC가 제공하는 특정 확장점입니다. AOP는 프록시 기반의 범용 메커니즘입니다.

## 10. 함정

**Filter가 같은 요청에 두 번 실행된다**

- **증상**: 로그가 두 번 찍히거나 인증이 두 번 수행됩니다.
- **원인**: `RequestDispatcher.forward()`를 쓰면 Servlet Container가 Filter Chain을 처음부터 다시 통과시킵니다. Spring MVC 내부에서 예외 처리 시 `/error`로 forward가 발생합니다.
- **해법**: `Filter` 대신 `OncePerRequestFilter`를 상속하세요.

**Filter에서 요청 본문을 읽으면 Controller가 빈 body를 받는다**

- **증상**: 로깅 Filter에서 `request.getInputStream()`을 읽은 뒤 `@RequestBody`가 항상 비어 있습니다.
- **원인**: `InputStream`은 한 번 읽으면 커서가 끝으로 이동해 다시 읽을 수 없습니다.
- **해법**: `ContentCachingRequestWrapper`로 감싸고, `chain.doFilter()` 실행 뒤에 읽습니다.

**`postHandle`은 예외 발생 시 실행되지 않는다**

- **증상**: `postHandle`에서 응답 로그를 찍으려는데, 예외가 발생한 요청만 기록이 빠집니다.
- **원인**: DispatcherServlet은 예외가 발생하면 `postHandle`을 건너뜁니다.
- **해법**: "무슨 일이 있어도 실행돼야 한다"면 `afterCompletion`에 둡니다.

## 11. 참고자료

- [Spring MVC DispatcherServlet 공식 문서](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-servlet.html)
- `06-spring/14-dispatcher-servlet.md` — DispatcherServlet이 요청을 처리하는 더 자세한 흐름
- `06-spring/15-filter-interceptor-aop.md` — 세 가지의 경계를 더 깊게

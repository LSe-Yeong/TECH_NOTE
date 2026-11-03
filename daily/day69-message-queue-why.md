# 왜 비동기인가 — 메시지 큐는 무엇을 분리하고, 그 대가로 무엇을 가져가는가

## 1. 핵심 개념

메시지 큐는 **보내는 쪽과 처리하는 쪽 사이에 끼우는 저장소**입니다. 프로듀서는 메시지를 넣고 바로 돌아오고, 컨슈머는 자기 속도로 꺼내서 처리합니다. 호출의 의미가 "지금 같이 처리하자"에서 "이 일을 적어뒀으니 처리해라"로 바뀝니다.

> 큐가 없으면 **가장 느린 하위 시스템이 내 API의 응답 시간을 결정합니다.** 주문을 DB에 저장하는 데 20ms인데 영수증 메일 발송이 3초 걸리면 주문 API는 3초입니다. 메일 서버가 죽으면 주문도 못 받습니다. DB도 내 코드도 멀쩡한데 서비스가 멈춥니다.

이 문서는 하나의 질문에 답합니다. **요청 처리 경로에 큐를 끼우면 무엇이 분리되고, 그 대가로 어떤 계약이 바뀌는가.**

## 2. 동기 호출이 무너지는 지점

### 2-1. 응답 시간은 더해지고, 가용성은 곱해집니다

한 요청이 A → B → C를 순서대로 동기 호출하면 응답 시간은 세 구간의 **합**입니다. 여기까지는 직관적입니다.

문제는 가용성입니다. 세 단계가 전부 성공해야 요청이 성공하므로, 각 단계가 독립적으로 99.9% 가동한다고 가정하면 전체는 `0.999³ ≈ 99.7%`입니다. 단계를 늘릴수록 내려갑니다. 이 계산은 제가 가정값으로 한 산수이고 특정 제품의 측정값이 아니지만, 방향은 분명합니다. **동기 체인에 의존성을 하나 더 넣는 것은 내 API의 가용성을 빌려주는 일입니다.**

핵심 기능(주문 저장)과 부가 기능(메일 발송)이 같은 체인에 있으면, 부가 기능의 가용성이 핵심 기능의 가용성이 됩니다.

### 2-2. 먼저 떨어지는 자원은 CPU가 아니라 스레드입니다

이게 실무에서 실제로 보는 모습입니다. 서블릿 기반 서버는 요청 하나를 스레드 하나가 처음부터 끝까지 붙잡습니다. 외부 호출을 기다리는 동안 그 스레드는 아무 일도 하지 않으면서 점유됩니다.

요청당 3초가 걸리고 워커 스레드가 200개라면 이론 처리량은 `200 / 3초 ≈ 초당 66건`입니다. 67번째 요청부터는 큐에서 기다립니다. 이때 CPU 사용률은 한가합니다. 기다리는 중이니까요.

더 나쁜 건 **전염**입니다. 스레드 풀은 엔드포인트별로 나뉘어 있지 않습니다. 느린 결제 API가 풀을 다 먹으면 멀쩡한 상품 조회 API도 같이 느려집니다. 지표에서는 "전체 레이턴시 상승"으로만 보이고 원인 엔드포인트가 드러나지 않습니다(`daily/day54-golden-signals.md`).

### 2-3. 피크를 기준으로 서버를 삽니다

동기 처리에서는 들어오는 속도와 처리하는 속도가 같아야 합니다. 평소 초당 100건인데 이벤트 때 초당 2,000건이 들어온다면, 서버는 2,000건 기준으로 준비해야 합니다. 나머지 23시간은 그 용량이 놀고 있습니다.

## 3. 큐가 실제로 분리하는 것 세 가지

"비동기로 만든다"는 결과이고, 큐가 하는 일은 분리입니다. 무엇을 분리하는지가 도입 근거입니다.

### 3-1. 시간 — 들어오는 속도와 처리하는 속도를 떼어냅니다

이걸 **Queue-Based Load Leveling** 패턴이라고 부릅니다. 큐를 버퍼로 두면 서비스는 변동이 심한 요청을 자기 페이스로 처리할 수 있고, 서비스가 내려가 있어도 프로듀서는 계속 메시지를 넣을 수 있습니다. 그래서 **피크 부하가 아니라 평균 부하 기준으로 인스턴스를 유지해도 됩니다**([Queue-Based Load Leveling pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/queue-based-load-leveling)).

이게 큐를 넣는 가장 흔한 이유이고, 가장 오해가 적은 이유입니다.

### 3-2. 실패 — 재시도를 호출자 밖으로 옮깁니다

동기 호출에서 재시도는 호출자 책임입니다. 스레드를 잡고 3번 기다려야 하고, 그 사이 서버가 재배포되면 작업이 사라집니다.

큐에서는 재시도가 브로커의 기능입니다. SQS를 예로 들면 컨슈머가 메시지를 받으면 **visibility timeout** 동안 다른 컨슈머에게 보이지 않고, 그 안에 삭제하지 않으면 다시 큐에 나타납니다. 기본값은 30초, 최대 12시간입니다. 메시지는 기본 4일 보관하고 1분~14일로 조정합니다([Amazon SQS message quotas](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/quotas-messages.html)).

영구적으로 실패하는 메시지는 격리합니다. SQS는 redrive 정책의 `maxReceiveCount`를 넘겨 수신된 메시지를 **데드레터 큐(DLQ)** 로 보냅니다([Using dead-letter queues](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-dead-letter-queues.html)).

### 3-3. 대상 — 누가 받는지를 프로듀서가 몰라도 됩니다

동기 호출은 "누구를 부를지"를 호출 코드에 적어야 합니다. 알림을 추가하려면 주문 서비스를 고쳐야 합니다.

큐/토픽에 넣으면 프로듀서는 구독자를 모릅니다. 특히 Kafka는 **읽어도 메시지를 지우지 않습니다.** 공식 문서는 "전통적인 메시징 시스템과 달리 이벤트는 소비된 후에 삭제되지 않는다"고 적고, 보관 기간은 토픽별 설정으로 정합니다([Kafka Introduction](https://kafka.apache.org/intro)). 그래서 같은 이벤트를 여러 소비자가 각자 읽고, 새 소비자가 과거 데이터부터 다시 읽을 수 있습니다.

## 4. 큐가 해결하지 않는 것

여기가 가장 많이 틀리는 지점입니다.

### 4-1. 일이 빨라지지 않습니다. 기다리는 주체가 바뀔 뿐입니다

메일 발송이 3초 걸렸다면 큐를 넣어도 3초 걸립니다. 줄어든 것은 **클라이언트가 보는 응답 시간**이고, 전체 완료 시간은 큐 대기 시간이 붙어서 오히려 늘어납니다.

그래서 큐는 "결과를 안 기다려도 되는 일"에만 효과가 있습니다. 결과를 기다려야 하는 일에 큐를 끼우면 대기 비용만 추가됩니다.

### 4-2. 처리량은 컨슈머가 정합니다. 큐 길이는 그 차이의 누적입니다

큐를 넣으면 요청을 "받을 수" 있게 되지, "처리할 수" 있게 되는 게 아닙니다. 평균 생산 속도가 평균 소비 속도보다 크면 큐는 계속 자라고 지연이 누적됩니다. 그래서 큐 깊이를 모니터링하고 컨슈머를 확장하거나 프로듀서 쪽에서 작업을 버려야 합니다([Queue-Based Load Leveling pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/queue-based-load-leveling)).

큐 깊이를 지금의 부하로 읽으면 안 됩니다. **깊이는 "그동안 못 처리한 양의 누적"입니다.** 생산이 소비보다 초당 10건씩 빠르면 1시간 뒤 36,000건이 쌓여 있습니다. 트래픽이 정상으로 돌아와도 그 빚은 그대로 남아 있고, 컨슈머가 그걸 다 소화하는 동안 체감 지연은 계속 나쁩니다.

### 4-3. 큐는 장애를 뒤로 미룹니다. 지우지 않습니다

큐가 차 있는 동안 API는 200을 돌려줍니다. 사용자 입장에서는 성공입니다. 그런데 메시지가 보관 기간을 넘기면 조용히 사라집니다. "성공 응답을 받았는데 메일이 안 왔다"가 되고, 로그에는 에러가 없습니다.

DLQ도 같은 함정이 있습니다. SQS 표준 큐에서 **메시지 만료는 항상 최초 인큐 시각을 기준으로 계산되고, DLQ로 옮겨도 그 시각은 바뀌지 않습니다.** 원본 큐에서 1일을 보낸 메시지는 보관 기간 4일인 DLQ에서 3일 뒤에 삭제됩니다. 그래서 DLQ의 보관 기간을 원본보다 길게 잡는 것이 권장됩니다(FIFO 큐는 반대로 인큐 시각이 리셋됩니다 — [Using dead-letter queues](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-dead-letter-queues.html)).

## 5. 코드로 보는 세 단계

### 5-1. 동기 — 메일 서버가 주문을 막습니다 ❌

```java
@Service
@RequiredArgsConstructor
public class OrderService {

    private final OrderRepository orderRepository;
    private final MailClient mailClient;

    @Transactional
    public Long placeOrder(OrderCommand command) {
        Order order = orderRepository.save(Order.from(command));
        mailClient.sendOrderConfirmation(order);  // 3초. 그리고 트랜잭션 안
        return order.getId();
    }
}
```

문제가 두 개입니다. 응답이 메일 서버 속도에 묶이고, **외부 호출이 DB 트랜잭션 안에 있어서 커넥션을 3초간 잡습니다.** 메일 서버가 느려지면 커넥션 풀이 먼저 마릅니다.

### 5-2. `@Async` — 이건 큐가 아닙니다 △

가장 먼저 떠오르는 해법이고, 가장 자주 사고가 납니다.

```java
@Async
public void sendOrderConfirmation(Order order) { ... }
```

Spring Boot 3.4의 `TaskExecutionProperties` 기본값은 `pool.core-size = 8`, `pool.max-size = Integer.MAX_VALUE`, `pool.queue-capacity = Integer.MAX_VALUE`입니다([TaskExecutionProperties.java, v3.4.0](https://github.com/spring-projects/spring-boot/blob/v3.4.0/spring-boot-project/spring-boot-autoconfigure/src/main/java/org/springframework/boot/autoconfigure/task/TaskExecutionProperties.java)). 여기서 세 가지가 따라옵니다.

1. **동시 처리량은 8입니다.** `ThreadPoolExecutor` 문서는 코어 스레드가 모두 바쁠 때 무한 큐를 쓰면 작업이 큐에서 대기하므로 "코어 풀 크기를 넘는 스레드는 절대 생성되지 않고, 따라서 `maximumPoolSize`는 아무 효과가 없다"고 명시합니다([ThreadPoolExecutor](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/concurrent/ThreadPoolExecutor.html)). `max-size`를 키워도 안 늘어납니다.
2. **큐가 무한히 자랍니다.** 같은 문서는 이 방식이 순간적인 버스트는 잘 흡수하지만 "처리 속도보다 작업이 계속 빠르게 도착하면 작업 큐가 무한히 커질 수 있다"고 경고합니다. 끝은 OOM입니다.
3. **프로세스가 죽으면 전부 사라집니다.** 큐가 힙에 있으니까요. 배포할 때마다 미처리 작업이 날아가고, graceful shutdown을 설정해도 종료 대기 시간 안에 못 끝낸 것은 그대로 유실됩니다(`daily/day18-graceful-shutdown.md`).

`@Async`는 **유실돼도 괜찮은 일**에만 씁니다. 메일·알림·집계 갱신처럼 "안 되면 다음에"가 성립하는 일입니다. 결제 정산을 여기 넣으면 배포 한 번에 돈이 사라집니다.

### 5-3. 커밋 후 발행 + 브로커 ✔️

```java
@Service
@RequiredArgsConstructor
public class OrderService {

    private final OrderRepository orderRepository;
    private final ApplicationEventPublisher eventPublisher;

    @Transactional
    public Long placeOrder(OrderCommand command) {
        Order order = orderRepository.save(Order.from(command));
        eventPublisher.publishEvent(new OrderPlacedEvent(order.getId()));
        return order.getId();
    }
}

@Component
@RequiredArgsConstructor
public class OrderPlacedPublisher {

    private final SqsTemplate sqsTemplate;

    @TransactionalEventListener  // 기본 phase = AFTER_COMMIT
    public void publish(OrderPlacedEvent event) {
        sqsTemplate.send("order-placed", event);
    }
}
```

`@TransactionalEventListener`의 기본 단계는 `AFTER_COMMIT`이고, 실행 중인 트랜잭션이 없으면 리스너는 **호출되지 않습니다**(`fallbackExecution = true`로 바꿀 수 있습니다 — [Transaction-bound Events](https://docs.spring.io/spring-framework/reference/data-access/transaction/event.html)). 롤백된 주문의 메일이 나가는 사고를 이게 막아줍니다.

## 6. 응답의 의미가 바뀝니다

큐를 넣는 순간 API 계약이 바뀝니다. 더 이상 "처리했다"를 돌려줄 수 없고 "접수했다"만 돌려줄 수 있습니다.

```
POST /orders  →  202 Accepted
                 Location: /orders/9281
                 { "orderId": 9281, "status": "ACCEPTED" }
```

그래서 **결과를 확인할 수단을 같이 설계해야 합니다.** 상태 조회 엔드포인트, 웹소켓/SSE 푸시, 콜백 중 하나입니다. 메시지 큐는 단방향 통신 수단이라 응답이 필요하면 별도 경로를 만들어야 한다는 점은 패턴 문서도 명시하는 고려사항입니다([Queue-Based Load Leveling pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/queue-based-load-leveling)).

이 설계를 안 하면 사용자는 새로고침을 반복하고, 고객센터는 "결제했는데 주문이 없다" 문의를 받습니다. 비동기화의 실제 비용은 대부분 여기서 발생합니다.

## 7. 반드시 따라오는 대가 세 가지

### 7-1. 같은 메시지를 두 번 받습니다

SQS 표준 큐 문서는 이렇게 적습니다. 표준 큐는 **at-least-once** 전달을 보장하며, 고도로 분산된 구조 때문에 메시지 사본이 둘 이상 전달될 수 있고 순서가 뒤바뀔 수 있습니다. 순서는 최선 노력(best-effort)입니다([Amazon SQS standard queues](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues.html)).

그래서 **컨슈머는 멱등해야 합니다.** 선택이 아닙니다. 같은 메시지를 두 번 처리해도 결과가 같아야 중복 결제·중복 발송이 안 생깁니다(`daily/day21-idempotency.md`).

### 7-2. 순서를 지키려면 병렬성을 내놓습니다

순서 보장은 공짜가 아니고, 가격표가 명시돼 있습니다.

| 방식 | 순서 범위 | 처리량 |
|---|---|---|
| SQS 표준 | 보장 없음(최선 노력) | API 액션당 거의 무제한 |
| SQS FIFO | 메시지 그룹 단위 | 파티션당 API 액션별 **300 TPS**, 배치 사용 시 초당 3,000건 |
| SQS FIFO 고처리량 모드 | 메시지 그룹 단위 | 비배치 기준 리전별 상한(버지니아 북부·오레곤·아일랜드 최대 70,000 TPS, 그 외 기본 2,400 TPS) |

출처: [Amazon SQS message quotas](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/quotas-messages.html).

Kafka도 구조는 같습니다. 같은 키를 가진 이벤트는 같은 파티션에 쓰이고, 특정 토픽-파티션의 컨슈머는 쓰인 순서 그대로 읽습니다([Kafka Introduction](https://kafka.apache.org/intro)). 즉 **순서의 단위가 병렬 처리의 단위입니다.** 주문별 순서만 필요하면 키를 주문 ID로 잡아 병렬성을 확보할 수 있고, 전역 순서가 필요하면 파티션 1개 = 컨슈머 1개가 됩니다.

전역 순서가 정말 필요한지 먼저 따져야 합니다. 대부분은 "엔티티 하나 안에서의 순서"면 충분합니다.

### 7-3. DB 커밋과 메시지 발행은 원자적이지 않습니다

이게 비동기화의 가장 깊은 함정입니다. 커밋은 성공했는데 발행이 실패하면 주문은 있고 후속 처리는 없습니다. 반대로 발행 후 커밋이 실패하면 없는 주문의 메일이 나갑니다.

`AFTER_COMMIT`은 후자를 막지만 전자를 못 막습니다. 커밋 직후 브로커가 응답하지 않으면 메시지는 그냥 유실됩니다. 완전한 해법은 메시지를 같은 트랜잭션에서 DB 테이블에 쓰고 별도 프로세스가 그 테이블을 읽어 발행하는 **Outbox 패턴**입니다(토픽맵 `08-system-design/11-outbox-pattern`, 미작성).

## 8. 언제 쓰지 말아야 하는가

패턴 문서가 적합하지 않다고 꼽는 두 경우가 그대로 기준이 됩니다. 호출자가 **낮은 지연의 동기 응답**을 필요로 할 때, 그리고 부하가 예측 가능하고 낮게 안정적일 때입니다([Queue-Based Load Leveling pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/queue-based-load-leveling)).

실무 기준으로 옮기면 이렇습니다.

- 호출 결과로 응답 내용이 결정된다(재고 확인 후 구매 가능 여부 반환) → 동기
- 실패를 사용자에게 즉시 알려야 한다(카드 승인 거절) → 동기
- 후속 작업이 실패해도 요청은 성공으로 끝나도 된다 → 비동기
- 느린 의존성이 핵심 기능의 가용성을 끌어내린다 → 비동기

큐를 넣으면 운영 대상이 늘어납니다. 브로커, DLQ, 컨슈머 배포, 재처리 절차, 큐 깊이 알림. 하루 수백 건 처리하는 서비스에서는 이 비용이 이득보다 큽니다.

## 9. 비슷하지만 다른 선택지들

"지금 처리하지 않는다"를 구현하는 방법은 큐 말고도 있습니다. 네 가지를 같은 축으로 비교하면 큐가 어디에 들어가는지 보입니다.

| 방식 | 작업이 사는 곳 | 유실 조건 | 지연 | 적합한 일 |
|---|---|---|---|---|
| 동기 호출 | 없음(호출 스택) | 요청 실패 = 사용자 인지 | 즉시 | 결과가 응답에 필요한 일 |
| `@Async` 스레드 풀 | 프로세스 힙 | 프로세스 종료 시 전부 | 수 ms | 유실돼도 되는 부가 작업 |
| DB 테이블 + 스케줄러 | DB | DB 유실과 동일 | 폴링 주기 | 건수가 적고 브로커를 들이기 아까울 때 |
| 메시지 브로커 | 브로커(복제 저장) | 보관 기간 초과, DLQ 방치 | 수십 ms~ | 유실이 돈·신뢰로 이어지는 일 |

세 번째 줄을 과소평가하지 않는 게 좋습니다. `orders_outbox` 같은 테이블에 넣고 스케줄러가 1초마다 긁어가는 구조는 트랜잭션 원자성을 공짜로 얻고, 조회·재처리를 SQL로 할 수 있습니다. 대가는 폴링 지연과 DB 부하, 그리고 여러 인스턴스가 같은 행을 집는 문제(`SELECT ... FOR UPDATE SKIP LOCKED` 같은 장치가 필요합니다)입니다. 처리량이 늘어나면 브로커로 옮기게 되지만, **시작점으로는 합리적인 선택입니다.**

반대로 `@Async`는 "브로커의 저렴한 버전"이 아닙니다. 저장소가 힙이라는 점에서 성질이 다릅니다. 이 둘을 같은 칸에 놓고 고르면 배포 때마다 조용히 작업이 사라집니다.

## 10. 함정

**컨슈머가 계속 같은 메시지를 다시 받습니다**
- **증상**: 처리는 성공하는데 같은 작업이 30초마다 반복됩니다. 메일이 여러 번 갑니다.
- **원인**: 처리 시간이 visibility timeout(기본 30초)보다 길어서, 삭제 전에 메시지가 다시 보이게 됐습니다.
- **해법**: 타임아웃을 실제 처리 시간의 최악값보다 길게 잡습니다. 길이가 들쭉날쭉하면 처리 중 주기적으로 타임아웃을 연장합니다. 그리고 멱등 처리를 함께 둡니다.

**장애가 끝났는데 지연이 몇 시간째 안 떨어집니다**
- **증상**: 트래픽은 정상인데 메시지 처리가 계속 느립니다.
- **원인**: 장애 중 쌓인 백로그입니다. 큐 깊이는 생산-소비 차이의 누적이라 정상화만으로는 줄지 않습니다.
- **해법**: 컨슈머를 일시적으로 증설해 소비 속도를 생산 속도보다 크게 만듭니다. 이때 하위 의존성(DB)이 받는 부하가 평시보다 커지므로 증설 상한을 둡니다. 알림은 깊이 절대값보다 **증가 추세**와 가장 오래된 메시지의 나이로 거는 쪽이 유용합니다.

**DLQ에 쌓인 메시지가 어느 날 사라져 있습니다**
- **증상**: DLQ 알림을 보고 다음 주에 보러 갔는데 메시지가 없습니다.
- **원인**: 표준 큐는 만료를 최초 인큐 시각으로 계산하고, DLQ로 옮겨도 그 시각이 유지됩니다.
- **해법**: DLQ 보관 기간을 원본 큐보다 길게(원본 4일이면 DLQ 14일) 설정하고, DLQ 깊이에 알림을 걸어 "아무도 안 보는 DLQ"를 만들지 않습니다.

**비동기로 바꿨는데 커넥션 풀이 더 빨리 마릅니다**
- **증상**: `@Async`로 외부 호출을 빼냈는데 DB 커넥션 타임아웃이 늘었습니다.
- **원인**: 비동기 메서드 안에서 다시 DB를 쓰는데, 풀 크기는 그대로인 채 동시 실행 주체만 늘었습니다.
- **해법**: 비동기 작업의 동시성(코어 스레드 수)을 커넥션 풀 크기와 함께 보고 상한을 정합니다. 기본값 8을 무심코 키우면 그만큼 커넥션을 더 요구합니다.

**예외가 조용히 사라집니다**
- **증상**: 비동기 작업이 실패해도 로그에 아무것도 없습니다.
- **원인**: `@Async void` 메서드의 예외는 호출자에게 전파되지 않고, `@ControllerAdvice` 경계 밖입니다(`daily/day68-exception-handling.md`).
- **해법**: `AsyncUncaughtExceptionHandler`를 등록하거나 반환형을 `CompletableFuture`로 바꿔 예외를 받습니다. 브로커를 쓰는 경우에는 DLQ가 이 역할을 합니다.

## 11. 참고자료

- [Amazon SQS message quotas](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/quotas-messages.html)
- [Amazon SQS standard queues](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues.html)
- [Using dead-letter queues in Amazon SQS](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-dead-letter-queues.html)
- [Queue-Based Load Leveling pattern — Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/patterns/queue-based-load-leveling)
- [Apache Kafka Introduction](https://kafka.apache.org/intro)
- [ThreadPoolExecutor (Java SE 21)](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/concurrent/ThreadPoolExecutor.html)
- [Spring Framework — Transaction-bound Events](https://docs.spring.io/spring-framework/reference/data-access/transaction/event.html)
- 관련 문서: `daily/day21-idempotency.md`, `daily/day18-graceful-shutdown.md`, `daily/day54-golden-signals.md`, `daily/day68-exception-handling.md`
